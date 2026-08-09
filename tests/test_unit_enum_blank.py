"""A NOT NULL enum column must never be written BLANK through the gateway (req #3432).

No database, no `exports.sh`. Three layers, and each one fails for a different
reason if the fix is reverted:

  * REGISTRY CONFORMANCE — the candidate columns are re-derived from
    `DarwinSQL/schema.sql` on every run, so a new enum column fails the build
    until somebody classifies it. This is the `CREATOR_TABLE_REFERENCES`
    discipline (req #3125): the audit that filed that requirement counted eleven
    columns and the DDL said thirty-six, so no list here is hand-counted.
  * GUARD BEHAVIOUR — what `check_enum_blanks` refuses and, just as important,
    what it must NOT refuse. An absent key is the partial-write contract; a
    guard that refused omission would break every POST that relies on a column
    default and every PUT that names one field.
  * GATEWAY BOUNDARY — `rest_post` and `rest_put` called for real. The
    connection they are handed raises if anything asks it for a cursor, so a
    test that returns 400 has PROVED no SQL ran, and a test that raises has
    proved the guard let a legitimate write through instead of over-refusing.

WHY THE BLANK IS THE WHOLE OF IT. Measured in production 2026-08-09: 18
`requirements` rows carry `ai_model=''` and/or `effort=''` — the two NOT NULL
enum columns in the entire schema that have no column DEFAULT, which is what
made a caller's OMISSION land as MySQL's implicit empty-string fill under this
instance's non-strict `sql_mode`. Req #3434 gives them a DEFAULT so omission is
safe; this file is the other half, and covers the caller that sends the key with
nothing in it. The allowed VALUES are deliberately not asserted anywhere here —
see the `ENUM_COLUMNS` comment for why the registry holds no value lists.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth_utils import (ENUM_COLUMNS, FREE_TEXT_NOT_NULL_COLUMNS, _is_blank,
                        check_enum_blanks)
from rest_post import rest_post
from rest_put import rest_put


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# schema.sql parsing — the source of truth the registry is checked against
# ---------------------------------------------------------------------------

# A column no wider than this is a candidate. The bound is structural rather
# than semantic on purpose: "which columns hold an enum" is exactly the judgment
# this file exists to stop somebody making silently, so the parse casts a wide
# net and the registries record the call. Every enum column in the schema today
# is VARCHAR(32) or narrower (`branches.branch_type` is the widest).
NARROW = 32

_CREATE = re.compile(r'\s*CREATE TABLE (?:IF NOT EXISTS )?`?(\w+)`?', re.I)
_END = re.compile(r'\s*\)\s*;')
_NOT_A_COLUMN = re.compile(
    r'(PRIMARY|UNIQUE|CONSTRAINT|FOREIGN|INDEX|KEY|CHECK)\b', re.I)
_COLUMN = re.compile(
    r'`?(\w+)`?\s+(ENUM\s*\([^)]*\)|VARCHAR\s*\(\s*(\d+)\s*\)'
    r'|CHAR\s*\(\s*(\d+)\s*\))(.*)$', re.I)


def _schema_path():
    """DarwinSQL/schema.sql as a sibling of Lambda-Rest, or None."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, '..', '..', 'DarwinSQL', 'schema.sql')
    return candidate if os.path.exists(candidate) else None


def _closed(text):
    """True when `text` has no unbalanced `(`.

    A definition ends at a TOP-LEVEL comma, never one inside a parenthesis. A
    wrapped `ENUM('draft','active',` / `'paused')` value list ends its first line
    on a comma, and treating that as the end of the statement drops the column
    from the parse ENTIRELY — silently, which would make
    `test_every_candidate_column_is_classified` vacuous for exactly the shape a
    five-value enum is most naturally written in. Found by mutation-testing this
    parser against an injected column, not by reading it.
    """
    return text.count('(') == text.count(')')


