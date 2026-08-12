"""Cross-tenant tests for join-through junction authorization (req #3122).

The #3094 profiles-leak pattern applied to the tables that carry no `creator_fk`:
plant real rows for a victim, drive the gateway as a second authenticated user,
and prove the answer is 404 or 403 — never data, and never a write that lands.

Every one of these FAILED before req #3122. The gateway had no scoping for these
tables at all, so an unfiltered `GET` on a step-dependency table returned every
user's dependency edges, `PUT`/`DELETE` by id rewrote or removed another user's
gate, and `POST` injected one into their plan.

**Retargeted to the Pipeline 2.0 junctions by req #3356**, which dropped the 1.0
plan layer this file was written against. The worked example moves from
`pipeline_step_deps` / `pipeline_step_requirements` to `pipeline_step_deps` /
`pipeline_step_requirements`; the rule under test, the attacks, and every
assertion are unchanged. Deleting the file instead would have left the 2.0
junctions with unit-tier registry checks and NO end-to-end cross-tenant coverage
anywhere — the tier this file exists to be.

Two 1.0-only shapes did not survive the move, both because 2.0 moved the time
gate off the edge and onto `pipeline_steps.not_before`:
`pipeline_step_deps.dep_step_fk` is NOT NULL, so there is no wall-clock gate row
with a NULL verify column (that rule keeps its unit-tier case,
`test_unit_junction_scoping.py::test_null_verify_columns_are_skipped_not_refused`),
and there is no innocuous `time_at` column to mutate, so the PUT cases move the
edge's own `dep_step_fk` between owned steps instead. Each plan therefore builds
THREE steps rather than two, because `UNIQUE (step_fk, dep_step_fk)` means a case
that creates a spare edge needs a target the fixture edge is not already using.

The victim-side tests interleaved through the file matter as much as the attacker
ones: a scoping rule that also breaks the owner is not a fix. Each attacker
refusal is paired with a raw-SQL assertion that the row is genuinely untouched —
a 404 that hid a completed write would look identical from the outside.

Needs `darwin_dev` (`. exports.sh`); skips cleanly without it.
"""
import json
import time
import uuid

import pytest

from conftest import extract_id


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def intruder_fk():
    return f"junction-intruder-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def intruder(intruder_fk, db_connection):
    """A second authenticated identity, with a Lambda invoke factory bound to it."""
    from handler import lambda_handler

    def _invoke(method, path, query=None, body=None):
        return lambda_handler({
            'httpMethod': method,
            'path': path,
            'queryStringParameters': query,
            'body': json.dumps(body) if body is not None else None,
            'requestContext': {'authorizer': {'claims': {'sub': intruder_fk}}},
        }, {})

    _invoke('POST', '/darwin_dev/profiles', body={
        'id': intruder_fk, 'name': 'Junction Intruder',
        'email': 'junction-intruder@test.invalid'})
    yield _invoke
    _purge(db_connection, intruder_fk)


def _teardown_plan(cur, creator):
    """The plan half of a creator's teardown, in FK-safe order.

    Deps before steps (`dep_step_fk` is RESTRICT), links before requirements
    (`requirement_fk` is RESTRICT), epics before categories
    (`epics.category_fk` is RESTRICT). Anything else and the DELETE
    fails on a constraint rather than cleaning up.
    """
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


def _purge(conn, creator):
    """Tear a creator's plan/requirement graph down, then the profile itself."""
    import pymysql as _pymysql
    try:
        with conn.cursor() as cur:
            _teardown_plan(cur, creator)
            cur.execute("DELETE FROM profiles WHERE id = %s", (creator,))
        conn.commit()
    except _pymysql.MySQLError:
        conn.rollback()


# ---------------------------------------------------------------------------
# Fixtures — one plan per identity, built through the gateway
# ---------------------------------------------------------------------------

