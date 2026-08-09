import os
import json
import re
import pymysql

from classifier import varDump, pretty_print_sql
from rest_api_utils import compose_rest_response
from db_connection import get_connection
from rest_get_database import rest_get_database
from rest_get_table import rest_get_table
from rest_put import rest_put
from rest_post import rest_post
from rest_delete import rest_delete
from auth_utils import (get_authenticated_user, CREATOR_FK_TABLES,
                        JUNCTION_OWNERSHIP, PROFILE_TABLE)
import pipeline2_compose

# req #3367 — the ONE non-generic route (remediation B, composing form).
# `pipeline2_compose` / `pipeline2_compose_epic` are not real tables; they are
# reserved route names dispatched to `pipeline2_compose.py` BEFORE the generic
# `{database}/{table}` gateway ever sees them. GET only, `id` as a query
# string parameter — same grammar as every other single-row lookup
# (`GET /darwin/pipeline2_compose?id=5`), so the existing darwin-mcp REST
# client needs no new URL-building code, only a new response-shape method.
PIPELINE2_COMPOSE_ROUTES = {
    'pipeline2_compose': pipeline2_compose.compose_pipeline2,
    'pipeline2_compose_epic': pipeline2_compose.compose_pipeline2_epic,
}


#
# HTTP Method const values
#
get_method = 'GET'
post_method = 'POST'
put_method = 'PUT'
delete_method = 'DELETE'
options_method = 'OPTIONS'

db_names = set(os.environ['db_name'].split(','))

print('RestApi-MySql-Lambda init code executing.')

SAFE_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

# The same integer grammar auth_utils._reference_value enforces for a body-
# supplied id — MySQL's, not Python's (req #3122's canonicalization rule).
# QSP values arrive as strings, so this is the ONE place that grammar needs
# restating for a query-string id rather than a body field.
_ID_QSP_RE = re.compile(r'^[+-]?[0-9]+$')


def _parse_id_qsp(event):
    """The `id` query-string parameter as an int, or None if absent/invalid."""
    qsp = event.get('queryStringParameters') or {}
    raw = qsp.get('id')
    if raw is None or not _ID_QSP_RE.match(raw.strip()):
        return None
    return int(raw.strip())

def parse_path(path):

    #
    # Split first level of path into database.
    # Second level of path into table.
    # Save aside the database/table connection as applicable.
    #
    split_path = path[1:].split('/')
    database = split_path[0]
    table = split_path[1] if len(split_path) > 1 else ''

    if table and not SAFE_NAME_RE.match(table):
        return {'path': path, 'database': database, 'table': '', 'conn': '', 'error': f"Invalid table name: {table}"}

    conn = get_connection(database) if database in db_names else ''

    #varDump({'path': path, 'database': database, 'table': table}, 'parse_path results', 'json')
    return {'path': path, 'database': database, 'table': table, 'conn': conn}


#FAAS ENTRY POINT: the AWS Lambda function is configured to call this function by name.
def lambda_handler(event, context):
    db_info = None
    try:
        #varDump(event, 'lambda_handler dump event')
        #varDump(context, 'lambda_handler context')
        path = event.get('path')
        print(f"Lambda Handler Invoked for {path}.{event['httpMethod']}")

        if path:
            db_info = parse_path(path)
        else:
            return compose_rest_response(400, '', f"No path provided")

        if 'error' in db_info:
            return compose_rest_response(400, '', db_info['error'])

        if db_info['database'] in db_names:
            response = rest_api_from_table(event, db_info)
        else:
            response = compose_rest_response(404, '', f"URL/path not found: {path}")

        return response
    except pymysql.OperationalError as e:
        code = e.args[0] if e.args else 0
        if code == 1040:
            print(f"DB_CONNECTION_LIMIT ({code}): {e}")
            return compose_rest_response(503, '', 'DB_CONNECTION_LIMIT')
        print(f"DB_ERROR ({code}): {e}")
        return compose_rest_response(503, '', 'DB_UNAVAILABLE')
    except Exception as e:
        print(f"UNHANDLED_EXCEPTION {type(e).__name__}: {e}")
        return compose_rest_response(503, '', 'SERVICE_UNAVAILABLE')
    finally:
        if db_info and db_info.get('conn'):
            try:
                db_info['conn'].close()
            except Exception:
                pass

