"""The Pipeline 2.0 composing route — integration tier (req #3367).

`GET /darwin_dev/pipeline_compose?id=<pipeline_id>` and
`GET /darwin_dev/pipeline_compose_epic?id=<epic_id>` — the ONE non-generic
route this requirement adds. Everything here is driven through
`lambda_handler` exactly like the generic gateway's own tests, proving the
route end to end: auth, scoping, shape, derivation, and the budget ladder.

The plan/epic/step fixtures are built through the REAL gateway (POST to the
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
            cur.execute("DELETE FROM pipeline_step_deps WHERE step_fk IN "
                        "(SELECT id FROM pipeline_steps WHERE creator_fk = %s)", (creator,))
            cur.execute("DELETE FROM pipeline_step_requirements WHERE step_fk IN "
                        "(SELECT id FROM pipeline_steps WHERE creator_fk = %s)", (creator,))
            cur.execute("DELETE FROM pipeline_steps WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM epics WHERE creator_fk = %s", (creator,))
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
    """One pipeline, one epic, two requirement-backed steps, one gate step
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

    resp = owner('POST', '/darwin_dev/epics', body={
        'pipeline_fk': ids['pipeline'], 'title': 'p2compose epic',
        'description': 'build it', 'epic_status': 'active',
        'category_fk': ids['category'], 'sort_order': 'NULL', 'closed': '0'})
    assert resp['statusCode'] == 200, resp
    ids['epic'] = int(extract_id(resp))

    for key, title, status in (('req_a', 'requirement A', 'development'),
                               ('req_b', 'requirement B', 'authoring')):
        resp = owner('POST', '/darwin_dev/requirements', body={
            'title': title, 'requirement_status': status,
            'category_fk': ids['category'], 'coordination_type': 'deployed',
            'ai_model': 'sonnet', 'effort': 'high'})
        assert resp['statusCode'] == 200, resp
        ids[key] = int(extract_id(resp))

    for key, title, run in (('step_a', 'read service', 'auto'),
                            ('step_b', 'tools', 'auto'),
                            ('step_gate', 'gate', 'manual')):
        resp = owner('POST', '/darwin_dev/pipeline_steps', body={
            'epic_fk': ids['epic'], 'title': title, 'run': run})
        assert resp['statusCode'] == 200, resp
        ids[key] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/pipeline_step_requirements',
                body={'step_fk': ids['step_a'], 'requirement_fk': ids['req_a']})
    assert resp['statusCode'] in (200, 201), resp
    resp = owner('POST', '/darwin_dev/pipeline_step_requirements',
                body={'step_fk': ids['step_b'], 'requirement_fk': ids['req_b']})
    assert resp['statusCode'] in (200, 201), resp

    for dep in (ids['step_a'], ids['step_b']):
        resp = owner('POST', '/darwin_dev/pipeline_step_deps',
                    body={'step_fk': ids['step_gate'], 'dep_step_fk': dep})
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

        assert set(body) == {'pipeline', 'epics', 'steps', 'step_requirements',
                             'step_deps', 'requirements', 'derived'}
        assert body['pipeline']['title'] == 'p2compose plan'
        assert body['pipeline']['step_count'] == 3
        assert [s['title'] for s in body['steps']] == ['read service', 'tools', 'gate']
        assert len(body['step_requirements']) == 2
        assert len(body['step_deps']) == 2
        assert sorted(r['id'] for r in body['requirements']) == sorted(
            [plan['req_a'], plan['req_b']])

        assert len(body['epics']) == 1
        epic = body['epics'][0]
        assert set(epic) == {'id', 'pipeline_fk', 'title', 'description',
                             'epic_status', 'sort_order', 'category_fk', 'closed'}
        assert epic['description'] == 'build it'

    def test_requirements_are_the_light_projection(self, owner, plan):
        # `started_at`/`completed_at` added by req #3381's code review
        # (2026-08-09) — the browser's client-side time axis
        # (pipelinePlanTime.js) reads them per-requirement and had no
        # evidence at all without this widening. Still light: no
        # `description`, no `feature_fk` (2.0 has no Feature).
        resp = _get(owner, 'pipeline_compose', plan['pipeline'])
        body = json.loads(resp['body'])
        for row in body['requirements']:
            assert set(row) == {'id', 'title', 'requirement_status', 'coordination_type',
                                'ai_model', 'effort', 'machine_fk', 'tracking',
                                'started_at', 'completed_at'}
            assert 'description' not in row
            assert 'feature_fk' not in row

    def test_steps_have_no_state_column_and_epic_fk_not_pipeline_fk(self, owner, plan):
        resp = _get(owner, 'pipeline_compose', plan['pipeline'])
        body = json.loads(resp['body'])
        for step in body['steps']:
            assert 'state' not in step and 'status' not in step
            assert 'pipeline_fk' not in step
            assert step['epic_fk'] == plan['epic']

    def test_derived_is_a_real_answer(self, owner, plan):
        resp = _get(owner, 'pipeline_compose', plan['pipeline'])
        body = json.loads(resp['body'])
        derived = body['derived']
        assert 'withheld' not in derived
        assert derived['display_order'] == [plan['step_a'], plan['step_b'], plan['step_gate']]
        by_id = {row['id']: row['state'] for row in derived['rows']}
        # req_a is `development` -> its step is running; req_b is `authoring`
        # -> pending; the gate waits on both -> pending.
        assert by_id[plan['step_a']] == 'running'
        assert by_id[plan['step_b']] == 'pending'
        assert by_id[plan['step_gate']] == 'pending'

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


