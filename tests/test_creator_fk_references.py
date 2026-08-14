"""Cross-tenant tests for outbound FK ownership on creator_fk tables (req #3125).

The #3094/#3122 pattern aimed at the tables that DO carry `creator_fk`: plant
real rows for a victim, drive the gateway as a second authenticated user, and
prove the answer is 403 or 400 — never a write that lands.

WHAT MAKES THIS CLASS DIFFERENT from req #3122. There, the attacker had to reach
a row they did not own. Here they never do: they write their OWN row, correctly
scoped to their own `creator_fk`, and merely POINT it at the victim. Every
existing check passes, because every existing check asks who owns the row and
none asks who owns what it references.

`test_the_victim_can_still_delete_their_own_plan_after_a_refused_attack` is the
one that states the stakes. `fk_test_runs_plan` is `ON DELETE RESTRICT`, so a
single accepted POST would leave the victim permanently unable to delete their
own test plan — blocked by a `test_runs` row that is scoped to the attacker and
therefore invisible, unlistable and undeletable to them. No self-service
recovery exists; that is why the requirement calls it a grief-lock.

Every attacker test is paired with a raw-SQL assertion that nothing landed — a
403 that hid a completed write would look identical from the outside. The
victim-side tests interleaved through the file matter as much: a rule that also
breaks the owner is not a fix, and this one now runs on `tasks` and `areas`.

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
    return f"fkref-intruder-{int(time.time())}-{uuid.uuid4().hex[:6]}"


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
        'id': intruder_fk, 'name': 'FK Reference Intruder',
        'email': 'fkref-intruder@test.invalid'})
    yield _invoke
    _purge(db_connection, intruder_fk)


def _purge(conn, creator):
    """Tear a creator's test/task graph down in FK-safe order.

    Results before runs and cases (both RESTRICT), runs before plans (RESTRICT),
    everything before categories (RESTRICT). Anything else and the DELETE fails
    on a constraint rather than cleaning up.
    """
    import pymysql as _pymysql
    try:
        with conn.cursor() as cur:
            for statement in (
                    "DELETE FROM test_results WHERE creator_fk = %s",
                    "DELETE FROM test_runs WHERE creator_fk = %s",
                    "DELETE FROM test_plans WHERE creator_fk = %s",
                    "DELETE FROM test_cases WHERE creator_fk = %s",
                    "DELETE FROM requirements WHERE creator_fk = %s",
                    "DELETE FROM tasks WHERE creator_fk = %s",
                    "DELETE FROM recurring_tasks WHERE creator_fk = %s",
                    "DELETE FROM areas WHERE creator_fk = %s",
                    "DELETE FROM domains WHERE creator_fk = %s",
                    "DELETE FROM categories WHERE creator_fk = %s",
                    "DELETE FROM projects WHERE creator_fk = %s",
                    "DELETE FROM profiles WHERE id = %s"):
                cur.execute(statement, (creator,))
        conn.commit()
    except _pymysql.MySQLError:
        conn.rollback()


# ---------------------------------------------------------------------------
# Fixtures — one full graph per identity, built through the gateway
# ---------------------------------------------------------------------------

def _build_graph(post, label):
    """project -> category -> {test_plan -> test_run, test_case}, + domain -> area.

    Built through the REST API rather than raw SQL on purpose: it is
    simultaneously the regression guard that an OWNER can still create every one
    of these rows now that each POST costs an ownership lookup.
    """
    ids = {}

    resp = post('/darwin_dev/projects', {'project_name': f'{label} project'})
    assert resp['statusCode'] == 200, f'{label} project POST: {resp}'
    ids['project'] = extract_id(resp)

    resp = post('/darwin_dev/categories', {'category_name': f'{label} category',
                                           'project_fk': ids['project']})
    assert resp['statusCode'] == 200, f'{label} category POST: {resp}'
    ids['category'] = extract_id(resp)

    resp = post('/darwin_dev/test_plans', {'title': f'{label} plan',
                                           'category_fk': ids['category']})
    assert resp['statusCode'] == 200, f'{label} test_plan POST: {resp}'
    ids['test_plan'] = extract_id(resp)

    resp = post('/darwin_dev/test_runs', {'test_plan_fk': ids['test_plan'],
                                          'run_status': 'in_progress'})
    assert resp['statusCode'] == 200, f'{label} test_run POST: {resp}'
    ids['test_run'] = extract_id(resp)

    resp = post('/darwin_dev/test_cases', {'title': f'{label} case',
                                           'steps': 'do the thing',
                                           'expected': 'the thing happened',
                                           'category_fk': ids['category']})
    assert resp['statusCode'] == 200, f'{label} test_case POST: {resp}'
    ids['test_case'] = extract_id(resp)

    resp = post('/darwin_dev/domains', {'domain_name': f'{label[:12]} dom',
                                        'closed': '0'})
    assert resp['statusCode'] == 200, f'{label} domain POST: {resp}'
    ids['domain'] = extract_id(resp)

    resp = post('/darwin_dev/areas', {'area_name': f'{label[:12]} area',
                                      'domain_fk': ids['domain'], 'closed': '0'})
    assert resp['statusCode'] == 200, f'{label} area POST: {resp}'
    ids['area'] = extract_id(resp)

    return ids


@pytest.fixture(scope="module")
def victim(invoke, test_data, db_connection, creator_fk):
    ids = _build_graph(lambda path, body: invoke('POST', path, body=body), 'victim')
    yield ids
    _purge_owned(db_connection, creator_fk)


def _purge_owned(conn, creator):
    """Same teardown as `_purge` but leaves the profile — conftest owns it."""
    import pymysql as _pymysql
    try:
        with conn.cursor() as cur:
            for statement in (
                    "DELETE FROM test_results WHERE creator_fk = %s",
                    "DELETE FROM test_runs WHERE creator_fk = %s",
                    "DELETE FROM test_plans WHERE creator_fk = %s",
                    "DELETE FROM test_cases WHERE creator_fk = %s",
                    "DELETE FROM requirements WHERE creator_fk = %s",
                    "DELETE FROM categories WHERE creator_fk = %s",
                    "DELETE FROM projects WHERE creator_fk = %s"):
                cur.execute(statement, (creator,))
        conn.commit()
    except _pymysql.MySQLError:
        conn.rollback()


@pytest.fixture(scope="module")
def attacker(intruder):
    """The intruder's own graph — the launchpad for "own row, foreign target"."""
    return _build_graph(lambda path, body: intruder('POST', path, body=body),
                        'intruder')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count(conn, table, column, value):
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = %s", (value,))
        row = cur.fetchone()
    return row['n'] if isinstance(row, dict) else row[0]


