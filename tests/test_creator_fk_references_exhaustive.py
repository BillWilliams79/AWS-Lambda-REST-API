"""EVERY registered column, BOTH verbs, cross-tenant (req #3125).

`test_creator_fk_references.py` covers the attack in depth on a handful of
representative columns. This file covers it in BREADTH: the requirement asks for
"cross-tenant test cases in the #3094/#3122 pattern **for every column, both
verbs**", and that is 47 columns across 29 tables (see
`test_the_matrix_is_the_whole_registry` for the count's own history), so it is
generated from the registry rather than hand-written 94 times.

Generating from `CREATOR_TABLE_REFERENCES` is also the point. A hand-written list
would drift from the registry exactly the way the registry would have drifted from
`schema.sql` — the drift this whole requirement exists to stop. Add a column to the
registry and it is tested here on the next run, or the fixture fails loudly
because nobody taught it how to build that table.

Each case builds a **complete, valid** row for the attacker with every one of its
own reference columns pointing at the attacker's own parents, then swaps exactly
ONE of them for the victim's. So a 403 can only be the column under test — not a
missing NOT NULL, not a second foreign reference, not an FK typo.

Needs `darwin_dev` (`. exports.sh`); skips cleanly without it.
"""
import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth_utils import CREATOR_TABLE_REFERENCES

from conftest import extract_id


# Every (table, column, parent) the registry declares — the test matrix.
TRIPLES = [(table, column, parent)
           for table, columns in sorted(CREATOR_TABLE_REFERENCES.items())
           for column, parent in columns]

# Parent tables a fixture graph must supply an owned row for.
PARENTS = sorted({parent for _, _, parent in TRIPLES})


def _tid(triple):
    return f'{triple[0]}.{triple[1]}->{triple[2]}'


# ---------------------------------------------------------------------------
# Minimal valid bodies — the NON-reference columns each table demands
# ---------------------------------------------------------------------------
#
# Derived from `DESC`: NOT NULL, no default, not auto_increment. Reference
# columns are added by the test itself, so they are deliberately absent here.
# `seed` makes UNIQUE keys (machines.hostname, map_routes.route_id,
# dev_servers.(machine_fk, port)) distinct between the two identities.

def _required_columns(table, seed):
    return {
        'agent_telemetry_row_docs': {'doc_path': f'/{seed}/doc.md',
                                     'actual_tokens': 1},
        'agent_telemetry_rows': {'agent_name': f'{seed}-agent'},
        'agent_telemetry_runs': {'label': f'{seed}-run'},
        'areas': {'area_name': f'{seed}-area'[:32], 'closed': '0'},
        'branches': {'branch_type': 'development', 'major': 1, 'minor': 0},
        'build_projects': {'title': f'{seed}-bp'},
        'builds': {'position': 1, 'build_number': 1},
        'categories': {'category_name': f'{seed}-cat'[:32]},
        'customer_releases': {},
        'dev_servers': {'port': 3000 + (seed_int(seed) % 8), 'pid': 999000,
                        'workspace_path': f'/tmp/{seed}'},
        'epics': {'title': f'{seed}-epic'},
        'map_runs': {'run_id': seed_int(seed), 'activity_id': f'{seed}-act',
                     'activity_name': 'ride', 'start_time': '2026-07-27 00:00:00',
                     'run_time_sec': 1, 'distance_mi': 1},
        # Req #3224. NO required non-reference columns: `polls` and `claimed_at`
        # carry DEFAULTs, `epic_key` is GENERATED, and `creator_fk` is forced
        # from the token — so the body is exactly the three references the test
        # adds. Its UNIQUE (pipeline_fk, epic_key) is why `_drop` matters here,
        # like the three tables named in that function.
        'orchestration_claims': {},
        'pipeline_steps': {'title': f'{seed}-step'},
        'pipelines': {'title': f'{seed}-pipeline'},
        # Req #3337. Like `epics`/`pipelines` above, the only NOT NULL,
        # no-default, non-reference column each carries is `title`.
        'pipeline2_pipelines': {'title': f'{seed}-p2pipeline'},
        'pipeline2_epics': {'title': f'{seed}-p2epic'},
        'pipeline2_steps': {'title': f'{seed}-p2step'},
        'recurring_tasks': {'description': f'{seed}-rt', 'recurrence': 'daily',
                            'anchor_date': '2026-07-27'},
        'requirements': {'title': f'{seed}-req', 'ai_model': 'opus',
                         'effort': 'high'},
        # No NOT NULL columns of their own, but `rest_post` 400s an EMPTY body
        # (`if not body`), so each needs one harmless column to be a valid write
        # at all. Their only registered reference is the nullable `machine_fk`.
        'swarm_sessions': {'task_name': f'{seed}-sess'},
        'swarm_starts': {'arguments': f'{seed}-args'},
        'swarm_undos': {'reason': f'{seed}-reason'},
        # Req #3202. The only NOT NULL, no-default, non-reference column;
        # `machine_fk` is nullable (see the schema comment — no backfill was
        # possible for this one), so the reference the test adds is optional
        # in the schema but still exercised here like every other column.
        'swarm_completes': {'skill_name': f'{seed}-skill'},
        'tasks': {'priority': '0', 'done': '0', 'description': f'{seed}-task'},
        'test_cases': {'title': f'{seed}-case', 'steps': 's', 'expected': 'e'},
        'test_plans': {'title': f'{seed}-plan'},
        'test_results': {},
        'test_runs': {'run_status': 'in_progress'},
    }[table]


