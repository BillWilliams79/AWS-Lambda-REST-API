"""The Pipeline 2.0 composing route — integration tier (req #3367).

`GET /darwin_dev/pipeline_compose?id=<pipeline_id>` and
`GET /darwin_dev/pipeline_compose_initiative?id=<initiative_id>` — the ONE non-generic
route this requirement adds. Everything here is driven through
`lambda_handler` exactly like the generic gateway's own tests, proving the
route end to end: auth, scoping, shape, derivation, and the budget ladder.

The plan/initiative/epic fixtures are built through the REAL gateway (POST to the
generic `pipeline2_*` table routes) rather than raw SQL — same discipline as
`test_junction_scoping.py`: it is simultaneously the regression guard that an
owner can still create this graph at all.

Needs `darwin_dev` (`. exports.sh`); skips cleanly without it (via the
`invoke`/`db_connection` fixtures).
"""
import json
import time
import uuid

import pytest

from conftest import extract_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def owner_fk():
    return f"p2compose-owner-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def other_fk():
    return f"p2compose-other-{int(time.time())}-{uuid.uuid4().hex[:6]}"


def _invoker(sub):
    from handler import lambda_handler

    def _invoke(method, path, query=None, body=None):
        return lambda_handler({
            'httpMethod': method,
            'path': path,
            'queryStringParameters': query,
            'body': json.dumps(body) if body is not None else None,
            'requestContext': {'authorizer': {'claims': {'sub': sub}}},
        }, {})
    return _invoke


def _purge(conn, creator):
    import pymysql as _pymysql
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM epic_deps WHERE epic_fk IN "
                        "(SELECT id FROM epics WHERE creator_fk = %s)", (creator,))
            cur.execute("DELETE FROM epic_requirements WHERE epic_fk IN "
                        "(SELECT id FROM epics WHERE creator_fk = %s)", (creator,))
            cur.execute("DELETE FROM epics WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM initiatives WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM pipelines WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM requirements WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM categories WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM projects WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM profiles WHERE id = %s", (creator,))
        conn.commit()
    except _pymysql.MySQLError:
        conn.rollback()


@pytest.fixture(scope="module")
def owner(owner_fk, db_connection):
    invoke = _invoker(owner_fk)
    invoke('POST', '/darwin_dev/profiles', body={
        'id': owner_fk, 'name': 'p2compose owner', 'email': 'p2c-owner@test.invalid'})
    yield invoke
    _purge(db_connection, owner_fk)


@pytest.fixture(scope="module")
def other(other_fk, db_connection):
    invoke = _invoker(other_fk)
    invoke('POST', '/darwin_dev/profiles', body={
        'id': other_fk, 'name': 'p2compose other', 'email': 'p2c-other@test.invalid'})
    yield invoke
    _purge(db_connection, other_fk)


@pytest.fixture(scope="module")
def plan(owner):
    """One pipeline, one initiative, two requirement-backed epics, one gate epic
    depending on both — mirrors the darwin-mcp unit fixture's shape."""
    ids = {}

    resp = owner('POST', '/darwin_dev/projects', body={'project_name': 'p2compose project'})
    assert resp['statusCode'] == 200, resp
    ids['project'] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/categories',
                body={'category_name': 'p2compose category', 'project_fk': ids['project']})
    assert resp['statusCode'] == 200, resp
    ids['category'] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/pipelines', body={
        'title': 'p2compose plan', 'description': 'the goal',
        'pipeline_status': 'active', 'execution_mode': 'parallel'})
    assert resp['statusCode'] == 200, resp
    ids['pipeline'] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/initiatives', body={
        'pipeline_fk': ids['pipeline'], 'title': 'p2compose initiative',
        'description': 'build it', 'initiative_status': 'active',
        'category_fk': ids['category'], 'sort_order': 'NULL', 'closed': '0'})
    assert resp['statusCode'] == 200, resp
    ids['initiative'] = int(extract_id(resp))

    for key, title, status in (('req_a', 'requirement A', 'development'),
                               ('req_b', 'requirement B', 'authoring')):
        resp = owner('POST', '/darwin_dev/requirements', body={
            'title': title, 'requirement_status': status,
            'category_fk': ids['category'], 'coordination_type': 'deployed',
            'ai_model': 'sonnet', 'effort': 'high'})
        assert resp['statusCode'] == 200, resp
        ids[key] = int(extract_id(resp))

    for key, title, run in (('epic_a', 'read service', 'auto'),
                            ('epic_b', 'tools', 'auto'),
                            ('epic_gate', 'gate', 'manual')):
        resp = owner('POST', '/darwin_dev/epics', body={
            'initiative_fk': ids['initiative'], 'title': title, 'run': run})
        assert resp['statusCode'] == 200, resp
        ids[key] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/epic_requirements',
                body={'epic_fk': ids['epic_a'], 'requirement_fk': ids['req_a']})
    assert resp['statusCode'] in (200, 201), resp
    resp = owner('POST', '/darwin_dev/epic_requirements',
                body={'epic_fk': ids['epic_b'], 'requirement_fk': ids['req_b']})
    assert resp['statusCode'] in (200, 201), resp

    for dep in (ids['epic_a'], ids['epic_b']):
        resp = owner('POST', '/darwin_dev/epic_deps',
                    body={'epic_fk': ids['epic_gate'], 'dep_epic_fk': dep})
        assert resp['statusCode'] == 200, resp

    return ids