def _build_plan(post, label):
    """project/category -> pipeline -> epic -> 3 steps -> 1 dep edge -> requirement -> 1 link.

    Built through the REST API rather than raw SQL on purpose: it is simultaneously
    the regression guard that an OWNER can still create every one of these rows.

    THREE steps, not two: `pipeline_step_deps` is `UNIQUE (step_fk,
    dep_step_fk)`, and several owner-side cases create a spare edge that must not
    collide with the fixture's own. `step_c` is that spare target and carries no
    edge of its own.
    """
    ids = {}

    resp = post('/darwin_dev/projects', {'project_name': f'{label} project'})
    assert resp['statusCode'] == 200
    ids['project'] = extract_id(resp)

    resp = post('/darwin_dev/categories', {'category_name': f'{label} category',
                                           'project_fk': ids['project']})
    assert resp['statusCode'] == 200
    ids['category'] = extract_id(resp)

    resp = post('/darwin_dev/pipelines', {'title': f'{label} plan',
                                                    'pipeline_status': 'draft'})
    assert resp['statusCode'] == 200, f'{label} pipeline POST: {resp}'
    ids['pipeline'] = extract_id(resp)

    # 2.0 containment: a step belongs to an epic, and the epic to the plan. There
    # is no `pipeline_fk` on a step — the plan is derived through the epic.
    resp = post('/darwin_dev/epics',
                {'pipeline_fk': ids['pipeline'], 'title': f'{label} epic',
                 'category_fk': ids['category']})
    assert resp['statusCode'] == 200, f'{label} epic POST: {resp}'
    ids['epic'] = extract_id(resp)

    for key in ('step_a', 'step_b', 'step_c'):
        resp = post('/darwin_dev/pipeline_steps',
                    {'epic_fk': ids['epic'], 'title': f'{label} {key}',
                     'run': 'auto'})
        assert resp['statusCode'] == 200, f'{label} {key} POST: {resp}'
        ids[key] = extract_id(resp)

    # step_b waits for step_a. A surrogate-id junction row — the shape req #3111
    # flagged, and the one an attacker could address directly.
    resp = post('/darwin_dev/pipeline_step_deps',
                {'step_fk': ids['step_b'], 'dep_step_fk': ids['step_a']})
    assert resp['statusCode'] == 200, f'{label} dep POST: {resp}'
    ids['dep'] = extract_id(resp)

    resp = post('/darwin_dev/requirements',
                {'title': f'{label} requirement', 'requirement_status': 'authoring',
                 'category_fk': ids['category'], 'coordination_type': 'implemented',
                 'ai_model': 'opus', 'effort': 'high'})
    assert resp['statusCode'] == 200
    ids['requirement'] = extract_id(resp)

    # PK is `requirement_fk` alone and there is no `id` column, so `rest_post`
    # skips the read-back: 201 with no body.
    resp = post('/darwin_dev/pipeline_step_requirements',
                {'step_fk': ids['step_a'], 'requirement_fk': ids['requirement']})
    assert resp['statusCode'] in (200, 201), f'{label} link POST: {resp}'
    return ids


@pytest.fixture(scope="module")
def victim_plan(invoke, test_data, db_connection, creator_fk):
    ids = _build_plan(lambda path, body: invoke('POST', path, body=body), 'victim')
    yield ids
    import pymysql as _pymysql
    try:
        with db_connection.cursor() as cur:
            _teardown_plan(cur, creator_fk)
        db_connection.commit()
    except _pymysql.MySQLError:
        db_connection.rollback()


@pytest.fixture(scope="module")
def intruder_plan(intruder):
    """The intruder's own plan — the launchpad for "own row, foreign target" writes."""
    return _build_plan(lambda path, body: intruder('POST', path, body=body), 'intruder')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(response):
    """The rows a GET returned, or [] for a 404. Never raises on an error body."""
    if response['statusCode'] != 200:
        return []
    body = json.loads(response['body'])
    return body if isinstance(body, list) else [body]


def _dep_row(conn, dep_id):
    with conn.cursor() as cur:
        cur.execute("SELECT step_fk, dep_step_fk FROM pipeline_step_deps WHERE id = %s",
                    (dep_id,))
        return cur.fetchone()


def _count(conn, sql, params):
    """A COUNT(*) as an int. `conn` is a DictCursor connection, so alias and read
    by name — positional indexing raises KeyError on this fixture."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()['n']


# ---------------------------------------------------------------------------
# The fixture itself is a claim — check it before trusting any 404 below
# ---------------------------------------------------------------------------

def test_the_victims_rows_really_exist(db_connection, victim_plan):
    """Otherwise every 404 in this file would pass for the wrong reason."""
    assert _dep_row(db_connection, victim_plan['dep']) is not None
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_requirements "
                  "WHERE step_fk = %s AND requirement_fk = %s",
                  (victim_plan['step_a'], victim_plan['requirement'])) == 1


# ---------------------------------------------------------------------------
# GET — the unscoped LIST was the biggest half of the leak
# ---------------------------------------------------------------------------

def test_list_of_all_edges_excludes_another_users(intruder, victim_plan, intruder_plan):
    """`GET /pipeline_step_deps` with no filter returned EVERY user's edges."""
    ids = {str(row['id']) for row in _rows(intruder('GET', '/darwin_dev/pipeline_step_deps'))}
    assert str(victim_plan['dep']) not in ids
    assert str(intruder_plan['dep']) in ids      # and the intruder still sees their own


