"""The POST read-back must return the row that was written — and only that row (req #3094).

`rest_post.py` finishes a single-object POST by reading the new row back:

    SELECT CONCAT('[', GROUP_CONCAT(JSON_OBJECT(...)), ']') FROM {table} WHERE id=...

Req #3057 gated that on an `id` COLUMN existing. That is the wrong predicate.
`profiles.id` is a `varchar(64)` holding the Cognito sub and is **not**
`AUTO_INCREMENT`, so `LAST_INSERT_ID()` returned 0 — `db_connection.py` opens a
new connection per invocation, so nothing had ever generated an id on it — and
the read-back became `WHERE id=0`. MySQL coerces the VARCHAR column to a number
for that comparison, and **every id that does not begin with a digit coerces to
0**, so they all matched. The read-back carries no `creator_fk` predicate and its
`GROUP_CONCAT` has no `GROUP BY`, so the matches collapsed into a single array:
whoever POSTed a profile got back 200 plus other users' profiles (id, name,
email, timezone). Measured 2026-07-26: `darwin_dev` 11 profiles / 5 matching
`WHERE id=0`, `darwin` (production) 17 / 5 — the leak was live in production.
Reachable by any Cognito-authenticated caller issuing `POST /{db}/profiles`.

The fix reads `Extra` off the `DESC` rows already in hand and only trusts
`LAST_INSERT_ID()` when the column is actually `auto_increment`; otherwise it
reads back on the id the body supplied, bound as a string so MySQL compares
varchar to varchar and can never coerce the column.

Two layers here, because they fail differently:

- `TestProfilePostReadBack` drives the real Lambda against darwin_dev. It asserts
  the caller's own row comes back AND that a second profile whose id also
  coerces to 0 does not — with an explicit precondition check, so the test can
  never pass vacuously because the coercion set happened to be empty.
- `TestReadBackIdSelection` is DB-free and pins the decision itself: which id the
  read-back uses, that it is BOUND rather than interpolated, and that a
  `LAST_INSERT_ID()` of 0 never reaches SQL as `WHERE id=0`. A future refactor
  that reintroduces the bug fails here without needing exports.sh.
"""
import json
import time
import uuid

import pytest

from rest_post import rest_post


# ---------------------------------------------------------------------------
# Integration — the real handler against darwin_dev
# ---------------------------------------------------------------------------

def _zero_coercing_id(tag):
    """A profile id that MySQL coerces to 0 — i.e. it does not start with a digit.

    That is the whole precondition for the #3094 leak, and it is what every real
    Cognito sub used here looks like (`conftest.creator_fk` is `pytest-...`).
    """
    return f"{tag}-{int(time.time())}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def bystander_profile(invoke, db_connection):
    """A second profile, owned by someone else, whose id also coerces to 0.

    This is the row the broken read-back handed to the wrong caller. It has to
    exist while the POST under test runs, or the test proves nothing.
    """
    other = _zero_coercing_id('bystander')
    response = invoke('POST', '/darwin_dev/profiles', body={
        'id': other,
        'name': 'Bystander User',
        'email': 'bystander@test.invalid',
    }, authenticated_user=other)
    assert response['statusCode'] in (200, 201)
    yield other
    import pymysql as _pymysql
    try:
        with db_connection.cursor() as cur:
            cur.execute('DELETE FROM profiles WHERE id = %s', (other,))
        db_connection.commit()
    except _pymysql.MySQLError:
        db_connection.rollback()


