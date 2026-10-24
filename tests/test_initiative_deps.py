"""Initiative-to-initiative dependencies, end to end against darwin_dev (req #3823).

Through the real `lambda_handler`: the gateway REFUSES an unsatisfiable edge
(self, cross-plan, a cycle on the combined initiative + epic graph — and an
epic edge contradicting an initiative edge), ownership is DERIVED through the
waiting initiative, a lock freezes the edge, and the composed read carries the
edges and holds the waiting initiative's epics while its dependency holds open
work. `test_pipeline2_derive.py` proves the derivation itself without a DB.
"""
import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from test_pipeline2_compose import _invoker, _purge, extract_id   # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def owner_fk():
    return f"initdeps-owner-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def other_fk():
    return f"initdeps-other-{int(time.time())}-{uuid.uuid4().hex[:6]}"


def _profiled(fk, db_connection, name):
    invoke = _invoker(fk)
    invoke('POST', '/darwin_dev/profiles', body={
        'id': fk, 'name': name, 'email': f'{name}@test.invalid'})
    return invoke


@pytest.fixture(scope="module")
def owner(owner_fk, db_connection):
    invoke = _profiled(owner_fk, db_connection, 'initdeps-owner')
    yield invoke
    _purge(db_connection, owner_fk)


@pytest.fixture(scope="module")
def other(other_fk, db_connection):
    invoke = _profiled(other_fk, db_connection, 'initdeps-other')
    yield invoke
    _purge(db_connection, other_fk)


def _new_plan(invoke, title):
    """Pipeline with initiatives A, B, C — one epic each, one requirement each
    (A's in development, B's and C's swarm_ready)."""
    ids = {}
    ids['project'] = int(extract_id(invoke('POST', '/darwin_dev/projects',
                                           body={'project_name': f'{title} project'})))
    ids['category'] = int(extract_id(invoke('POST', '/darwin_dev/categories', body={
        'category_name': f'{title} category', 'project_fk': ids['project']})))
    ids['pipeline'] = int(extract_id(invoke('POST', '/darwin_dev/pipelines', body={
        'title': title, 'pipeline_status': 'active'})))
    for key, status in (('A', 'development'), ('B', 'swarm_ready'), ('C', 'swarm_ready')):
        ids[key] = int(extract_id(invoke('POST', '/darwin_dev/initiatives', body={
            'pipeline_fk': ids['pipeline'], 'title': key, 'initiative_status': 'active',
            'category_fk': ids['category'], 'closed': '0'})))
        ids['e' + key] = int(extract_id(invoke('POST', '/darwin_dev/epics', body={
            'initiative_fk': ids[key], 'title': 'epic ' + key, 'run': 'auto',
            'checkpoint': 0})))
        ids['r' + key] = int(extract_id(invoke('POST', '/darwin_dev/requirements', body={
            'title': 'req ' + key, 'requirement_status': status,
            'category_fk': ids['category'], 'coordination_type': 'implemented',
            'ai_model': 'sonnet', 'effort': 'high'})))
        invoke('POST', '/darwin_dev/epic_requirements',
               body={'epic_fk': ids['e' + key], 'requirement_fk': ids['r' + key]})
    return ids


@pytest.fixture(scope="module")
def plan(owner):
    return _new_plan(owner, 'initdeps plan')


def _edge(invoke, waiter, dep):
    return invoke('POST', '/darwin_dev/initiative_deps',
                  body={'initiative_fk': waiter, 'dep_initiative_fk': dep})


def _unedge(invoke, waiter, dep):
    return invoke('DELETE', '/darwin_dev/initiative_deps',
                  body={'initiative_fk': waiter, 'dep_initiative_fk': dep})


def _body(resp):
    return json.loads(resp['body'])


def _composed(invoke, pipeline_id):
    resp = invoke('GET', '/darwin_dev/pipeline_compose', query={'id': str(pipeline_id)})
    assert resp['statusCode'] == 200, resp
    body = json.loads(resp['body'])
    return json.loads(body) if isinstance(body, str) else body


