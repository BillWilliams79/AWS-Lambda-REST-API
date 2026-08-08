"""Join-through authorization for tables with no creator_fk (req #3122) — no DB.

Two jobs, and the first matters more than the second.

**The registry must be COMPLETE.** A table that carries no `creator_fk` and is in
neither `CREATOR_FK_TABLES` nor `JUNCTION_OWNERSHIP` is unscoped on every verb —
every user's rows, readable, writable and deletable by every other user. That is
not a hypothetical: it was the state of all thirteen such tables until this
requirement. `test_every_unscoped_table_is_registered` derives the set from
`schema.sql`, so adding a junction without registering it fails here rather than
shipping a silent leak.

**The predicate must be SOUND.** Deriving authorization through a parent proves
nothing if the parent is itself unscoped, or if the column named does not exist,
so both are checked against the DDL rather than trusted.

Everything here runs without a database or `exports.sh`.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth_utils import (CREATOR_FK_TABLES, JUNCTION_OWNERSHIP, PROFILE_TABLE,
                        UNSCOPED_TABLES, _reference_value,
                        check_junction_parent_ownership,
                        junction_parent_columns, junction_scope_clause)


# ---------------------------------------------------------------------------
# schema.sql parsing — the source of truth these registries are checked against
# ---------------------------------------------------------------------------

def _schema_path():
    """DarwinSQL/schema.sql as a sibling of Lambda-Rest, or None."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, '..', '..', 'DarwinSQL', 'schema.sql')
    return candidate if os.path.exists(candidate) else None


def _parse_schema():
    """{table: {'columns': set(), 'has_creator_fk': bool}} from schema.sql."""
    path = _schema_path()
    if path is None:
        pytest.skip('DarwinSQL/schema.sql not present as a sibling repo')

    tables, current = {}, None
    for line in open(path).read().splitlines():
        stripped = line.strip()
        match = re.match(r'CREATE TABLE (?:IF NOT EXISTS )?`?(\w+)`?', stripped)
        if match:
            current = match.group(1)
            tables[current] = {'columns': set(), 'has_creator_fk': False}
            continue
        if current is None:
            continue
        if stripped.startswith(');'):
            current = None
            continue
        # A column definition: an identifier followed by a type. Constraint and
        # key lines start with a reserved word, so they are filtered out first.
        if re.match(r'(PRIMARY|UNIQUE|CONSTRAINT|FOREIGN|INDEX|KEY|CHECK)\b',
                    stripped, re.I):
            continue
        column = re.match(r'`?(\w+)`?\s+[A-Za-z]', stripped)
        if column:
            name = column.group(1)
            tables[current]['columns'].add(name)
            if name == 'creator_fk':
                tables[current]['has_creator_fk'] = True
    return tables


@pytest.fixture(scope='module')
def schema():
    return _parse_schema()


# ---------------------------------------------------------------------------
# Registry completeness — the test that stops the next silent leak
# ---------------------------------------------------------------------------

def test_schema_parse_found_the_tables(schema):
    """Guard the guard: an empty parse would make every test below vacuous."""
    assert len(schema) > 40, f'parsed only {len(schema)} tables from schema.sql'
    assert schema['pipeline_step_deps']['columns'] >= {'id', 'step_fk', 'dep_step_fk'}
    assert schema['requirements']['has_creator_fk']


# COVERS: SCH-014
def test_every_unscoped_table_is_registered(schema):
    """Every table without creator_fk must be in JUNCTION_OWNERSHIP.

    THE invariant of req #3122. `profiles` is scoped by `id` and is the one
    permitted special case; `UNSCOPED_TABLES` is the written-down escape hatch and
    is empty. Anything else absent from both is unscoped on GET/PUT/DELETE/POST.
    Derived from schema.sql, so it fails helpfully if pipeline2_step_deps or
    pipeline2_step_requirements (neither carries creator_fk) is missing from
    JUNCTION_OWNERSHIP.
    """
    unscoped = {name for name, info in schema.items()
                if not info['has_creator_fk'] and name != PROFILE_TABLE}
    unregistered = sorted(unscoped - set(JUNCTION_OWNERSHIP) - UNSCOPED_TABLES)
    assert not unregistered, (
        'tables with no creator_fk and no join-through rule — every user sees '
        f'and can modify every other user\'s rows in these: {unregistered}')