class TestProfilePostReadBack:
    """POST /profiles returns the caller's row and nothing else."""

    def test_post_profile_returns_only_the_callers_row(
            self, invoke, db_connection, bystander_profile):
        """The requirement's assertion: one row back, and it is the caller's."""
        mine = _zero_coercing_id('owner')

        # Precondition. If ids stopped coercing to 0 this test would pass for the
        # wrong reason, so assert the hazard is real before asserting it is gone.
        with db_connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM profiles WHERE id=0')
            coercing = cur.fetchone()['n']
        assert coercing >= 1, (
            'no profile id coerces to 0, so this test cannot detect the #3094 '
            'read-back collapse'
        )

        try:
            response = invoke('POST', '/darwin_dev/profiles', body={
                'id': mine,
                'name': 'Owner User',
                'email': 'owner@test.invalid',
            }, authenticated_user=mine)

            assert response['statusCode'] == 200
            body = json.loads(response['body'])
            assert isinstance(body, list)

            # Exactly one row. Before the fix this was every zero-coercing profile.
            assert len(body) == 1, (
                f'read-back returned {len(body)} rows; POST must return only the '
                f'row it wrote (req #3094)'
            )
            assert body[0]['id'] == mine
            assert body[0]['name'] == 'Owner User'

            # And name the leak explicitly, so a failure reads as what it is.
            returned_ids = {row['id'] for row in body}
            assert bystander_profile not in returned_ids, (
                "POST /profiles leaked another user's profile row"
            )
        finally:
            import pymysql as _pymysql
            try:
                with db_connection.cursor() as cur:
                    cur.execute('DELETE FROM profiles WHERE id = %s', (mine,))
                db_connection.commit()
            except _pymysql.MySQLError:
                db_connection.rollback()

    def test_forged_id_is_overridden_by_the_jwt(
            self, invoke, db_connection, bystander_profile):
        """A body `id` naming someone else is replaced by the token sub — and the
        read-back follows the token, not the body."""
        mine = _zero_coercing_id('forger')
        try:
            response = invoke('POST', '/darwin_dev/profiles', body={
                'id': bystander_profile,   # forged — must be overridden
                'name': 'Forger User',
                'email': 'forger@test.invalid',
            }, authenticated_user=mine)

            assert response['statusCode'] == 200
            body = json.loads(response['body'])
            assert len(body) == 1
            assert body[0]['id'] == mine
            assert body[0]['name'] == 'Forger User'
        finally:
            import pymysql as _pymysql
            try:
                with db_connection.cursor() as cur:
                    cur.execute('DELETE FROM profiles WHERE id = %s', (mine,))
                db_connection.commit()
            except _pymysql.MySQLError:
                db_connection.rollback()

    def test_auto_increment_table_still_reads_back(self, invoke, creator_fk):
        """Regression guard on the path that was always fine.

        `domains.id` IS auto_increment, so the read-back still goes through
        LAST_INSERT_ID(). Narrowing the gate must not cost the common case its
        200-with-body.
        """
        response = invoke('POST', '/darwin_dev/domains', body={
            'domain_name': 'req3094 readback domain',
            'creator_fk': creator_fk,
            'closed': '0',
        })
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert len(body) == 1
        assert body[0]['domain_name'] == 'req3094 readback domain'
        assert int(body[0]['id']) > 0

        # Session-scoped cleanup in conftest deletes domains by creator_fk.

    def test_blank_template_id_still_reads_back(self, invoke, creator_fk):
        """End-to-end guard for the shape the Darwin UI actually POSTs.

        The frontend's blank "type here to create" row is `{'id': '', ...}` and
        is spread straight into the body. That must still come back 200 with the
        generated row — narrowing the read-back gate must not reclassify the
        single most common create in the product as 201-with-no-body.
        """
        response = invoke('POST', '/darwin_dev/domains', body={
            'id': '',
            'domain_name': 'req3094 template domain',
            'creator_fk': creator_fk,
            'closed': '0',
        })
        assert response['statusCode'] == 200, (
            'a blank template id must fall through to LAST_INSERT_ID(), not be '
            'read back as WHERE id=""'
        )
        body = json.loads(response['body'])
        assert len(body) == 1
        assert body[0]['domain_name'] == 'req3094 template domain'
        assert int(body[0]['id']) > 0


# ---------------------------------------------------------------------------
# Unit — which id the read-back picks, with no database at all
# ---------------------------------------------------------------------------