def _column(conn, table, row_id, column):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {column} AS v FROM {table} WHERE id = %s", (row_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return row['v'] if isinstance(row, dict) else row[0]


# ---------------------------------------------------------------------------
# POST — the attacker's own row, pointed at the victim's parent
# ---------------------------------------------------------------------------

def test_post_naming_a_victims_test_plan_is_refused(intruder, victim, attacker,
                                                    db_connection):
    """THE grief-lock. A `test_runs` row of the attacker's own, hung off the
    victim's plan through an `ON DELETE RESTRICT` FK."""
    before = _count(db_connection, 'test_runs', 'test_plan_fk', victim['test_plan'])

    resp = intruder('POST', '/darwin_dev/test_runs',
                    body={'test_plan_fk': victim['test_plan'],
                          'run_status': 'in_progress'})

    assert resp['statusCode'] == 403, resp
    assert json.loads(resp['body']) == 'FORBIDDEN'
    assert _count(db_connection, 'test_runs', 'test_plan_fk',
                  victim['test_plan']) == before, 'a row landed anyway'


def test_the_victim_can_still_delete_their_own_plan_after_a_refused_attack(
        invoke, intruder, victim, attacker, db_connection):
    """What the refusal is FOR — stated as the outcome, not the status code.

    With the attack accepted, this DELETE answers 409 naming `fk_test_runs_plan`,
    and the victim has no way to clear it: the blocking `test_runs` row is scoped
    to the attacker, so it is absent from their GET, unaddressable by their PUT
    and untouchable by their DELETE. The plan is theirs forever.

    Builds a plan of its own so the shared fixture survives for other tests.
    """
    resp = invoke('POST', '/darwin_dev/test_plans',
                  body={'title': 'victim disposable plan',
                        'category_fk': victim['category']})
    assert resp['statusCode'] == 200, resp
    plan_id = extract_id(resp)

    attack = intruder('POST', '/darwin_dev/test_runs',
                      body={'test_plan_fk': plan_id, 'run_status': 'in_progress'})
    assert attack['statusCode'] == 403, attack

    resp = invoke('DELETE', '/darwin_dev/test_plans', body={'id': plan_id})
    assert resp['statusCode'] == 200, (
        'the victim cannot delete their own test plan — the grief-lock is live: '
        f'{resp}')
    assert _count(db_connection, 'test_plans', 'id', plan_id) == 0