def test_registry_names_no_table_that_has_its_own_creator_fk(schema):
    """A table with creator_fk belongs in CREATOR_FK_TABLES, not here.

    Registering it in both would be harmless but confusing; registering it ONLY
    here would replace a direct ownership check with an indirect one for no
    reason. Either way it is a mistake, and it is cheap to catch.
    """
    misplaced = sorted(name for name in JUNCTION_OWNERSHIP
                       if schema.get(name, {}).get('has_creator_fk'))
    assert not misplaced, f'carry their own creator_fk: {misplaced}'


def test_every_registered_table_exists_in_the_schema(schema):
    """A registry entry for a dropped table is dead weight that hides a real gap."""
    unknown = sorted(set(JUNCTION_OWNERSHIP) - set(schema))
    assert not unknown, f'registered but not in schema.sql: {unknown}'


# ---------------------------------------------------------------------------
# Soundness of each entry
# ---------------------------------------------------------------------------

def test_every_parent_is_itself_creator_scoped():
    """Deriving through an unscoped parent would prove nothing.

    `step_fk IN (SELECT id FROM pipeline_steps WHERE creator_fk = %s)` is only an
    authorization check because `pipeline_steps` HAS a creator_fk. Point a rule at
    a table that does not and the subquery silently authorizes everybody.
    """
    for table in JUNCTION_OWNERSHIP:
        for column, parent in junction_parent_columns(table):
            assert parent in CREATOR_FK_TABLES, (
                f'{table}.{column} resolves through {parent}, which is not in '
                'CREATOR_FK_TABLES — the join-through would authorize anybody')


def test_every_declared_column_exists_on_its_table(schema):
    """A typo'd column name is a 1054 at runtime on a security-critical path."""
    for table in JUNCTION_OWNERSHIP:
        columns = schema[table]['columns']
        for column, _ in junction_parent_columns(table):
            assert column in columns, f'{table} has no column {column}'


def test_every_parent_table_has_an_id_column(schema):
    """The subquery selects `id` from the parent; it must have one."""
    for table in JUNCTION_OWNERSHIP:
        for _, parent in junction_parent_columns(table):
            assert 'id' in schema[parent]['columns'], f'{parent} has no id column'


def test_scope_column_is_not_repeated_in_verify():
    """The scope column is already checked; listing it twice would double a query."""
    for table, entry in JUNCTION_OWNERSHIP.items():
        scope_column = entry['scope'][0]
        verify_columns = [c for c, _ in entry.get('verify', ())]
        assert scope_column not in verify_columns, (
            f'{table}: {scope_column} is both the scope column and a verify entry')


def test_priority_card_order_deliberately_does_not_verify_task_id():
    """The documented exception, pinned so it cannot be "tidied up".

    `priority_card_order` declares NO foreign keys, so the database already
    tolerates a dangling `task_id`. Verifying it on write would invent referential
    integrity under cover of an authorization change and would 403 a real race in
    PriorityCard.jsx (a task deleted in another tab between the sort and the POST).
    Ownership rides on `domain_id`; a foreign `task_id` leaks nothing.
    """
    entry = JUNCTION_OWNERSHIP['priority_card_order']
    assert entry['scope'] == ('domain_id', 'domains')
    assert 'task_id' not in [c for c, _ in entry.get('verify', ())]


# ---------------------------------------------------------------------------
# junction_scope_clause
# ---------------------------------------------------------------------------

def test_scope_clause_has_exactly_one_placeholder():
    """Callers append ONE parameter for it. A second %s would shift every bind."""
    for table in JUNCTION_OWNERSHIP:
        clause = junction_scope_clause(table)
        assert clause.count('%s') == 1, f'{table}: {clause}'