# ---------------------------------------------------------------------------
# Shape and content
# ---------------------------------------------------------------------------

def _get(invoke, table, row_id):
    return invoke('GET', f'/darwin_dev/{table}', query={'id': str(row_id)})


class TestWholePlanCompose:
    def test_carries_the_whole_plan(self, owner, plan):
        resp = _get(owner, 'pipeline_compose', plan['pipeline'])
        assert resp['statusCode'] == 200, resp
        body = json.loads(resp['body'])

        assert set(body) == {'pipeline', 'initiatives', 'epics', 'epic_requirements',
                             'epic_deps', 'requirements', 'derived'}
        assert body['pipeline']['title'] == 'p2compose plan'
        assert body['pipeline']['epic_count'] == 3
        assert [s['title'] for s in body['epics']] == ['read service', 'tools', 'gate']
        assert len(body['epic_requirements']) == 2
        assert len(body['epic_deps']) == 2
        assert sorted(r['id'] for r in body['requirements']) == sorted(
            [plan['req_a'], plan['req_b']])

        assert len(body['initiatives']) == 1
        initiative = body['initiatives'][0]
        assert set(initiative) == {'id', 'pipeline_fk', 'title', 'description',
                             'initiative_status', 'locked', 'sort_order', 'category_fk',
                             'closed'}
        assert initiative['locked'] == 0
        assert body['pipeline']['locked'] == 0
        for epic in body['epics']:
            assert epic['checkpoint'] == 1 and epic['locked'] == 0
        assert initiative['description'] == 'build it'

    def test_requirements_are_the_light_projection(self, owner, plan):
        # `started_at`/`completed_at` added by req #3381's code review
        # (2026-08-09) — the browser's client-side time axis
        # (pipelinePlanTime.js) reads them per-requirement and had no
        # evidence at all without this widening. Still light: no
        # `description`, and no reference to the retired middle tier (2.0
        # has no such column at all).
        resp = _get(owner, 'pipeline_compose', plan['pipeline'])
        body = json.loads(resp['body'])
        for row in body['requirements']:
            assert set(row) == {'id', 'title', 'requirement_status', 'coordination_type',
                                'ai_model', 'effort', 'machine_fk', 'tracking',
                                'started_at', 'completed_at'}
            assert 'description' not in row

    def test_epics_have_no_state_column_and_initiative_fk_not_pipeline_fk(self, owner, plan):
        resp = _get(owner, 'pipeline_compose', plan['pipeline'])
        body = json.loads(resp['body'])
        for epic in body['epics']:
            assert 'state' not in epic and 'status' not in epic
            assert 'pipeline_fk' not in epic
            assert epic['initiative_fk'] == plan['initiative']

    def test_derived_is_a_real_answer(self, owner, plan):
        resp = _get(owner, 'pipeline_compose', plan['pipeline'])
        body = json.loads(resp['body'])
        derived = body['derived']
        assert 'withheld' not in derived
        assert derived['display_order'] == [plan['epic_a'], plan['epic_b'], plan['epic_gate']]
        by_id = {row['id']: row for row in derived['rows']}
        # An epic has no state (req #3750) — it carries its open work. req_a is
        # `development` and req_b `authoring`, both open; the gate holds
        # nothing of its own and waits on both.
        assert by_id[plan['epic_a']]['open_req_ids'] == [plan['req_a']]
        assert by_id[plan['epic_b']]['open_req_ids'] == [plan['req_b']]
        assert by_id[plan['epic_gate']]['open_req_ids'] == []
        assert by_id[plan['epic_gate']]['gate_open'] is False
        assert all('state' not in row for row in derived['rows'])
        assert all('completed_at' not in epic for epic in body['epics'])

    def test_missing_pipeline_is_404(self, owner):
        resp = _get(owner, 'pipeline_compose', 999999999)
        assert resp['statusCode'] == 404, resp
        assert resp['body'] == '"NOT FOUND"'

    def test_browser_and_daemon_receive_byte_identical_derived_blocks(self, owner, plan):
        """req #3367's acceptance criterion, literally: 'a test proves the
        browser and the daemon receive byte-identical derived blocks for the
        same plan.' There is only one producer now — this route — so a
        'browser read' and a 'daemon passthrough read' are the same HTTP call
        made twice. That is not a tautology to wave through: before this
        requirement there were two DIFFERENT producers (`pipelineModel.js` in
        the browser, `pipeline2_derive.py` in the daemon) that COULD disagree,
        and the corpus existed to catch it when they did. Proving two calls
        to the one remaining producer return identical bytes is what "one
        derivation, in one place" cashes out to once B is chosen."""
        first = _get(owner, 'pipeline_compose', plan['pipeline'])
        second = _get(owner, 'pipeline_compose', plan['pipeline'])
        assert first['body'] == second['body']
        assert json.loads(first['body'])['derived'] == json.loads(second['body'])['derived']


