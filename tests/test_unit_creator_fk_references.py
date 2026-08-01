"""Outbound FK ownership on creator_fk-bearing tables (req #3125) — no DB.

`test_unit_junction_scoping.py` asks *who owns this row* for the tables that
cannot answer it themselves. This file asks the other question, of the tables
that CAN: **who owns the rows this row points at.**

THE GRIEF-LOCK. `creator_fk` scoping is not weakened by the attack — it is what
makes the attack work. The attacker POSTs a row of their OWN, so the token-forced
`creator_fk` is theirs and every check in `auth_utils` passes, carrying a `*_fk`
that names a VICTIM's parent. On the fourteen columns that are `ON DELETE
RESTRICT`, the victim's `DELETE` of their own parent now answers 409 naming a
constraint held by a row they cannot see (it is scoped to the attacker), cannot
list, and cannot delete. Every tool the victim has is `creator_fk`-scoped away
from the row pinning them: there is no self-service recovery at all.

**The registry must be COMPLETE, and it is DERIVED here rather than reviewed.**
That is the load-bearing test in this file. The audit that filed req #3125
reported "test_runs.test_plan_fk and ten sibling columns"; re-deriving the same
rule from `schema.sql` gives **38 columns across 25 tables** (36 when #3125
shipped; req #3186's two `swarm_sessions` attribution FKs are the proof the
mechanism works — they failed this test until registered). A hand-counted
security boundary drifts silently — `test_every_cross_tenant_fk_column_is_registered`
re-derives it on every run, so a new FK column fails the build instead.

Everything here runs without a database or `exports.sh`.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth_utils import (CREATOR_FK_TABLES, CREATOR_TABLE_REFERENCES,
                        JUNCTION_OWNERSHIP, PROFILE_TABLE,
                        UNCHECKED_CREATOR_REFERENCES, _PLAIN_IDENTIFIER_RE,
                        body_column, check_body_keys,
                        creator_table_reference_columns, force_column,
                        plan_parent_lookups, referenced_parent_columns,
                        resolve_parent_lookups)


# ---------------------------------------------------------------------------
# schema.sql parsing — foreign keys, which the junction file did not need
# ---------------------------------------------------------------------------

def _schema_text():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, '..', '..', 'DarwinSQL', 'schema.sql')
    if not os.path.exists(path):
        pytest.skip('DarwinSQL/schema.sql not present as a sibling repo')
    with open(path) as handle:
        return handle.read()


# `[CONSTRAINT name] FOREIGN KEY (col) REFERENCES parent (pcol) [ON ... ]`, matched
# against the block with its newlines collapsed, because the DDL wraps every one
# of these across three lines.
_FK_RE = re.compile(
    r'(?:CONSTRAINT `?(\w+)`? )?FOREIGN KEY \(`?(\w+)`?\)\s*'
    r'REFERENCES `?(\w+)`? \(`?(\w+)`?\)'
    r'((?:\s+ON (?:UPDATE|DELETE) (?:CASCADE|RESTRICT|SET NULL|NO ACTION))*)',
    re.I)

_RESERVED = re.compile(r'(PRIMARY|UNIQUE|CONSTRAINT|FOREIGN|INDEX|KEY|CHECK)\b', re.I)


def _parse_schema():
    """{table: {'columns': set, 'fks': [(column, parent, on_delete)]}}."""
    blocks, current, buf = {}, None, []
    for line in _schema_text().splitlines():
        stripped = line.strip()
        match = re.match(r'CREATE TABLE (?:IF NOT EXISTS )?`?(\w+)`?', stripped)
        if match:
            current, buf = match.group(1), []
            continue
        if current is None:
            continue
        if stripped.startswith(');'):
            blocks[current], current = '\n'.join(buf), None
            continue
        buf.append(stripped)

    tables = {}
    for name, body in blocks.items():
        columns = set()
        for line in body.splitlines():
            if _RESERVED.match(line):
                continue
            column = re.match(r'`?(\w+)`?\s+[A-Za-z]', line)
            if column:
                columns.add(column.group(1))
        fks = []
        for match in _FK_RE.finditer(re.sub(r'\s+', ' ', body)):
            actions = (match.group(5) or '').upper()
            on_delete = 'RESTRICT' if 'ON DELETE RESTRICT' in actions else (
                'SET NULL' if 'ON DELETE SET NULL' in actions else (
                    'CASCADE' if 'ON DELETE CASCADE' in actions else 'NO ACTION'))
            fks.append((match.group(2), match.group(3), on_delete))
        tables[name] = {'columns': columns, 'fks': fks}
    return tables


@pytest.fixture(scope='module')
def schema():
    return _parse_schema()


@pytest.fixture(scope='module')
def creator_scoped(schema):
    """Tables carrying creator_fk, per the DDL — not per the registry."""
    return {name for name, info in schema.items() if 'creator_fk' in info['columns']}


def _cross_tenant_fk_columns(schema, creator_scoped):
    """{(table, column): (parent, on_delete)} — the whole of req #3125's scope.

    Every `*_fk` on a `creator_fk`-bearing table whose target is ALSO
    creator-scoped. `creator_fk` itself is excluded: it is forced from the token
    by rest_post/rest_put, so a body cannot aim it anywhere.
    """
    found = {}
    for table in sorted(creator_scoped):
        for column, parent, on_delete in schema[table]['fks']:
            if column == 'creator_fk' or parent not in creator_scoped:
                continue
            found[(table, column)] = (parent, on_delete)
    return found


def _registered():
    return {(table, column): parent
            for table, columns in CREATOR_TABLE_REFERENCES.items()
            for column, parent in columns}


# ---------------------------------------------------------------------------
# Guard the guard
# ---------------------------------------------------------------------------

def test_the_schema_parse_actually_found_foreign_keys(schema, creator_scoped):
    """An empty or FK-blind parse would make every derivation below vacuous."""
    assert len(schema) > 40, f'parsed only {len(schema)} tables'
    assert len(creator_scoped) > 30, f'parsed only {len(creator_scoped)} creator tables'
    parsed = sum(len(info['fks']) for info in schema.values())
    declared = len(re.findall(r'FOREIGN KEY', _schema_text()))
    assert parsed == declared, (
        f'parsed {parsed} foreign keys but the DDL declares {declared} — the '
        'derivation below would silently miss the difference')
    # A known row, spelled out, so a regex that matched the wrong groups fails here.
    assert ('test_plan_fk', 'test_plans', 'RESTRICT') in schema['test_runs']['fks']


def test_the_ddl_and_the_registry_agree_on_which_tables_carry_creator_fk(creator_scoped):
    """`CREATOR_FK_TABLES` is the input to the derivation, so it must be right.

    Already covered from the darwin-mcp side; asserted here because every test
    below reads it as the definition of "creator-scoped".
    """
    assert creator_scoped == set(CREATOR_FK_TABLES), {
        'in schema.sql only': sorted(creator_scoped - CREATOR_FK_TABLES),
        'in CREATOR_FK_TABLES only': sorted(CREATOR_FK_TABLES - creator_scoped),
    }


# ---------------------------------------------------------------------------
# Completeness — the test that stops the next grief-lock
# ---------------------------------------------------------------------------

def test_every_cross_tenant_fk_column_is_registered(schema, creator_scoped):
    """THE invariant of req #3125, re-derived from the DDL on every run.

    An unregistered column is one POST away from pinning a victim's row forever.
    The previous audit of this exact class hand-counted eleven columns; the DDL
    says thirty-six. This is why the list is derived and not reviewed.
    """
    expected = set(_cross_tenant_fk_columns(schema, creator_scoped))
    missing = sorted(expected - set(_registered()) - set(UNCHECKED_CREATOR_REFERENCES))
    assert not missing, (
        'FK columns on creator_fk-bearing tables whose target is another '
        "user's row, with no ownership check on write — an attacker's own row "
        f'can be pointed at a victim parent through any of these: {missing}')


def test_the_registry_declares_nothing_the_schema_does_not(schema, creator_scoped):
    """A stale entry is dead weight that makes the real coverage harder to read.

    It also costs a live SELECT per write, so it is not free.
    """
    expected = _cross_tenant_fk_columns(schema, creator_scoped)
    extra = sorted(set(_registered()) - set(expected))
    assert not extra, f'registered but not a cross-tenant FK in schema.sql: {extra}'


def test_every_registered_column_names_the_parent_the_ddl_names(schema, creator_scoped):
    """A right column pointed at the wrong parent checks ownership of the wrong row.

    It would pass every other test in this file and authorize nothing: the lookup
    would run against a table the id does not belong to, find no row, and read
    "does not exist" — straight through to the FK.
    """
    expected = _cross_tenant_fk_columns(schema, creator_scoped)
    for key, parent in _registered().items():
        assert parent == expected[key][0], (
            f'{key[0]}.{key[1]} is registered against {parent} but the DDL '
            f'references {expected[key][0]}')


def test_every_restrict_column_is_covered(schema, creator_scoped):
    """The grief-lock subset, called out because it is the one with no recovery.

    CASCADE and SET NULL columns are a cross-tenant write; RESTRICT columns are a
    permanent denial of service on the victim's own row. Both are refused, but a
    gap here is the severe one.
    """
    expected = _cross_tenant_fk_columns(schema, creator_scoped)
    restrict = {key for key, (_, action) in expected.items() if action == 'RESTRICT'}
    assert restrict, 'no RESTRICT columns parsed — the derivation is broken'
    missing = sorted(restrict - set(_registered()))
    assert not missing, f'ON DELETE RESTRICT columns with no ownership check: {missing}'


def test_the_column_the_requirement_named_is_covered():
    """`test_runs.test_plan_fk` — the specific column req #3125 was filed for."""
    assert ('test_plan_fk', 'test_plans') in creator_table_reference_columns('test_runs')