@pytest.mark.parametrize('table,column,parent_key,extra', [
    ('test_runs', 'test_plan_fk', 'test_plan', {'run_status': 'in_progress'}),
    ('test_plans', 'category_fk', 'category', {'title': 'stolen category plan'}),
    ('test_cases', 'category_fk', 'category', {'title': 'stolen category case',
                                               'steps': 's', 'expected': 'e'}),
    ('categories', 'project_fk', 'project', {'category_name': 'stolen project cat'}),
    ('areas', 'domain_fk', 'domain', {'area_name': 'stolen domain area',
                                      'closed': '0'}),
    ('tasks', 'area_fk', 'area', {'description': 'stolen area task',
                                  'priority': '0', 'done': '0'}),
])
def test_post_naming_any_victim_parent_is_refused(intruder, victim, attacker,
                                                  db_connection, table, column,
                                                  parent_key, extra):
    """One case per representative column, spanning RESTRICT and CASCADE alike.

    The CASCADE ones are not grief-locks, but they are still the attacker's row
    living inside the victim's tree — and on `areas`/`tasks` that tree is the
    user's whole task plan.
    """
    parent_id = victim[parent_key]
    before = _count(db_connection, table, column, parent_id)

    body = dict(extra)
    body[column] = parent_id
    resp = intruder('POST', f'/darwin_dev/{table}', body=body)

    assert resp['statusCode'] == 403, f'{table}.{column}: {resp}'
    assert _count(db_connection, table, column, parent_id) == before, (
        f'{table}.{column}: a row landed anyway')


def test_a_multi_parent_write_is_refused_on_any_one_foreign_parent(
        intruder, victim, attacker, db_connection):
    """`requirements` names three parents (project_fk, category_fk, machine_fk —
    the retired middle tier's reference was dropped at req #3355). Owning some
    of them is not enough."""
    before = _count(db_connection, 'requirements', 'category_fk', victim['category'])

    resp = intruder('POST', '/darwin_dev/requirements',
                    body={'title': 'mixed-parent requirement',
                          'requirement_status': 'authoring',
                          'coordination_type': 'implemented',
                          'ai_model': 'opus', 'effort': 'high',
                          'project_fk': attacker['project'],
                          'category_fk': victim['category']})

    assert resp['statusCode'] == 403, resp
    assert _count(db_connection, 'requirements', 'category_fk',
                  victim['category']) == before