def test_edge_by_id_is_not_readable_by_another_user(intruder, victim_plan):
    """The addressability req #3111 flagged: GET by the edge's surrogate id."""
    resp = intruder('GET', '/darwin_dev/pipeline_step_deps',
                    query={'id': str(victim_plan['dep'])})
    assert resp['statusCode'] == 404


def test_edges_by_foreign_step_fk_are_not_readable(intruder, victim_plan):
    resp = intruder('GET', '/darwin_dev/pipeline_step_deps',
                    query={'step_fk': str(victim_plan['step_b'])})
    assert resp['statusCode'] == 404


def test_requirement_links_of_a_foreign_step_are_not_readable(intruder, victim_plan):
    """The composite-PK junction leaks the same way, id column or not."""
    resp = intruder('GET', '/darwin_dev/pipeline_step_requirements',
                    query={'step_fk': str(victim_plan['step_a'])})
    assert resp['statusCode'] == 404


def test_the_owner_can_still_read_their_own_edge(invoke, victim_plan):
    """The fix must narrow to the owner, not past them."""
    resp = invoke('GET', '/darwin_dev/pipeline_step_deps',
                  query={'id': str(victim_plan['dep'])})
    assert resp['statusCode'] == 200
    rows = _rows(resp)
    assert len(rows) == 1
    assert str(rows[0]['step_fk']) == str(victim_plan['step_b'])


def test_the_owner_can_still_read_their_own_requirement_links(invoke, victim_plan):
    resp = invoke('GET', '/darwin_dev/pipeline_step_requirements',
                  query={'step_fk': str(victim_plan['step_a'])})
    assert resp['statusCode'] == 200
    assert len(_rows(resp)) == 1


def test_every_edge_on_an_owned_step_is_returned_not_just_the_scope_column(
        invoke, victim_plan, db_connection):
    """`verify` columns are checked on INSERT only, never ANDed into a read.

    The 1.0 form of this test planted a wall-clock gate row (`dep_step_fk` NULL,
    `time_at` set) and proved the read did not filter it away — a
    `dep_step_fk IN (...)` predicate would have hidden every time gate in the
    plan, and an ungated-looking step gets LAUNCHED. 2.0 moved the time gate onto
    `pipeline_steps.not_before`, so `dep_step_fk` is NOT NULL and there is no
    such row to plant. What survives, and is asserted here, is the general
    property that only the SCOPE column narrows a read: a second edge on the same
    step comes back too.
    """
    resp = invoke('POST', '/darwin_dev/pipeline_step_deps',
                  body={'step_fk': victim_plan['step_b'],
                        'dep_step_fk': victim_plan['step_c']})
    assert resp['statusCode'] == 200
    extra = extract_id(resp)
    try:
        rows = _rows(invoke('GET', '/darwin_dev/pipeline_step_deps',
                            query={'step_fk': str(victim_plan['step_b'])}))
        returned = {str(row['id']) for row in rows}
        assert str(extra) in returned
        assert str(victim_plan['dep']) in returned
    finally:
        with db_connection.cursor() as cur:
            cur.execute("DELETE FROM pipeline_step_deps WHERE id = %s", (extra,))
        db_connection.commit()


def test_unauthenticated_access_to_a_junction_is_403(victim_plan):
    """With no identity there is nothing to derive scoping from, so refuse."""
    from handler import lambda_handler
    resp = lambda_handler({
        'httpMethod': 'GET', 'path': '/darwin_dev/pipeline_step_deps',
        'queryStringParameters': None, 'body': None, 'requestContext': {}}, {})
    assert resp['statusCode'] == 403


# ---------------------------------------------------------------------------
# PUT — the unscoped `else` branch of rest_put
# ---------------------------------------------------------------------------

def test_put_cannot_repoint_another_users_edge(intruder, victim_plan,
                                               intruder_plan, db_connection):
    """Re-pointing an edge silently rewires another user's execution order."""
    before = _dep_row(db_connection, victim_plan['dep'])
    resp = intruder('PUT', '/darwin_dev/pipeline_step_deps',
                    body=[{'id': str(victim_plan['dep']),
                           'dep_step_fk': str(intruder_plan['step_c'])}])
    assert resp['statusCode'] == 204            # matched nothing
    assert _dep_row(db_connection, victim_plan['dep']) == before