# `DESC {table}` rows are (Field, Type, Null, Key, Default, Extra). Only `Extra`
# distinguishes an id MySQL generates from one the caller supplies, which is
# precisely the distinction #3057 missed.
PROFILES_DESC = [
    ('id', 'varchar(64)', 'NO', 'PRI', None, ''),
    ('name', 'varchar(256)', 'NO', '', None, ''),
    ('email', 'varchar(256)', 'NO', '', None, ''),
]
DOMAINS_DESC = [
    ('id', 'int', 'NO', 'PRI', None, 'auto_increment'),
    ('domain_name', 'varchar(256)', 'NO', '', None, ''),
    ('creator_fk', 'varchar(64)', 'NO', 'MUL', None, ''),
]

READ_BACK_ROW = (('[{"id": "x"}]',),)


class FakeCursor:
    """Replays canned results by statement kind and records every execute().

    Deliberately not a mock library: the assertions below are about the exact
    SQL text and the exact bound args, and a recorder makes that legible.

    Note what it does NOT model: real pymysql applies `query % escaped_args`
    when args are present, so the SQL text is a format string. This fake stores
    both halves untouched and never formats, so it cannot surface a `%` in a
    DESC-derived column name. That hazard is handled by widening the read-back's
    `except` to `Exception` in rest_post.py, not by this fake.
    """

    def __init__(self, script):
        self._script = script
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, args=None):
        self._script['executed'].append((' '.join(statement.split()), args))
        collapsed = ' '.join(statement.split()).upper()
        if collapsed.startswith('INSERT'):
            self._last = None
            return 1
        if collapsed.startswith('DESC'):
            self._last = self._script['desc']
            return len(self._script['desc'])
        if 'LAST_INSERT_ID()' in collapsed:
            self._script['last_insert_id_queried'] = True
            self._last = ((self._script['last_insert_id'],),)
            return 1
        self._last = self._script['read_back']
        return 1

    def fetchall(self):
        return self._last

    def fetchone(self):
        return self._last[0] if self._last else None


class FakeConn:
    def __init__(self, script):
        self._script = script

    def cursor(self):
        return FakeCursor(self._script)

    def rollback(self):
        pass


def run_post(desc, body, last_insert_id=0, read_back=READ_BACK_ROW):
    script = {
        'desc': desc,
        'last_insert_id': last_insert_id,
        'read_back': read_back,
        'executed': [],
        'last_insert_id_queried': False,
    }
    response = rest_post('POST', FakeConn(script), 'darwin_dev', 'sometable',
                         dict(body), authenticated_user=None)
    return response, script


def read_back_call(script):
    """The (sql, args) of the read-back SELECT, or None if it never ran."""
    for sql, args in script['executed']:
        if sql.upper().startswith('SELECT CONCAT'):
            return sql, args
    return None