def seed_int(seed):
    """A small stable int from a seed string, for UNIQUE-keyed columns."""
    return abs(hash(seed)) % 100000 + 1


# COVERS: SCH-016
def test_the_matrix_is_the_whole_registry():
    """Guard the guard: a generation bug would make every case below vacuous."""
    assert len(TRIPLES) == sum(len(v) for v in CREATOR_TABLE_REFERENCES.values())
    # 36 at req #3125, 38 at #3186 (which added the two `swarm_sessions`
    # attribution FKs and left this literal at 36 — it has been failing since),
    # 41 at #3224's three `orchestration_claims` columns, 45 at #3337's four
    # Pipeline 2.0 plan-layer columns. Found already red at 48 when #3350
    # landed (this file had drifted, undetected because nobody re-ran it): 47
    # from req #3369's two `orchestration_claims.pipeline2_fk`/`.epic2_fk`, 48
    # from req #3202's one `swarm_completes.machine_fk` — neither accompanied
    # by an update here, and `swarm_completes` had no body template at all
    # (see `_required_columns`). #3350 fixes both gaps AND adds its own two
    # `swarm_sessions` 2.0 attribution siblings (pipeline2_fk/epic2_fk — no
    # new parent tables, both already built for #3337's own
    # pipeline2_epics/pipeline2_steps entries), landing on 50. Req #3355 drops
    # `features` — both its `requirements.feature_fk` column AND its own
    # `('category_fk', 'categories')`/`('epic_fk', 'epics')` entry — taking
    # TRIPLES to 47 and, since `features` was itself a PARENT of nothing else
    # registered, PARENTS to 23.
    assert len(TRIPLES) == 47, f'expected 47 registered columns, generated {len(TRIPLES)}'
    assert len(PARENTS) == 23, PARENTS
    assert ('test_runs', 'test_plan_fk', 'test_plans') in TRIPLES


# COVERS: SCH-016
def test_every_table_in_the_registry_has_a_body_template():
    """A new registered table must fail HERE, not as a confusing KeyError inside
    a parametrized case where it would look like an authorization result."""
    for table in CREATOR_TABLE_REFERENCES:
        try:
            _required_columns(table, 'probe')
        except KeyError:
            pytest.fail(f'{table} is registered but this file cannot build a row '
                        'for it — add its required columns to _required_columns')


# ---------------------------------------------------------------------------
# Identities and their asset graphs
# ---------------------------------------------------------------------------