def rest_api_from_table(event, db_info):

    #varDump(db_info, "db_info at start of rest_api_from_table call")
    database = db_info['database']
    table = db_info['table']
    conn = db_info['conn']
    http_method = event.get('httpMethod')

    if not event:
        print('no event')
        return compose_rest_response(500, '', 'REST API call received with no event')

    if not conn:
        print('no conn')
        return compose_rest_response(500, '', 'REST API call, no database connection')

    if not http_method:
        print('No HTTP method')
        return compose_rest_response(500, '', 'REST API call received with no HTTP method')

    # OPTIONS (CORS preflight) — no auth required
    if http_method == options_method:
        return compose_rest_response(200, '', '')

    # Extract authenticated user from Cognito authorizer claims
    authenticated_user = get_authenticated_user(event)

    # req #3367 — the composing route, dispatched BEFORE the generic gateway
    # (these are not real tables, so DESC/CRUD below would only ever fail).
    if table in PIPELINE2_COMPOSE_ROUTES:
        return _rest_pipeline2_compose(table, conn, event, http_method,
                                       authenticated_user)

    # Block unauthenticated access to user-scoped tables.
    #
    # JUNCTION_OWNERSHIP tables join in (req #3122). Their scoping is derived
    # from a parent's creator_fk, so with no identity there is nothing to derive
    # it FROM — every WHERE clause below would simply omit the predicate and hand
    # back every user's rows. API Gateway's Cognito authorizer should mean this
    # never fires; it is the second lock, for the day the authorizer is
    # misconfigured on one route.
    if (table in CREATOR_FK_TABLES or table == PROFILE_TABLE
            or table in JUNCTION_OWNERSHIP):
        if authenticated_user is None:
            print(f'Auth: unauthenticated request to user table {table}')
            return compose_rest_response(403, '', 'FORBIDDEN')

    body = None
    if event['body'] is not None:
        body = json.loads(event['body'])

    #
    # FILTER BY HTTP METHOD
    #
    if http_method == put_method:

        # PUT Method
        return rest_put(put_method, conn, database, table, body, authenticated_user)

    elif http_method == get_method:

        # GET Method
        if table:
            return rest_get_table(get_method, conn, database, table, event, authenticated_user)
        else:
            return rest_get_database(get_method, conn, database)

    elif http_method == post_method:

        # POST Method
        return rest_post(post_method, conn, database, table, body, authenticated_user)

    elif http_method == delete_method:

        # DELETE Method
        return rest_delete(delete_method, conn, database, table, body, authenticated_user)


def _rest_pipeline2_compose(table, conn, event, http_method, authenticated_user):
    """req #3367 — GET-only, `id` as a query-string parameter, same shape as
    every other single-row lookup. Not a real table, so PUT/POST/DELETE and a
    missing/malformed `id` are refused here rather than reaching pymysql."""
    if http_method != get_method:
        return compose_rest_response(
            400, '', f"{table} is a read-only composed route; {http_method} not allowed")

    # Same gate the generic CREATOR_FK_TABLES check gives every other
    # user-scoped table — this route names none of the real table names that
    # check matches on, so it needs its own.
    if authenticated_user is None:
        print(f'Auth: unauthenticated request to composed route {table}')
        return compose_rest_response(403, '', 'FORBIDDEN')

    row_id = _parse_id_qsp(event)
    if row_id is None:
        return compose_rest_response(400, '', f"{table}: a valid integer 'id' query "
                                     "parameter is required")

    try:
        composed = PIPELINE2_COMPOSE_ROUTES[table](conn, row_id, authenticated_user)
    except ValueError as e:
        # A data-integrity issue (epic names a pipeline_fk that does not
        # resolve for this creator) — real but not the caller's fault to fix
        # by retrying, so 500 rather than 400/404.
        print(f"{table} data integrity error: {e}")
        return compose_rest_response(500, '', str(e))

    if composed is None:
        return compose_rest_response(404, '', 'NOT FOUND')
    return compose_rest_response(200, composed)
