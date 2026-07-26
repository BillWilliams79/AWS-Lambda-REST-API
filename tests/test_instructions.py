"""REST contracts for the `instructions` registry table (req #3049).

The Darwin UI at /agents/instructions writes this table directly, so these tests
lock the behaviours that UI depends on. Two are contracts about FAILURE, and they
matter as much as the happy path:

- A duplicate `name` surfaces as HTTP **500** carrying the raw pymysql message,
  not a 409. The UI parses `1062` + `uq_instructions_name` out of that string to
  tell "you picked a taken name" from "the database is broken". If someone later
  maps IntegrityError to a real status code, these tests fail and force the UI's
  error parser to be updated in the same change.
- `instructions` is in CREATOR_FK_TABLES, so a client-supplied `creator_fk` must
  be OVERWRITTEN with the authenticated Cognito sub, never trusted.
"""
import json

import pytest

from conftest import extract_id


def _err(response):
    """The error string Lambda-Rest puts on the wire (JSON-encoded)."""
    return json.loads(response['body'])


@pytest.fixture
def instruction(invoke, creator_fk):
    """A throwaway instruction row, removed after the test."""
    created = []

    def _make(name, content='binding text', **extra):
        resp = invoke('POST', '/darwin_dev/instructions', body={
            'name': name, 'content': content, 'creator_fk': creator_fk, **extra,
        })
        assert resp['statusCode'] == 200, resp['body']
        row_id = extract_id(resp)
        created.append(row_id)
        return row_id

    yield _make

    for row_id in created:
        invoke('DELETE', '/darwin_dev/instructions', body={'id': row_id})


class TestInstructionsCRUD:

    def test_crud_lifecycle(self, invoke, creator_fk):
        """POST → PUT → GET → DELETE → GET 404 through the generic passthrough.

        req #3061: this fixture used to round-trip a `sort_order` field, but
        migration 072 (req #3063) dropped `instructions.sort_order` — the catalog
        column that was always distinct from `agent_instructions.sort_order`, the
        boot load order. The passthrough builds its column list from the body, so
        the phantom key was a MySQL 1054, not a skipped field. The multi-column
        PUT it was there to cover now round-trips `name`, which is the other
        column the /agents/instructions UI edits.
        """
        create = invoke('POST', '/darwin_dev/instructions', body={
            'name': f'pytest-{creator_fk}-lifecycle',
            'content': 'never fabricate a root cause',
            'creator_fk': creator_fk,
        })
        assert create['statusCode'] == 200
        row_id = extract_id(create)
        assert row_id is not None

        update = invoke('PUT', '/darwin_dev/instructions', body=[
            {'id': row_id, 'content': 'REVISED duty',
             'name': f'pytest-{creator_fk}-lifecycle-renamed'},
        ])
        assert update['statusCode'] in (200, 204)

        get = invoke('GET', '/darwin_dev/instructions', query={'id': row_id})
        assert get['statusCode'] == 200
        row = json.loads(get['body'])[0]
        assert row['content'] == 'REVISED duty'
        assert row['name'] == f'pytest-{creator_fk}-lifecycle-renamed'

        assert invoke('DELETE', '/darwin_dev/instructions',
                      body={'id': row_id})['statusCode'] == 200
        assert invoke('GET', '/darwin_dev/instructions',
                      query={'id': row_id})['statusCode'] == 404

    def test_post_overwrites_client_supplied_creator_fk(self, invoke, creator_fk, instruction):
        """A caller must not be able to plant a row on someone else's account."""
        resp = invoke('POST', '/darwin_dev/instructions', body={
            'name': f'pytest-{creator_fk}-spoof',
            'content': 'x',
            'creator_fk': 'somebody-elses-cognito-sub',
        })
        assert resp['statusCode'] == 200
        row_id = extract_id(resp)
        try:
            row = json.loads(invoke('GET', '/darwin_dev/instructions',
                                    query={'id': row_id})['body'])[0]
            assert row['creator_fk'] == creator_fk
        finally:
            invoke('DELETE', '/darwin_dev/instructions', body={'id': row_id})

    def test_closed_soft_delete_keeps_the_row(self, invoke, creator_fk, instruction):
        """Closing is the retire path — it must not remove anything."""
        row_id = instruction(f'pytest-{creator_fk}-closed')
        assert invoke('PUT', '/darwin_dev/instructions',
                      body=[{'id': row_id, 'closed': '1'}])['statusCode'] in (200, 204)
        row = json.loads(invoke('GET', '/darwin_dev/instructions',
                                query={'id': row_id})['body'])[0]
        assert row['closed'] == 1
        assert row['name'] == f'pytest-{creator_fk}-closed'


