import json
import re

import pymysql

from classifier import varDump
from auth_utils import JUNCTION_OWNERSHIP, check_junction_parent_ownership

#
# json response utility function
#
def compose_rest_response(status_code, body='', http_message=''):

    #
    # Compose AWS Lambda proxy response format
    # https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-output-format
    #
    print(f"HTTP Status Code: {status_code}")

    lambda_rest_api_response = {
        'isBase64Encoded': False,
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'body, Content-Type, Access-Control-Allow-Headers, Access-Control-Allow-Origin, Access-Control-Allow-Methods',
                    'Access-Control-Allow-Methods': 'PUT, GET, POST, DELETE, OPTIONS',
        }
    }

    # On an error status the body IS http_message — whatever the caller passed as
    # `body` is discarded. http_message is usually a string; the 409 path
    # (req #3059) passes a dict, which json.dumps renders as a JSON OBJECT so the
    # client reads errno and constraint instead of parsing prose.
    if status_code not in (200, 201, 204):
        print(f"Error message inserted into body.  {body} : {http_message}")
        body = http_message

    #
    # json encode body, insert into response
    #
    if body is not None:
        lambda_rest_api_response['body'] = json.dumps(body)
    else:
        print('body is empty')

    #varDump(lambda_rest_api_response, 'Lambda proxy response')

    return lambda_rest_api_response


# ---------------------------------------------------------------------------
# Junction write authorization (req #3122)
# ---------------------------------------------------------------------------

def junction_write_guard(conn, table, bodies, authenticated_user, method,
                         require_scope=True):
    """403/400 response when a write names a parent the caller does not own, else None.

    Shared by `rest_post` and `rest_put` because BOTH can hand a row to another
    creator, by different routes: POST has no WHERE clause to scope, and PUT's
    WHERE only proves ownership of the row's parent BEFORE the update while its
    SET clause can rewrite that very column afterwards. Guarding one verb and not
    the other simply moves the hole.

    Returns BEFORE opening a cursor for any table this does not apply to, which is
    almost every write. Opening one unconditionally is not merely wasteful: it
    moves the request's first cursor acquisition ahead of the INSERT, so a
    connection that fails on `cursor()` fails HERE — with nothing written and
    nothing to roll back. That regressed `tests/test_unit_error_detail_wiring.py`.

    A failure of the CHECK ITSELF is a 500, never a pass. It runs before any
    write, so refusing costs nothing; treating an unreadable parent table as
    "probably fine" would turn one broken query into an authorization bypass.
    """
    if authenticated_user is None or table not in JUNCTION_OWNERSHIP:
        return None
    try:
        with conn.cursor() as cursor:
            verdict = check_junction_parent_ownership(
                cursor, table, bodies, authenticated_user,
                require_scope=require_scope)
    except pymysql.Error as e:
        errno, detail = error_detail(e)
        errorMsg = (f"HTTP {method} junction ownership check failed: "
                    f"{errno} {detail}")
        print(errorMsg)
        return compose_rest_response(500, '', errorMsg)

    if verdict is None:
        return None
    status, message = verdict
    return compose_rest_response(status, '', message)


# ---------------------------------------------------------------------------
# Integrity violations -> HTTP 409 CONFLICT (req #3059)
# ---------------------------------------------------------------------------
#
# Before this, EVERY pymysql failure was a 500 carrying the raw driver message,
# so a client could not tell "you picked a taken name" from "the database is
# broken" without regex-matching prose. Three errnos mean the request conflicts
# with data that already exists, and only those three get the 409:
#
#   1062  Duplicate entry ... for key ...       UNIQUE / PRIMARY KEY collision
#   1451  Cannot delete or update a parent row  FK RESTRICT protecting children
#   1452  Cannot add or update a child row      FK pointing at a row that is gone
#
# The line is deliberate, not a shortlist to grow casually: a 409 tells the
# caller that retrying with different data can succeed. A missing column (1054),
# a NOT NULL with no default (1364), a lost connection (2013) — none of those
# keep that promise, so they stay 500s.

INTEGRITY_ERRNOS = frozenset({1062, 1451, 1452})

# `... for key 'instructions.uq_instructions_name'` — MySQL 8 qualifies the key
# name with its table, 5.7 does not. Anchored at end-of-message and quote-free in
# the group so a duplicated VALUE that itself contains "for key '...'" cannot be
# mistaken for the key.
_DUP_KEY_RE = re.compile(r"for key '([^']+)'\s*$")

# ``... (`darwin_dev`.`areas`, CONSTRAINT `areas_ibfk_1` FOREIGN KEY ...)``
_FK_CONSTRAINT_RE = re.compile(r"CONSTRAINT `([^`]+)`")


def error_detail(exc):
    """(errno, message) from a pymysql.Error, tolerant of a short args tuple.

    All eleven error-formatting sites in the CRUD modules — rest_post (5),
    rest_get_table (2), rest_put, rest_delete (2), rest_get_database — used to
    read `f"...: {e.args[0]} {e.args[1]}"` directly. pymysql raises ONE-arg
    errors from its own plumbing (`ProgrammingError("Cursor closed")`,
    `Error("Already closed")`), so that raised IndexError from INSIDE the
    `except pymysql.Error` block; `lambda_handler`'s blanket `except Exception`
    then swallowed it into a 503 SERVICE_UNAVAILABLE naming nothing. On a GET
    that also cost a round trip — darwin-mcp retries idempotent GETs once on 503.

    Going through here keeps the 2-arg message byte-identical (verified per-site)
    and turns the short-args case into a real 500 that names the failure.
    `tests/test_unit_error_detail_wiring.py` holds the sites to this; the pure
    function is covered in `tests/test_unit_conflict.py`.
    """
    errno = exc.args[0] if exc.args else None
    message = exc.args[1] if len(exc.args) > 1 else ''
    return errno, message


def integrity_errno(exc):
    """The MySQL errno of `exc` when it is an integrity violation, else None.

    Total over every shape pymysql raises, including no args at all — this is
    called from inside an `except` block, where anything it raised would escape
    as a 503 that names nothing.
    """
    errno, _ = error_detail(exc)
    try:
        return errno if errno in INTEGRITY_ERRNOS else None
    except TypeError:
        return None          # unhashable args[0] — not an errno by any reading


def constraint_name(errno, message):
    """The index / FK name the violation names, unqualified. None when absent.

    MySQL 8 reports a duplicate key as `table.index`; the schema declares plain
    `index`. Stripping the qualifier lets a consumer compare against the name it
    can actually read in the DDL — and nothing is lost, because the response
    carries `table` separately, sourced from the handler rather than the message.
    """
    match = (_DUP_KEY_RE if errno == 1062 else _FK_CONSTRAINT_RE).search(message or '')
    return match.group(1).rsplit('.', 1)[-1] if match else None


def compose_conflict_response(table, exc, error_message):
    """409 CONFLICT for a MySQL integrity violation, with a structured body.

    Body shape:

        {"error": "CONFLICT", "errno": 1062,
         "constraint": "uq_instructions_name", "table": "instructions",
         "message": "HTTP PUT SQL FAILED: 1062 Duplicate entry 'x' for key ..."}

    `error_message` is the exact string the 500 path used to put on the wire and
    is echoed verbatim under `message`. That is a compatibility promise, not
    padding: darwin-mcp's client._translate and any log grep written against the
    old contract keep working while they move over to `errno`.
    """
    errno, detail = error_detail(exc)
    return compose_rest_response(409, '', {
        'error': 'CONFLICT',
        'errno': errno,
        'constraint': constraint_name(errno, detail),
        'table': table,
        'message': error_message,
    })
