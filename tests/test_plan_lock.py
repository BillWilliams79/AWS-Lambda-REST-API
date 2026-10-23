"""The plan-layer LOCK guard, end to end against darwin_dev (req #3649).

`tests/test_unit_plan_lock.py` proves the guard's planning and the wiring with a
fake cursor; this file proves the SQL — one JOIN per chain, the cascade, the
creator scoping — against the real tables, through the real `lambda_handler`,
and that a locked row still accepts exactly the writes a lock does not protect.

# COVERS: SCH-041
"""
import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from test_pipeline2_compose import _invoker, _purge, extract_id   # noqa: E402


@pytest.fixture(scope="module")
def owner_fk():
    return f"planlock-owner-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def owner(owner_fk, db_connection):
    invoke = _invoker(owner_fk)
    invoke('POST', '/darwin_dev/profiles', body={
        'id': owner_fk, 'name': 'planlock owner', 'email': 'planlock@test.invalid'})
    yield invoke
    _purge(db_connection, owner_fk)


@pytest.fixture(scope="module")
def plan(owner):
    """Pipeline P: initiative A (epics a1, a2; a2 depends on a1) and initiative B (epic
    b1). One swarm_ready requirement seated on a1, one unseated."""
    ids = {}
    resp = owner('POST', '/darwin_dev/projects', body={'project_name': 'planlock project'})
    ids['project'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/categories',
                 body={'category_name': 'planlock category', 'project_fk': ids['project']})
    ids['category'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/pipelines', body={
        'title': 'planlock plan', 'pipeline_status': 'active', 'execution_mode': 'parallel'})
    ids['pipeline'] = int(extract_id(resp))
    for key, title in (('initiative_a', 'A'), ('initiative_b', 'B')):
        resp = owner('POST', '/darwin_dev/initiatives', body={
            'pipeline_fk': ids['pipeline'], 'title': title, 'initiative_status': 'active',
            'category_fk': ids['category'], 'closed': '0'})
        ids[key] = int(extract_id(resp))
    for key, initiative, title in (('a1', 'initiative_a', 'a1'), ('a2', 'initiative_a', 'a2'), ('b1', 'initiative_b', 'b1')):
        resp = owner('POST', '/darwin_dev/epics',
                     body={'initiative_fk': ids[initiative], 'title': title, 'run': 'auto'})
        ids[key] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/epic_deps',
                 body={'epic_fk': ids['a2'], 'dep_epic_fk': ids['a1']})
    for key in ('req_seated', 'req_free'):
        resp = owner('POST', '/darwin_dev/requirements', body={
            'title': key, 'requirement_status': 'swarm_ready', 'category_fk': ids['category'],
            'coordination_type': 'implemented', 'ai_model': 'sonnet', 'effort': 'high'})
        ids[key] = int(extract_id(resp))
    owner('POST', '/darwin_dev/epic_requirements',
          body={'epic_fk': ids['a1'], 'requirement_fk': ids['req_seated']})
    return ids


def _put(owner, table, row):
    return owner('PUT', f'/darwin_dev/{table}', body=[row])


def _body(resp):
    return json.loads(resp['body'])


def _set_locked(owner, table, row_id, flag):
    resp = _put(owner, table, {'id': row_id, 'locked': flag})
    assert resp['statusCode'] in (200, 204), resp


def test_a_locked_epic_refuses_authoring_but_takes_the_lock(owner, plan):
    _set_locked(owner, 'epics', plan['a2'], 1)
    try:
        resp = _put(owner, 'epics', {'id': plan['a2'], 'title': 'renamed'})
        assert resp['statusCode'] == 423, resp
        body = _body(resp)
        assert body['error'] == 'LOCKED'
        assert (body['table'], body['id'], body['locked_by'], body['locked_id']) == (
            'epics', plan['a2'], 'epic', plan['a2'])
        assert 'unlock' in body['message']
        for field in ({'checkpoint': 0}, {'run': 'manual'}, {'notes': 'x'},
                      {'not_before': '2026-12-01 00:00:00'}):
            assert _put(owner, 'epics', {'id': plan['a2'], **field})['statusCode'] == 423, field
        # No child under it: a link, an edge.
        resp = owner('POST', '/darwin_dev/epic_requirements',
                     body={'epic_fk': plan['a2'], 'requirement_fk': plan['req_free']})
        assert resp['statusCode'] == 423, resp
        resp = owner('POST', '/darwin_dev/epic_deps',
                     body={'epic_fk': plan['a2'], 'dep_epic_fk': plan['b1']})
        assert resp['statusCode'] == 423, resp
        # ...and its existing edge cannot be removed, nor the epic itself.
        resp = owner('DELETE', '/darwin_dev/epic_deps', body={'epic_fk': plan['a2']})
        assert resp['statusCode'] == 423, resp
        resp = owner('DELETE', '/darwin_dev/epics', body={'id': plan['a2']})
        assert resp['statusCode'] == 423, resp
    finally:
        _set_locked(owner, 'epics', plan['a2'], 0)
    # Unlocked again, the same rename lands.
    resp = _put(owner, 'epics', {'id': plan['a2'], 'title': 'a2'})
    assert resp['statusCode'] in (200, 204), resp