def _parse_columns(path):
    """`(candidates, all_text_columns)` from the DDL, each `{table: {column…}}`.

    `candidates` is the structural sweep — NOT NULL, and either a real
    `ENUM(...)` or a CHAR/VARCHAR no wider than `NARROW`. That is what every
    column must be CLASSIFIED against.

    `all_text_columns` is every NOT NULL CHAR/VARCHAR/ENUM of ANY width, and it
    exists because the sweep is a filter rather than a proof: a bounded domain
    declared wider (`swarm_completes.skill_name` VARCHAR(64)) is registered by
    hand, so "does this registered column exist?" has to be asked against the
    wider set or the hand registration would read as a typo.

    Comments are stripped FIRST. `pipelines.execution_mode` declares its type on
    one line and `NOT NULL DEFAULT 'parallel'` on the next with a `--` comment
    between them, so a line-at-a-time parse that respected comments would read
    the column as nullable and drop the schema's only two real `ENUM(...)`
    columns without saying so.
    """
    candidates, all_text = {}, {}
    table = None
    buffer = ''
    for raw in open(path).read().splitlines():
        line = raw.split('--', 1)[0].rstrip()
        match = _CREATE.match(line)
        if match:
            table, buffer = match.group(1), ''
            continue
        if table is None:
            continue
        if _END.match(line) and _closed(buffer):
            table, buffer = None, ''
            continue
        buffer = (buffer + ' ' + line.strip()).strip()
        if not buffer:
            continue
        # Complete at a top-level trailing comma, or as soon as the definition
        # carries its own nullness — the latter is what lets the two-line ENUM
        # above resolve, the `_closed` guard is what stops a wrapped value list
        # from resolving too early.
        if not _closed(buffer):
            continue
        if not (buffer.endswith(',') or re.search(r'NULL\b', buffer, re.I)):
            continue
        statement, buffer = buffer.rstrip(',').strip(), ''
        if _NOT_A_COLUMN.match(statement):
            continue
        column = _COLUMN.match(statement)
        if not column:
            continue
        name, column_type, varchar_width, char_width, tail = column.groups()
        if 'NOT NULL' not in tail.upper():
            continue
        if re.search(r'PRIMARY KEY|AUTO_INCREMENT', tail, re.I):
            continue
        all_text.setdefault(table, set()).add(name)
        width = int(varchar_width or char_width or 0)
        if not column_type.upper().startswith('ENUM') and width > NARROW:
            continue
        candidates.setdefault(table, set()).add(name)
    return candidates, all_text


@pytest.fixture(scope='module')
def parsed():
    path = _schema_path()
    if path is None:
        pytest.skip('DarwinSQL/schema.sql not present as a sibling repo')
    return _parse_columns(path)


@pytest.fixture(scope='module')
def candidates(parsed):
    return parsed[0]


@pytest.fixture(scope='module')
def all_text_columns(parsed):
    return parsed[1]


def _pairs(registry):
    return {(table, column)
            for table, columns in registry.items() for column in columns}


# ---------------------------------------------------------------------------
# Registry conformance — the test that stops the next unregistered enum
# ---------------------------------------------------------------------------

def test_schema_parse_found_the_columns(candidates, all_text_columns):
    """Guard the guard: an empty parse would make every test below vacuous."""
    assert len(_pairs(candidates)) > 30, (
        f'parsed only {len(_pairs(candidates))} candidate columns from schema.sql')
    # One of each shape the parser has to handle: a plain narrow VARCHAR, and
    # the two-line real ENUM whose NOT NULL sits under a comment.
    assert 'ai_model' in candidates['requirements']
    assert 'effort' in candidates['requirements']
    assert 'execution_mode' in candidates['pipelines']
    # The wider set is a superset and reaches past NARROW.
    assert _pairs(candidates) <= _pairs(all_text_columns)
    assert 'skill_name' in all_text_columns['swarm_completes']
    assert 'skill_name' not in candidates.get('swarm_completes', set())