def _composed_initiative(invoke, initiative_id):
    resp = invoke('GET', '/darwin_dev/pipeline_compose_initiative',
                  query={'id': str(initiative_id)})
    assert resp['statusCode'] == 200, resp
    body = json.loads(resp['body'])
    return json.loads(body) if isinstance(body, str) else body


def test_an_edge_holds_the_waiting_initiative_and_the_read_carries_it(owner, plan):
    assert _edge(owner, plan['B'], plan['A'])['statusCode'] in (200, 201)
    try:
        composed = _composed(owner, plan['pipeline'])
        assert [(d['initiative_fk'], d['dep_initiative_fk'])
                for d in composed['initiative_deps']] == [(plan['B'], plan['A'])]
        rows = {r['id']: r for r in composed['derived']['rows']}
        assert rows[plan['eB']]['initiative_blocked_by'] == [plan['A']]
        assert rows[plan['eB']]['launch_candidate'] is False
        assert rows[plan['eC']]['launch_candidate'] is True
        # The initiative-scoped read gives the same answer for B.
        scoped = _composed_initiative(owner, plan['B'])
        assert scoped['derived']['rows'][0]['initiative_blocked_by'] == [plan['A']]
        assert scoped['derived']['violations'] == []
        # A's last requirement closing releases B on the next read.
        owner('PUT', '/darwin_dev/requirements',
              body=[{'id': plan['rA'], 'requirement_status': 'met'}])
        rows = {r['id']: r for r in _composed(owner, plan['pipeline'])['derived']['rows']}
        assert rows[plan['eB']]['initiative_blocked_by'] == []
        assert rows[plan['eB']]['launch_candidate'] is True
        assert _composed_initiative(owner, plan['B'])['derived']['rows'][0][
            'launch_candidate'] is True
    finally:
        owner('PUT', '/darwin_dev/requirements',
              body=[{'id': plan['rA'], 'requirement_status': 'development'}])
        _unedge(owner, plan['B'], plan['A'])


def test_self_cycle_and_cross_plan_edges_are_refused_by_name(owner, plan):
    resp = _edge(owner, plan['A'], plan['A'])
    assert resp['statusCode'] == 409, resp
    assert _body(resp)['constraint'] == 'initiative-self-dependency'

    assert _edge(owner, plan['B'], plan['A'])['statusCode'] in (200, 201)
    assert _edge(owner, plan['C'], plan['B'])['statusCode'] in (200, 201)
    try:
        resp = _edge(owner, plan['A'], plan['C'])
        assert resp['statusCode'] == 409, resp
        body = _body(resp)
        assert body['constraint'] == 'initiative-cycle'
        assert 'wait for each other forever' in body['message']

        second = _new_plan(owner, 'initdeps second plan')
        resp = _edge(owner, plan['A'], second['A'])
        assert resp['statusCode'] == 409, resp
        assert _body(resp)['constraint'] == 'initiative-cross-plan'
    finally:
        _unedge(owner, plan['C'], plan['B'])
        _unedge(owner, plan['B'], plan['A'])


def test_an_epic_edge_contradicting_an_initiative_edge_is_refused_both_ways(owner, plan):
    assert _edge(owner, plan['B'], plan['A'])['statusCode'] in (200, 201)
    try:
        # An epic in A waiting on an epic in B contradicts "B waits for A".
        resp = owner('POST', '/darwin_dev/epic_deps',
                     body={'epic_fk': plan['eA'], 'dep_epic_fk': plan['eB']})
        assert resp['statusCode'] == 409, resp
        assert _body(resp)['constraint'] == 'initiative-cycle'
        # The consistent direction is fine.
        resp = owner('POST', '/darwin_dev/epic_deps',
                     body={'epic_fk': plan['eB'], 'dep_epic_fk': plan['eA']})
        assert resp['statusCode'] in (200, 201), resp
        owner('DELETE', '/darwin_dev/epic_deps',
              body={'epic_fk': plan['eB'], 'dep_epic_fk': plan['eA']})
    finally:
        _unedge(owner, plan['B'], plan['A'])
    # ...and the other order: the epic edge first, then the initiative edge.
    resp = owner('POST', '/darwin_dev/epic_deps',
                 body={'epic_fk': plan['eA'], 'dep_epic_fk': plan['eB']})
    assert resp['statusCode'] in (200, 201), resp
    try:
        resp = _edge(owner, plan['B'], plan['A'])
        assert resp['statusCode'] == 409, resp
        assert f"epic {plan['eA']}" in _body(resp)['message']
    finally:
        owner('DELETE', '/darwin_dev/epic_deps',
              body={'epic_fk': plan['eA'], 'dep_epic_fk': plan['eB']})