def test_a_locked_initiative_cascades_to_its_epics_and_refuses_new_ones(owner, plan):
    _set_locked(owner, 'initiatives', plan['initiative_a'], 1)
    try:
        resp = _put(owner, 'epics', {'id': plan['a1'], 'title': 'x'})
        assert resp['statusCode'] == 423, resp
        assert (_body(resp)['locked_by'], _body(resp)['locked_id']) == ('initiative', plan['initiative_a'])
        resp = owner('POST', '/darwin_dev/epics',
                     body={'initiative_fk': plan['initiative_a'], 'title': 'new', 'run': 'auto'})
        assert resp['statusCode'] == 423, resp
        assert 'cannot add epics under initiatives' in _body(resp)['message']
        # Moving an epic INTO the locked initiative is refused; the other initiative is open.
        resp = _put(owner, 'epics', {'id': plan['b1'], 'initiative_fk': plan['initiative_a']})
        assert resp['statusCode'] == 423, resp
        resp = _put(owner, 'epics', {'id': plan['b1'], 'title': 'b1'})
        assert resp['statusCode'] in (200, 204), resp
        # The initiative's own authoring fields are frozen; its status and closure are not.
        assert _put(owner, 'initiatives', {'id': plan['initiative_a'], 'sort_order': 2})['statusCode'] == 423
        assert _put(owner, 'initiatives', {'id': plan['initiative_a'], 'initiative_status': 'paused'})['statusCode'] in (200, 204)
        assert _put(owner, 'initiatives', {'id': plan['initiative_a'], 'initiative_status': 'active'})['statusCode'] in (200, 204)
        resp = owner('DELETE', '/darwin_dev/initiatives', body={'id': plan['initiative_a']})
        assert resp['statusCode'] == 423, resp
    finally:
        _set_locked(owner, 'initiatives', plan['initiative_a'], 0)


def test_a_locked_plan_freezes_everything_under_it(owner, plan):
    _set_locked(owner, 'pipelines', plan['pipeline'], 1)
    try:
        for table, row in (('pipelines', {'id': plan['pipeline'], 'title': 'x'}),
                           ('pipelines', {'id': plan['pipeline'], 'execution_mode': 'serial'}),
                           ('initiatives', {'id': plan['initiative_b'], 'title': 'x'}),
                           ('epics', {'id': plan['b1'], 'title': 'x'})):
            resp = _put(owner, table, row)
            assert resp['statusCode'] == 423, (table, row, resp)
            assert _body(resp)['locked_by'] == 'pipeline'
        resp = owner('POST', '/darwin_dev/initiatives', body={
            'pipeline_fk': plan['pipeline'], 'title': 'C', 'initiative_status': 'active',
            'category_fk': plan['category'], 'closed': '0'})
        assert resp['statusCode'] == 423, resp
        resp = owner('DELETE', '/darwin_dev/pipelines', body={'id': plan['pipeline']})
        assert resp['statusCode'] == 423, resp
        # The plan still runs: its status writes, and its stamps with it.
        resp = _put(owner, 'pipelines', {'id': plan['pipeline'], 'pipeline_status': 'paused'})
        assert resp['statusCode'] in (200, 204), resp
        resp = _put(owner, 'pipelines', {'id': plan['pipeline'], 'pipeline_status': 'active'})
        assert resp['statusCode'] in (200, 204), resp
    finally:
        _set_locked(owner, 'pipelines', plan['pipeline'], 0)
    assert _put(owner, 'epics', {'id': plan['b1'], 'title': 'b1'})['statusCode'] in (200, 204)