class TestReadBackIdSelection:

    def test_non_auto_increment_reads_back_on_the_supplied_id(self):
        """The #3094 case. profiles.id is supplied, not generated."""
        sub = 'a1b2c3d4-0000-4000-8000-abcdefabcdef'
        response, script = run_post(PROFILES_DESC, {'id': sub, 'name': 'n'})

        assert response['statusCode'] == 200
        sql, args = read_back_call(script)
        assert args == (sub,), 'read-back must use the id the body supplied'
        assert 'WHERE id=%s' in sql, 'the id must be BOUND, not interpolated'
        assert sub not in sql, 'the id must not appear in the SQL text'
        assert not script['last_insert_id_queried'], (
            'LAST_INSERT_ID() is meaningless on a non-auto_increment id and must '
            'not be consulted'
        )

    def test_non_auto_increment_id_is_bound_as_a_string(self):
        """A numeric-looking id must still go down as a string.

        Binding an int against a VARCHAR column is what makes MySQL coerce the
        COLUMN to a number — the exact mechanic of the leak.
        """
        response, script = run_post(PROFILES_DESC, {'id': 12345, 'name': 'n'})

        assert response['statusCode'] == 200
        _, args = read_back_call(script)
        assert args == ('12345',)
        assert isinstance(args[0], str)

    def test_non_auto_increment_with_no_id_skips_the_read_back(self):
        """Nothing identifies the row, so 201 CREATED — never `WHERE id=0`."""
        response, script = run_post(PROFILES_DESC, {'name': 'n'})

        assert response['statusCode'] == 201
        assert read_back_call(script) is None
        assert not script['last_insert_id_queried']

    @pytest.mark.parametrize('empty_id', ['', 0, None], ids=['blank', 'zero', 'none'])
    def test_a_falsy_body_id_falls_through_to_last_insert_id(self, empty_id):
        """The shape the Darwin frontend actually sends.

        Every "type into the blank row to create" template carries `id: ''` and
        is spread straight into the POST body (`AreaTabPanel.jsx`, `TaskCard.jsx`,
        `CategoryCard.jsx`, `ProjectEdit.jsx`, `DomainEdit.jsx`, ...). MySQL
        coerces `''` to 0 on an AUTO_INCREMENT column and generates a real id, so
        the body's `''` identifies nothing — treating it as a supplied id reads
        back on `WHERE id=''`, matches no row, and downgrades the response to
        201-with-no-body. Those callers do their real work in the 200 branch: the
        201 branch only invalidates a query, losing the new id, the pending
        -mutation replay, and the post-create navigate. Falsy means absent.
        """
        response, script = run_post(DOMAINS_DESC,
                                    {'id': empty_id, 'domain_name': 'd'},
                                    last_insert_id=91)

        assert response['statusCode'] == 200
        assert script['last_insert_id_queried']
        _, args = read_back_call(script)
        assert args == (91,)

    def test_null_sentinel_id_counts_as_absent(self):
        """`"NULL"` is the caller's explicit-NULL sentinel; `id = NULL` matches
        nothing, so treat it as no id rather than reading back on the string."""
        response, script = run_post(PROFILES_DESC, {'id': 'NULL', 'name': 'n'})

        assert response['statusCode'] == 201
        assert read_back_call(script) is None

    def test_auto_increment_uses_last_insert_id(self):
        """The ordinary path, unchanged."""
        response, script = run_post(DOMAINS_DESC, {'domain_name': 'd'},
                                    last_insert_id=4242)

        assert response['statusCode'] == 200
        assert script['last_insert_id_queried']
        sql, args = read_back_call(script)
        assert args == (4242,)
        assert 'WHERE id=%s' in sql

    def test_auto_increment_with_zero_last_insert_id_skips_the_read_back(self):
        """LAST_INSERT_ID() is 0 when MySQL generated nothing on this connection
        — which happens on an explicit-id write. `WHERE id=0` must never be the
        answer; that is req #3094 under a different table."""
        response, script = run_post(DOMAINS_DESC, {'domain_name': 'd'},
                                    last_insert_id=0)

        assert response['statusCode'] == 201
        assert read_back_call(script) is None

    def test_explicit_id_into_an_auto_increment_column_wins(self):
        """MySQL leaves LAST_INSERT_ID() untouched for a value it did not
        generate, so the body's id is the only thing that identifies the row."""
        response, script = run_post(DOMAINS_DESC, {'id': 77, 'domain_name': 'd'},
                                    last_insert_id=0)

        assert response['statusCode'] == 200
        _, args = read_back_call(script)
        assert args == (77,)
        assert not script['last_insert_id_queried']

    def test_table_with_no_id_column_still_skips_the_read_back(self):
        """req #3057's junction-table contract, unchanged by this fix."""
        junction_desc = [
            ('agent_fk', 'int', 'NO', 'PRI', None, ''),
            ('instruction_fk', 'int', 'NO', 'PRI', None, ''),
        ]
        response, script = run_post(junction_desc,
                                    {'agent_fk': 1, 'instruction_fk': 2})

        assert response['statusCode'] == 201
        assert read_back_call(script) is None
        assert not script['last_insert_id_queried']