def test_bulk_put_mixing_own_and_foreign_edges_only_touches_own(
        intruder, victim_plan, intruder_plan, db_connection):
    """The CASE-syntax path. A mixed batch must not carry the foreign row through.

    Both rows name a step the INTRUDER owns, so the write guard has nothing to
    refuse — the only thing that can keep the victim's row out of the statement is
    the scoping predicate, which is exactly what is under test here.
    """
    victim_before = _dep_row(db_connection, victim_plan['dep'])
    resp = intruder('PUT', '/darwin_dev/pipeline_step_deps', body=[
        {'id': str(intruder_plan['dep']),
         'dep_step_fk': str(intruder_plan['step_c'])},
        {'id': str(victim_plan['dep']),
         'dep_step_fk': str(intruder_plan['step_c'])},
    ])
    assert resp['statusCode'] in (200, 204)
    assert _dep_row(db_connection, victim_plan['dep']) == victim_before
    with db_connection.cursor() as cur:
        cur.execute("SELECT dep_step_fk FROM pipeline_step_deps WHERE id = %s",
                    (intruder_plan['dep'],))
        # the intruder's own row DID update
        assert str(cur.fetchone()['dep_step_fk']) == str(intruder_plan['step_c'])
        # put it back: later cases assert on this edge's shape
        cur.execute("UPDATE pipeline_step_deps SET dep_step_fk = %s WHERE id = %s",
                    (intruder_plan['step_a'], intruder_plan['dep']))
    db_connection.commit()


def test_the_owner_can_still_update_their_own_edge(invoke, victim_plan, db_connection):
    resp = invoke('PUT', '/darwin_dev/pipeline_step_deps',
                  body=[{'id': str(victim_plan['dep']),
                         'dep_step_fk': str(victim_plan['step_c'])}])
    assert resp['statusCode'] == 200
    with db_connection.cursor() as cur:
        cur.execute("SELECT dep_step_fk FROM pipeline_step_deps WHERE id = %s",
                    (victim_plan['dep'],))
        assert str(cur.fetchone()['dep_step_fk']) == str(victim_plan['step_c'])
        cur.execute("UPDATE pipeline_step_deps SET dep_step_fk = %s WHERE id = %s",
                    (victim_plan['step_a'], victim_plan['dep']))
    db_connection.commit()


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

def test_delete_cannot_remove_another_users_edge_by_id(intruder, victim_plan,
                                                       db_connection):
    """Deleting a gate makes the step eligible — it gets LAUNCHED, not just edited."""
    resp = intruder('DELETE', '/darwin_dev/pipeline_step_deps',
                    body={'id': str(victim_plan['dep'])})
    assert resp['statusCode'] == 404
    assert _dep_row(db_connection, victim_plan['dep']) is not None


def test_delete_cannot_strip_a_foreign_steps_whole_gate(intruder, victim_plan,
                                                        db_connection):
    """`{"step_fk": N}` is the shape `set_step_deps` uses to clear a gate."""
    resp = intruder('DELETE', '/darwin_dev/pipeline_step_deps',
                    body={'step_fk': str(victim_plan['step_b'])})
    assert resp['statusCode'] == 404
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE step_fk = %s",
                  (victim_plan['step_b'],)) == 1


def test_delete_cannot_unlink_a_foreign_steps_requirement(intruder, victim_plan,
                                                          db_connection):
    resp = intruder('DELETE', '/darwin_dev/pipeline_step_requirements',
                    body={'step_fk': str(victim_plan['step_a']),
                          'requirement_fk': str(victim_plan['requirement'])})
    assert resp['statusCode'] == 404
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_requirements "
                  "WHERE step_fk = %s AND requirement_fk = %s",
                  (victim_plan['step_a'], victim_plan['requirement'])) == 1


def test_bulk_delete_cannot_remove_another_users_edge(intruder, victim_plan,
                                                      db_connection):
    resp = intruder('DELETE', '/darwin_dev/pipeline_step_deps',
                    body=[{'id': str(victim_plan['dep'])}])
    assert resp['statusCode'] == 404
    assert _dep_row(db_connection, victim_plan['dep']) is not None