def test_scope_clause_never_selects_from_the_table_it_scopes():
    """MySQL 1093 forbids an UPDATE/DELETE subquery naming its own target table.

    Every rule points at a PARENT, so this holds by construction — but a future
    self-referencing junction would break UPDATE and DELETE at runtime only.
    """
    for table, entry in JUNCTION_OWNERSHIP.items():
        assert entry['scope'][1] != table, f'{table} scopes through itself'


def test_scope_clause_is_none_for_unregistered_tables():
    for table in ('requirements', 'profiles', 'tasks', 'not_a_table'):
        assert junction_scope_clause(table) is None


def test_scope_clause_shape():
    assert (junction_scope_clause('pipeline_step_deps')
            == 'step_fk IN (SELECT id FROM pipeline_steps WHERE creator_fk = %s)')


# ---------------------------------------------------------------------------
# _reference_value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw', [None, 'NULL', ''])
def test_reference_value_treats_the_empty_shapes_as_no_value(raw):
    """`None`, the "NULL" sentinel and "" all mean "names no row" on this wire."""
    assert _reference_value(raw) is None


@pytest.mark.parametrize('raw,expected', [
    (5, '5'), ('5', '5'), (0, '0'),
    # Every form MySQL would coerce to the SAME row must canonicalize to the same
    # key, or the ownership lookup compares the request's text against the
    # database's canonical id, matches nothing, and reads a foreign parent as
    # "does not exist" — then the FK coerces it back and writes the row.
    (5.0, '5'), (' 5', '5'), ('5 ', '5'), ('+5', '5'), ('05', '5'), ('  0005  ', '5'),
])
def test_reference_value_canonicalizes_every_form_mysql_would_coerce(raw, expected):
    assert _reference_value(raw) == expected


@pytest.mark.parametrize('raw', [
    '5abc', 'abc', '5.7', 5.7, [5], {'id': 5}, float('inf'), float('nan'),
    # Where PYTHON and MYSQL disagree about what an integer is. `int()` accepts
    # PEP 515 underscore separators and Unicode digit classes; MySQL truncates at
    # the first non-ASCII digit. `'5_0'` is the clean exploit that came out of
    # this: Python reads 50 (nonexistent -> "leave it to the FK"), MySQL reads 5
    # and writes the row onto step 5. `_ASCII_INT_RE` uses `[0-9]`, never `\d`.
    '5_0', '9_825', '٩٨٢٥', '１９８２５', '5e2', '0x2661', '\xa05',
    # Leading whitespace MySQL does NOT skip. Measured: it skips space and tab
    # and nothing else, so these store 0 in an INT column while Python reads 5.
    '\n5', '\r5', '\v5', '\f5',
    # Outside INT range, where MySQL CLAMPS instead of rejecting — '2147483648'
    # names row 2147483647 to the database and a different row to this check.
    '2147483648', '-2147483649', 2 ** 31, -2 ** 31 - 1, 10 ** 30, 1e20,
])
def test_reference_value_rejects_what_is_not_an_integer_id(raw):
    """This RDS instance runs a NON-STRICT sql_mode, so MySQL would truncate
    `'5abc'` to 5 silently rather than reject it. Refuse instead of guessing."""
    with pytest.raises(ValueError):
        _reference_value(raw)


@pytest.mark.parametrize('raw', [True, False])
def test_reference_value_rejects_booleans(raw):
    """`int(True)` is 1 — a boolean would silently name row 1."""
    with pytest.raises(ValueError):
        _reference_value(raw)


# ---------------------------------------------------------------------------
# check_junction_parent_ownership
# ---------------------------------------------------------------------------