def test_a_wrapped_enum_value_list_does_not_end_the_definition_early():
    """The `_closed` guard, tested directly rather than trusted.

    A five-value `ENUM(...)` wrapped across two lines ends its first line on a
    comma. Before this guard the parser took that comma as the end of the
    statement, matched nothing, and dropped the column from `candidates`
    ENTIRELY — so the classification test would have passed while the gateway
    silently accepted `''` on it.
    """
    import tempfile
    ddl = (
        "CREATE TABLE IF NOT EXISTS zz_probe (\n"
        "    id INT NOT NULL PRIMARY KEY AUTO_INCREMENT,\n"
        "    wrapped ENUM('draft', 'active',\n"
        "                 'paused', 'completed')\n"
        "                 NOT NULL DEFAULT 'draft',\n"
        "    flat VARCHAR(16) NOT NULL DEFAULT 'x'\n"
        ");\n")
    with tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False) as handle:
        handle.write(ddl)
        path = handle.name
    try:
        candidates, _ = _parse_columns(path)
    finally:
        os.unlink(path)
    assert candidates.get('zz_probe') == {'wrapped', 'flat'}


def test_every_candidate_column_is_classified(candidates):
    """THE invariant: no NOT NULL enum-shaped column is silently unguarded.

    Add `swarm_status_v2 VARCHAR(16) NOT NULL DEFAULT 'x'` to schema.sql and this
    fails until it is put in `ENUM_COLUMNS` or written down as free text — which
    is the whole point, because the alternative is a column that quietly accepts
    `''` for however long it takes somebody to notice a reader matching no
    branch.
    """
    classified = _pairs(ENUM_COLUMNS) | _pairs(FREE_TEXT_NOT_NULL_COLUMNS)
    unclassified = sorted(_pairs(candidates) - classified)
    assert not unclassified, (
        'NOT NULL enum-shaped columns in schema.sql that are in neither '
        f'ENUM_COLUMNS nor FREE_TEXT_NOT_NULL_COLUMNS: {unclassified}')


def test_no_column_is_in_both_registries():
    """A column is either policed or exempt. Both is a contradiction, and the
    guard would silently police it — the registry that is READ would win over
    the one that documents the decision."""
    overlap = sorted(_pairs(ENUM_COLUMNS) & _pairs(FREE_TEXT_NOT_NULL_COLUMNS))
    assert not overlap, f'registered as both enum and free text: {overlap}'


def test_every_registered_column_exists_in_the_schema(all_text_columns):
    """A registered column the DDL does not have is dead weight that reads as
    coverage. Catches a rename and a typo alike.

    Checked against the WIDER set, not `candidates`: a bounded domain declared
    wider than `NARROW` is registered by hand and is legitimately outside the
    sweep, so asking this question against the sweep would reject the two real
    ones as typos."""
    unknown = sorted(
        (_pairs(ENUM_COLUMNS) | _pairs(FREE_TEXT_NOT_NULL_COLUMNS))
        - _pairs(all_text_columns))
    assert not unknown, (
        f'registered but not a NOT NULL text column in schema.sql: {unknown}')


def test_the_hand_registered_wide_columns_are_covered(candidates):
    """The sweep is a filter, not a proof — these two prove it and are the
    reason the distinction is written down rather than assumed away.

    Both accepted `''` silently until they were listed, and neither is narrow
    enough for the structural rule to have found them."""
    assert 'skill_name' in ENUM_COLUMNS['swarm_completes']
    assert 'provider' in ENUM_COLUMNS['user_integrations']
    assert 'skill_name' not in candidates.get('swarm_completes', set())
    assert 'provider' not in candidates.get('user_integrations', set())
    assert check_enum_blanks('swarm_completes', [{'skill_name': ''}]) == (400, 'BAD REQUEST')
    assert check_enum_blanks('user_integrations', [{'provider': ''}]) == (400, 'BAD REQUEST')


def test_the_four_columns_this_requirement_was_filed_for_are_registered():
    """Named explicitly so a refactor cannot drop them and stay green: these are
    the columns `/swarm-start` reads straight into the launch command."""
    assert {'ai_model', 'effort'} <= ENUM_COLUMNS['requirements']
    assert {'requirement_status', 'coordination_type'} <= ENUM_COLUMNS['requirements']


# ---------------------------------------------------------------------------
# _is_blank — what counts as "named the column and supplied nothing"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value', ['', ' ', '   ', '\t', '\n', ' \t\n ',
                                   None, 'NULL'])
def test_is_blank_catches_every_shape_of_no_value(value):
    assert _is_blank(value) is True


@pytest.mark.parametrize('value', ['opus', 'high', 'a', ' opus', 'opus ',
                                   'null', 'Null', 0, 1, False, True, 3.0])