# FK-safe teardown order. RESTRICT edges decide most of it: machines is RESTRICT
# from five tables, categories from five, test_plans from test_runs, test_cases
# and customers from their children. branches<->builds is the one cycle, and
# deleting builds first is safe because branches.parent_build_fk is SET NULL.
PURGE_ORDER = (
    'agent_telemetry_row_docs', 'agent_telemetry_rows', 'agent_telemetry_runs',
    'customer_releases', 'dev_servers', 'swarm_undos', 'swarm_completes',
    # req #3224/#3369. `machine_fk` is RESTRICT (like the five other tables
    # noted below), so this must precede `machines`. Not a PARENT — nothing
    # references `orchestration_claims` — so it needs no `_build_graph` entry,
    # only this safety-net sweep for rows a test case creates and does not
    # itself `_drop`.
    'orchestration_claims',
    'pipeline_steps', 'pipelines',
    'pipeline2_steps', 'pipeline2_epics', 'pipeline2_pipelines',
    'test_results', 'test_runs', 'test_plans', 'test_cases',
    'requirements', 'epics',
    'tasks', 'recurring_tasks', 'areas', 'domains',
    'builds', 'branches', 'build_projects', 'customers',
    'map_runs', 'map_routes',
    'categories', 'projects',
    'swarm_sessions', 'swarm_starts', 'machines',
)


def _purge(conn, creator, drop_profile):
    import pymysql as _pymysql
    try:
        with conn.cursor() as cur:
            for table in PURGE_ORDER:
                cur.execute(f"DELETE FROM {table} WHERE creator_fk = %s", (creator,))
            if drop_profile:
                cur.execute("DELETE FROM profiles WHERE id = %s", (creator,))
        conn.commit()
    except _pymysql.MySQLError as e:
        conn.rollback()
        print(f'teardown for {creator} failed: {e}')


def _make_invoke(sub):
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


def _build_graph(invoke, seed):
    """One owned row in each of the 23 parent tables, created THROUGH the gateway.

    Doubling as the owner-side regression proof: every one of these POSTs now
    runs the ownership guard, so a rule that over-refuses fails here before any
    attacker case is reached.
    """
    ids = {}

    def post(table, body):
        resp = invoke('POST', f'/darwin_dev/{table}', body=body)
        assert resp['statusCode'] in (200, 201), f'{seed} {table} POST: {resp}'
        new_id = extract_id(resp)
        assert new_id is not None, f'{seed} {table} POST returned no id: {resp}'
        ids[table] = new_id
        return new_id

    req = lambda t: _required_columns(t, seed)

    # Roots — nothing referenced.
    post('projects', {'project_name': f'{seed}-proj'})
    post('domains', {'domain_name': f'{seed}-dom'[:32], 'closed': '0'})
    post('machines', {'title': f'{seed}-m', 'hostname': f'{seed}-host',
                      'platform': 'darwin', 'arch': 'arm64'})
    post('customers', {'customer_name': f'{seed}-cust'})
    post('map_routes', {'route_id': seed_int(seed), 'name': f'{seed}-route'})
    post('build_projects', req('build_projects'))
    post('swarm_sessions', req('swarm_sessions'))
    post('swarm_starts', req('swarm_starts'))
    post('pipelines', req('pipelines'))
    post('agent_telemetry_runs', req('agent_telemetry_runs'))
    post('pipeline2_pipelines', req('pipeline2_pipelines'))

    # One level down.
    post('categories', dict(req('categories'), project_fk=ids['projects']))
    post('areas', dict(req('areas'), domain_fk=ids['domains']))
    post('branches', dict(req('branches'), project_fk=ids['build_projects']))
    post('agent_telemetry_rows', dict(req('agent_telemetry_rows'),
                                      run_fk=ids['agent_telemetry_runs']))

    # Two levels down.
    post('epics', dict(req('epics'), category_fk=ids['categories']))
    post('test_plans', dict(req('test_plans'), category_fk=ids['categories']))
    post('test_cases', dict(req('test_cases'), category_fk=ids['categories']))
    post('recurring_tasks', dict(req('recurring_tasks'), area_fk=ids['areas']))
    post('builds', dict(req('builds'), branch_fk=ids['branches']))
    post('pipeline2_epics', dict(req('pipeline2_epics'),
                                 pipeline_fk=ids['pipeline2_pipelines'],
                                 category_fk=ids['categories']))

    # Three.
    post('requirements', dict(req('requirements'), category_fk=ids['categories']))
    post('test_runs', dict(req('test_runs'), test_plan_fk=ids['test_plans']))
    post('pipeline2_steps', dict(req('pipeline2_steps'), epic_fk=ids['pipeline2_epics']))

    missing = [p for p in PARENTS if p not in ids]
    assert not missing, f'{seed} graph is missing parent rows for {missing}'
    return ids