class TestInitiativeScopedCompose:
    def test_carries_one_initiative(self, owner, plan):
        resp = _get(owner, 'pipeline_compose_initiative', plan['initiative'])
        assert resp['statusCode'] == 200, resp
        body = json.loads(resp['body'])
        assert len(body['initiatives']) == 1
        assert body['initiatives'][0]['id'] == plan['initiative']
        assert body['initiatives'][0]['epic_count'] == 3
        assert body['pipeline']['id'] == plan['pipeline']

    def test_missing_initiative_is_404(self, owner):
        resp = _get(owner, 'pipeline_compose_initiative', 999999999)
        assert resp['statusCode'] == 404, resp


# ---------------------------------------------------------------------------
# Cross-tenant scoping (req #3122/#3125's discipline applied to this route)
# ---------------------------------------------------------------------------

class TestScoping:
    def test_unauthenticated_is_403(self, plan):
        from handler import lambda_handler
        resp = lambda_handler({
            'httpMethod': 'GET', 'path': '/darwin_dev/pipeline_compose',
            'queryStringParameters': {'id': str(plan['pipeline'])},
            'body': None, 'requestContext': {},
        }, {})
        assert resp['statusCode'] == 403, resp
        assert resp['body'] == '"FORBIDDEN"'

    def test_another_creator_cannot_read_the_plan(self, other, plan):
        resp = _get(other, 'pipeline_compose', plan['pipeline'])
        assert resp['statusCode'] == 404, resp

    def test_another_creator_cannot_read_the_initiative(self, other, plan):
        resp = _get(other, 'pipeline_compose_initiative', plan['initiative'])
        assert resp['statusCode'] == 404, resp

    def test_missing_id_is_400(self, owner):
        resp = owner('GET', '/darwin_dev/pipeline_compose', query=None)
        assert resp['statusCode'] == 400, resp

    def test_non_get_is_400(self, owner, plan):
        resp = owner('POST', '/darwin_dev/pipeline_compose', body={'id': plan['pipeline']})
        assert resp['statusCode'] == 400, resp