def test_a_bulk_post_is_refused_whole_when_one_row_names_a_victim_parent(
        intruder, victim, attacker, db_connection):
    """A bulk POST is ONE multi-value INSERT: it lands or rolls back as a unit,
    so a single foreign reference anywhere in the batch must refuse all of it."""
    before_ok = _count(db_connection, 'test_runs', 'test_plan_fk',
                       attacker['test_plan'])
    before_bad = _count(db_connection, 'test_runs', 'test_plan_fk',
                        victim['test_plan'])

    resp = intruder('POST', '/darwin_dev/test_runs', body=[
        {'test_plan_fk': attacker['test_plan'], 'run_status': 'in_progress'},
        {'test_plan_fk': victim['test_plan'], 'run_status': 'in_progress'},
    ])

    assert resp['statusCode'] == 403, resp
    assert _count(db_connection, 'test_runs', 'test_plan_fk',
                  attacker['test_plan']) == before_ok, 'the good row landed'
    assert _count(db_connection, 'test_runs', 'test_plan_fk',
                  victim['test_plan']) == before_bad, 'the foreign row landed'


# ---------------------------------------------------------------------------
# PUT — the other door
# ---------------------------------------------------------------------------

def test_put_repointing_an_owned_row_at_a_victim_parent_is_refused(
        intruder, victim, attacker, db_connection):
    """The row is genuinely the attacker's, so `creator_fk = %s` passes.

    The SET clause then rewrites `test_plan_fk` to the victim's plan. Guarding
    POST alone leaves this door wide open — exactly how the equivalent junction
    guard was defeated in req #3122.
    """
    resp = intruder('POST', '/darwin_dev/test_runs',
                    body={'test_plan_fk': attacker['test_plan'],
                          'run_status': 'in_progress'})
    assert resp['statusCode'] == 200, resp
    run_id = extract_id(resp)

    resp = intruder('PUT', '/darwin_dev/test_runs',
                    body=[{'id': run_id, 'test_plan_fk': victim['test_plan']}])

    assert resp['statusCode'] == 403, resp
    assert str(_column(db_connection, 'test_runs', run_id, 'test_plan_fk')) == \
        str(attacker['test_plan']), 'the row was re-pointed anyway'


def test_a_bulk_put_is_refused_when_any_row_names_a_victim_parent(
        intruder, victim, attacker, db_connection):
    """The CASE-syntax path. `PriorityCard.jsx`-shaped traffic goes through it,
    so it is live code, not just the single-row branch in another costume."""
    ids = []
    for _ in range(2):
        resp = intruder('POST', '/darwin_dev/test_runs',
                        body={'test_plan_fk': attacker['test_plan'],
                              'run_status': 'in_progress'})
        assert resp['statusCode'] == 200, resp
        ids.append(extract_id(resp))

    resp = intruder('PUT', '/darwin_dev/test_runs', body=[
        {'id': ids[0], 'notes': 'harmless'},
        {'id': ids[1], 'test_plan_fk': victim['test_plan']},
    ])

    assert resp['statusCode'] == 403, resp
    for run_id in ids:
        assert str(_column(db_connection, 'test_runs', run_id, 'test_plan_fk')) == \
            str(attacker['test_plan'])
    assert _column(db_connection, 'test_runs', ids[0], 'notes') != 'harmless', (
        'the batch partially applied')


# ---------------------------------------------------------------------------
# The divergent forms — where Python and MySQL disagree about a value
# ---------------------------------------------------------------------------

def _divergent_forms(parent_id):
    """Spellings of `parent_id` that MySQL reads as that row and Python does not.

    Each one defeated the junction check before req #3122 canonicalized at the
    door: the lookup compared the request's text against MySQL's canonical id,
    matched nothing, read "does not exist", and fell through to the FK — which
    then coerced the value right back and wrote the row. Measured, not assumed.
    """
    return [
        f'{parent_id}_0',        # PEP 515 — int() reads it, MySQL truncates at '_'
        f'{parent_id}.0',        # float string — MySQL truncates at '.'
        f'{parent_id}abc',       # numeric prefix — non-strict sql_mode truncates
        f' {parent_id}',         # whitespace MySQL DOES skip
        f'\xa0{parent_id}',      # U+00A0 — whitespace MySQL does NOT skip
        f'0{parent_id}',         # leading zero
        f'+{parent_id}',         # explicit sign
        f'{parent_id}e0',        # scientific notation
        '٢',                # Unicode digit — MySQL reads 0, Python reads 2
    ]