class FakeCursor:
    """Answers `SELECT id, creator_fk FROM parent WHERE id IN (...)` from a map.

    Rows absent from the map do not exist at all — which the check must treat
    differently from rows that exist under another creator.
    """

    def __init__(self, rows):
        self.rows = {parent: {str(i): owner for i, owner in table.items()}
                     for parent, table in rows.items()}
        self.queries = []
        self._result = []

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        parent = re.search(r'FROM (\w+)', sql).group(1)
        table = self.rows.get(parent, {})
        self._result = [(i, table[i]) for i in (str(p) for p in params)
                        if i in table]

    def fetchall(self):
        return self._result


# Steps 1 and 2 and requirement 10 are the victim's; 3 and 11 belong to somebody
# else; anything else does not exist.
ROWS = {'pipeline_steps': {1: 'victim', 2: 'victim', 3: 'stranger'},
        'requirements': {10: 'victim', 11: 'stranger'}}


def test_allows_a_write_whose_parents_are_all_owned():
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps',
        [{'step_fk': 1, 'dep_step_fk': 2, 'time_at': None}], 'victim') is None


def test_refuses_a_foreign_scope_parent():
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': 3}], 'victim') == (403, 'FORBIDDEN')


def test_refuses_a_foreign_verify_parent_on_an_owned_row():
    """Own step, somebody else's dep target.

    Not merely a leak: `dep_step_fk` is ON DELETE RESTRICT, so an edge pointing at
    another user's step makes THEIR step undeletable — a denial of service on
    their plan edit, executed entirely from inside my own plan.
    """
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps',
        [{'step_fk': 1, 'dep_step_fk': 3}], 'victim') == (403, 'FORBIDDEN')


def test_a_nonexistent_parent_is_left_to_the_foreign_key_not_refused_here():
    """The deliberate asymmetry: absent is NOT the same as somebody else's.

    Refusing a missing id with 403 too would hide whether it is real, but the id
    space is a dense auto-increment any caller can already infer — so the oracle
    is worth almost nothing, while the cost lands on every ordinary FK typo, as
    `FORBIDDEN — references a row another creator owns`: a confidently wrong
    explanation of a mistyped id. Letting it through produces the 409/1452 the
    error contract already defines, which names the constraint and promises
    something true of this case (retrying with different data can succeed).
    """
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps',
        [{'step_fk': 1, 'dep_step_fk': 999999}], 'victim') is None
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': 999999}], 'victim') is None


def test_one_foreign_id_refuses_even_when_the_others_are_absent():
    """A missing id must not launder a foreign one sharing the same query."""
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_requirements',
        [{'step_fk': 1, 'requirement_fk': 999999},
         {'step_fk': 1, 'requirement_fk': 11}], 'victim') == (403, 'FORBIDDEN')


def test_null_verify_columns_are_skipped_not_refused():
    """A wall-clock gate row carries `dep_step_fk: None` and is perfectly legal."""
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps',
        [{'step_fk': 1, 'dep_step_fk': None, 'time_at': '2026-07-27 06:31:38'}],
        'victim') is None


def test_a_missing_scope_column_is_400_not_403():
    """Ownership cannot be established, but the fault is the body, not the identity.

    The scope column is NOT NULL in every registered table, so the INSERT could
    only fail anyway; answering 403 would blame the caller's credentials for a
    malformed request.
    """
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'dep_step_fk': 1}], 'victim') == (400, 'BAD REQUEST')


def test_a_null_scope_column_is_400():
    cursor = FakeCursor(ROWS)
    for empty in (None, 'NULL'):
        assert check_junction_parent_ownership(
            cursor, 'pipeline_step_deps', [{'step_fk': empty}], 'victim') \
            == (400, 'BAD REQUEST')


