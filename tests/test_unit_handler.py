"""
Unit tests for handler.py pure logic — no database required.

Tests cover SAFE_NAME_RE regex, parse_path() logic, and
rest_api_from_table() routing. Uses mocked env vars and connections.

Run: pytest tests/test_unit_handler.py -v
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Add Lambda-Rest root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# handler.py reads env vars at module scope (lines 25-28).
# We must set them BEFORE importing handler.
_MOCK_ENV = {
    'endpoint': 'localhost',
    'username': 'test_user',
    'db_password': 'test_pass',
    'db_name': 'darwin2',
}

with patch.dict(os.environ, _MOCK_ENV):
    from handler import SAFE_NAME_RE, parse_path, rest_api_from_table
    from rest_api_utils import compose_rest_response


pytestmark = pytest.mark.unit

_SENTINEL = object()


# ===========================================================================
# SAFE_NAME_RE tests
# ===========================================================================

class TestSafeNameRegex:
    """Tests for the SAFE_NAME_RE table name validation regex."""

    def test_valid_simple_name(self):
        assert SAFE_NAME_RE.match('profiles2')

    def test_valid_underscore_prefix(self):
        assert SAFE_NAME_RE.match('_private_table')

    def test_valid_mixed_case(self):
        assert SAFE_NAME_RE.match('MyTable_123')

    def test_rejects_sql_injection(self):
        """Table name with semicolon should be rejected."""
        assert SAFE_NAME_RE.match('tasks; DROP TABLE tasks') is None

    def test_rejects_number_prefix(self):
        """Table names cannot start with a digit."""
        assert SAFE_NAME_RE.match('2tables') is None

    def test_rejects_empty_string(self):
        assert SAFE_NAME_RE.match('') is None

    def test_rejects_spaces(self):
        assert SAFE_NAME_RE.match('my table') is None

    def test_rejects_special_chars(self):
        assert SAFE_NAME_RE.match('table-name') is None


# ===========================================================================
# parse_path() tests
# ===========================================================================

class TestParsePath:
    """Tests for parse_path() URL path parsing."""

    @patch('handler.get_connection')
    def test_valid_database_and_table(self, mock_conn):
        """Standard path /darwin2/areas2 extracts both parts."""
        mock_conn.return_value = MagicMock()
        result = parse_path('/darwin2/areas2')
        assert result['database'] == 'darwin2'
        assert result['table'] == 'areas2'
        assert result['conn'] is not None

    @patch('handler.get_connection')
    def test_database_only_path(self, mock_conn):
        """Path with database only — table is empty string."""
        mock_conn.return_value = MagicMock()
        result = parse_path('/darwin2')
        assert result['database'] == 'darwin2'
        assert result['table'] == ''

    def test_invalid_table_name_returns_error(self):
        """Invalid table name returns error in result dict."""
        result = parse_path('/darwin2/bad;name')
        assert 'error' in result
        assert 'Invalid table name' in result['error']

    def test_unknown_database_returns_empty_conn(self):
        """Unknown database name returns empty string for conn."""
        result = parse_path('/unknown_db/table')
        assert result['database'] == 'unknown_db'
        assert result['conn'] == ''

    @patch('handler.get_connection')
    def test_deep_path_ignores_extra_segments(self, mock_conn):
        """Path with 3+ segments still extracts first two."""
        mock_conn.return_value = MagicMock()
        result = parse_path('/darwin2/areas2/extra/deep')
        assert result['database'] == 'darwin2'
        assert result['table'] == 'areas2'


# ===========================================================================
# rest_api_from_table() routing tests
# ===========================================================================

class TestRestApiFromTable:
    """Tests for HTTP method routing in rest_api_from_table()."""

    def _make_event(self, method='GET', body=None, path='/darwin2/areas2'):
        return {
            'httpMethod': method,
            'path': path,
            'queryStringParameters': None,
            'body': json.dumps(body) if body is not None else None,
        }

    def _make_db_info(self, conn=_SENTINEL):
        return {
            'database': 'darwin2',
            'table': 'areas2',
            'conn': MagicMock() if conn is _SENTINEL else conn,
            'path': '/darwin2/areas2',
        }

    def test_no_connection_returns_500(self):
        """Empty conn string triggers 500 response."""
        event = self._make_event()
        db_info = self._make_db_info(conn='')
        response = rest_api_from_table(event, db_info)
        assert response['statusCode'] == 500
        assert 'no database connection' in json.loads(response['body']).lower()

    def test_options_returns_200(self):
        """OPTIONS method returns 200 directly (CORS preflight)."""
        event = self._make_event(method='OPTIONS')
        db_info = self._make_db_info()
        response = rest_api_from_table(event, db_info)
        assert response['statusCode'] == 200