def test_unchecked_creator_references_is_a_written_down_exemption_set():
    """Empty, and every entry that ever appears must name something real.

    Same call as `UNSCOPED_TABLES`: omission and exemption are indistinguishable
    in a hand-written registry unless the exemption has to be written somewhere.
    """
    assert UNCHECKED_CREATOR_REFERENCES == frozenset(), (
        'a column has been exempted from ownership checking — that needs a '
        'documented reason at least as good as priority_card_order\'s: '
        f'{sorted(UNCHECKED_CREATOR_REFERENCES)}')


# ---------------------------------------------------------------------------
# Soundness of each entry
# ---------------------------------------------------------------------------

def test_every_registered_table_carries_its_own_creator_fk(schema):
    """This registry is for tables whose OWN ownership is already settled.

    A table without `creator_fk` belongs in `JUNCTION_OWNERSHIP`, where the
    references also become the read/update/delete predicate. Registered here it
    would be checked on write and left unscoped on every other verb.
    """
    wrong = sorted(t for t in CREATOR_TABLE_REFERENCES
                   if 'creator_fk' not in schema.get(t, {}).get('columns', ()))
    assert not wrong, f'no creator_fk — these belong in JUNCTION_OWNERSHIP: {wrong}'


def test_every_parent_is_itself_creator_scoped():
    """Checking ownership against an unscoped parent proves nothing."""
    for table in CREATOR_TABLE_REFERENCES:
        for column, parent in creator_table_reference_columns(table):
            assert parent in CREATOR_FK_TABLES, (
                f'{table}.{column} is checked against {parent}, which has no '
                'creator_fk — the lookup would authorize anybody')


