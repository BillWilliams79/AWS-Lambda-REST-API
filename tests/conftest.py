"""
Lambda-Rest pytest shared fixtures.

Provides DB connection, API Gateway event builder, test data isolation,
and automatic cleanup. All tests use darwin_dev test database.
"""
import sys
import os
import json
import time
import uuid

import pytest

# Add Lambda-Rest root to path so we can import handler, etc.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# handler.py reads env vars at module scope. Guard the import so unit tests
# (which don't need lambda_handler) can run without exports.sh.
try:
    from handler import lambda_handler
except KeyError:
    lambda_handler = None


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def _has_db_env_vars():
    """Check if database environment variables are available."""
    return all(k in os.environ for k in ('endpoint', 'username', 'db_password'))


@pytest.fixture(scope="session")
def db_connection():
    """Shared pymysql connection to darwin_dev test database.

    Skips if env vars not set (allows unit tests to run without exports.sh).
    """
    if not _has_db_env_vars():
        pytest.skip("Database env vars not set (run . exports.sh for integration tests)")
    import pymysql
    conn = pymysql.connect(
        host=os.environ['endpoint'],
        user=os.environ['username'],
        password=os.environ['db_password'],
        database='darwin_dev',
        cursorclass=pymysql.cursors.DictCursor,
    )
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Test data isolation
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def creator_fk():
    """Unique creator_fk per test session for data isolation."""
    return f"pytest-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="session")
def test_ids():
    """Mutable dict to share IDs between setup and tests within a session."""
    return {}


# ---------------------------------------------------------------------------
# Lambda event builder
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def invoke():
    """Factory that builds an API Gateway event and invokes lambda_handler.

    Usage:
        response = invoke('GET', '/darwin_dev/areas', query={'id': '1'})
        response = invoke('POST', '/darwin_dev/areas', body={...})

    Skips if lambda_handler not available (unit test mode without exports.sh).
    """
    if lambda_handler is None:
        pytest.skip("lambda_handler not available (run . exports.sh for integration tests)")
    def _invoke(method, path, query=None, body=None):
        event = {
            'httpMethod': method,
            'path': path,
            'queryStringParameters': query,
            'body': json.dumps(body) if body is not None else None,
        }
        return lambda_handler(event, {})
    return _invoke


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def extract_id(response):
    """Extract record id from a POST response body."""
    if response and 'body' in response:
        body = json.loads(response['body'])
        if isinstance(body, list) and len(body) > 0 and 'id' in body[0]:
            return str(body[0]['id'])
    return None


# ---------------------------------------------------------------------------
# Test data setup & cleanup
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def test_data(request, creator_fk, test_ids):
    """Create isolated test hierarchy: profile → domain → area → task.

    Yields test_ids dict with keys: profile_id, domain_id, area_id, task_id.
    Cleans up ALL test data by creator_fk after session.
    Skips setup/teardown when DB env vars are not available (unit test mode).
    """
    if not _has_db_env_vars():
        yield test_ids
        return

    invoke = request.getfixturevalue('invoke')
    db_connection = request.getfixturevalue('db_connection')
    # Create profile
    invoke('POST', '/darwin_dev/profiles', body={
        'id': creator_fk,
        'name': 'pytest User',
        'email': 'pytest@test.com',
        'subject': creator_fk,
        'userName': creator_fk,
        'region': 'us-west-1',
        'userPoolId': 'test-pool',
    })
    test_ids['profile_id'] = creator_fk

    # Create domain
    resp = invoke('POST', '/darwin_dev/domains', body={
        'domain_name': 'pytest Domain',
        'creator_fk': creator_fk,
        'closed': '0',
    })
    test_ids['domain_id'] = extract_id(resp)

    # Create area
    resp = invoke('POST', '/darwin_dev/areas', body={
        'area_name': 'pytest Area',
        'creator_fk': creator_fk,
        'domain_fk': test_ids['domain_id'],
        'closed': '0',
        'sort_order': '1',
    })
    test_ids['area_id'] = extract_id(resp)

    # Create task
    resp = invoke('POST', '/darwin_dev/tasks', body={
        'priority': '0',
        'done': '0',
        'description': 'pytest Task',
        'area_fk': test_ids['area_id'],
        'creator_fk': creator_fk,
    })
    test_ids['task_id'] = extract_id(resp)

    yield test_ids

    # Cleanup: delete all test data by creator_fk (order matters for FK constraints)
    import pymysql as _pymysql
    try:
        with db_connection.cursor() as cur:
            cur.execute('DELETE FROM tasks WHERE creator_fk = %s', (creator_fk,))
            cur.execute('DELETE FROM areas WHERE creator_fk = %s', (creator_fk,))
            cur.execute('DELETE FROM domains WHERE creator_fk = %s', (creator_fk,))
            cur.execute('DELETE FROM profiles WHERE id = %s', (creator_fk,))
        db_connection.commit()
    except _pymysql.MySQLError:
        db_connection.rollback()