def test_is_blank_leaves_real_values_alone(value):
    """`'null'` lowercase is NOT the sentinel — the gateway's spelling is exactly
    `'NULL'`, and quietly widening that would refuse a legitimate value on some
    future column whose domain contains the word.

    `0` and `False` are wrong values, not absent ones. Refusing them would be the
    DOMAIN check this guard deliberately does not make.
    """
    assert _is_blank(value) is False


# ---------------------------------------------------------------------------
# check_enum_blanks — the guard itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('blank', ['', '   ', None, 'NULL'])
def test_refuses_a_blank_on_a_registered_column(blank):
    assert check_enum_blanks('requirements', [{'ai_model': blank}]) == (400, 'BAD REQUEST')


def test_refuses_a_blank_however_the_key_is_cased():
    """MySQL matches a column name case-insensitively, so `{"AI_MODEL": ""}`
    writes `requirements.ai_model`. An exact-string lookup would see no column
    named at all and wave it through — the req #3125 rule, which defeated two
    other registries before it was written down."""
    for key in ('AI_MODEL', 'Ai_Model', 'aI_mOdEl'):
        assert check_enum_blanks('requirements', [{key: ''}]) == (400, 'BAD REQUEST')


def test_allows_a_real_value():
    assert check_enum_blanks('requirements', [{'ai_model': 'opus',
                                               'effort': 'high'}]) is None


def test_allows_an_absent_column():
    """The partial-write contract. On a POST an absent key takes the column
    default (req #3434 gives these two one); on a PUT it means unchanged. A guard
    that required the column would break both."""
    assert check_enum_blanks('requirements', [{'title': 'x'}]) is None
    assert check_enum_blanks('requirements', [{'id': 1, 'title': 'x'}]) is None


def test_ignores_an_unregistered_column_on_a_registered_table():
    """`requirements.title` is NOT NULL too, and Darwin's blank-row pattern POSTs
    it empty. Policing it here would refuse the app's own create flow."""
    assert check_enum_blanks('requirements', [{'title': ''}]) is None
    assert check_enum_blanks('requirements', [{'description': ''}]) is None


def test_ignores_an_unregistered_table():
    assert check_enum_blanks('tasks', [{'task_name': ''}]) is None
    assert check_enum_blanks('nonexistent_table', [{'anything': ''}]) is None


def test_exempt_free_text_columns_are_not_policed():
    """`areas.area_name` holds a single-space row in production and Darwin's
    template row POSTs it empty; `map_runs.activity_name` is whatever the
    Cyclemeter/Strava import found. Refusing these would be a regression, which
    is why they are written down rather than merely omitted."""
    assert check_enum_blanks('areas', [{'area_name': ''}]) is None
    assert check_enum_blanks('map_runs', [{'activity_name': ''}]) is None
    assert check_enum_blanks('agents', [{'ai_model': ''}]) is None
    # …and the enum column on the same table still is.
    assert check_enum_blanks('areas', [{'sort_mode': ''}]) == (400, 'BAD REQUEST')
    assert check_enum_blanks('agents', [{'effort': ''}]) == (400, 'BAD REQUEST')


def test_one_blank_anywhere_refuses_the_whole_batch():
    """A bulk POST is one multi-value INSERT that lands or rolls back as a unit,
    so a per-item verdict is not available to the caller anyway."""
    batch = [{'ai_model': 'opus'}, {'ai_model': 'sonnet'}, {'ai_model': ''}]
    assert check_enum_blanks('requirements', batch) == (400, 'BAD REQUEST')


def test_a_non_dict_body_is_refused():
    assert check_enum_blanks('requirements', ['not a dict']) == (400, 'BAD REQUEST')


# ---------------------------------------------------------------------------
# Gateway boundary — rest_post / rest_put for real
# ---------------------------------------------------------------------------

class CursorRequested(Exception):
    """Raised by the stub connection the instant anything opens a cursor."""


class NoSqlConnection:
    """A connection that cannot run SQL, so reaching the database is visible.

    A refusal must return 400 having never asked for a cursor; a legitimate write
    must reach one. Asserting BOTH is what makes these tests fail on a reverted
    wiring (no refusal) and on an over-broad guard (no cursor) alike, instead of
    passing vacuously.
    """

    def cursor(self):
        raise CursorRequested()

    def rollback(self):
        raise CursorRequested()