def test_every_declared_column_exists_on_its_table(schema):
    """A typo'd column name is silently absent from every body — a check that
    never fires, on a security-critical path, with no error to notice."""
    for table in CREATOR_TABLE_REFERENCES:
        for column, _ in creator_table_reference_columns(table):
            assert column in schema[table]['columns'], f'{table} has no column {column}'


def test_every_parent_table_has_an_id_column(schema):
    """The lookup selects `id` from the parent; it must have one."""
    for table in CREATOR_TABLE_REFERENCES:
        for _, parent in creator_table_reference_columns(table):
            assert 'id' in schema[parent]['columns'], f'{parent} has no id column'


def test_every_column_is_backed_by_a_real_foreign_key(schema):
    """Why this registry needs no `fk_enforced` flag.

    "Parent does not exist" is deliberately left to the database as a 409/1452
    rather than answered 403 here. That is only correct where a FK actually
    exists to reject it — `priority_card_order` is the junction-side exception
    that proves it. Every column here came from a `FOREIGN KEY` declaration, so
    the exception cannot arise; this re-derives that from the DDL rather than
    trusting the sentence.
    """
    for table in CREATOR_TABLE_REFERENCES:
        declared = {(column, parent) for column, parent, _ in schema[table]['fks']}
        for entry in creator_table_reference_columns(table):
            assert entry in declared, (
                f'{table}.{entry[0]} is not a declared FOREIGN KEY, so a missing '
                'parent would not be rejected by anything')