def test_no_divergent_spelling_of_a_victim_parent_ever_lands(
        intruder, victim, attacker, db_connection):
    """Refused either way — 400 for a form MySQL would truncate, 403 for one it
    would not — and never a 200. The status matters less than the row count."""
    plan = victim['test_plan']
    before = _count(db_connection, 'test_runs', 'test_plan_fk', plan)
    outcomes = {}

    for form in _divergent_forms(plan):
        resp = intruder('POST', '/darwin_dev/test_runs',
                        body={'test_plan_fk': form, 'run_status': 'in_progress'})
        outcomes[repr(form)] = resp['statusCode']
        assert resp['statusCode'] in (400, 403), f'{form!r} was accepted: {resp}'

    assert _count(db_connection, 'test_runs', 'test_plan_fk', plan) == before, (
        f'a divergent spelling landed a row on the victim plan: {outcomes}')


def test_the_same_divergent_spellings_are_refused_on_put(
        intruder, victim, attacker, db_connection):
    """PUT canonicalizes at the same door; the SET clause is the same hazard."""
    resp = intruder('POST', '/darwin_dev/test_runs',
                    body={'test_plan_fk': attacker['test_plan'],
                          'run_status': 'in_progress'})
    assert resp['statusCode'] == 200, resp
    run_id = extract_id(resp)

    for form in _divergent_forms(victim['test_plan']):
        resp = intruder('PUT', '/darwin_dev/test_runs',
                        body=[{'id': run_id, 'test_plan_fk': form}])
        assert resp['statusCode'] in (400, 403), f'{form!r} was accepted: {resp}'
        assert str(_column(db_connection, 'test_runs', run_id,
                           'test_plan_fk')) == str(attacker['test_plan']), \
            f'{form!r} re-pointed the row'


def test_an_out_of_range_id_is_refused_rather_than_clamped(intruder, attacker):
    """MySQL CLAMPS an out-of-range INT instead of rejecting it, so
    `'2147483648'` names row 2147483647 to the database and a different row to
    the check. 400 before any lookup."""
    for value in ('2147483648', '-2147483649'):
        resp = intruder('POST', '/darwin_dev/test_runs',
                        body={'test_plan_fk': value, 'run_status': 'in_progress'})
        assert resp['statusCode'] == 400, f'{value}: {resp}'


# ---------------------------------------------------------------------------
# Body KEY spelling — the bypass found in review, end to end
# ---------------------------------------------------------------------------
#
# The guard reads body keys as exact Python strings; MySQL resolves column names
# case-insensitively and its lexer discards backticks, whitespace and comments.
# Every spelling below wrote `tasks.area_fk` while `body.get('area_fk')` returned
# None, so the guard saw no reference and answered 200. Measured against
# darwin_dev, and the same trick defeated req #3122's junction registry.

KEY_SPELLINGS = ['AREA_FK', 'Area_Fk', '`area_fk`', 'area_fk ', ' area_fk',
                 'area_fk/*x*/', 'area_fk\t']


@pytest.mark.parametrize('key', KEY_SPELLINGS)
def test_no_spelling_of_a_reference_column_evades_the_guard(intruder, victim,
                                                            attacker,
                                                            db_connection, key):
    """403 for a case variant (matched), 400 for anything else (refused)."""
    before = _count(db_connection, 'tasks', 'area_fk', victim['area'])

    resp = intruder('POST', '/darwin_dev/tasks',
                    body={'description': 'key trick', 'priority': '0',
                          'done': '0', key: victim['area']})

    assert resp['statusCode'] in (400, 403), f'{key!r} was accepted: {resp}'
    assert _count(db_connection, 'tasks', 'area_fk',
                  victim['area']) == before, f'{key!r} landed a row'