def test_the_owner_can_still_delete_their_own_edge(invoke, victim_plan, db_connection):
    """Create-and-remove, so the fixture's edge survives for the tests after this."""
    resp = invoke('POST', '/darwin_dev/pipeline_step_deps',
                  body={'step_fk': victim_plan['step_a'],
                        'dep_step_fk': victim_plan['step_c']})
    assert resp['statusCode'] == 200
    throwaway = extract_id(resp)
    assert invoke('DELETE', '/darwin_dev/pipeline_step_deps',
                  body={'id': str(throwaway)})['statusCode'] == 200
    assert _dep_row(db_connection, throwaway) is None


# ---------------------------------------------------------------------------
# POST — no WHERE clause to hide behind, so the parents are checked explicitly
# ---------------------------------------------------------------------------

def test_post_cannot_add_an_edge_to_a_foreign_step(intruder, victim_plan,
                                                   db_connection):
    """Injecting a gate into somebody else's plan stalls their step indefinitely."""
    before = _count(db_connection,
                    "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE step_fk = %s",
                    (victim_plan['step_a'],))
    resp = intruder('POST', '/darwin_dev/pipeline_step_deps',
                    body={'step_fk': str(victim_plan['step_a']),
                          'dep_step_fk': str(victim_plan['step_b'])})
    assert resp['statusCode'] == 403
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE step_fk = %s",
                  (victim_plan['step_a'],)) == before


def test_post_cannot_point_an_owned_edge_at_a_foreign_step(intruder, victim_plan,
                                                           intruder_plan, db_connection):
    """Own step, foreign target — refused by the `verify` half of the registry.

    `dep_step_fk` is ON DELETE RESTRICT, so this edge would have made the victim's
    step permanently undeletable: a denial of service on their plan, mounted from
    entirely inside the attacker's own pipeline.
    """
    resp = intruder('POST', '/darwin_dev/pipeline_step_deps',
                    body={'step_fk': str(intruder_plan['step_a']),
                          'dep_step_fk': str(victim_plan['step_b'])})
    assert resp['statusCode'] == 403
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE dep_step_fk = %s",
                  (victim_plan['step_b'],)) == 0


def test_post_cannot_link_a_requirement_to_a_foreign_step(intruder, victim_plan,
                                                          db_connection):
    resp = intruder('POST', '/darwin_dev/pipeline_step_requirements',
                    body={'step_fk': str(victim_plan['step_a']),
                          'requirement_fk': str(victim_plan['requirement'])})
    assert resp['statusCode'] == 403
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_requirements WHERE step_fk = %s",
                  (victim_plan['step_a'],)) == 1


def test_post_cannot_pull_a_foreign_requirement_into_an_owned_step(
        intruder, victim_plan, intruder_plan, db_connection):
    """`requirement_fk` is RESTRICT — this would block the victim's own delete."""
    resp = intruder('POST', '/darwin_dev/pipeline_step_requirements',
                    body={'step_fk': str(intruder_plan['step_b']),
                          'requirement_fk': str(victim_plan['requirement'])})
    assert resp['statusCode'] == 403
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_requirements "
                  "WHERE requirement_fk = %s", (victim_plan['requirement'],)) == 1


def test_bulk_post_refuses_the_whole_batch_for_one_foreign_row(
        intruder, victim_plan, intruder_plan, db_connection):
    """One multi-value INSERT: a partial accept would be worse than a refusal."""
    before = _count(db_connection,
                    "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE step_fk = %s",
                    (intruder_plan['step_a'],))
    resp = intruder('POST', '/darwin_dev/pipeline_step_deps', body=[
        {'step_fk': str(intruder_plan['step_a']),
         'dep_step_fk': str(intruder_plan['step_c'])},
        {'step_fk': str(victim_plan['step_a']),
         'dep_step_fk': str(intruder_plan['step_c'])},
    ])
    assert resp['statusCode'] == 403
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE step_fk = %s",
                  (intruder_plan['step_a'],)) == before


def test_post_without_the_scope_column_is_400(intruder, victim_plan):
    """Ownership cannot be established — but that is a malformed body, not a
    credentials problem, so it must not read as 403."""
    resp = intruder('POST', '/darwin_dev/pipeline_step_deps',
                    body={'dep_step_fk': str(victim_plan['step_a'])})
    assert resp['statusCode'] == 400