def test_an_empty_string_scope_column_is_CHECKED_as_row_zero_not_treated_as_null():
    """`''` is not NULL on this wire, and req #3125 stopped pretending it was.

    Only the literal `"NULL"` is mapped to SQL NULL by rest_post/rest_put; `''`
    is passed straight through, and this instance's non-strict `sql_mode`
    coerces it to **0** in an INT column. Reading it as "no value" therefore left
    a value the statement writes completely unchecked — the same
    check-says-one-thing-writer-does-another shape as the `'9825_0'` bug.

    Answer moves from 400 to whatever row 0 turns out to be. Here `pipeline_steps`
    has no row 0, so it falls through to the FK as a 409/1452 — still a refusal,
    now for the true reason. On `priority_card_order`, which declares NO foreign
    key, this is the difference between refusing and writing a permanently
    invisible `domain_id = 0` row (see the test below).
    """
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': ''}], 'victim') is None
    assert cursor.queries[0][1] == ('0',), 'row 0 was not the id looked up'


def test_an_empty_string_on_a_table_with_no_fk_is_refused_rather_than_written():
    """The hazard the change above actually closes.

    `priority_card_order` declares no foreign keys, so nothing downstream would
    reject `domain_id = 0`. On a PUT (`require_scope=False`) the old reading of
    `''` skipped the column entirely and let the row land, invisible to every
    user until AUTO_INCREMENT reached 0.
    """
    cursor = FakeCursor({'domains': {5: 'victim'}})
    assert check_junction_parent_ownership(
        cursor, 'priority_card_order', [{'domain_id': '', 'task_id': 77}],
        'victim', require_scope=False) == (403, 'FORBIDDEN')


def test_one_query_per_parent_table_not_per_row():
    """A 3,000-row map_coordinates import must not become 3,000 SELECTs."""
    cursor = FakeCursor({'map_runs': {7: 'victim'}})
    bodies = [{'map_run_fk': 7, 'seq': n, 'latitude': 0, 'longitude': 0}
              for n in range(3000)]
    assert check_junction_parent_ownership(
        cursor, 'map_coordinates', bodies, 'victim') is None
    assert len(cursor.queries) == 1
    assert len(cursor.queries[0][1]) == 1      # one id, de-duplicated 3,000 ways


def test_a_single_foreign_row_refuses_the_whole_batch():
    """The INSERT is one statement that lands or rolls back as a unit."""
    cursor = FakeCursor(ROWS)
    bodies = [{'step_fk': 1, 'requirement_fk': 10},
              {'step_fk': 3, 'requirement_fk': 10}]
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_requirements', bodies, 'victim') == (403, 'FORBIDDEN')


def test_mixed_int_and_str_ids_collapse_to_one():
    """`1` and `"1"` name one row; counting them as two would refuse a valid write."""
    cursor = FakeCursor(ROWS)
    bodies = [{'step_fk': 1, 'requirement_fk': 10},
              {'step_fk': '1', 'requirement_fk': '10'}]
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_requirements', bodies, 'victim') is None
    for _, params in cursor.queries:
        assert len(params) == 1


def test_unregistered_tables_are_not_checked():
    """The guard runs on every POST; it must be inert for ordinary tables."""
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'requirements', [{'title': 'x'}], 'victim') is None
    assert cursor.queries == []


def test_no_authenticated_user_skips_the_check():
    """handler.py already 403s these tables without an identity (defence in depth).

    Reaching here with None means a direct call from a test, not a request, and
    inventing a refusal would break those callers for no security gain.
    """
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': 1}], None) is None
    assert cursor.queries == []


def test_a_non_dict_body_is_rejected_rather_than_crashing():
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', ['not-a-dict'], 'victim') == (400, 'BAD REQUEST')