def test_creator_fk_is_never_itself_registered():
    """It is forced from the token on both verbs, so a body cannot aim it.

    Registering it would spend a SELECT per write to confirm the caller owns
    their own profile.
    """
    for table in CREATOR_TABLE_REFERENCES:
        columns = [c for c, _ in creator_table_reference_columns(table)]
        assert 'creator_fk' not in columns, f'{table} registers creator_fk'
        assert PROFILE_TABLE not in [p for _, p in
                                     creator_table_reference_columns(table)], (
            f'{table} checks ownership against {PROFILE_TABLE}')


def test_no_column_is_registered_twice():
    """A duplicate would be harmless but hides which entry is authoritative."""
    for table, columns in CREATOR_TABLE_REFERENCES.items():
        names = [c for c, _ in columns]
        assert len(names) == len(set(names)), f'{table} repeats a column: {names}'


def test_the_two_registries_never_name_the_same_table():
    """`referenced_parent_columns` branches on this, so overlap would make the
    order of those branches a silent behavioural decision.

    It cannot happen by construction — one registry is for tables WITH
    `creator_fk` and the other for tables WITHOUT — but the dispatcher should not
    depend on that being remembered.
    """
    overlap = sorted(set(CREATOR_TABLE_REFERENCES) & set(JUNCTION_OWNERSHIP))
    assert not overlap, f'in both registries: {overlap}'


def test_referenced_parent_columns_dispatches_to_both_registries():
    assert referenced_parent_columns('test_runs') == [('test_plan_fk', 'test_plans')]
    assert referenced_parent_columns('pipeline_step_deps')[0] == ('step_fk',
                                                                  'pipeline_steps')
    assert referenced_parent_columns('profiles') == []
    assert referenced_parent_columns('not_a_table') == []


# ---------------------------------------------------------------------------
# Behaviour — planning and the verdict
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
        self._result = [(i, table[i]) for i in (str(p) for p in params) if i in table]

    def fetchall(self):
        return self._result


# Plan 1 is the victim's, plan 2 belongs to somebody else, 999 does not exist.
ROWS = {'test_plans': {1: 'victim', 2: 'stranger'},
        'categories': {10: 'victim', 11: 'stranger'},
        'areas': {20: 'victim', 21: 'stranger'},
        'recurring_tasks': {30: 'victim'},
        'projects': {40: 'victim'},
        'machines': {50: 'victim', 51: 'stranger'},
        'features': {60: 'victim'}}


def _check(table, bodies, user='victim', require_scope=True, rows=None):
    """plan + resolve, the same two calls `parent_reference_guard` makes."""
    cursor = FakeCursor(ROWS if rows is None else rows)
    lookups, refusal = plan_parent_lookups(table, bodies, require_scope=require_scope)
    if refusal is not None:
        return refusal, cursor
    if not lookups:
        return None, cursor
    return resolve_parent_lookups(cursor, table, lookups, user), cursor


def test_a_write_naming_only_owned_parents_is_allowed():
    verdict, cursor = _check('test_runs', [{'test_plan_fk': 1}])
    assert verdict is None
    assert len(cursor.queries) == 1


def test_the_grief_lock_write_is_refused():
    """The attack: the attacker's OWN row, pointed at the victim's test plan.

    `creator_fk` is forced to the attacker by rest_post, so nothing else in the
    gateway objects — and `fk_test_runs_plan` is ON DELETE RESTRICT, so the row
    would make the victim's plan permanently undeletable.
    """
    verdict, _ = _check('test_runs', [{'test_plan_fk': 2}], user='victim')
    assert verdict == (403, 'FORBIDDEN')


def test_a_parent_that_does_not_exist_falls_through_to_the_foreign_key():
    """409/1452, not 403 — absent is not foreign.

    Answering 403 for a typo'd id would be a confidently wrong explanation, and
    the 409 contract already promises the true thing: retrying with different
    data can succeed.
    """
    verdict, _ = _check('test_runs', [{'test_plan_fk': 999}])
    assert verdict is None