def test_a_nonexistent_step_is_still_the_foreign_key_409_not_a_403(intruder,
                                                                   victim_plan,
                                                                   intruder_plan):
    """Absent and foreign are DIFFERENT answers, deliberately.

    403 is reserved for "this row belongs to somebody else". A step id that does
    not exist at all is an ordinary FK mistake and keeps the answer the error
    contract already defines — 409 with errno 1452, naming the constraint and
    promising something true of the case (retrying with different data can
    succeed). Collapsing the two would hide whether an id is real, which buys
    almost nothing against a dense auto-increment sequence, and would charge every
    FK typo a confidently wrong explanation: "references a row another creator
    owns", of a row that does not exist.
    """
    foreign = intruder('POST', '/darwin_dev/pipeline_step_deps',
                       body={'step_fk': str(victim_plan['step_a']),
                             'dep_step_fk': str(intruder_plan['step_c'])})
    assert foreign['statusCode'] == 403

    missing = intruder('POST', '/darwin_dev/pipeline_step_deps',
                       body={'step_fk': '999999999',
                             'dep_step_fk': str(intruder_plan['step_c'])})
    assert missing['statusCode'] == 409
    assert json.loads(missing['body'])['errno'] == 1452


def test_the_owner_can_still_create_edges_and_links(invoke, victim_plan, db_connection):
    """The whole owner-side write path, after every refusal above."""
    resp = invoke('POST', '/darwin_dev/pipeline_step_deps',
                  body={'step_fk': victim_plan['step_a'],
                        'dep_step_fk': victim_plan['step_b']})
    assert resp['statusCode'] == 200
    new_dep = extract_id(resp)
    try:
        assert _dep_row(db_connection, new_dep) is not None
    finally:
        with db_connection.cursor() as cur:
            cur.execute("DELETE FROM pipeline_step_deps WHERE id = %s", (new_dep,))
        db_connection.commit()


# ---------------------------------------------------------------------------
# requirement_sessions — a deliberate behaviour change, not a side effect
# ---------------------------------------------------------------------------

def test_a_foreign_requirement_can_no_longer_be_linked_to_an_owned_session(
        intruder, intruder_fk, victim_plan, db_connection):
    """darwin-mcp's test_gateway_write_scoping.py pinned the OPPOSITE of this.

    Its docstring recorded that linking a foreign requirement succeeded because
    "junctions have NO creator_fk, so the gateway cannot scope them", and flagged
    the asymmetry as "a design question rather than changed here". Req #3122 is
    that answer: the gateway scopes them through their parent, and the link is
    refused. That test is updated in the same change set.
    """
    session = intruder('POST', '/darwin_dev/swarm_sessions',
                       body={'task_name': 'junction-scope-probe',
                             'swarm_status': 'starting'})
    assert session['statusCode'] == 200
    session_id = extract_id(session)
    try:
        resp = intruder('POST', '/darwin_dev/requirement_sessions',
                        body={'requirement_fk': str(victim_plan['requirement']),
                              'session_fk': str(session_id)})
        assert resp['statusCode'] == 403
        assert _count(db_connection,
                      "SELECT COUNT(*) AS n FROM requirement_sessions WHERE session_fk = %s",
                      (session_id,)) == 0
    finally:
        with db_connection.cursor() as cur:
            cur.execute("DELETE FROM requirement_sessions WHERE session_fk = %s",
                        (session_id,))
            cur.execute("DELETE FROM swarm_sessions WHERE id = %s", (session_id,))
        db_connection.commit()


# ---------------------------------------------------------------------------
# The other door: an UPDATE that HANDS a row to another creator
# ---------------------------------------------------------------------------
#
# The WHERE predicate proves ownership of the row's parent BEFORE the statement.
# The SET clause is built from every key in the body — including the scope column
# itself — so scoping the read side alone let a caller pass the predicate on their
# own row and then reassign it. Found in code review, reproduced against
# darwin_dev, and every test below failed until `rest_put` grew its own guard.


def test_put_cannot_move_an_owned_edge_onto_a_foreign_step(
        intruder, victim_plan, intruder_plan, db_connection):
    """The scope column is writable, so the WHERE clause alone proves nothing.

    `{"id": <my edge>, "step_fk": <their step>}` passes `step_fk IN (my steps)`
    on its CURRENT value and then moves the row. The victim's step ends up gated
    on a dependency they never created — and per the orchestration doctrine an
    unexpected gate means their step is not launched.
    """
    resp = intruder('PUT', '/darwin_dev/pipeline_step_deps',
                    body=[{'id': str(intruder_plan['dep']),
                           'step_fk': str(victim_plan['step_a'])}])
    assert resp['statusCode'] == 403
    with db_connection.cursor() as cur:
        cur.execute("SELECT step_fk FROM pipeline_step_deps WHERE id = %s",
                    (intruder_plan['dep'],))
        assert str(cur.fetchone()['step_fk']) == str(intruder_plan['step_b'])