@pytest.fixture(scope="module")
def victim_graph(db_connection, test_data):
    sub = f"exh-victim-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    invoke = _make_invoke(sub)
    invoke('POST', '/darwin_dev/profiles',
           body={'id': sub, 'name': 'Exhaustive Victim',
                 'email': f'{sub}@test.invalid'})
    try:
        yield sub, invoke, _build_graph(invoke, f'exhv{uuid.uuid4().hex[:5]}')
    finally:
        _purge(db_connection, sub, drop_profile=True)


@pytest.fixture(scope="module")
def attacker_graph(db_connection, test_data):
    sub = f"exh-attacker-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    invoke = _make_invoke(sub)
    invoke('POST', '/darwin_dev/profiles',
           body={'id': sub, 'name': 'Exhaustive Attacker',
                 'email': f'{sub}@test.invalid'})
    try:
        yield sub, invoke, _build_graph(invoke, f'exha{uuid.uuid4().hex[:5]}')
    finally:
        _purge(db_connection, sub, drop_profile=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_body(table, ids, seed):
    """A complete body for `table` with EVERY reference pointing at `ids`.

    The baseline a case mutates by exactly one column, so a refusal can only be
    that column.
    """
    body = dict(_required_columns(table, seed))
    for column, parent in CREATOR_TABLE_REFERENCES[table]:
        body[column] = ids[parent]

    # `builds` is UNIQUE (branch_fk, position) and the fixture graph already
    # holds position 1 on the only branch this identity owns — it is a PARENT
    # row, so unlike a case's row it is never dropped. Cases take a slot well
    # clear of it. (`_drop` handles collisions BETWEEN cases; this one is with a
    # row that has to survive.)
    if table == 'builds':
        body['position'] = body['build_number'] = 1000 + seed_int(seed) % 8000
    return body


def _count_referencing(conn, table, column, value):
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = %s",
                    (value,))
        row = cur.fetchone()
    return row['n'] if isinstance(row, dict) else row[0]


def _drop(conn, table, row_id):
    """Remove a row a case created, so the next case can create the same shape.

    Four tables put a UNIQUE key ON their reference columns —
    `builds (branch_fk, position)`, `customer_releases (customer_fk, build_fk)`,
    `test_results (test_run_fk, test_case_fk)` and, since req #3224,
    `orchestration_claims (pipeline_fk, epic_key)` — so two cases writing the
    identical owned row collide on 1062 rather than testing anything. Deleting
    between cases is simpler and more honest than manufacturing a pool of spare
    parents whose only purpose is to dodge a UNIQUE key.
    """
    import pymysql as _pymysql
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (row_id,))
        conn.commit()
    except _pymysql.MySQLError as e:
        conn.rollback()
        print(f'could not drop {table}.{row_id}: {e}')


def _value(conn, table, row_id, column):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {column} AS v FROM {table} WHERE id = %s", (row_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return row['v'] if isinstance(row, dict) else row[0]


# ---------------------------------------------------------------------------
# POST — every column
# ---------------------------------------------------------------------------

# COVERS: SCH-017
@pytest.mark.parametrize('triple', TRIPLES, ids=[_tid(t) for t in TRIPLES])
def test_post_naming_a_victim_parent_is_refused(triple, victim_graph,
                                                attacker_graph, db_connection):
    """50 cases (four of them #3337's, two of them req #3369's, one req #3202's,
    two more #3350's, against a
    victim-owned pipeline2_pipelines -> pipeline2_epics chain built by
    `_build_graph`). The attacker's own, otherwise-valid row, aimed at the
    victim.

    `creator_fk` is forced from the attacker's token, so nothing else in the
    gateway objects — this is the whole vulnerability in one request.
    """
    table, column, parent = triple
    _, victim_ids = victim_graph[0], victim_graph[2]
    _, attacker_invoke, attacker_ids = attacker_graph

    body = _own_body(table, attacker_ids, 'atk')
    body[column] = victim_ids[parent]

    before = _count_referencing(db_connection, table, column, victim_ids[parent])
    resp = attacker_invoke('POST', f'/darwin_dev/{table}', body=body)

    assert resp['statusCode'] == 403, f'{_tid(triple)} was not refused: {resp}'
    assert _count_referencing(db_connection, table, column,
                              victim_ids[parent]) == before, \
        f'{_tid(triple)}: a row landed on the victim parent anyway'