def test_the_write_guard_opens_no_cursor_when_it_does_not_apply():
    """rest_post and rest_put call the guard on EVERY write, junction or not.

    Opening a cursor there would move the request's first cursor acquisition
    ahead of the INSERT, so a connection that fails on `cursor()` would fail with
    nothing written and nothing to roll back — which is exactly how this
    regressed `test_unit_error_detail_wiring.py`'s bulk-rollback assertion.

    req #3125 renamed the guard (it now covers `CREATOR_TABLE_REFERENCES` too) and
    made this property harder to hold rather than easier: `requirements` IS
    registered now, so "does not apply" can no longer be answered from the table
    name alone. The guard plans its lookups purely — no cursor — and returns when
    there is nothing to look up. Each case below is a different route to that:
    a body naming no parent, an unauthenticated call, and a table in neither
    registry.
    """
    from rest_api_utils import parent_reference_guard

    class ExplodingConn:
        def cursor(self):
            raise AssertionError('the guard opened a cursor it did not need')

    # Registered under req #3125, but this body names no parent column.
    assert parent_reference_guard(
        ExplodingConn(), 'requirements', [{'title': 'x'}], 'victim', 'POST') is None
    # The hot path req #3125 must not slow down or break.
    assert parent_reference_guard(
        ExplodingConn(), 'tasks', [{'id': 5, 'done': 1}], 'victim', 'PUT',
        require_scope=False) is None
    # No identity — nothing to derive an answer from.
    assert parent_reference_guard(
        ExplodingConn(), 'pipeline_step_deps', [{'step_fk': 1}], None, 'POST') is None
    # In neither registry.
    assert parent_reference_guard(
        ExplodingConn(), 'profiles', [{'name': 'x'}], 'victim', 'PUT') is None


def test_the_write_guard_answers_a_malformed_body_without_a_cursor():
    """A 400 needs no lookup, so it must not need a cursor either.

    `'9825_0'` is refused by `_reference_value` at the door — Python reads 98250,
    MySQL reads 9825. Planning is pure, so that verdict is reached before the
    guard ever asks the connection for anything.
    """
    from rest_api_utils import parent_reference_guard

    class ExplodingConn:
        def cursor(self):
            raise AssertionError('the guard opened a cursor it did not need')

    response = parent_reference_guard(
        ExplodingConn(), 'test_runs', [{'test_plan_fk': '9825_0'}], 'victim', 'POST')
    assert response['statusCode'] == 400


def test_put_omitting_the_scope_column_is_not_a_400():
    """On an UPDATE an absent scope column means "unchanged", not "malformed".

    PriorityCard.jsx bulk-PUTs `{id, sort_order}` on every hand-sort save; a 400
    there would break the feature outright.
    """
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'time_at': '2026-07-27 00:00:00'}],
        'victim', require_scope=False) is None


def test_put_still_refuses_a_foreign_scope_column_when_it_IS_present():
    """The whole reason PUT needs this guard: the SET clause can rewrite the
    scope column, so the WHERE predicate only proves ownership of the row's
    parent BEFORE the statement."""
    cursor = FakeCursor(ROWS)
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': 3}], 'victim',
        require_scope=False) == (403, 'FORBIDDEN')


def test_a_table_with_no_foreign_keys_refuses_a_parent_that_does_not_exist():
    """`priority_card_order` declares no FKs, so nothing else would reject it.

    Everywhere else "absent" is deliberately left to the FK as a 409/1452. Here
    the row would simply insert and sit invisible until AUTO_INCREMENT reached
    that domain id and handed it to whoever got there.
    """
    cursor = FakeCursor({'domains': {5: 'victim'}})
    assert check_junction_parent_ownership(
        cursor, 'priority_card_order',
        [{'domain_id': 5, 'task_id': 77}], 'victim') is None
    assert check_junction_parent_ownership(
        cursor, 'priority_card_order',
        [{'domain_id': 999999, 'task_id': 77}], 'victim') == (403, 'FORBIDDEN')


def test_fk_enforced_defaults_to_true_so_only_the_declared_exception_differs():
    """Every other table leaves a missing parent to its foreign key."""
    for table, entry in JUNCTION_OWNERSHIP.items():
        if table == 'priority_card_order':
            assert entry.get('fk_enforced') is False
        else:
            assert entry.get('fk_enforced', True) is True, table


# ---------------------------------------------------------------------------
# The handler's unauthenticated gate
# ---------------------------------------------------------------------------