def test_put_cannot_repoint_an_owned_edge_at_a_foreign_step(
        intruder, victim_plan, intruder_plan, db_connection):
    """`verify` columns were INSERT-only, so PUT walked straight past them.

    `dep_step_fk` is ON DELETE RESTRICT: an edge pointing at the victim's step
    makes that step undeletable and unmergeable, from inside the attacker's plan.
    """
    resp = intruder('PUT', '/darwin_dev/pipeline_step_deps',
                    body=[{'id': str(intruder_plan['dep']),
                           'dep_step_fk': str(victim_plan['step_b'])}])
    assert resp['statusCode'] == 403
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE dep_step_fk = %s",
                  (victim_plan['step_b'],)) == 0


def test_bulk_put_cannot_smuggle_a_foreign_parent_in_one_row(
        intruder, victim_plan, intruder_plan, db_connection):
    """One CASE statement covers every row, so one bad row refuses the batch."""
    resp = intruder('PUT', '/darwin_dev/pipeline_step_deps', body=[
        {'id': str(intruder_plan['dep']),
         'dep_step_fk': str(intruder_plan['step_c'])},
        {'id': str(intruder_plan['dep']), 'step_fk': str(victim_plan['step_a'])},
    ])
    assert resp['statusCode'] == 403
    with db_connection.cursor() as cur:
        cur.execute("SELECT step_fk FROM pipeline_step_deps WHERE id = %s",
                    (intruder_plan['dep'],))
        assert str(cur.fetchone()['step_fk']) == str(intruder_plan['step_b'])


def test_the_owner_can_still_move_their_own_edge_between_their_own_steps(
        invoke, victim_plan, db_connection):
    """Rewriting the scope column is legitimate — within your own rows."""
    resp = invoke('POST', '/darwin_dev/pipeline_step_deps',
                  body={'step_fk': victim_plan['step_a'],
                        'dep_step_fk': victim_plan['step_c']})
    assert resp['statusCode'] == 200
    moved = extract_id(resp)
    try:
        assert invoke('PUT', '/darwin_dev/pipeline_step_deps',
                      body=[{'id': str(moved),
                             'step_fk': str(victim_plan['step_b'])}])['statusCode'] == 200
        with db_connection.cursor() as cur:
            cur.execute("SELECT step_fk FROM pipeline_step_deps WHERE id = %s",
                        (moved,))
            assert str(cur.fetchone()['step_fk']) == str(victim_plan['step_b'])
    finally:
        with db_connection.cursor() as cur:
            cur.execute("DELETE FROM pipeline_step_deps WHERE id = %s", (moved,))
        db_connection.commit()


def test_put_cannot_push_an_owned_row_into_another_users_account(
        intruder, intruder_fk, creator_fk, test_data, db_connection):
    """`creator_fk` was not stripped from PUT bodies, unlike POST.

    A push rather than a pull — you cannot steal a row this way — but it is still
    a cross-tenant stored write, and it lands the victim an orphan task pointing
    at an area in somebody else's domain.
    """
    domain = intruder('POST', '/darwin_dev/domains', body={'domain_name': 'push'})
    domain_id = extract_id(domain)
    area = intruder('POST', '/darwin_dev/areas',
                    body={'area_name': 'push', 'domain_fk': domain_id,
                          'closed': '0', 'sort_order': '1'})
    area_id = extract_id(area)
    task = intruder('POST', '/darwin_dev/tasks',
                    body={'description': 'push', 'area_fk': area_id,
                          'priority': '0', 'done': '0'})
    task_id = extract_id(task)
    try:
        intruder('PUT', '/darwin_dev/tasks',
                 body=[{'id': str(task_id), 'creator_fk': creator_fk}])
        with db_connection.cursor() as cur:
            cur.execute("SELECT creator_fk FROM tasks WHERE id = %s", (task_id,))
            assert cur.fetchone()['creator_fk'] == intruder_fk
    finally:
        with db_connection.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            cur.execute("DELETE FROM areas WHERE id = %s", (area_id,))
            cur.execute("DELETE FROM domains WHERE id = %s", (domain_id,))
        db_connection.commit()


# ---------------------------------------------------------------------------
# DELETE body keys are SQL — the injection that cancelled the predicate
# ---------------------------------------------------------------------------