def test_a_case_variant_on_put_cannot_repoint_a_row(intruder, victim, attacker,
                                                    db_connection):
    resp = intruder('POST', '/darwin_dev/test_runs',
                    body={'test_plan_fk': attacker['test_plan'],
                          'run_status': 'in_progress'})
    assert resp['statusCode'] == 200, resp
    run_id = extract_id(resp)

    resp = intruder('PUT', '/darwin_dev/test_runs',
                    body=[{'id': run_id, 'TEST_PLAN_FK': victim['test_plan']}])

    assert resp['statusCode'] == 403, resp
    assert str(_column(db_connection, 'test_runs', run_id, 'test_plan_fk')) == \
        str(attacker['test_plan'])


def test_the_same_column_named_twice_in_two_spellings_is_refused(
        intruder, victim, attacker, db_connection):
    """The variant that beats case-insensitive matching on its own.

    MySQL applies the LAST assignment, so the guard would check the owned plan,
    approve, and the statement would apply the victim's.
    """
    resp = intruder('POST', '/darwin_dev/test_runs',
                    body={'test_plan_fk': attacker['test_plan'],
                          'run_status': 'in_progress'})
    assert resp['statusCode'] == 200, resp
    run_id = extract_id(resp)

    resp = intruder('PUT', '/darwin_dev/test_runs',
                    body=[{'id': run_id,
                           'test_plan_fk': attacker['test_plan'],
                           'TEST_PLAN_FK': victim['test_plan']}])

    assert resp['statusCode'] == 400, resp
    assert str(_column(db_connection, 'test_runs', run_id, 'test_plan_fk')) == \
        str(attacker['test_plan'])


def test_a_case_variant_in_a_LATER_bulk_put_item_is_still_checked(
        intruder, victim, attacker, db_connection):
    """The one combination the two rules do not individually cover.

    Two keys colliding within ONE body are refused; two bodies each using a
    different spelling are legal (they are separate rows). The bulk CASE path
    then builds a separate `CASE` expression per distinct key string, so
    `area_fk` and `AREA_FK` become two assignments to one column. The guard has
    to have inspected BOTH bodies' values for it to matter — verified here rather
    than reasoned about.
    """
    ids = []
    for _ in range(2):
        resp = intruder('POST', '/darwin_dev/test_runs',
                        body={'test_plan_fk': attacker['test_plan'],
                              'run_status': 'in_progress'})
        assert resp['statusCode'] == 200, resp
        ids.append(extract_id(resp))

    resp = intruder('PUT', '/darwin_dev/test_runs', body=[
        {'id': ids[0], 'test_plan_fk': attacker['test_plan']},
        {'id': ids[1], 'TEST_PLAN_FK': victim['test_plan']},
    ])

    assert resp['statusCode'] == 403, resp
    for run_id in ids:
        assert str(_column(db_connection, 'test_runs', run_id, 'test_plan_fk')) == \
            str(attacker['test_plan'])


def test_a_bulk_put_with_different_keys_per_item_still_works_for_the_owner(
        invoke, victim, db_connection):
    """Items in a bulk PUT need NOT name the same columns — unlike a bulk POST,
    the CASE syntax handles that natively, and `PriorityCard.jsx`-shaped traffic
    relies on it. The uniformity rule is a POST-only constraint."""
    resp = invoke('POST', '/darwin_dev/tasks',
                  body={'description': 'bulk a', 'priority': '0', 'done': '0',
                        'area_fk': victim['area']})
    a = extract_id(resp)
    resp = invoke('POST', '/darwin_dev/tasks',
                  body={'description': 'bulk b', 'priority': '0', 'done': '0',
                        'area_fk': victim['area']})
    b = extract_id(resp)

    resp = invoke('PUT', '/darwin_dev/tasks', body=[
        {'id': a, 'done': '1'},
        {'id': b, 'area_fk': victim['area'], 'sort_order': '2'},
    ])
    assert resp['statusCode'] == 200, resp