def test_handler_403s_unauthenticated_junction_requests():
    """With no identity there is nothing to derive scoping FROM.

    Every WHERE clause would simply omit the predicate and hand back every user's
    rows, so the junction tables must join the 403 gate rather than fall through
    it. Read from the source because importing handler.py needs the DB env vars.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    source = open(os.path.join(here, '..', 'handler.py')).read()
    assert 'JUNCTION_OWNERSHIP' in source, \
        'handler.py does not import the junction registry'
    gate = re.search(r'if \(table in CREATOR_FK_TABLES.*?FORBIDDEN', source, re.S)
    assert gate and 'JUNCTION_OWNERSHIP' in gate.group(0), \
        'the unauthenticated 403 gate does not cover junction tables'


# ---------------------------------------------------------------------------
# Numeric-coercion bypass (found on re-review, after the DictCursor change)
# ---------------------------------------------------------------------------
#
# The check briefly keyed a dict on the DATABASE's ids and then iterated the
# REQUEST's raw strings to decide. `'9825.0' in {'9825': ...}` is False, so a
# foreign parent was classified as "does not exist", fell through the
# leave-it-to-the-FK branch, and MySQL — non-strict sql_mode on this instance —
# coerced it straight back to 9825 and wrote the row. Every variant below landed
# a gate on another user's step through a 200 while the plain integer got a 403.

# Forms that name row 9825 unambiguously and so must CANONICALIZE to '9825'.
COERCION_VARIANTS = [9825.0, ' 9825', '9825 ', '+9825', '09825']

# Forms MySQL would still coerce to 9825 under this instance's non-strict
# sql_mode, but which Python cannot read as an integer. These are refused with a
# 400 before any lookup — also a refusal, and no write reaches the database.
TRUNCATING_VARIANTS = ['9825.000', '9825abc', '9825 rows',
                       # Python and MySQL disagree on these; refusing at the door
                       # is the only way the two layers cannot be played apart.
                       '9825_0', '9_825', '٩٨٢٥', '１９８２５', '9825e2', '0x2661']


@pytest.mark.parametrize('variant', COERCION_VARIANTS)
def test_a_foreign_parent_is_refused_in_every_numeric_form(variant):
    cursor = FakeCursor({'pipeline_steps': {9825: 'stranger'}})
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': variant}],
        'victim') == (403, 'FORBIDDEN')


@pytest.mark.parametrize('variant', COERCION_VARIANTS)
def test_a_foreign_verify_target_is_refused_in_every_numeric_form(variant):
    cursor = FakeCursor({'pipeline_steps': {1: 'victim', 9825: 'stranger'}})
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': 1, 'dep_step_fk': variant}],
        'victim') == (403, 'FORBIDDEN')


@pytest.mark.parametrize('variant', COERCION_VARIANTS)
def test_the_same_forms_are_refused_on_a_put(variant):
    """The PUT guard shares the check, so it shares the bypass if one exists."""
    cursor = FakeCursor({'pipeline_steps': {9825: 'stranger'}})
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': variant}], 'victim',
        require_scope=False) == (403, 'FORBIDDEN')


@pytest.mark.parametrize('variant', COERCION_VARIANTS)
def test_an_OWNED_parent_is_still_allowed_in_every_numeric_form(variant):
    """The mirror image: canonicalization must not falsely refuse your own row.

    The same keying bug ran backwards on `fk_enforced: False` — an owned domain
    sent as a float was logged as "does not exist" and refused.
    """
    cursor = FakeCursor({'pipeline_steps': {9825: 'victim'}})
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': variant}], 'victim') is None


@pytest.mark.parametrize('variant', COERCION_VARIANTS)
def test_priority_card_order_accepts_an_owned_domain_in_every_numeric_form(variant):
    cursor = FakeCursor({'domains': {9825: 'victim'}})
    assert check_junction_parent_ownership(
        cursor, 'priority_card_order', [{'domain_id': variant, 'task_id': 7}],
        'victim') is None


def test_a_non_integer_parent_reference_is_400_not_a_silent_truncation():
    """`'9825abc'` truncates to 9825 under this instance's non-strict sql_mode."""
    cursor = FakeCursor({'pipeline_steps': {9825: 'stranger'}})
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': '9825abc'}],
        'victim') == (400, 'BAD REQUEST')
    assert cursor.queries == []


