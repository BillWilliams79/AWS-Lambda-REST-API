"""Every CRUD entry point survives a pymysql error carrying only ONE arg.

This is the regression guard for the defect req #3059's code review found, and it
is deliberately separate from `test_unit_conflict.py`: that file tests
`error_detail` as a pure function, which proves the helper is safe but proves
NOTHING about whether the modules actually call it. Someone could reintroduce
`f"{e.args[0]} {e.args[1]}"` at any of the eleven sites and every other unit test
would stay green, because the tests that drive these functions for real need a
live database and are all skipped without `exports.sh`.

The bug: pymysql raises one-arg errors from its own plumbing —
`ProgrammingError("Cursor closed")` (cursors.py), `Error("Already closed")`
(connections.py). Reading `e.args[1]` inside `except pymysql.Error` raised
IndexError, which escaped the handler's per-module error path and was swallowed
by `lambda_handler`'s blanket `except Exception` as a 503 SERVICE_UNAVAILABLE
that named nothing. On a GET that 503 is worse than cosmetic: darwin-mcp retries
idempotent GETs once on 503, so it silently double-fetched before surfacing
DB_UNAVAILABLE.

No database required — the connection is a stub whose cursor() raises.
"""
import json

import pymysql
import pytest

from rest_delete import rest_delete
from rest_get_database import rest_get_database
from rest_get_table import rest_get_table
from rest_post import rest_post
from rest_put import rest_put


class OneArgErrorConn:
    """A connection whose every cursor() raises pymysql's one-arg error.

    Mirrors pymysql's real behaviour: `Cursor.execute` on a closed cursor raises
    `ProgrammingError('Cursor closed')` — args of length 1, no errno.
    """

    def __init__(self, exc=None):
        self.exc = exc or pymysql.ProgrammingError('Cursor closed')
        self.rollbacks = 0

    def cursor(self):
        raise self.exc

    def rollback(self):
        self.rollbacks += 1


def body_of(response):
    return json.loads(response['body'])


# (label, callable) — one entry per code path that formats a pymysql error.
CRUD_PATHS = [
    ('POST single', lambda conn: rest_post(
        'POST', conn, 'darwin_dev', 'areas', {'area_name': 'x'}, None)),
    ('POST bulk', lambda conn: rest_post(
        'POST', conn, 'darwin_dev', 'areas', [{'area_name': 'x'}], None)),
    ('PUT', lambda conn: rest_put(
        'PUT', conn, 'darwin_dev', 'areas', [{'id': 1, 'area_name': 'x'}], None)),
    ('DELETE single', lambda conn: rest_delete(
        'DELETE', conn, 'darwin_dev', 'areas', {'id': 1}, None)),
    ('DELETE bulk', lambda conn: rest_delete(
        'DELETE', conn, 'darwin_dev', 'areas', [{'id': 1}], None)),
    ('GET table', lambda conn: rest_get_table(
        'GET', conn, 'darwin_dev', 'areas', {'queryStringParameters': None}, None)),
    ('GET database', lambda conn: rest_get_database('GET', conn, 'darwin_dev')),
]


@pytest.mark.parametrize('label, call', CRUD_PATHS, ids=[p[0] for p in CRUD_PATHS])
def test_a_one_arg_pymysql_error_yields_a_500_not_an_escaped_indexerror(label, call):
    # The assertion that matters is simply that this RETURNS. Before the fix the
    # IndexError propagated out of `call` and pytest reported an error, not a
    # failure — which is exactly how it stayed invisible in production as a 503.
    response = call(OneArgErrorConn())

    assert response['statusCode'] == 500, label
    # The driver's text still reaches the client. pymysql puts a one-arg error's
    # message in args[0], so it lands in the errno slot — odd-looking, but it
    # NAMES the failure, which the swallowed 503 never did.
    assert 'Cursor closed' in body_of(response), label


@pytest.mark.parametrize('label, call', CRUD_PATHS, ids=[p[0] for p in CRUD_PATHS])
def test_a_zero_arg_pymysql_error_also_returns(label, call):
    response = call(OneArgErrorConn(pymysql.Error()))
    assert response['statusCode'] == 500, label


@pytest.mark.parametrize('label, call', [p for p in CRUD_PATHS if 'bulk' in p[0]],
                         ids=[p[0] for p in CRUD_PATHS if 'bulk' in p[0]])
def test_the_bulk_paths_still_roll_back_before_reporting(label, call):
    """The rollback must not be skipped by the error-formatting change.

    Both bulk paths issue ONE multi-value statement, so a failure there leaves a
    partially-applied transaction if nothing rolls it back.
    """
    conn = OneArgErrorConn()
    call(conn)
    assert conn.rollbacks == 1, label


def test_a_one_arg_error_is_never_mistaken_for_a_conflict():
    """The 409 gate must not fire on an error with no errno.

    `integrity_errno` sees the string 'Cursor closed' in the errno slot. It is
    hashable and not in INTEGRITY_ERRNOS, so it returns None — but if that ever
    regressed, the client would get a 409 promising that retrying with different
    data can succeed, for a dead cursor.
    """
    for label, call in CRUD_PATHS:
        response = call(OneArgErrorConn())
        assert response['statusCode'] != 409, label