class TestInstructionsUniqueName:
    """The exact wire contract the UI's error parser reads."""

    def test_duplicate_name_post_is_500_with_1062(self, invoke, creator_fk, instruction):
        name = f'pytest-{creator_fk}-dupe'
        instruction(name)
        resp = invoke('POST', '/darwin_dev/instructions', body={
            'name': name, 'content': 'second row', 'creator_fk': creator_fk,
        })
        assert resp['statusCode'] == 500
        message = _err(resp)
        assert '1062' in message
        assert 'uq_instructions_name' in message

    def test_rename_onto_existing_name_is_500_with_1062(self, invoke, creator_fk, instruction):
        taken = f'pytest-{creator_fk}-taken'
        instruction(taken)
        victim_id = instruction(f'pytest-{creator_fk}-victim')

        resp = invoke('PUT', '/darwin_dev/instructions',
                      body=[{'id': victim_id, 'name': taken}])
        assert resp['statusCode'] == 500
        message = _err(resp)
        assert '1062' in message
        assert 'uq_instructions_name' in message

    def test_unique_key_does_not_exclude_closed_rows(self, invoke, creator_fk, instruction):
        """A CLOSED row still owns its name.

        This is why the UI pre-checks uniqueness against the UNFILTERED catalog:
        colliding with a row the page is not currently showing is the confusing
        failure that check exists to prevent.
        """
        name = f'pytest-{creator_fk}-closed-holds-name'
        row_id = instruction(name)
        invoke('PUT', '/darwin_dev/instructions', body=[{'id': row_id, 'closed': '1'}])

        resp = invoke('POST', '/darwin_dev/instructions', body={
            'name': name, 'content': 'reusing a retired name', 'creator_fk': creator_fk,
        })
        assert resp['statusCode'] == 500
        assert 'uq_instructions_name' in _err(resp)


class TestInstructionsCreatorIsolation:
    """instructions is in CREATOR_FK_TABLES — writes must be scoped."""

    def test_put_from_another_user_changes_nothing(self, invoke, creator_fk, instruction):
        row_id = instruction(f'pytest-{creator_fk}-isolation-put')

        resp = invoke('PUT', '/darwin_dev/instructions',
                      body=[{'id': row_id, 'content': 'hijacked'}],
                      authenticated_user='a-different-cognito-sub')
        assert resp['statusCode'] == 204          # NO DATA CHANGED — scoped out

        row = json.loads(invoke('GET', '/darwin_dev/instructions',
                                query={'id': row_id})['body'])[0]
        assert row['content'] == 'binding text'

    def test_delete_from_another_user_removes_nothing(self, invoke, creator_fk, instruction):
        row_id = instruction(f'pytest-{creator_fk}-isolation-delete')

        resp = invoke('DELETE', '/darwin_dev/instructions', body={'id': row_id},
                      authenticated_user='a-different-cognito-sub')
        assert resp['statusCode'] == 404          # nothing matched under that sub

        assert invoke('GET', '/darwin_dev/instructions',
                      query={'id': row_id})['statusCode'] == 200

    def test_unauthenticated_write_is_rejected(self, invoke, creator_fk):
        resp = invoke('POST', '/darwin_dev/instructions', body={
            'name': f'pytest-{creator_fk}-anon', 'content': 'x',
        }, authenticated_user=None)
        assert resp['statusCode'] == 403