def test_a_body_naming_no_parent_needs_no_lookup():
    """The common case on `tasks`, `areas` and `requirements` — the hot tables.

    No cursor is opened at all for these; `parent_reference_guard` returns on the
    empty plan.
    """
    lookups, refusal = plan_parent_lookups('tasks', [{'id': 5, 'done': 1}],
                                           require_scope=False)
    assert (lookups, refusal) == ({}, None)


@pytest.mark.parametrize('value', [None, 'NULL'])
def test_an_explicitly_null_reference_names_nothing(value):
    """`None` and the `"NULL"` sentinel both become SQL NULL, which names no row."""
    lookups, refusal = plan_parent_lookups('test_runs', [{'test_plan_fk': value}])
    assert (lookups, refusal) == ({}, None)


def test_an_empty_string_is_checked_as_row_zero_because_that_is_what_gets_written():
    """`''` is NOT the NULL sentinel — only the literal `"NULL"` is.

    `rest_post`/`rest_put` pass `''` straight through, and this instance's
    non-strict `sql_mode` coerces it to 0 in an INT column. Reading it as "names
    nothing" left a written value unchecked: the same shape as `'9825_0'`, where
    the check and the statement disagree about what the body said.

    No `id = 0` row exists in any parent table today, so the observable answer is
    unchanged (a 409/1452 from the FK) — but it is now unchanged for a reason
    rather than by luck.
    """
    lookups, refusal = plan_parent_lookups('test_runs', [{'test_plan_fk': ''}])
    assert refusal is None
    assert lookups == {'test_plans': ['0']}


def test_an_absent_reference_on_a_creator_table_is_never_a_400():
    """There is no scope column here, so `require_scope` must not invent one.

    A junction's scope column is mandatory on INSERT because it is the only thing
    that establishes ownership. On a creator table ownership is already settled by
    `creator_fk`, so a missing NOT NULL reference is the database's 1364 to
    report — 400-ing it here would refuse a body that MySQL has better words for.
    """
    verdict, cursor = _check('test_runs', [{'notes': 'x'}], require_scope=True)
    assert verdict is None
    assert cursor.queries == []


def test_a_put_that_repoints_a_reference_is_refused():
    """The other door. The UPDATE's own `creator_fk = %s` predicate passes — the
    caller really does own the row — and then the SET clause hands it to the
    victim's parent. Guarding POST alone just moves the hole to PUT.
    """
    verdict, _ = _check('test_runs', [{'test_plan_fk': 2}], require_scope=False)
    assert verdict == (403, 'FORBIDDEN')


def test_one_foreign_reference_refuses_the_whole_bulk_batch():
    """A bulk POST is ONE multi-value INSERT: it lands or rolls back as a unit."""
    verdict, _ = _check('tasks', [{'area_fk': 20}, {'area_fk': 20}, {'area_fk': 21}])
    assert verdict == (403, 'FORBIDDEN')


def test_lookups_are_grouped_per_parent_table_not_per_row():
    """A 3,000-row import must not become 3,000 SELECTs."""
    bodies = [{'area_fk': 20, 'recurring_task_fk': 30} for _ in range(500)]
    verdict, cursor = _check('tasks', bodies)
    assert verdict is None
    assert len(cursor.queries) == 2, [q[0] for q in cursor.queries]


def test_a_table_with_several_parents_asks_each_one_once():
    """`requirements` names four different parent tables in one body."""
    verdict, cursor = _check('requirements', [{'project_fk': 40, 'category_fk': 10,
                                               'machine_fk': 50, 'feature_fk': 60}])
    assert verdict is None
    assert len(cursor.queries) == 4


def test_a_foreign_parent_in_any_position_is_refused():
    """Not just the first column checked."""
    verdict, _ = _check('requirements', [{'project_fk': 40, 'category_fk': 10,
                                          'machine_fk': 51}])
    assert verdict == (403, 'FORBIDDEN')


@pytest.mark.parametrize('variant', [
    # Every form Python and MySQL read differently. `'2_0'` is the sharp one:
    # Python's int() reads 20 (nonexistent -> waved through to the FK) while
    # MySQL truncates at the underscore and writes the row onto plan 2 — the
    # STRANGER's. Refused at the door instead, before any lookup.
    '2_0', '2.0', '٢', '２', '\xa02', '\n2', '2abc', '2e0', '0x2',
    # MySQL CLAMPS out of INT range rather than rejecting.
    '2147483648', '-2147483649',
])
def test_forms_only_mysql_would_read_as_an_id_are_refused_before_any_lookup(variant):
    verdict, cursor = _check('test_runs', [{'test_plan_fk': variant}])
    assert verdict == (400, 'BAD REQUEST')
    assert cursor.queries == []