# ---------------------------------------------------------------------------
# PUT — every column
# ---------------------------------------------------------------------------

# COVERS: SCH-017
@pytest.mark.parametrize('triple', TRIPLES, ids=[_tid(t) for t in TRIPLES])
def test_put_repointing_at_a_victim_parent_is_refused(triple, victim_graph,
                                                      attacker_graph,
                                                      db_connection):
    """50 more. The row is genuinely the attacker's, so the `creator_fk = %s`
    predicate passes and only the SET clause is hostile — the door that stays
    open if POST alone is guarded."""
    table, column, parent = triple
    victim_ids = victim_graph[2]
    _, attacker_invoke, attacker_ids = attacker_graph

    created = attacker_invoke(
        'POST', f'/darwin_dev/{table}',
        body=_own_body(table, attacker_ids, f'p{seed_int(table + column) % 9999}'))
    assert created['statusCode'] in (200, 201), \
        f'{_tid(triple)} owner POST failed: {created}'
    row_id = extract_id(created)
    assert row_id is not None, f'{_tid(triple)} POST returned no id: {created}'

    try:
        original = _value(db_connection, table, row_id, column)

        resp = attacker_invoke('PUT', f'/darwin_dev/{table}',
                               body=[{'id': row_id, column: victim_ids[parent]}])

        assert resp['statusCode'] == 403, \
            f'{_tid(triple)} PUT was not refused: {resp}'
        assert _value(db_connection, table, row_id, column) == original, \
            f'{_tid(triple)}: the row was re-pointed at the victim anyway'
    finally:
        _drop(db_connection, table, row_id)


# ---------------------------------------------------------------------------
# The divergent forms, on every column
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('triple', TRIPLES, ids=[_tid(t) for t in TRIPLES])
def test_no_divergent_spelling_of_a_victim_parent_lands_on_any_column(
        triple, victim_graph, attacker_graph, db_connection):
    """The #3122 value-divergence payloads, applied to all 50 columns.

    Each is a spelling MySQL reads as the victim's id and Python does not. Any
    one accepted is the same cross-tenant write through a different door, so the
    assertion that matters is the row count, not the status.
    """
    table, column, parent = triple
    victim_ids = victim_graph[2]
    _, attacker_invoke, attacker_ids = attacker_graph
    target = victim_ids[parent]

    forms = [f'{target}_0', f'{target}.0', f'{target}abc', f' {target}',
             f'\xa0{target}', f'0{target}', f'+{target}', '٢']

    before = _count_referencing(db_connection, table, column, target)
    for form in forms:
        body = _own_body(table, attacker_ids, 'dvg')
        body[column] = form
        resp = attacker_invoke('POST', f'/darwin_dev/{table}', body=body)
        assert resp['statusCode'] in (400, 403), \
            f'{_tid(triple)} accepted {form!r}: {resp}'

    assert _count_referencing(db_connection, table, column, target) == before, \
        f'{_tid(triple)}: a divergent spelling landed a row on the victim parent'


# ---------------------------------------------------------------------------
# Owner-side regression, per column
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('triple', TRIPLES, ids=[_tid(t) for t in TRIPLES])
def test_the_owner_can_still_write_every_guarded_column(triple, attacker_graph,
                                                        db_connection):  # noqa: D401
    """A rule that also breaks the owner is not a fix.

    The fixture graph already proves the owner can CREATE each table; this proves
    they can still PUT each individual reference column to a row they own — the
    legitimate move the guard must never catch.
    """
    table, column, parent = triple
    _, invoke, ids = attacker_graph

    created = invoke('POST', f'/darwin_dev/{table}',
                     body=_own_body(table, ids, f'own{seed_int(column) % 9999}'))
    assert created['statusCode'] in (200, 201), f'{_tid(triple)}: {created}'
    row_id = extract_id(created)
    assert row_id is not None, f'{_tid(triple)} POST returned no id: {created}'

    try:
        resp = invoke('PUT', f'/darwin_dev/{table}',
                      body=[{'id': row_id, column: ids[parent]}])
        assert resp['statusCode'] in (200, 204), \
            f'{_tid(triple)}: the OWNER was refused their own parent: {resp}'
    finally:
        _drop(db_connection, table, row_id)