def test_a_creator_fk_case_variant_cannot_give_a_row_away(intruder, intruder_fk,
                                                          victim, attacker,
                                                          creator_fk,
                                                          db_connection):
    """`PUT [{"id": <mine>, "CREATOR_FK": "<victim>"}]` handed the row over.

    Not a grief-lock but the same root cause, and it defeated req #3122's
    `rest_put` `creator_fk` override — which exists precisely to stop a body
    pushing a row into another account. Verified landing before the fix.
    """
    resp = intruder('POST', '/darwin_dev/test_runs',
                    body={'test_plan_fk': attacker['test_plan'],
                          'run_status': 'in_progress'})
    assert resp['statusCode'] == 200, resp
    run_id = extract_id(resp)

    resp = intruder('PUT', '/darwin_dev/test_runs',
                    body=[{'id': run_id, 'CREATOR_FK': creator_fk}])

    assert _column(db_connection, 'test_runs', run_id, 'creator_fk') == \
        intruder_fk, f'the row was given away (status {resp["statusCode"]})'


def test_the_owner_is_unaffected_by_the_key_check(invoke, victim, db_connection):
    """Every column in `schema.sql` is a plain identifier, so nothing real breaks.

    Includes the `id: ''` blank-row template shape Darwin POSTs everywhere.
    """
    resp = invoke('POST', '/darwin_dev/tasks',
                  body={'id': '', 'description': 'plain keys', 'priority': '0',
                        'done': '0', 'area_fk': victim['area'],
                        'recurring_task_fk': 'NULL'})
    assert resp['statusCode'] == 200, resp


# ---------------------------------------------------------------------------
# Bulk POST column uniformity
# ---------------------------------------------------------------------------

def test_a_bulk_post_with_mismatched_columns_is_a_400_not_a_503(invoke, victim):
    """A bulk INSERT builds ONE column list from item 0 and indexes every item
    by it: a column missing from a later item raised KeyError from outside the
    try block and surfaced as a 503 naming nothing."""
    resp = invoke('POST', '/darwin_dev/tasks', body=[
        {'description': 'a', 'priority': '0', 'done': '0',
         'area_fk': victim['area']},
        {'description': 'b', 'priority': '0', 'done': '0'},
    ])
    assert resp['statusCode'] == 400, resp


def test_a_bulk_post_does_not_silently_drop_a_column_absent_from_item_zero(
        invoke, victim, db_connection):
    """The mirror case: `area_fk` was checked by the guard and then dropped from
    the statement, so the set inspected and the set written had drifted apart."""
    resp = invoke('POST', '/darwin_dev/tasks', body=[
        {'description': 'c', 'priority': '0', 'done': '0'},
        {'description': 'd', 'priority': '0', 'done': '0',
         'area_fk': victim['area']},
    ])
    assert resp['statusCode'] == 400, resp


def test_a_uniform_bulk_post_still_works(invoke, victim, db_connection):
    resp = invoke('POST', '/darwin_dev/tasks', body=[
        {'description': 'e', 'priority': '0', 'done': '0',
         'area_fk': victim['area']},
        {'description': 'f', 'priority': '0', 'done': '0',
         'area_fk': victim['area']},
    ])
    assert resp['statusCode'] == 201, resp
    assert json.loads(resp['body'])['inserted'] == 2


# ---------------------------------------------------------------------------
# Absent is not foreign — the 409 contract survives
# ---------------------------------------------------------------------------