def test_ownership_is_derived_through_the_waiting_initiative(owner, other, plan):
    theirs = _new_plan(other, 'initdeps intruder plan')
    # Waiting on somebody else's initiative: their row would become undeletable.
    resp = _edge(other, theirs['A'], plan['A'])
    assert resp['statusCode'] == 403, resp
    # Writing an edge onto somebody else's initiative.
    resp = _edge(other, plan['B'], theirs['A'])
    assert resp['statusCode'] == 403, resp
    assert _edge(owner, plan['B'], plan['A'])['statusCode'] in (200, 201)
    try:
        # The intruder's unfiltered read sees none of the owner's edges.
        resp = other('GET', '/darwin_dev/initiative_deps')
        if resp['statusCode'] == 404:
            rows = []
        else:
            rows = json.loads(resp['body'])
            rows = json.loads(rows) if isinstance(rows, str) else rows
        assert all(r['initiative_fk'] != plan['B'] for r in rows)
    finally:
        _unedge(owner, plan['B'], plan['A'])


def test_an_initiative_waited_on_cannot_be_deleted_until_the_edge_goes(owner, plan):
    extra = int(extract_id(owner('POST', '/darwin_dev/initiatives', body={
        'pipeline_fk': plan['pipeline'], 'title': 'doomed', 'initiative_status': 'active',
        'category_fk': plan['category'], 'closed': '0'})))
    assert _edge(owner, plan['C'], extra)['statusCode'] in (200, 201)
    resp = owner('DELETE', '/darwin_dev/initiatives', body={'id': extra})
    assert resp['statusCode'] == 409, resp
    _unedge(owner, plan['C'], extra)
    resp = owner('DELETE', '/darwin_dev/initiatives', body={'id': extra})
    assert resp['statusCode'] == 200, resp


def test_a_locked_initiative_freezes_its_edges(owner, plan):
    owner('PUT', '/darwin_dev/initiatives', body=[{'id': plan['B'], 'locked': 1}])
    try:
        resp = _edge(owner, plan['B'], plan['A'])
        assert resp['statusCode'] == 423, resp
    finally:
        owner('PUT', '/darwin_dev/initiatives', body=[{'id': plan['B'], 'locked': 0}])
    assert _edge(owner, plan['B'], plan['A'])['statusCode'] in (200, 201)
    owner('PUT', '/darwin_dev/initiatives', body=[{'id': plan['B'], 'locked': 1}])
    try:
        assert _unedge(owner, plan['B'], plan['A'])['statusCode'] == 423
    finally:
        owner('PUT', '/darwin_dev/initiatives', body=[{'id': plan['B'], 'locked': 0}])
    assert _unedge(owner, plan['B'], plan['A'])['statusCode'] == 200


def test_a_re_pointing_put_is_refused(owner, plan):
    resp = _edge(owner, plan['B'], plan['A'])
    edge_id = int(extract_id(resp))
    try:
        resp = owner('PUT', '/darwin_dev/initiative_deps',
                     body=[{'id': edge_id, 'dep_initiative_fk': plan['C']}])
        assert resp['statusCode'] == 400, resp
    finally:
        _unedge(owner, plan['B'], plan['A'])


