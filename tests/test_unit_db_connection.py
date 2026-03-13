"""
Unit tests for db_connection.py — fresh connection per invocation.

Run: pytest tests/test_unit_db_connection.py -v
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Add Lambda-Rest root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

_MOCK_ENV = {
    'endpoint': 'localhost',
    'username': 'test_user',
    'db_password': 'test_pass',
    'db_name': 'darwin_dev',
}

with patch.dict(os.environ, _MOCK_ENV):
    from db_connection import get_connection

pytestmark = pytest.mark.unit


class TestGetConnection:
    """Tests for get_connection() — fresh connection per invocation."""

    @patch('db_connection.pymysql.connect')
    def test_returns_new_connection_each_call(self, mock_connect):
        """Each call creates a fresh connection — no caching."""
        conn_a = MagicMock(name='conn_a')
        conn_b = MagicMock(name='conn_b')
        mock_connect.side_effect = [conn_a, conn_b]

        result1 = get_connection('darwin_dev')
        result2 = get_connection('darwin_dev')

        assert result1 is conn_a
        assert result2 is conn_b
        assert mock_connect.call_count == 2

    @patch('db_connection.pymysql.connect')
    def test_autocommit_true(self, mock_connect):
        """Connection is created with autocommit=True."""
        mock_connect.return_value = MagicMock()
        get_connection('darwin_dev')
        _, kwargs = mock_connect.call_args
        assert kwargs.get('autocommit') is True

    @patch('db_connection.pymysql.connect')
    def test_connect_timeout(self, mock_connect):
        """Connection is created with connect_timeout=5."""
        mock_connect.return_value = MagicMock()
        get_connection('darwin_dev')
        _, kwargs = mock_connect.call_args
        assert kwargs.get('connect_timeout') == 5

    @patch('db_connection.pymysql.connect')
    def test_read_write_timeout(self, mock_connect):
        """Connection is created with read_timeout=15 and write_timeout=15."""
        mock_connect.return_value = MagicMock()
        get_connection('darwin_dev')
        _, kwargs = mock_connect.call_args
        assert kwargs.get('read_timeout') == 15
        assert kwargs.get('write_timeout') == 15

    @patch('db_connection.pymysql.connect')
    def test_passes_database_name(self, mock_connect):
        """Database name is passed correctly."""
        mock_connect.return_value = MagicMock()
        get_connection('darwin_dev')
        _, kwargs = mock_connect.call_args
        assert kwargs.get('database') == 'darwin_dev'

    @patch('db_connection.pymysql.connect')
    @patch('db_connection.endpoint', 'localhost')
    @patch('db_connection.username', 'test_user')
    @patch('db_connection.password', 'test_pass')
    def test_uses_env_credentials(self, mock_connect):
        """Credentials from module-level vars (sourced from env) are passed to pymysql.connect."""
        mock_connect.return_value = MagicMock()
        get_connection('darwin')
        _, kwargs = mock_connect.call_args
        assert kwargs.get('host') == 'localhost'
        assert kwargs.get('user') == 'test_user'
        assert kwargs.get('password') == 'test_pass'