def test_a_parent_that_does_not_exist_is_still_a_409_not_a_403(intruder, attacker):
    """A typo'd FK must keep the answer that is true of it.

    403 would be a confidently wrong explanation; 409 promises the thing that is
    actually the case — retrying with different data can succeed — and names the
    constraint. Same call `check_junction_parent_ownership` made in req #3122.
    """
    resp = intruder('POST', '/darwin_dev/test_runs',
                    body={'test_plan_fk': 2147483000, 'run_status': 'in_progress'})

    assert resp['statusCode'] == 409, resp
    body = json.loads(resp['body'])
    assert body['errno'] == 1452, body
    assert body['constraint'] == 'fk_test_runs_plan', body


# ---------------------------------------------------------------------------
# Victim-side regression — the owner must be unaffected
# ---------------------------------------------------------------------------

def test_the_owner_can_still_post_every_guarded_row(invoke, victim, db_connection):
    """The fixtures already prove this for eight tables; this states it directly
    for the two hottest, where a false refusal would break the whole app."""
    resp = invoke('POST', '/darwin_dev/tasks',
                  body={'description': 'victim own task', 'priority': '0',
                        'done': '0', 'area_fk': victim['area']})
    assert resp['statusCode'] == 200, resp
    task_id = extract_id(resp)
    assert str(_column(db_connection, 'tasks', task_id, 'area_fk')) == \
        str(victim['area'])

    resp = invoke('POST', '/darwin_dev/areas',
                  body={'area_name': 'victim own area 2',
                        'domain_fk': victim['domain'], 'closed': '0'})
    assert resp['statusCode'] == 200, resp


def test_the_owner_can_still_repoint_their_own_row(invoke, victim, db_connection):
    """A PUT that moves a row between two parents the caller owns is legitimate
    and must not be caught by the guard."""
    resp = invoke('POST', '/darwin_dev/test_plans',
                  body={'title': 'victim second plan',
                        'category_fk': victim['category']})
    assert resp['statusCode'] == 200, resp
    other_plan = extract_id(resp)

    resp = invoke('PUT', '/darwin_dev/test_runs',
                  body=[{'id': victim['test_run'], 'test_plan_fk': other_plan}])
    assert resp['statusCode'] == 200, resp
    assert str(_column(db_connection, 'test_runs', victim['test_run'],
                       'test_plan_fk')) == str(other_plan)

    # Put it back so the fixture stays coherent for any later test.
    resp = invoke('PUT', '/darwin_dev/test_runs',
                  body=[{'id': victim['test_run'],
                         'test_plan_fk': victim['test_plan']}])
    assert resp['statusCode'] == 200, resp


def test_a_put_that_names_no_parent_still_works(invoke, victim, db_connection):
    """The hot path. `PUT /darwin_dev/tasks [{"id": n, "done": 1}]` names no
    parent, so the guard must return without a lookup — and without breaking."""
    resp = invoke('POST', '/darwin_dev/tasks',
                  body={'description': 'victim toggle task', 'priority': '0',
                        'done': '0', 'area_fk': victim['area']})
    assert resp['statusCode'] == 200, resp
    task_id = extract_id(resp)

    resp = invoke('PUT', '/darwin_dev/tasks', body=[{'id': task_id, 'done': '1'}])
    assert resp['statusCode'] == 200, resp
    assert _column(db_connection, 'tasks', task_id, 'done') == 1


def test_the_owner_can_still_null_out_an_optional_reference(invoke, victim,
                                                            db_connection):
    """`"NULL"` is the wire sentinel for SQL NULL and names no row, so it must
    not be mistaken for an id — nor required to be one."""
    resp = invoke('POST', '/darwin_dev/tasks',
                  body={'description': 'victim nullable task', 'priority': '0',
                        'done': '0', 'area_fk': victim['area'],
                        'recurring_task_fk': 'NULL'})
    assert resp['statusCode'] == 200, resp
    task_id = extract_id(resp)
    assert _column(db_connection, 'tasks', task_id, 'recurring_task_fk') is None