# ---------------------------------------------------------------------------
# Initiative-scoped derivation nuance: a cross-initiative dependency is reported
# differently depending on which route answers (req #3345/#3349's own tested
# behaviour — carried over verbatim now that Lambda-Rest is the one place it
# runs).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def two_initiative_plan(owner):
    ids = {}
    resp = owner('POST', '/darwin_dev/projects', body={'project_name': 'p2compose 2-initiative project'})
    ids['project'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/categories',
                body={'category_name': 'p2compose 2-initiative category', 'project_fk': ids['project']})
    ids['category'] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/pipelines', body={
        'title': 'p2compose two initiatives', 'pipeline_status': 'active',
        'execution_mode': 'parallel'})
    ids['pipeline'] = int(extract_id(resp))

    for key, title, order in (('initiative_a', 'initiative A', '1'), ('initiative_b', 'initiative B', '2')):
        resp = owner('POST', '/darwin_dev/initiatives', body={
            'pipeline_fk': ids['pipeline'], 'title': title, 'initiative_status': 'active',
            'category_fk': ids['category'], 'sort_order': order, 'closed': '0'})
        assert resp['statusCode'] == 200, resp
        ids[key] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/epics',
                body={'initiative_fk': ids['initiative_a'], 'title': 'An epic', 'run': 'auto'})
    ids['epic_a'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/epics',
                body={'initiative_fk': ids['initiative_b'], 'title': 'B epic', 'run': 'auto'})
    ids['epic_b'] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/requirements', body={
        'title': 'two-initiative requirement', 'requirement_status': 'swarm_ready',
        'category_fk': ids['category'], 'coordination_type': 'deployed',
        'ai_model': 'sonnet', 'effort': 'high'})
    ids['req'] = int(extract_id(resp))
    owner('POST', '/darwin_dev/epic_requirements',
         body={'epic_fk': ids['epic_b'], 'requirement_fk': ids['req']})
    owner('POST', '/darwin_dev/epic_deps',
         body={'epic_fk': ids['epic_b'], 'dep_epic_fk': ids['epic_a']})
    return ids


def test_initiative_scoped_reports_out_of_scope_never_dangling(owner, two_initiative_plan):
    resp = _get(owner, 'pipeline_compose_initiative', two_initiative_plan['initiative_b'])
    body = json.loads(resp['body'])
    derived = body['derived']
    assert derived['out_of_scope_dep_ids'] == [two_initiative_plan['epic_a']]
    assert [v for v in derived['violations'] if v['invariant'] == 'dangling-dependency'] == []


def test_whole_plan_sees_the_same_edge_as_an_ordinary_satisfied_gate(owner, two_initiative_plan):
    # Epic A holds no work, so it holds nothing (req #3750) — B's gate is open
    # and B's launch-ready requirement makes it eligible.
    resp = _get(owner, 'pipeline_compose', two_initiative_plan['pipeline'])
    body = json.loads(resp['body'])
    derived = body['derived']
    assert derived['out_of_scope_dep_ids'] == []
    assert derived['violations'] == []
    assert two_initiative_plan['epic_b'] in derived['eligible_epic_ids']


