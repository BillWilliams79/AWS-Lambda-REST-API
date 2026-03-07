"""
Security tests for creator_fk enforcement in Lambda-Rest.

Verifies that authenticated users cannot access, modify, or delete
another user's data. Uses a second "attacker" user identity alongside
the session's legitimate test user.
"""
import json
import time
import uuid

import pytest

from conftest import extract_id


@pytest.fixture(scope="module")
def attacker_fk():
    """Unique attacker identity for cross-user security tests."""
    return f"attacker-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def attacker_invoke(attacker_fk):
    """Invoke factory authenticated as the attacker user."""
    from handler import lambda_handler

    def _invoke(method, path, query=None, body=None):
        event = {
            'httpMethod': method,
            'path': path,
            'queryStringParameters': query,
            'body': json.dumps(body) if body is not None else None,
            'requestContext': {
                'authorizer': {
                    'claims': {'sub': attacker_fk}
                }
            },
        }
        return lambda_handler(event, {})
    return _invoke


@pytest.fixture(scope="module")
def attacker_profile(attacker_fk, attacker_invoke, db_connection):
    """Create attacker profile and clean up after module."""
    attacker_invoke('POST', '/darwin_dev/profiles', body={
        'id': attacker_fk,
        'name': 'Attacker User',
        'email': 'attacker@test.com',
        'subject': attacker_fk,
        'userName': attacker_fk,
        'region': 'us-west-1',
        'userPoolId': 'test-pool',
    })
    yield attacker_fk
    import pymysql as _pymysql
    try:
        with db_connection.cursor() as cur:
            cur.execute('DELETE FROM profiles WHERE id = %s', (attacker_fk,))
        db_connection.commit()
    except _pymysql.MySQLError:
        db_connection.rollback()