def test_the_composed_read_carries_the_flags(owner, plan):
    _set_locked(owner, 'initiatives', plan['initiative_a'], 1)
    _put(owner, 'epics', {'id': plan['b1'], 'checkpoint': 0})
    try:
        resp = owner('GET', '/darwin_dev/pipeline_compose', query={'id': str(plan['pipeline'])})
        body = json.loads(resp['body'])
        assert body['pipeline']['locked'] == 0
        initiatives = {e['id']: e for e in body['initiatives']}
        assert initiatives[plan['initiative_a']]['locked'] == 1 and initiatives[plan['initiative_b']]['locked'] == 0
        rows = {r['id']: r for r in body['derived']['rows']}
        assert rows[plan['a1']]['checkpoint'] is True and rows[plan['b1']]['checkpoint'] is False
        assert rows[plan['a2']]['locked'] is False
        assert 'launch_queue' in body['derived']
        assert [e['requirement_id'] for e in body['derived']['launch_queue']] == [plan['req_seated']]
    finally:
        _set_locked(owner, 'initiatives', plan['initiative_a'], 0)
        _put(owner, 'epics', {'id': plan['b1'], 'checkpoint': 1})


def test_deleting_an_open_initiative_with_a_locked_epic_under_it_is_423_and_strips_no_gate(owner, plan):
    """Review W1/C2: the UI and darwin-mcp clear dependency rows before the
    initiative; the gateway must refuse the initiative AND the edge deletes."""
    _set_locked(owner, 'epics', plan['a2'], 1)
    try:
        resp = owner('DELETE', '/darwin_dev/initiatives', body={'id': plan['initiative_a']})
        assert resp['statusCode'] == 423, resp
        assert (_body(resp)['locked_by'], _body(resp)['locked_id']) == ('epic', plan['a2'])
        # The locked epic's own edge is refused too.
        resp = owner('DELETE', '/darwin_dev/epic_deps', body={'epic_fk': plan['a2']})
        assert resp['statusCode'] == 423, resp
        resp = owner('GET', '/darwin_dev/epic_deps', query={'epic_fk': str(plan['a2'])})
        assert resp['statusCode'] == 200
        # The whole plan too, through the same cascade check.
        resp = owner('DELETE', '/darwin_dev/pipelines', body={'id': plan['pipeline']})
        assert resp['statusCode'] == 423, resp
    finally:
        _set_locked(owner, 'epics', plan['a2'], 0)


def test_unlocking_and_editing_in_one_put_lands(owner, plan):
    _set_locked(owner, 'epics', plan['b1'], 1)
    resp = _put(owner, 'epics', {'id': plan['b1'], 'locked': 0, 'title': 'b1 renamed'})
    assert resp['statusCode'] in (200, 204), resp
    resp = owner('GET', '/darwin_dev/epics', query={'id': str(plan['b1'])})
    rows = json.loads(resp['body'])
    while isinstance(rows, str):          # the generic GET is double-encoded
        rows = json.loads(rows)
    assert rows[0]['locked'] == 0 and rows[0]['title'] == 'b1 renamed'
    _put(owner, 'epics', {'id': plan['b1'], 'title': 'b1'})


def test_a_seated_requirement_deletes_with_its_seat_unless_the_epic_is_locked(owner, plan):
    """Req #3706: a requirement seated on an epic could not be deleted at all
    (RESTRICT, 409/1451). It now deletes and its seat goes with it — except
    under a lock, where the cascade would unlink it from a relic."""
    resp = owner('POST', '/darwin_dev/requirements', body={
        'title': 'req_doomed', 'requirement_status': 'swarm_ready',
        'category_fk': plan['category'], 'coordination_type': 'implemented',
        'ai_model': 'sonnet', 'effort': 'high'})
    doomed = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/epic_requirements',
                 body={'epic_fk': plan['b1'], 'requirement_fk': doomed})
    assert resp['statusCode'] in (200, 201), resp

    _set_locked(owner, 'initiatives', plan['initiative_b'], 1)
    try:
        resp = owner('DELETE', '/darwin_dev/requirements', body={'id': doomed})
        assert resp['statusCode'] == 423, resp
        body = _body(resp)
        assert (body['table'], body['id'], body['locked_by'], body['locked_id']) == (
            'requirements', doomed, 'initiative', plan['initiative_b'])
        assert f"seated on epic {plan['b1']}" in body['message']
    finally:
        _set_locked(owner, 'initiatives', plan['initiative_b'], 0)

    resp = owner('DELETE', '/darwin_dev/requirements', body={'id': doomed})
    assert resp['statusCode'] == 200, resp
    resp = owner('GET', '/darwin_dev/epic_requirements',
                 query={'requirement_fk': str(doomed)})
    assert resp['statusCode'] == 404, resp
    resp = owner('GET', '/darwin_dev/epics', query={'id': str(plan['b1'])})
    assert resp['statusCode'] == 200, resp