@pytest.mark.parametrize('variant', [2, '2', ' 2', '2\t', '+2', '02', 2.0])
def test_forms_mysql_and_python_agree_on_still_reach_the_verdict(variant):
    """Canonicalization must not become a bypass.

    Each of these is the stranger's plan 2 to MySQL, so each must be a 403 — an
    earlier version of the junction check compared the request's raw text against
    the database's canonical id, matched nothing, read "does not exist", and let
    every one of them through to be coerced back and written.
    """
    verdict, _ = _check('test_runs', [{'test_plan_fk': variant}])
    assert verdict == (403, 'FORBIDDEN')


def test_a_non_dict_body_is_rejected_rather_than_crashing():
    verdict, cursor = _check('test_runs', ['not-a-dict'])
    assert verdict == (400, 'BAD REQUEST')
    assert cursor.queries == []


# ---------------------------------------------------------------------------
# Body KEYS — the bypass that defeated both registries (found in review)
# ---------------------------------------------------------------------------
#
# A body's keys become SQL IDENTIFIERS, and every check reads them back as exact
# Python strings. MySQL matches a column name case-insensitively and its lexer
# discards backticks, whitespace and comments, so each spelling below wrote the
# column while `body.get(...)` returned None and the guard saw no reference at
# all. Measured against darwin_dev: all five landed a `tasks` row on another
# user's area through a 200, and the same trick defeated req #3122's junctions.

BYPASS_SPELLINGS = ['AREA_FK', 'Area_Fk', '`area_fk`', 'area_fk ', ' area_fk',
                    'area_fk/*x*/', 'area_fk\t', 'area fk', 'area_fk;']


@pytest.mark.parametrize('key', BYPASS_SPELLINGS)
def test_a_key_that_is_not_a_plain_column_name_is_refused(key):
    """Charset restriction, not normalization — `area_fk/*x*/` is why.

    No case-folding routine can enumerate everything MySQL's lexer throws away,
    and every miss is silent. Constraining the key to `[A-Za-z0-9_$]+` leaves
    case as the only variance MySQL still has.
    """
    if _PLAIN_IDENTIFIER_RE.fullmatch(key):
        # Case-only variants are legal identifiers and are handled by matching,
        # not by refusal — asserted separately below.
        pytest.skip('a plain identifier; covered by the case-matching test')
    assert check_body_keys('tasks', [{'description': 'x', key: 7}]) == \
        (400, 'BAD REQUEST')


@pytest.mark.parametrize('key', ['AREA_FK', 'Area_Fk', 'area_FK'])
def test_a_case_variant_key_is_matched_not_ignored(key):
    """`{"AREA_FK": <their area>}` writes `area_fk`, so it must be CHECKED."""
    verdict, cursor = _check('tasks', [{'description': 'x', key: 21}])
    assert verdict == (403, 'FORBIDDEN')
    assert len(cursor.queries) == 1


def test_two_keys_naming_the_same_column_are_refused_outright():
    """The variant a case-insensitive matcher alone would still lose to.

    MySQL allows a column to be assigned twice in one UPDATE and applies the
    LAST one, so `{"test_plan_fk": <mine>, "TEST_PLAN_FK": <theirs>}` would have
    the guard look up the owned plan, approve, and the statement apply the other.
    Refused rather than resolved — it is never a legitimate body.
    """
    assert check_body_keys('test_runs', [{'test_plan_fk': 1,
                                          'TEST_PLAN_FK': 2}]) == (400, 'BAD REQUEST')
    # Including when neither spelling is a reference column at all.
    assert check_body_keys('tasks', [{'done': 1, 'DONE': 0}]) == (400, 'BAD REQUEST')