def test_delete_body_key_injection_cannot_cancel_the_scoping(
        intruder, victim_plan, db_connection):
    """`{"id = 1 OR step_fk = N OR id": 1}` renders as

        WHERE id = 1 OR step_fk = N OR id = %s AND step_fk IN (SELECT ...)

    which MySQL reads as `id=1 OR TRUE-ish OR (...)`, because AND binds tighter
    than OR — and the placeholder and argument counts still balance, so it runs.
    Measured against darwin_dev deleting the victim's edges outright. Defeats the
    pre-existing `creator_fk` scoping the same way, on every table.
    """
    before = _count(db_connection,
                    "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE step_fk = %s",
                    (victim_plan['step_b'],))
    assert before == 1

    resp = intruder('DELETE', '/darwin_dev/pipeline_step_deps', body={
        f"id = 1 OR step_fk = {victim_plan['step_b']} OR id": '1'})
    assert resp['statusCode'] == 400
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM pipeline_step_deps WHERE step_fk = %s",
                  (victim_plan['step_b'],)) == before


def test_delete_body_key_injection_cannot_cancel_creator_fk_scoping(
        intruder, test_data, test_ids, db_connection):
    """The same payload against an ordinary creator_fk table."""
    resp = intruder('DELETE', '/darwin_dev/tasks',
                    body={'id = 1 OR 1=1 OR id': '1'})
    assert resp['statusCode'] == 400
    assert _count(db_connection, "SELECT COUNT(*) AS n FROM tasks WHERE id = %s",
                  (test_ids['task_id'],)) == 1


def test_delete_rejects_an_unknown_column_rather_than_interpolating_it(intruder):
    resp = intruder('DELETE', '/darwin_dev/pipeline_step_deps',
                    body={'not_a_column': '1'})
    assert resp['statusCode'] == 400


def test_the_owner_can_still_delete_by_a_real_column(invoke, victim_plan,
                                                     db_connection):
    """Key validation must not break the legitimate multi-key delete."""
    resp = invoke('POST', '/darwin_dev/pipeline_step_deps',
                  body={'step_fk': victim_plan['step_a'],
                        'dep_step_fk': victim_plan['step_b']})
    assert resp['statusCode'] == 200
    made = extract_id(resp)
    assert invoke('DELETE', '/darwin_dev/pipeline_step_deps',
                  body={'step_fk': str(victim_plan['step_a']),
                        'dep_step_fk': str(victim_plan['step_b'])})['statusCode'] == 200
    assert _dep_row(db_connection, made) is None


# ---------------------------------------------------------------------------
# priority_card_order — the one table with no FK to fall through to
# ---------------------------------------------------------------------------

def test_a_domain_that_does_not_exist_is_refused_where_no_fk_would_catch_it(
        intruder, db_connection):
    """`priority_card_order` declares no foreign keys at all.

    Everywhere else "the parent does not exist" is left to the FK as a 409/1452.
    Here nothing would reject it, and the row would sit invisible until
    AUTO_INCREMENT reached that domain id and handed it to its new owner.
    """
    resp = intruder('POST', '/darwin_dev/priority_card_order',
                    body={'domain_id': '999999999', 'task_id': '1',
                          'sort_order': '0'})
    assert resp['statusCode'] == 403
    assert _count(db_connection,
                  "SELECT COUNT(*) AS n FROM priority_card_order WHERE domain_id = %s",
                  (999999999,)) == 0


def test_the_owner_can_still_order_cards_in_their_own_domain(
        invoke, test_data, test_ids, db_connection):
    """The whole priority_card_order round trip, including the bulk PUT."""
    resp = invoke('POST', '/darwin_dev/priority_card_order',
                  body={'domain_id': test_ids['domain_id'],
                        'task_id': test_ids['task_id'], 'sort_order': '0'})
    assert resp['statusCode'] == 200
    order_id = extract_id(resp)
    try:
        assert invoke('PUT', '/darwin_dev/priority_card_order',
                      body=[{'id': str(order_id), 'sort_order': '3'}])['statusCode'] == 200
        rows = _rows(invoke('GET', '/darwin_dev/priority_card_order',
                            query={'domain_id': str(test_ids['domain_id'])}))
        assert [r['sort_order'] for r in rows] == [3]
    finally:
        with db_connection.cursor() as cur:
            cur.execute("DELETE FROM priority_card_order WHERE id = %s", (order_id,))
        db_connection.commit()