def test_epic_edges_crossing_both_ways_through_unrelated_epics_are_accepted(owner, plan):
    """Code review, req #3823: an initiative edge is judged epic by epic. With
    B waiting for A, an epic of A may wait on a SECOND, unrelated epic of B."""
    b2 = int(extract_id(owner('POST', '/darwin_dev/epics', body={
        'initiative_fk': plan['B'], 'title': 'epic B2', 'run': 'auto', 'checkpoint': 0})))
    # C waits for A; A's epic waits on B's epic; B's OTHER epic waits on C's.
    # Lifted to initiatives that is A -> B -> C -> A; epic by epic nothing loops.
    assert _edge(owner, plan['C'], plan['A'])['statusCode'] in (200, 201)
    try:
        r1 = owner('POST', '/darwin_dev/epic_deps',
                   body={'epic_fk': plan['eA'], 'dep_epic_fk': plan['eB']})
        assert r1['statusCode'] in (200, 201), r1
        r2 = owner('POST', '/darwin_dev/epic_deps',
                   body={'epic_fk': b2, 'dep_epic_fk': plan['eC']})
        assert r2['statusCode'] in (200, 201), r2
        # ...but the SAME epic of B waiting on C's closes the loop.
        r3 = owner('POST', '/darwin_dev/epic_deps',
                   body={'epic_fk': plan['eB'], 'dep_epic_fk': plan['eC']})
        assert r3['statusCode'] == 409, r3
        assert _body(r3)['constraint'] == 'initiative-cycle'
    finally:
        for a, b in ((plan['eA'], plan['eB']), (b2, plan['eC'])):
            owner('DELETE', '/darwin_dev/epic_deps', body={'epic_fk': a, 'dep_epic_fk': b})
        _unedge(owner, plan['C'], plan['A'])
        owner('DELETE', '/darwin_dev/epics', body={'id': b2})


def test_re_pointing_an_epic_edge_into_a_contradiction_is_refused(owner, plan):
    """An owner may re-point their own epic edge — but not into one that
    contradicts an initiative edge (B waits for A, so A's epic cannot wait on B's)."""
    resp = owner('POST', '/darwin_dev/epic_deps',
                 body={'epic_fk': plan['eA'], 'dep_epic_fk': plan['eC']})
    edge_id = int(extract_id(resp))
    assert _edge(owner, plan['B'], plan['A'])['statusCode'] in (200, 201)
    try:
        resp = owner('PUT', '/darwin_dev/epic_deps',
                     body=[{'id': edge_id, 'dep_epic_fk': plan['eB']}])
        assert resp['statusCode'] == 409, resp
        assert _body(resp)['constraint'] == 'initiative-cycle'
        # A harmless re-point still lands.
        resp = owner('PUT', '/darwin_dev/epic_deps',
                     body=[{'id': edge_id, 'dep_epic_fk': plan['eC']}])
        assert resp['statusCode'] in (200, 204), resp
    finally:
        owner('DELETE', '/darwin_dev/epic_deps', body={'id': edge_id})
        _unedge(owner, plan['B'], plan['A'])


def test_an_epic_edge_inside_one_initiative_that_closes_a_gate_cycle_is_refused(owner, plan):
    """Delta review, req #3823: C waits for B; eA -> eC and eB -> eA2 are fine;
    then eA2 -> eA — INSIDE initiative A — closes
    eA2 -> eA -> eC -> g(C) -> eB -> eA2, and is refused."""
    a2 = int(extract_id(owner('POST', '/darwin_dev/epics', body={
        'initiative_fk': plan['A'], 'title': 'epic A2', 'run': 'auto', 'checkpoint': 0})))
    assert _edge(owner, plan['C'], plan['B'])['statusCode'] in (200, 201)
    made = []
    try:
        for a, b in ((plan['eA'], plan['eC']), (plan['eB'], a2)):
            r = owner('POST', '/darwin_dev/epic_deps', body={'epic_fk': a, 'dep_epic_fk': b})
            assert r['statusCode'] in (200, 201), r
            made.append((a, b))
        r = owner('POST', '/darwin_dev/epic_deps', body={'epic_fk': a2, 'dep_epic_fk': plan['eA']})
        assert r['statusCode'] == 409, r
        assert _body(r)['constraint'] == 'initiative-cycle'
    finally:
        for a, b in made:
            owner('DELETE', '/darwin_dev/epic_deps', body={'epic_fk': a, 'dep_epic_fk': b})
        _unedge(owner, plan['C'], plan['B'])
        owner('DELETE', '/darwin_dev/epics', body={'id': a2})