def test_a_creator_fk_case_variant_cannot_survive_the_override():
    """`PUT [{"id": <mine>, "CREATOR_FK": "<their sub>"}]` gave the row AWAY.

    `'creator_fk' in body` is a Python string test; MySQL's column lookup is not.
    The WHERE clause matched on the row's current owner and the SET clause then
    reassigned it. Verified against darwin_dev before the fix.

    `force_column` replaces the caller's spelling rather than adding the
    canonical one beside it — two spellings of one column in an INSERT is MySQL
    1110 and a 500.
    """
    body = {'id': 5, 'CREATOR_FK': 'victim'}
    force_column(body, 'creator_fk', 'attacker')
    assert body == {'id': 5, 'creator_fk': 'attacker'}
    assert body_column(body, 'CREATOR_FK') == (True, 'attacker')


def test_the_charset_gate_makes_python_and_mysql_folding_agree_exactly():
    """Why `[A-Za-z0-9_$]+` is the RIGHT boundary, measured against darwin_dev.

    The gate is only sound if, for every key it ACCEPTS, Python's `.lower()`
    folds the name exactly the way MySQL does. Measured 2026-07-27:

      * MySQL folds **ASCII A-Z and nothing else**. `SELECT ＡREA_FK` (fullwidth
        A) is 1054 — it does not fold Unicode to ASCII.
      * It DOES fold `U+212A` KELVIN SIGN to `K`: `SELECT AREA_F<U+212A>`
        resolves to `area_fk`. So does Python's `.lower()`. That agreement is
        luck, not design — and it never has to be relied on, because the key is
        not ASCII and the gate refuses it first.
      * `$` IS legal in an unquoted identifier and folds normally (`A$B` and
        `a$b` are one column, verified with a temp table), which is why it is in
        the charset rather than excluded as exotic.

    Within ASCII, `.lower()` folds A-Z and leaves `0-9`, `_` and `$` alone —
    identical to MySQL. So the accepted set is exactly the set where the two
    agree, and everything MySQL might fold differently is a 400 before folding
    is ever consulted. That is what makes a charset restriction sufficient where
    a normalizer would not be.
    """
    for accepted in ('area_fk', 'AREA_FK', 'Area_Fk', 'a$b', 'A$B', 'x9_$'):
        assert _PLAIN_IDENTIFIER_RE.fullmatch(accepted), accepted
        # The only transformation MySQL applies to these is the ASCII fold.
        assert accepted.lower() == ''.join(
            chr(ord(c) + 32) if 'A' <= c <= 'Z' else c for c in accepted)

    # Non-ASCII never reaches the fold: refused by the charset.
    for refused in ('AREA_FK', 'ＡREA_FK', 'area_fk '):
        assert not _PLAIN_IDENTIFIER_RE.fullmatch(refused), refused
        assert check_body_keys('tasks', [{refused: 1}]) == (400, 'BAD REQUEST')


def test_ordinary_bodies_are_untouched_by_the_key_check():
    """Every column in schema.sql is `[a-z0-9_]`, so nothing real is refused."""
    assert check_body_keys('tasks', [
        {'id': '', 'description': 'x', 'priority': '0', 'done': '0',
         'area_fk': 7, 'sort_order': 3, 'recurring_task_fk': 'NULL'}]) is None
    assert check_body_keys('profiles', [{'id': 'sub', 'name': 'n',
                                         'theme_mode': 'dark'}]) is None
    assert check_body_keys('anything', []) is None


def test_a_non_dict_body_is_refused_by_the_key_check_too():
    """It runs before everything, so it must survive a malformed body itself."""
    assert check_body_keys('tasks', ['nope']) == (400, 'BAD REQUEST')
    assert check_body_keys('tasks', [{5: 'x'}]) == (400, 'BAD REQUEST')


def test_a_dict_cursor_is_read_the_same_as_a_tuple_cursor():
    """db_connection opens tuple cursors; tests/conftest.py opens DictCursor.

    A KeyError here is not a `pymysql.Error`, so it would escape the guard's
    `except` and surface as a 503 naming nothing.
    """
    class DictCursor(FakeCursor):
        def fetchall(self):
            return [{'id': i, 'creator_fk': o} for i, o in self._result]

    cursor = DictCursor(ROWS)
    lookups, _ = plan_parent_lookups('test_runs', [{'test_plan_fk': 2}])
    assert resolve_parent_lookups(cursor, 'test_runs', lookups,
                                  'victim') == (403, 'FORBIDDEN')