class TestEpicScopedCompose:
    def test_carries_one_epic(self, owner, plan):
        resp = _get(owner, 'pipeline_compose_epic', plan['epic'])
        assert resp['statusCode'] == 200, resp
        body = json.loads(resp['body'])
        assert len(body['epics']) == 1
        assert body['epics'][0]['id'] == plan['epic']
        assert body['epics'][0]['step_count'] == 3
        assert body['pipeline']['id'] == plan['pipeline']

    def test_missing_epic_is_404(self, owner):
        resp = _get(owner, 'pipeline_compose_epic', 999999999)
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

    def test_another_creator_cannot_read_the_epic(self, other, plan):
        resp = _get(other, 'pipeline_compose_epic', plan['epic'])
        assert resp['statusCode'] == 404, resp

    def test_missing_id_is_400(self, owner):
        resp = owner('GET', '/darwin_dev/pipeline_compose', query=None)
        assert resp['statusCode'] == 400, resp

    def test_non_get_is_400(self, owner, plan):
        resp = owner('POST', '/darwin_dev/pipeline_compose', body={'id': plan['pipeline']})
        assert resp['statusCode'] == 400, resp


# ---------------------------------------------------------------------------
# Epic-scoped derivation nuance: a cross-epic dependency is reported
# differently depending on which route answers (req #3345/#3349's own tested
# behaviour — carried over verbatim now that Lambda-Rest is the one place it
# runs).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def two_epic_plan(owner):
    ids = {}
    resp = owner('POST', '/darwin_dev/projects', body={'project_name': 'p2compose 2-epic project'})
    ids['project'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/categories',
                body={'category_name': 'p2compose 2-epic category', 'project_fk': ids['project']})
    ids['category'] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/pipelines', body={
        'title': 'p2compose two epics', 'pipeline_status': 'active',
        'execution_mode': 'parallel'})
    ids['pipeline'] = int(extract_id(resp))

    for key, title, order in (('epic_a', 'epic A', '1'), ('epic_b', 'epic B', '2')):
        resp = owner('POST', '/darwin_dev/epics', body={
            'pipeline_fk': ids['pipeline'], 'title': title, 'epic_status': 'active',
            'category_fk': ids['category'], 'sort_order': order, 'closed': '0'})
        assert resp['statusCode'] == 200, resp
        ids[key] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/pipeline_steps',
                body={'epic_fk': ids['epic_a'], 'title': 'A step', 'run': 'auto',
                      'completed_at': '2026-08-01 00:00:00'})
    ids['step_a'] = int(extract_id(resp))
    resp = owner('POST', '/darwin_dev/pipeline_steps',
                body={'epic_fk': ids['epic_b'], 'title': 'B step', 'run': 'auto'})
    ids['step_b'] = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/requirements', body={
        'title': 'two-epic requirement', 'requirement_status': 'authoring',
        'category_fk': ids['category'], 'coordination_type': 'deployed',
        'ai_model': 'sonnet', 'effort': 'high'})
    ids['req'] = int(extract_id(resp))
    owner('POST', '/darwin_dev/pipeline_step_requirements',
         body={'step_fk': ids['step_b'], 'requirement_fk': ids['req']})
    owner('POST', '/darwin_dev/pipeline_step_deps',
         body={'step_fk': ids['step_b'], 'dep_step_fk': ids['step_a']})
    return ids


def test_epic_scoped_reports_out_of_scope_never_dangling(owner, two_epic_plan):
    resp = _get(owner, 'pipeline_compose_epic', two_epic_plan['epic_b'])
    body = json.loads(resp['body'])
    derived = body['derived']
    assert derived['out_of_scope_dep_ids'] == [two_epic_plan['step_a']]
    assert [v for v in derived['violations'] if v['invariant'] == 'dangling-dependency'] == []


def test_whole_plan_sees_the_same_edge_as_an_ordinary_satisfied_gate(owner, two_epic_plan):
    resp = _get(owner, 'pipeline_compose', two_epic_plan['pipeline'])
    body = json.loads(resp['body'])
    derived = body['derived']
    assert derived['out_of_scope_dep_ids'] == []
    assert derived['violations'] == []
    assert two_epic_plan['step_b'] in derived['eligible_step_ids']