class TestCreatorFkSecurity:
    """Cross-user access control tests."""

    # -------------------------------------------------------------------
    # SEC-01: GET areas — attacker cannot see victim's areas
    # -------------------------------------------------------------------

    def test_get_areas_attacker_sees_nothing(self, attacker_invoke, attacker_profile, test_ids):
        """SEC-01: Attacker GET areas returns 404 — cannot see victim's data."""
        response = attacker_invoke('GET', '/darwin_dev/areas', query={
            'id': test_ids['area_id'],
        })
        assert response['statusCode'] == 404

    # -------------------------------------------------------------------
    # SEC-02: GET tasks — attacker cannot see victim's tasks
    # -------------------------------------------------------------------

    def test_get_tasks_attacker_sees_nothing(self, attacker_invoke, attacker_profile, test_ids):
        """SEC-02: Attacker GET tasks returns 404 — cannot see victim's tasks."""
        response = attacker_invoke('GET', '/darwin_dev/tasks', query={
            'id': test_ids['task_id'],
        })
        assert response['statusCode'] == 404

    # -------------------------------------------------------------------
    # SEC-03: GET profiles — can only see own profile
    # -------------------------------------------------------------------

    def test_get_profiles_only_own(self, attacker_invoke, attacker_profile, creator_fk):
        """SEC-03: Attacker GET profiles — can only see attacker's profile, not victim's."""
        response = attacker_invoke('GET', '/darwin_dev/profiles', query={
            'id': creator_fk,
        })
        # Should be 404 — attacker's JWT scopes to attacker's id only
        assert response['statusCode'] == 404

    # -------------------------------------------------------------------
    # SEC-04: POST domain with forged creator_fk — overridden by JWT
    # -------------------------------------------------------------------

    def test_post_forged_creator_fk_overridden(self, attacker_invoke, attacker_profile, creator_fk, db_connection):
        """SEC-04: POST domain with forged creator_fk — record created with attacker's ID."""
        response = attacker_invoke('POST', '/darwin_dev/domains', body={
            'domain_name': 'Forged Domain',
            'creator_fk': creator_fk,  # forged — should be overridden
            'closed': '0',
        })
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        domain_id = body[0]['id']

        # Verify the record was created with attacker's ID, not the forged one
        assert body[0]['creator_fk'] == attacker_profile  # attacker_fk, not creator_fk

        # Clean up
        import pymysql as _pymysql
        try:
            with db_connection.cursor() as cur:
                cur.execute('DELETE FROM domains WHERE id = %s', (domain_id,))
            db_connection.commit()
        except _pymysql.MySQLError:
            db_connection.rollback()

    # -------------------------------------------------------------------
    # SEC-05: PUT another user's area — returns 204 (no rows changed)
    # -------------------------------------------------------------------

    def test_put_other_users_area_no_effect(self, attacker_invoke, attacker_profile, test_ids):
        """SEC-05: Attacker PUT on victim's area — returns 204 (no rows matched)."""
        response = attacker_invoke('PUT', '/darwin_dev/areas', body=[
            {'id': test_ids['area_id'], 'area_name': 'HACKED'}
        ])
        assert response['statusCode'] == 204

    # -------------------------------------------------------------------
    # SEC-06: Bulk PUT mixing own/other records — only own updated
    # -------------------------------------------------------------------

    def test_bulk_put_mixed_records(self, invoke, attacker_invoke, attacker_profile, creator_fk, test_ids, db_connection):
        """SEC-06: Bulk PUT with victim's area_id — attacker can't update it."""
        # Create an area owned by the attacker
        attacker_area_resp = attacker_invoke('POST', '/darwin_dev/areas', body={
            'area_name': 'Attacker Area',
            'domain_fk': test_ids['domain_id'],  # FK violation since domain belongs to victim
            'closed': '0',
            'sort_order': '1',
        })
        # This will likely fail with 500 due to FK constraint (domain belongs to victim)
        # So create a domain for the attacker first
        attacker_domain_resp = attacker_invoke('POST', '/darwin_dev/domains', body={
            'domain_name': 'Attacker Domain',
            'closed': '0',
        })
        assert attacker_domain_resp['statusCode'] == 200
        attacker_domain_id = extract_id(attacker_domain_resp)

        attacker_area_resp = attacker_invoke('POST', '/darwin_dev/areas', body={
            'area_name': 'Attacker Area',
            'domain_fk': attacker_domain_id,
            'closed': '0',
            'sort_order': '1',
        })
        assert attacker_area_resp['statusCode'] == 200
        attacker_area_id = extract_id(attacker_area_resp)

        # Attacker bulk PUT: own area + victim's area
        response = attacker_invoke('PUT', '/darwin_dev/areas', body=[
            {'id': attacker_area_id, 'area_name': 'Attacker Updated'},
            {'id': test_ids['area_id'], 'area_name': 'HACKED'},
        ])
        # The update should succeed for the attacker's record only
        # Due to creator_fk scoping, victim's record won't match
        assert response['statusCode'] == 200

        # Verify victim's area was NOT modified
        victim_get = invoke('GET', '/darwin_dev/areas', query={'id': test_ids['area_id']})
        victim_body = json.loads(victim_get['body'])
        assert victim_body[0]['area_name'] != 'HACKED'

        # Clean up attacker's data
        import pymysql as _pymysql
        try:
            with db_connection.cursor() as cur:
                cur.execute('DELETE FROM areas WHERE id = %s', (attacker_area_id,))
                cur.execute('DELETE FROM domains WHERE id = %s', (attacker_domain_id,))
            db_connection.commit()
        except _pymysql.MySQLError:
            db_connection.rollback()

    # -------------------------------------------------------------------
    # SEC-07: DELETE another user's domain — returns 404
    # -------------------------------------------------------------------

    def test_delete_other_users_domain_returns_404(self, attacker_invoke, attacker_profile, test_ids):
        """SEC-07: Attacker DELETE on victim's domain — returns 404 (no rows matched)."""
        response = attacker_invoke('DELETE', '/darwin_dev/domains', body={
            'id': test_ids['domain_id'],
        })
        assert response['statusCode'] == 404

    # -------------------------------------------------------------------
    # SEC-08: Request without auth context to user table — returns 403
    # -------------------------------------------------------------------

    def test_no_auth_context_returns_403(self):
        """SEC-08: Request without auth context to user table returns 403."""
        from handler import lambda_handler
        event = {
            'httpMethod': 'GET',
            'path': '/darwin_dev/areas',
            'queryStringParameters': None,
            'body': None,
            'requestContext': {},
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 403

    # -------------------------------------------------------------------
    # SEC-09: GET SHOW TABLES without auth — succeeds (no user data)
    # -------------------------------------------------------------------

    def test_show_tables_no_auth_succeeds(self):
        """SEC-09: GET /darwin_dev (SHOW TABLES) without auth succeeds."""
        from handler import lambda_handler
        event = {
            'httpMethod': 'GET',
            'path': '/darwin_dev',
            'queryStringParameters': None,
            'body': None,
            'requestContext': {},
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 200

    # -------------------------------------------------------------------
    # SEC-10: POST without auth context to user table — returns 403
    # -------------------------------------------------------------------

    def test_post_no_auth_returns_403(self):
        """SEC-10: POST without auth context to user table returns 403."""
        from handler import lambda_handler
        event = {
            'httpMethod': 'POST',
            'path': '/darwin_dev/domains',
            'queryStringParameters': None,
            'body': '{"domain_name": "Unauthed", "closed": "0"}',
            'requestContext': {},
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 403

    # -------------------------------------------------------------------
    # SEC-11: PUT without auth context to user table — returns 403
    # -------------------------------------------------------------------

    def test_put_no_auth_returns_403(self):
        """SEC-11: PUT without auth context to user table returns 403."""
        from handler import lambda_handler
        event = {
            'httpMethod': 'PUT',
            'path': '/darwin_dev/areas',
            'queryStringParameters': None,
            'body': '[{"id": "1", "area_name": "Hacked"}]',
            'requestContext': {},
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 403

    # -------------------------------------------------------------------
    # SEC-12: DELETE without auth context to user table — returns 403
    # -------------------------------------------------------------------

    def test_delete_no_auth_returns_403(self):
        """SEC-12: DELETE without auth context to user table returns 403."""
        from handler import lambda_handler
        event = {
            'httpMethod': 'DELETE',
            'path': '/darwin_dev/domains',
            'queryStringParameters': None,
            'body': '{"id": "1"}',
            'requestContext': {},
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 403

    # -------------------------------------------------------------------
    # SEC-13: GET with forged creator_fk in QSP — ignored, uses JWT
    # -------------------------------------------------------------------

    def test_get_forged_creator_fk_qsp_ignored(self, invoke, attacker_invoke, attacker_profile, creator_fk, test_ids):
        """SEC-13: GET with victim's creator_fk in QSP — attacker still sees nothing."""
        response = attacker_invoke('GET', '/darwin_dev/areas', query={
            'creator_fk': creator_fk,  # forged — should be ignored
            'id': test_ids['area_id'],
        })
        # Attacker's JWT identity is used, not the forged QSP
        assert response['statusCode'] == 404