USER = '37df7531-0000-0000-0000-000000000000'


@pytest.mark.parametrize('blank', ['', '   ', None, 'NULL'])
def test_rest_post_refuses_a_blank_enum_without_touching_the_database(blank):
    response = rest_post('POST', NoSqlConnection(), 'darwin_dev', 'requirements',
                         {'title': 'x', 'category_fk': 1, 'ai_model': blank},
                         authenticated_user=USER)
    assert response['statusCode'] == 400


def test_rest_post_bulk_refuses_a_blank_enum_without_touching_the_database():
    response = rest_post('POST', NoSqlConnection(), 'darwin_dev', 'requirements',
                         [{'title': 'a', 'effort': 'high'},
                          {'title': 'b', 'effort': ''}],
                         authenticated_user=USER)
    assert response['statusCode'] == 400


@pytest.mark.parametrize('blank', ['', '   ', None, 'NULL'])
def test_rest_put_refuses_a_blank_enum_without_touching_the_database(blank):
    response = rest_put('PUT', NoSqlConnection(), 'darwin_dev', 'requirements',
                        [{'id': 1, 'effort': blank}], authenticated_user=USER)
    assert response['statusCode'] == 400


def test_rest_put_bulk_refuses_a_blank_enum_without_touching_the_database():
    response = rest_put('PUT', NoSqlConnection(), 'darwin_dev', 'requirements',
                        [{'id': 1, 'effort': 'high'},
                         {'id': 2, 'effort': ''}], authenticated_user=USER)
    assert response['statusCode'] == 400


@pytest.mark.parametrize('key', ['AI_MODEL', 'Ai_Model', 'aI_mOdEl'])
def test_rest_post_refuses_a_blank_however_the_key_is_cased(key):
    """The same case-insensitivity as the unit test above, but through the REAL
    entry point — because what makes it work is an ORDERING (`check_body_keys`
    settles the key charset before the guard reads it), and an ordering can only
    regress where the order actually is."""
    response = rest_post('POST', NoSqlConnection(), 'darwin_dev', 'requirements',
                         {'title': 'x', key: ''}, authenticated_user=USER)
    assert response['statusCode'] == 400


@pytest.mark.parametrize('key', ['EFFORT', 'Effort'])
def test_rest_put_refuses_a_blank_however_the_key_is_cased(key):
    response = rest_put('PUT', NoSqlConnection(), 'darwin_dev', 'requirements',
                        [{'id': 1, key: '   '}], authenticated_user=USER)
    assert response['statusCode'] == 400


def test_rest_post_lets_a_real_value_through_to_the_database():
    """The over-refusal half. Reaching the cursor is the pass condition — what
    the INSERT would then do needs a database and is not this file's question."""
    with pytest.raises(CursorRequested):
        rest_post('POST', NoSqlConnection(), 'darwin_dev', 'requirements',
                  {'title': 'x', 'ai_model': 'opus', 'effort': 'high'},
                  authenticated_user=USER)


def test_rest_put_lets_a_real_value_through_to_the_database():
    with pytest.raises(CursorRequested):
        rest_put('PUT', NoSqlConnection(), 'darwin_dev', 'requirements',
                 [{'id': 1, 'ai_model': 'opus'}], authenticated_user=USER)


def test_rest_post_lets_an_omitted_enum_through_to_the_database():
    """Omission is req #3434's half and must stay untouched here — a guard that
    required the column would break every caller relying on a column default."""
    with pytest.raises(CursorRequested):
        rest_post('POST', NoSqlConnection(), 'darwin_dev', 'requirements',
                  {'title': 'x', 'category_fk': 1}, authenticated_user=USER)


def test_rest_post_still_lets_a_blank_free_text_column_through():
    """Darwin's "type into the blank row" pattern POSTs template objects whose
    name field is empty. This is the regression the exemption set exists for."""
    with pytest.raises(CursorRequested):
        rest_post('POST', NoSqlConnection(), 'darwin_dev', 'domains',
                  {'domain_name': ''}, authenticated_user=USER)
