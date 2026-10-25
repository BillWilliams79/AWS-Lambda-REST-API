"""The plan-layer LOCK guard (req #3649) — no DB.

`plan_lock.py` is the ONE enforcement point for `pipelines.locked`,
`initiatives.locked` and `epics.locked`: a locked row, or any row under a
locked ancestor, accepts no authoring — no child created, deleted or moved,
no requirement linked or unlinked, no dependency edge, no title/notes/run/
checkpoint/not_before/sort_order — while the lock itself and lifecycle state
(`pipeline_status`, `initiative_status`, `closed`) still write. An epic has no
lifecycle state (req #3750). The answer is 423 LOCKED with an object body naming the OUTERMOST
locked level.

Three properties, each held here:

* **The cascade is derived from one SELECT**, and the verdict names the
  outermost lock (unlocking an epic helps nobody while its plan is locked).
* **Nothing a lock does not protect opens a cursor** — the `ExplodingConn`
  routes: `locked` itself, a lifecycle status, an unauthenticated call, a table outside the plan layer.
* **The wiring is real**: `rest_post` / `rest_put` / `rest_delete` reach the
  guard through their real entry points, asserted both ways — a protected
  write is refused with 423 and never reaches the statement, a permitted
  write reaches the cursor.

# COVERS: SCH-040
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import plan_lock                                        # noqa: E402
from plan_lock import (PLAN_LOCK, plan_lock_guard, plan_lock_guard_delete,  # noqa: E402
                       plan_lock_lookups, resolve_locks)
from rest_post import rest_post                         # noqa: E402
from rest_put import rest_put                           # noqa: E402

USER = 'victim'

# The fixture plan. Pipeline 7 (unlocked) holds initiative 70 (unlocked) -> epics
# 700, 701 (701 locked) and initiative 71 (LOCKED) -> epic 710. Pipeline 8 is LOCKED
# and holds initiative 80 -> epic 800. Pipeline 9 belongs to a stranger.
PIPELINES = {7: ('victim', 0), 8: ('victim', 1), 9: ('stranger', 0)}
INITIATIVES = {70: (7, 0), 71: (7, 1), 80: (8, 0), 90: (9, 0)}
EPICS = {700: (70, 0), 701: (70, 1), 710: (71, 0), 800: (80, 0), 900: (90, 0)}
LINKS = {5001: 700, 5002: 701, 5003: 710}           # requirement_fk -> epic_fk
DEPS = {1: (700, 701), 2: (710, 700), 3: (800, 800)}  # id -> (epic_fk, dep_epic_fk)


def _chain(epic_id=None, initiative_id=None, pipeline_id=None):
    """The chain row the real SELECT would return, outermost first."""
    if epic_id is not None:
        initiative_id = EPICS[epic_id][0]
    if initiative_id is not None:
        pipeline_id = INITIATIVES[initiative_id][0]
    owner, p_locked = PIPELINES[pipeline_id]
    row = [pipeline_id, p_locked]
    if initiative_id is not None:
        row += [initiative_id, INITIATIVES[initiative_id][1]]
    if epic_id is not None:
        row += [epic_id, EPICS[epic_id][1]]
    return owner, tuple(row)


class FakeCursor:
    """Answers the chain SELECTs from the fixture above, by table and ids."""

    def __init__(self):
        self.queries = []
        self._result = []

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            # The statement itself: reaching it is what the wiring tests
            # below observe. Nothing here can run it.
            raise CursorRequested()
        chain = re.search(r'FROM (\w+) t', sql)
        if chain is None:
            # `parent_reference_guard`'s own `SELECT id, creator_fk FROM
            # <parent> WHERE id IN (...)`, which runs before this guard on the
            # real entry points — answered so the wiring tests reach it.
            parent = re.search(r'FROM (\w+)', sql).group(1)
            owner_of = {'pipelines': lambda i: PIPELINES[i][0],
                        'initiatives': lambda i: PIPELINES[INITIATIVES[i][0]][0],
                        'epics': lambda i: _chain(epic_id=i)[0]}[parent]
            known = {'pipelines': PIPELINES, 'initiatives': INITIATIVES,
                     'epics': EPICS}[parent]
            self._result = [(str(i), owner_of(int(i))) for i in params
                            if int(i) in known]
            return
        table = chain.group(1)
        where = sql.split('WHERE', 1)[1]
        *ids, user = params
        ids = [int(i) for i in ids]
        rows = []
        if 'seated_id' in sql:
            # `resolve_locked_seats` (req #3706): requirement ids -> their
            # seat's chain, the requirement id leading the row.
            seats = [(i, _chain(epic_id=LINKS[i])) for i in ids if i in LINKS]
            self._result = [(i,) + row for i, (owner, row) in seats if owner == user]
            return
        if 'below_id' in sql:
            # `resolve_locked_below`: the locked rows UNDER the deleted ones.
            out = []
            if table == 'initiatives':
                out = [(e, sid) for e in ids for sid, (ep, lk) in EPICS.items()
                       if ep == e and lk]
            elif table == 'pipelines' and 'JOIN epics' in sql:
                out = [(p, sid) for p in ids for sid, (ep, lk) in EPICS.items()
                       if INITIATIVES[ep][0] == p and lk]
            elif table == 'pipelines':
                out = [(p, eid) for p in ids for eid, (pp, lk) in INITIATIVES.items()
                       if pp == p and lk]
            self._result = [(own, below) for own, below in out
                            if PIPELINES[own if table == 'pipelines' else INITIATIVES[own][0]][0] == user]
            return
        if table == 'pipelines':
            rows = [_chain(pipeline_id=i) for i in ids if i in PIPELINES]
        elif table == 'initiatives':
            rows = [_chain(initiative_id=i) for i in ids if i in INITIATIVES]
        elif table == 'epics':
            rows = [_chain(epic_id=i) for i in ids if i in EPICS]
        elif table == 'epic_requirements':
            if 't.epic_fk' in where:
                rows = [_chain(epic_id=i) for i in ids if i in EPICS]
            else:
                rows = [_chain(epic_id=LINKS[i]) for i in ids if i in LINKS]
        elif table == 'epic_deps':
            if 't.epic_fk' in where:
                rows = [_chain(epic_id=i) for i in ids if i in EPICS]
            else:
                rows = [_chain(epic_id=DEPS[i][0]) for i in ids if i in DEPS]
        self._result = [row for owner, row in rows if owner == user]

    def fetchall(self):
        return self._result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Conn:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.opened = 0

    def cursor(self):
        self.opened += 1
        return self.cursor_obj


class ExplodingConn:
    def cursor(self):
        raise AssertionError('the lock guard opened a cursor it did not need')

    def rollback(self):
        raise AssertionError('rollback on a connection that must not be used')


class CursorRequested(Exception):
    """Raised the instant the write statement itself is executed."""


def _body(resp):
    return json.loads(resp['body'])


# ---------------------------------------------------------------------------
# Planning is pure
# ---------------------------------------------------------------------------

def test_a_put_writing_only_unlocked_keys_plans_no_lookup():
    for table, body in (('epics', {'id': 701, 'locked': 0}),
                        ('initiatives', {'id': 71, 'initiative_status': 'paused', 'closed': 1}),
                        ('pipelines', {'id': 8, 'pipeline_status': 'completed',
                                       'started_at': 'x', 'completed_at': 'y'}),
                        ('pipelines', {'id': 8, 'LOCKED': 0, 'creator_fk': 'v'}),
                        # req #3804 — closing a plan and its card's place on the
                        # Pipelines page are not plan content.
                        ('pipelines', {'id': 8, 'closed': 1}),
                        ('pipelines', {'id': 8, 'sort_order': -3})):
        assert plan_lock_lookups(table, [body], 'PUT') == ([], [], None), table


def test_a_card_reorder_across_locked_plans_plans_no_lookup():
    """req #3804 — a reorder renumbers every card in one bulk PUT; a locked
    plan among them must not turn it into a 423."""
    rows = [{'id': 8, 'sort_order': 0}, {'id': 9, 'sort_order': 1}]
    assert plan_lock_lookups('pipelines', rows, 'PUT') == ([], [], None)


def test_a_put_writing_an_authoring_key_plans_the_row():
    assert plan_lock_lookups('epics', [{'id': 701, 'title': 't'}],
                             'PUT') == (['701'], [], None)
    assert plan_lock_lookups('epics', [{'id': 701, 'CHECKPOINT': 0}],
                             'PUT') == (['701'], [], None)
    assert plan_lock_lookups('initiatives', [{'id': 71, 'sort_order': 2}],
                             'PUT') == (['71'], [], None)
    assert plan_lock_lookups('pipelines', [{'id': 8, 'description': 'd'}],
                             'PUT') == (['8'], [], None)


def test_a_move_plans_the_destination_parent_too():
    assert plan_lock_lookups('epics', [{'id': 700, 'initiative_fk': 71}],
                             'PUT') == (['700'], ['71'], None)
    assert plan_lock_lookups('initiatives', [{'id': 70, 'pipeline_fk': 8}],
                             'PUT') == (['70'], ['8'], None)


def test_a_post_plans_its_container():
    assert plan_lock_lookups('initiatives', [{'pipeline_fk': 8, 'title': 'e'}],
                             'POST') == ([], ['8'], None)
    assert plan_lock_lookups('epics', [{'initiative_fk': '71', 'title': 's'}],
                             'POST') == ([], ['71'], None)
    assert plan_lock_lookups('epic_requirements',
                             [{'epic_fk': 710, 'requirement_fk': 1}],
                             'POST') == ([], ['710'], None)
    assert plan_lock_lookups('epic_deps',
                             [{'epic_fk': 710, 'dep_epic_fk': 700}],
                             'POST') == ([], ['710'], None)
    # A pipeline has no container.
    assert plan_lock_lookups('pipelines', [{'title': 'p'}], 'POST') == ([], [], None)


def test_an_uncanonical_id_is_a_400_before_any_lookup():
    assert plan_lock_lookups('epics', [{'id': '701abc', 'title': 't'}],
                             'PUT') == ([], [], (400, 'BAD REQUEST'))
    assert plan_lock_lookups('initiatives', [{'pipeline_fk': 8.5, 'title': 'e'}],
                             'POST') == ([], [], (400, 'BAD REQUEST'))
    assert plan_lock_lookups('initiatives', ['not-a-dict'], 'POST') == (
        [], [], (400, 'BAD REQUEST'))


def test_a_table_outside_the_plan_layer_plans_nothing():
    assert plan_lock_lookups('tasks', [{'id': 1, 'title': 't'}], 'PUT') == ([], [], None)


# ---------------------------------------------------------------------------
# Resolution — the cascade, from one SELECT
# ---------------------------------------------------------------------------

def test_resolve_names_the_outermost_locked_level():
    cursor = FakeCursor()
    assert resolve_locks(cursor, 'epics', 't.id IN (%s, %s, %s, %s)',
                         [700, 701, 710, 800], USER) == [
        (701, 'epic', 701),          # its own lock
        (710, 'initiative', 71),           # under a locked initiative
        (800, 'pipeline', 8)]        # under a locked plan, outermost named
    assert len(cursor.queries) == 1


def test_resolve_ignores_rows_another_creator_owns():
    cursor = FakeCursor()
    assert resolve_locks(cursor, 'epics', 't.id IN (%s)', [900], USER) == []
    assert resolve_locks(cursor, 'pipelines', 't.id IN (%s)', [9], USER) == []


def test_resolve_covers_every_registered_table_with_its_own_chain():
    cursor = FakeCursor()
    assert resolve_locks(cursor, 'pipelines', 't.id IN (%s, %s)', [7, 8], USER) == [
        (8, 'pipeline', 8)]
    assert resolve_locks(cursor, 'initiatives', 't.id IN (%s, %s, %s)', [70, 71, 80], USER) == [
        (71, 'initiative', 71), (80, 'pipeline', 8)]
    assert resolve_locks(cursor, 'epic_requirements',
                         't.requirement_fk = %s', [5003], USER) == [(710, 'initiative', 71)]
    assert resolve_locks(cursor, 'epic_deps', 't.id IN (%s, %s)',
                         [1, 3], USER) == [(800, 'pipeline', 8)]
    for table in PLAN_LOCK:
        assert table in plan_lock._CHAINS


# ---------------------------------------------------------------------------
# The guard — 423, with the object body
# ---------------------------------------------------------------------------

def test_put_on_a_locked_epic_is_423_naming_the_lock():
    conn = Conn()
    resp = plan_lock_guard(conn, 'epics', [{'id': 710, 'title': 'x'}],
                           USER, 'PUT')
    assert resp['statusCode'] == 423
    body = _body(resp)
    assert body['error'] == 'LOCKED'
    assert (body['table'], body['id'], body['locked_by'], body['locked_id']) == (
        'epics', 710, 'initiative', 71)
    assert 'locked by initiative 71' in body['message'] and 'unlock' in body['message']
    assert conn.opened == 1


def test_put_on_an_unlocked_row_passes_after_one_lookup():
    conn = Conn()
    assert plan_lock_guard(conn, 'epics', [{'id': 700, 'title': 'x'}],
                           USER, 'PUT') is None
    assert conn.opened == 1
    assert len(conn.cursor_obj.queries) == 1


def test_a_bulk_put_is_refused_whole_on_one_locked_row():
    resp = plan_lock_guard(Conn(), 'epics',
                           [{'id': 700, 'notes': 'a'}, {'id': 701, 'notes': 'b'}],
                           USER, 'PUT')
    assert resp['statusCode'] == 423
    assert _body(resp)['id'] == 701


def test_a_locked_plan_cascades_to_its_initiatives_and_epics():
    assert plan_lock_guard(Conn(), 'initiatives', [{'id': 80, 'title': 'x'}],
                           USER, 'PUT')['statusCode'] == 423
    assert _body(plan_lock_guard(Conn(), 'epics',
                                 [{'id': 800, 'run': 'manual'}],
                                 USER, 'PUT'))['locked_by'] == 'pipeline'


def test_post_into_a_locked_container_is_423():
    resp = plan_lock_guard(Conn(), 'epics',
                           [{'initiative_fk': 71, 'title': 'new'}], USER, 'POST')
    assert resp['statusCode'] == 423
    body = _body(resp)
    assert (body['table'], body['id'], body['locked_by']) == ('initiatives', 71, 'initiative')
    assert 'cannot add epics under initiatives 71' in body['message']
    assert plan_lock_guard(Conn(), 'initiatives', [{'pipeline_fk': 8, 'title': 'e'}],
                           USER, 'POST')['statusCode'] == 423
    assert plan_lock_guard(Conn(), 'epic_requirements',
                           [{'epic_fk': 701, 'requirement_fk': 9}],
                           USER, 'POST')['statusCode'] == 423
    assert plan_lock_guard(Conn(), 'epic_deps',
                           [{'epic_fk': 800, 'dep_epic_fk': 700}],
                           USER, 'POST')['statusCode'] == 423
    # An unlocked container is fine; a stranger's is not this guard's answer.
    assert plan_lock_guard(Conn(), 'epics', [{'initiative_fk': 70}],
                           USER, 'POST') is None
    assert plan_lock_guard(Conn(), 'epics', [{'initiative_fk': 90}],
                           USER, 'POST') is None


def test_a_move_into_a_locked_destination_is_423():
    resp = plan_lock_guard(Conn(), 'epics', [{'id': 700, 'initiative_fk': 71}],
                           USER, 'PUT')
    assert resp['statusCode'] == 423
    assert 'cannot move epics under initiatives 71' in _body(resp)['message']


def test_the_lock_itself_and_lifecycle_state_write_without_a_cursor():
    for table, body in (('epics', {'id': 710, 'locked': 0}),
                        ('initiatives', {'id': 80, 'initiative_status': 'paused'}),
                        ('initiatives', {'id': 71, 'closed': 1, 'locked': 1}),
                        ('pipelines', {'id': 8, 'pipeline_status': 'paused',
                                       'completed_at': 'NULL'})):
        assert plan_lock_guard(ExplodingConn(), table, [body], USER, 'PUT') is None, table


def test_no_identity_and_no_plan_table_open_no_cursor():
    assert plan_lock_guard(ExplodingConn(), 'epics',
                           [{'id': 710, 'title': 'x'}], None, 'PUT') is None
    assert plan_lock_guard(ExplodingConn(), 'tasks', [{'id': 1, 'title': 'x'}],
                           USER, 'PUT') is None
    assert plan_lock_guard(ExplodingConn(), 'pipelines', [{'title': 'p'}],
                           USER, 'POST') is None
    assert plan_lock_guard_delete(ExplodingConn(), 'tasks', 't.id = %s', [1],
                                  USER) is None


def test_delete_of_a_locked_row_or_its_children_is_423():
    assert plan_lock_guard_delete(Conn(), 'epics', 't.id = %s', [710],
                                  USER)['statusCode'] == 423
    assert plan_lock_guard_delete(Conn(), 'initiatives', 't.id IN (%s, %s)', [70, 71],
                                  USER)['statusCode'] == 423
    assert plan_lock_guard_delete(Conn(), 'pipelines', 't.id = %s', [8],
                                  USER)['statusCode'] == 423
    assert plan_lock_guard_delete(Conn(), 'epic_requirements',
                                  't.epic_fk = %s', [701], USER)['statusCode'] == 423
    assert plan_lock_guard_delete(Conn(), 'epic_deps',
                                  't.id IN (%s)', [3], USER)['statusCode'] == 423
    assert plan_lock_guard_delete(Conn(), 'epic_deps',
                                  't.id IN (%s)', [1], USER) is None
    assert plan_lock_guard_delete(Conn(), 'epics', 't.id = %s', [700],
                                  USER) is None


def test_a_failed_check_is_a_500_never_a_pass():
    class BrokenCursor(FakeCursor):
        def execute(self, sql, params=()):
            import pymysql
            raise pymysql.err.OperationalError(2013, 'Lost connection')

    class BrokenConn(Conn):
        def __init__(self):
            super().__init__()
            self.cursor_obj = BrokenCursor()

    resp = plan_lock_guard(BrokenConn(), 'epics', [{'id': 700, 'title': 'x'}],
                           USER, 'PUT')
    assert resp['statusCode'] == 500
    assert 'lock check failed' in json.loads(resp['body'])


# ---------------------------------------------------------------------------
# The wiring — through the real entry points
# ---------------------------------------------------------------------------

# `Conn` answers every guard SELECT and its cursor raises `CursorRequested`
# on the statement itself, so reaching the write is observable.
GuardConn = Conn


def test_rest_put_refuses_a_locked_epic_before_the_update():
    resp = rest_put('PUT', GuardConn(), 'darwin_dev', 'epics',
                    [{'id': 710, 'title': 'renamed'}], authenticated_user=USER)
    assert resp['statusCode'] == 423
    assert _body(resp)['locked_by'] == 'initiative'


def test_rest_put_lets_the_lock_itself_on_a_locked_epic_reach_the_update():
    with pytest.raises(CursorRequested):
        rest_put('PUT', GuardConn(), 'darwin_dev', 'epics',
                 [{'id': 710, 'locked': 0}], authenticated_user=USER)


def test_rest_post_refuses_a_child_of_a_locked_container_before_the_insert():
    resp = rest_post('POST', GuardConn(), 'darwin_dev', 'epic_deps',
                     {'epic_fk': 800, 'dep_epic_fk': 700}, authenticated_user=USER)
    assert resp['statusCode'] == 423
    assert _body(resp)['locked_by'] == 'pipeline'
    resp = rest_post('POST', GuardConn(), 'darwin_dev', 'epics',
                     [{'initiative_fk': 70, 'title': 'a'}, {'initiative_fk': 71, 'title': 'b'}],
                     authenticated_user=USER)
    assert resp['statusCode'] == 423


def test_rest_post_lets_a_child_of_an_unlocked_container_reach_the_insert():
    with pytest.raises(CursorRequested):
        rest_post('POST', GuardConn(), 'darwin_dev', 'epics',
                  {'initiative_fk': 70, 'title': 'a'}, authenticated_user=USER)


# ---------------------------------------------------------------------------
# Review findings (req #3649): W1 — the cascade runs DOWN; W4 — lifting a lock
# ---------------------------------------------------------------------------

def test_deleting_an_unlocked_container_with_a_locked_row_under_it_is_423():
    """Initiative 70 is open but holds locked epic 701; plan 7 is open but holds
    locked initiative 71. Deleting either would cascade through a lock."""
    resp = plan_lock_guard_delete(Conn(), 'initiatives', 't.id = %s', [70], USER)
    assert resp['statusCode'] == 423
    body = _body(resp)
    assert (body['table'], body['id'], body['locked_by'], body['locked_id']) == (
        'initiatives', 70, 'epic', 701)
    assert 'under it is locked' in body['message']
    resp = plan_lock_guard_delete(Conn(), 'pipelines', 't.id = %s', [7], USER)
    assert resp['statusCode'] == 423
    assert _body(resp)['locked_by'] == 'initiative'
    # A container with nothing locked under it still deletes.
    assert plan_lock_guard_delete(Conn(), 'initiatives', 't.id = %s', [80], USER) is not None  # plan 8 locked
    assert plan_lock_guard_delete(Conn(), 'pipelines', 't.id = %s', [9], USER) is None    # stranger's
    assert plan_lock_guard_delete(Conn(), 'initiatives', 't.id = %s', [90], USER) is None


def test_a_put_that_lifts_the_rows_own_lock_may_edit_in_the_same_call():
    # 701 is locked in its own right: unlocking and renaming together passes.
    assert plan_lock_guard(Conn(), 'epics',
                           [{'id': 701, 'locked': 0, 'title': 'renamed'}],
                           USER, 'PUT') is None
    assert plan_lock_guard(Conn(), 'epics',
                           [{'id': 701, 'LOCKED': '0', 'notes': 'n'}],
                           USER, 'PUT') is None
    # ...but not an ANCESTOR's lock: 710 sits under locked initiative 71.
    resp = plan_lock_guard(Conn(), 'epics',
                           [{'id': 710, 'locked': 0, 'title': 'renamed'}], USER, 'PUT')
    assert resp['statusCode'] == 423 and _body(resp)['locked_by'] == 'initiative'
    # Locking (locked=1) alongside an edit on a locked row is still refused.
    resp = plan_lock_guard(Conn(), 'epics',
                           [{'id': 701, 'locked': 1, 'title': 'renamed'}], USER, 'PUT')
    assert resp['statusCode'] == 423


def test_resolve_locks_reads_a_dict_cursor_row_too():
    class DictRowCursor(FakeCursor):
        def fetchall(self):
            levels = [lvl for lvl, _, _ in plan_lock._CHAINS['epics'][2]]
            out = []
            for row in super().fetchall():
                d = {}
                for (lvl, i, l) in zip(levels, row[0::2], row[1::2]):
                    d['%s_id' % lvl] = i
                    d['%s_locked' % lvl] = l
                out.append(d)
            return out
    assert resolve_locks(DictRowCursor(), 'epics', 't.id IN (%s, %s)',
                         [700, 710], USER) == [(710, 'initiative', 71)]


# ---------------------------------------------------------------------------
# req #3706 — deleting a requirement CASCADEs its seat, so a seat under a
# locked epic refuses the requirement delete
# ---------------------------------------------------------------------------

def test_deleting_a_requirement_seated_on_a_locked_epic_is_423():
    # 5002 sits on epic 701 (locked itself); 5003 on epic 710 (initiative 71 locked).
    resp = plan_lock_guard_delete(Conn(), 'requirements', 't.id = %s', [5002], USER)
    assert resp['statusCode'] == 423
    body = _body(resp)
    assert (body['table'], body['id'], body['locked_by'], body['locked_id']) == (
        'requirements', 5002, 'epic', 701)
    assert 'seated on epic 701' in body['message']
    body = _body(plan_lock_guard_delete(Conn(), 'requirements', 't.id = %s',
                                        [5003], USER))
    assert (body['locked_by'], body['locked_id']) == ('initiative', 71)


def test_deleting_an_unlocked_seated_or_unseated_requirement_passes():
    assert plan_lock_guard_delete(Conn(), 'requirements', 't.id = %s', [5001],
                                  USER) is None
    assert plan_lock_guard_delete(Conn(), 'requirements', 't.id = %s', [4242],
                                  USER) is None


def test_a_bulk_requirement_delete_is_refused_whole_on_one_locked_seat():
    resp = plan_lock_guard_delete(Conn(), 'requirements', 't.id IN (%s, %s)',
                                  [5001, 5003], USER)
    assert resp['statusCode'] == 423


def test_rest_delete_refuses_a_locked_seat_before_the_delete():
    # The bulk path: the single path's DESC key check needs a real table.
    from rest_delete import _rest_delete_bulk
    resp = _rest_delete_bulk('DELETE', GuardConn(), 'requirements',
                             [{'id': 5003}], USER)
    assert resp['statusCode'] == 423
    with pytest.raises(CursorRequested):
        _rest_delete_bulk('DELETE', GuardConn(), 'requirements', [{'id': 5001}], USER)

