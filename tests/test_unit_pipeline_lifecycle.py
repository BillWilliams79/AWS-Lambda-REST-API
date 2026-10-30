"""The pipeline lifecycle guard's planning and derivation, no database (req #3965).

`tests/test_pipeline_lifecycle.py` proves the same rules end to end against
darwin_dev; this file pins the rule table, the 400s, and the bulk-POST column
unification with a fake cursor.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pipeline_lifecycle as lifecycle                  # noqa: E402
from pipeline_lifecycle import (PIPELINE_STATUSES, plan_lifecycle,   # noqa: E402
                                pipeline_lifecycle_guard)


class _Cursor:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.log.append((sql, params))

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows=()):
        self.rows, self.log = list(rows), []

    def cursor(self):
        return _Cursor(self.rows, self.log)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(lifecycle, '_now', lambda: '2026-10-30 12:00:00')


def test_the_seven_values_in_order():
    assert PIPELINE_STATUSES == ('authoring', 'authorized', 'orchestration_ready',
                                 'orchestrating', 'met', 'wontfix', 'deferred')


def test_darwin_mcp_validates_the_same_seven():
    """The domain lives in two places (this gateway and darwin-mcp); held equal
    here whenever the DarwinAI-Config checkout sits beside this repo."""
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'darwin-mcp',
                        'services', 'pipelines2.py')
    if not os.path.exists(path):
        pytest.skip('darwin-mcp is not checked out beside Lambda-Rest')
    match = re.search(r"_VALID_PIPELINE2_STATUSES\s*=\s*[{(\[]([^})\]]*)[})\]]",
                      open(path).read())
    assert match, '_VALID_PIPELINE2_STATUSES not found'
    assert set(re.findall(r"'([a-z_]+)'", match.group(1))) == set(PIPELINE_STATUSES)


@pytest.mark.parametrize('value', ['draft', 'active', 'paused', 'completed', '',
                                   None, 'ORCHESTRATING', 7])
def test_an_unknown_status_is_400_before_any_read(value):
    conn = _Conn()
    resp = pipeline_lifecycle_guard(conn, 'pipelines', [{'id': 1, 'pipeline_status': value}],
                                    'u', 'PUT')
    assert resp['statusCode'] == 400
    assert conn.log == []


def test_other_tables_and_status_free_writes_are_untouched():
    for table, body in (('initiatives', {'id': 1, 'initiative_status': 'paused'}),
                        ('pipelines', {'id': 1, 'title': 't'})):
        conn = _Conn()
        before = dict(body)
        assert pipeline_lifecycle_guard(conn, table, [body], 'u', 'PUT') is None
        assert body == before and conn.log == []


def test_clearing_needs_no_read():
    work, lookups, refusal = plan_lifecycle(
        'pipelines', [{'id': 3, 'pipeline_status': 'orchestration_ready'}], 'PUT')
    assert refusal is None and lookups == [] and len(work) == 1


@pytest.mark.parametrize('status', ['authoring', 'authorized', 'orchestration_ready'])
def test_a_pre_run_status_clears_completed_and_keeps_started(status):
    body = {'id': 3, 'pipeline_status': status}
    assert pipeline_lifecycle_guard(_Conn(), 'pipelines', [body], 'u', 'PUT') is None
    assert body == {'id': 3, 'pipeline_status': status, 'completed_at': 'NULL'}


# COVERS: SCH-050
def test_orchestrating_stamps_started_only_when_unset():
    unset = {'id': 3, 'pipeline_status': 'orchestrating'}
    conn = _Conn([{'id': 3, 'started_at': None, 'completed_at': '2026-01-01 00:00:00'}])
    assert pipeline_lifecycle_guard(conn, 'pipelines', [unset], 'u', 'PUT') is None
    assert unset['started_at'] == '2026-10-30 12:00:00'
    assert unset['completed_at'] == 'NULL'
    sql, params = conn.log[0]
    assert 'creator_fk = %s' in sql and params == ('3', 'u')

    already = {'id': 3, 'pipeline_status': 'orchestrating'}
    conn = _Conn([(3, '2026-09-01 00:00:00', None)])          # a tuple cursor row
    assert pipeline_lifecycle_guard(conn, 'pipelines', [already], 'u', 'PUT') is None
    assert 'started_at' not in already


@pytest.mark.parametrize('status', ['met', 'wontfix', 'deferred'])
def test_a_terminal_status_stamps_completed_only_when_unset(status):
    body = {'id': 3, 'pipeline_status': status}
    conn = _Conn([{'id': 3, 'started_at': None, 'completed_at': None}])
    assert pipeline_lifecycle_guard(conn, 'pipelines', [body], 'u', 'PUT') is None
    assert body == {'id': 3, 'pipeline_status': status,
                    'completed_at': '2026-10-30 12:00:00'}

    body = {'id': 3, 'pipeline_status': status}
    conn = _Conn([{'id': 3, 'started_at': None, 'completed_at': '2026-08-09 11:45:15'}])
    assert pipeline_lifecycle_guard(conn, 'pipelines', [body], 'u', 'PUT') is None
    assert 'completed_at' not in body


def test_a_row_the_caller_does_not_own_gets_no_stamp():
    body = {'id': 99, 'pipeline_status': 'met'}
    assert pipeline_lifecycle_guard(_Conn([]), 'pipelines', [body], 'u', 'PUT') is None
    assert 'completed_at' not in body


def test_the_callers_own_stamp_wins():
    body = {'id': 3, 'pipeline_status': 'met', 'COMPLETED_AT': '2026-08-09 11:45:15'}
    assert pipeline_lifecycle_guard(_Conn([]), 'pipelines', [body], 'u', 'PUT') is None
    assert body == {'id': 3, 'pipeline_status': 'met', 'COMPLETED_AT': '2026-08-09 11:45:15'}


def test_a_post_stamps_without_reading_and_never_writes_a_clear():
    conn = _Conn()
    orchestrating = {'title': 't', 'pipeline_status': 'orchestrating'}
    authoring = {'title': 't', 'pipeline_status': 'authoring'}
    assert pipeline_lifecycle_guard(conn, 'pipelines', [orchestrating], 'u', 'POST') is None
    assert pipeline_lifecycle_guard(conn, 'pipelines', [authoring], 'u', 'POST') is None
    assert conn.log == []
    assert orchestrating == {'title': 't', 'pipeline_status': 'orchestrating',
                             'started_at': '2026-10-30 12:00:00'}
    assert authoring == {'title': 't', 'pipeline_status': 'authoring'}


def test_a_bulk_post_keeps_one_column_list():
    bodies = [{'title': 'a', 'pipeline_status': 'orchestrating'},
              {'title': 'b', 'pipeline_status': 'met'},
              {'title': 'c', 'pipeline_status': 'authoring'}]
    assert pipeline_lifecycle_guard(_Conn(), 'pipelines', bodies, 'u', 'POST') is None
    assert len({frozenset(b) for b in bodies}) == 1
    assert bodies[0]['started_at'] == '2026-10-30 12:00:00'
    assert bodies[0]['completed_at'] == 'NULL'
    assert bodies[1]['completed_at'] == '2026-10-30 12:00:00'
    assert bodies[2]['started_at'] == 'NULL' and bodies[2]['completed_at'] == 'NULL'


@pytest.mark.parametrize('status', ['met', 'authoring'])   # a stamping and a clearing one
def test_an_id_mysql_would_coerce_is_400(status):
    resp = pipeline_lifecycle_guard(_Conn(), 'pipelines',
                                    [{'id': '3abc', 'pipeline_status': status}], 'u', 'PUT')
    assert resp['statusCode'] == 400