def test_the_verdict_comes_from_the_rows_the_database_returned():
    """Structural guard on the shape of the bug, not just its symptoms.

    A verdict derived by iterating the REQUEST's ids can disagree with the
    database whenever the two spell an id differently. Deriving it from the
    returned rows cannot.

    Follows the loop rather than the entry point: req #3125 split the check into
    a pure planner and `resolve_parent_lookups`, which is now the one place any
    verdict is reached — for the junctions here and for the 36 creator-table
    columns alike. Asserting on the wrapper would have quietly stopped checking
    anything.
    """
    import inspect

    from auth_utils import resolve_parent_lookups

    source = inspect.getsource(resolve_parent_lookups)
    assert 'for row_id, owner in found' in source, \
        'the ownership verdict must be derived from the fetched rows'


@pytest.mark.parametrize('variant', TRUNCATING_VARIANTS)
def test_forms_only_mysql_would_read_as_an_id_are_refused_before_any_lookup(variant):
    """A refusal either way — 400 rather than 403, and nothing is written.

    These reach MySQL as an INT column value under a non-strict sql_mode, where
    `'9825abc'` truncates to 9825 silently. Refusing at the door means the
    ownership check never has to reason about a value two layers disagree on.
    """
    cursor = FakeCursor({'pipeline_steps': {9825: 'stranger'}})
    assert check_junction_parent_ownership(
        cursor, 'pipeline_step_deps', [{'step_fk': variant}],
        'victim') == (400, 'BAD REQUEST')
    assert cursor.queries == []


# ---------------------------------------------------------------------------
# The last two Python/MySQL divergences (closed on final review)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('space', [' ', '\t'])
def test_the_whitespace_mysql_actually_skips_is_accepted(space):
    """Space and tab, measured against a real INT column — not C `isspace`."""
    assert _reference_value(f'{space}9825') == '9825'
    assert _reference_value(f'9825{space}') == '9825'


@pytest.mark.parametrize('space', ['\n', '\r', '\v', '\f', '\xa0'])
def test_leading_whitespace_mysql_does_not_skip_is_refused(space):
    """MySQL stores 0 for these, so accepting them let the two layers disagree.

    Fail-closed even before this — `id` is AUTO_INCREMENT and never issues 0 — but
    on `priority_card_order` (no FK) it wrote a permanently invisible domain_id=0
    row, and `_SQL_SPACE`'s own comment claimed a behaviour MySQL does not have.
    """
    with pytest.raises(ValueError):
        _reference_value(f'{space}9825')


@pytest.mark.parametrize('raw', ['2147483648', 2 ** 31, '-2147483649',
                                 -2 ** 31 - 1, 10 ** 30, 1e20])
def test_values_outside_int_range_are_refused_rather_than_clamped(raw):
    """MySQL CLAMPS an out-of-range INT rather than rejecting it.

    So `'2147483648'` names row 2147483647 to the database while naming
    2147483648 here — the `'9825_0'` divergence wearing another costume. It fails
    closed today only because the highest parent id in either database is ~907k
    against an INT max of 2.1bn, and that is a property of the DATA that nothing
    enforces: one explicit-id insert or seeded import at the boundary turns it
    live. Refused in code so it does not depend on that staying true.
    """
    with pytest.raises(ValueError):
        _reference_value(raw)


@pytest.mark.parametrize('raw', [2 ** 31 - 1, -2 ** 31, '2147483647'])
def test_the_int_boundary_itself_is_still_accepted(raw):
    """Refuse OUTSIDE the range, not at it — these are representable ids."""
    assert _reference_value(raw) == str(int(raw))