# ---------------------------------------------------------------------------
# req #3597 (the user's amendment) / #3649 / #3750: a CHECKPOINT holding open
# work blocks everything downstream — across initiatives too. The initiative-scoped route must see a checkpoint
# in another initiative, and must not ship the plan graph it read to find it.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def checkpoint_plan(owner):
    ids = {}
    resp = owner('POST', '/darwin_dev/projects', body={'project_name': 'p2compose ckpt project'})
    ids['project'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/categories',
                body={'category_name': 'p2compose ckpt category', 'project_fk': ids['project']})
    ids['category'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/pipelines', body={
        'title': 'p2compose checkpoint', 'pipeline_status': 'active',
        'execution_mode': 'parallel'})
    ids['pipeline'] = int(extract_id(resp))
    for key, title, order in (('initiative_a', 'ckpt initiative A', '1'), ('initiative_b', 'ckpt initiative B', '2')):
        resp = owner('POST', '/darwin_dev/initiatives', body={
            'pipeline_fk': ids['pipeline'], 'title': title, 'initiative_status': 'active',
            'category_fk': ids['category'], 'sort_order': order, 'closed': '0'})
        assert resp['statusCode'] == 200, resp
        ids[key] = int(extract_id(resp))
    # A HOLDING checkpoint in initiative A: flag on (the default) with work in
    # development. An empty checkpoint would hold nothing (req #3750).
    resp = owner('POST', '/darwin_dev/epics',
                body={'initiative_fk': ids['initiative_a'], 'title': 'checkpoint', 'run': 'manual'})
    ids['checkpoint'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/requirements', body={
        'title': 'checkpoint work', 'requirement_status': 'development',
        'category_fk': ids['category'], 'coordination_type': 'implemented',
        'ai_model': 'sonnet', 'effort': 'high'})
    ids['work'] = int(extract_id(resp))
    owner('POST', '/darwin_dev/epic_requirements',
         body={'epic_fk': ids['checkpoint'], 'requirement_fk': ids['work']})
    resp = owner('POST', '/darwin_dev/epics',
                body={'initiative_fk': ids['initiative_b'], 'title': 'held work', 'run': 'auto'})
    ids['held'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/requirements', body={
        'title': 'checkpoint-held requirement', 'requirement_status': 'swarm_ready',
        'category_fk': ids['category'], 'coordination_type': 'deployed',
        'ai_model': 'sonnet', 'effort': 'high'})
    ids['req'] = int(extract_id(resp))
    owner('POST', '/darwin_dev/epic_requirements',
         body={'epic_fk': ids['held'], 'requirement_fk': ids['req']})
    owner('POST', '/darwin_dev/epic_deps',
         body={'epic_fk': ids['held'], 'dep_epic_fk': ids['checkpoint']})
    return ids


def test_initiative_scoped_read_holds_work_behind_another_initiatives_checkpoint(owner, checkpoint_plan):
    resp = _get(owner, 'pipeline_compose_initiative', checkpoint_plan['initiative_b'])
    assert resp['statusCode'] == 200, resp
    body = json.loads(resp['body'])
    row = next(r for r in body['derived']['rows'] if r['id'] == checkpoint_plan['held'])
    assert row['checkpoint_blocked_by'] == [checkpoint_plan['checkpoint']]
    assert row['launch_candidate'] is False
    # The plan graph fed the derivation and is NOT part of the response.
    assert 'plan_graph' not in body


def test_whole_plan_read_holds_the_same_epic(owner, checkpoint_plan):
    resp = _get(owner, 'pipeline_compose', checkpoint_plan['pipeline'])
    body = json.loads(resp['body'])
    row = next(r for r in body['derived']['rows'] if r['id'] == checkpoint_plan['held'])
    assert row['checkpoint_blocked_by'] == [checkpoint_plan['checkpoint']]
    assert row['launch_candidate'] is False


def test_initiative_scoped_read_releases_when_the_checkpoints_work_closes(owner, checkpoint_plan):
    """req #3649/#3750: the outside checkpoint holds while its WORK is open,
    so the plan graph must carry its requirement rows; its work going
    terminal releases the hold, and a `checkpoint=0` outside epic holds
    nothing whatever its work says."""
    ids = checkpoint_plan
    held = lambda: next(r for r in json.loads(_get(
        owner, 'pipeline_compose_initiative', ids['initiative_b'])['body'])['derived']['rows']
        if r['id'] == ids['held'])
    assert held()['checkpoint_blocked_by'] == [ids['checkpoint']]
    try:
        # The work going terminal releases it.
        owner('PUT', '/darwin_dev/requirements',
              body=[{'id': ids['work'], 'requirement_status': 'met'}])
        assert held()['checkpoint_blocked_by'] == []
        assert held()['launch_candidate'] is True
        # Back to open work, flag OFF: a priority, no hold.
        owner('PUT', '/darwin_dev/requirements',
              body=[{'id': ids['work'], 'requirement_status': 'development'}])
        owner('PUT', '/darwin_dev/epics',
              body=[{'id': ids['checkpoint'], 'checkpoint': 0}])
        assert held()['checkpoint_blocked_by'] == []
        assert held()['gate_open'] is False
    finally:
        owner('PUT', '/darwin_dev/requirements',
              body=[{'id': ids['work'], 'requirement_status': 'development'}])
        owner('PUT', '/darwin_dev/epics',
              body=[{'id': ids['checkpoint'], 'checkpoint': 1}])
