"""
Unit tests for db_connection.py — connection caching, reconnect, and with_retry.

Run: pytest tests/test_unit_db_connection.py -v
"""
import os
import sys
from unittest.mock import patch, MagicMock, call

import pymysql
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
    import db_connection
    from db_connection import get_connection, reconnect, with_retry, STALE_CONNECTION_ERRORS

pytestmark = pytest.mark.unit


# ===========================================================================
# with_retry() tests
# ===========================================================================

class TestWithRetry:
    """Tests for the with_retry() helper."""

    def test_happy_path_returns_result(self):
        """Operation succeeds on first try — returns result and same conn."""
        conn = MagicMock()
        result, returned_conn = with_retry(conn, 'darwin_dev', lambda c: 42)
        assert result == 42
        assert returned_conn is conn

    def test_retry_on_error_2006(self):
        """Error 2006 (server gone away) triggers reconnect and retry."""
        old_conn = MagicMock()
        new_conn = MagicMock()
        call_count = 0

        def operation(c):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise pymysql.OperationalError(2006, 'MySQL server has gone away')
            return 'success'

        with patch('db_connection.reconnect', return_value=new_conn) as mock_reconnect:
            result, returned_conn = with_retry(old_conn, 'darwin_dev', operation)

        assert result == 'success'
        assert returned_conn is new_conn
        mock_reconnect.assert_called_once_with('darwin_dev')

    def test_retry_on_error_2013(self):
        """Error 2013 (lost connection during query) triggers reconnect and retry."""
        old_conn = MagicMock()
        new_conn = MagicMock()
        call_count = 0

        def operation(c):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise pymysql.OperationalError(2013, 'Lost connection to MySQL server during query')
            return 'retry_success'

        with patch('db_connection.reconnect', return_value=new_conn) as mock_reconnect:
            result, returned_conn = with_retry(old_conn, 'darwin_dev', operation)

        assert result == 'retry_success'
        assert returned_conn is new_conn
        mock_reconnect.assert_called_once_with('darwin_dev')

    def test_returns_new_conn_after_retry(self):
        """After retry, the returned conn is the fresh connection from reconnect."""
        old_conn = MagicMock(name='old')
        new_conn = MagicMock(name='new')
        call_count = 0

        def operation(c):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise pymysql.OperationalError(2006, 'MySQL server has gone away')
            # Verify retry receives the new connection
            assert c is new_conn
            return 'ok'

        with patch('db_connection.reconnect', return_value=new_conn):
            result, returned_conn = with_retry(old_conn, 'darwin_dev', operation)

        assert returned_conn is new_conn

    def test_no_retry_on_non_stale_operational_error(self):
        """Non-stale OperationalError (e.g. 1045 access denied) propagates immediately."""
        conn = MagicMock()

        def operation(c):
            raise pymysql.OperationalError(1045, 'Access denied')

        with pytest.raises(pymysql.OperationalError) as exc_info:
            with_retry(conn, 'darwin_dev', operation)

        assert exc_info.value.args[0] == 1045

    def test_retry_on_interface_error(self):
        """InterfaceError(0, '') from broken connection triggers reconnect and retry."""
        old_conn = MagicMock()
        new_conn = MagicMock()
        call_count = 0

        def operation(c):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise pymysql.InterfaceError(0, '')
            return 'recovered'

        with patch('db_connection.reconnect', return_value=new_conn) as mock_reconnect:
            result, returned_conn = with_retry(old_conn, 'darwin_dev', operation)

        assert result == 'recovered'
        assert returned_conn is new_conn
        mock_reconnect.assert_called_once_with('darwin_dev')

    def test_propagates_error_when_interface_retry_also_fails(self):
        """If InterfaceError retry also fails, the second error propagates."""
        conn = MagicMock()
        new_conn = MagicMock()

        def operation(c):
            raise pymysql.InterfaceError(0, '')

        with patch('db_connection.reconnect', return_value=new_conn):
            with pytest.raises(pymysql.InterfaceError):
                with_retry(conn, 'darwin_dev', operation)

    def test_propagates_non_operational_error(self):
        """Non-OperationalError (e.g. ProgrammingError) propagates without retry."""
        conn = MagicMock()

        def operation(c):
            raise pymysql.ProgrammingError(1064, 'You have an error in your SQL syntax')

        with pytest.raises(pymysql.ProgrammingError):
            with_retry(conn, 'darwin_dev', operation)

    def test_propagates_error_when_retry_also_fails(self):
        """If the retry also fails, the second error propagates."""
        conn = MagicMock()
        new_conn = MagicMock()

        def operation(c):
            raise pymysql.OperationalError(2006, 'MySQL server has gone away')

        with patch('db_connection.reconnect', return_value=new_conn):
            with pytest.raises(pymysql.OperationalError) as exc_info:
                with_retry(conn, 'darwin_dev', operation)

        assert exc_info.value.args[0] == 2006


# ===========================================================================
# reconnect() tests
# ===========================================================================

class TestReconnect:
    """Tests for the reconnect() helper."""

    @patch('db_connection.pymysql.connect')
    def test_closes_old_and_creates_new(self, mock_connect):
        """reconnect() closes the stale connection and returns a fresh one."""
        old_conn = MagicMock()
        new_conn = MagicMock()
        mock_connect.return_value = new_conn

        saved = db_connection.connection.copy()
        db_connection.connection['test_db'] = old_conn
        try:
            result = reconnect('test_db')
            old_conn.close.assert_called_once()
            assert result is new_conn
            assert db_connection.connection['test_db'] is new_conn
        finally:
            db_connection.connection = saved

    @patch('db_connection.pymysql.connect')
    def test_handles_close_failure(self, mock_connect):
        """reconnect() still creates a new connection even if close() raises."""
        old_conn = MagicMock()
        old_conn.close.side_effect = Exception('already closed')
        new_conn = MagicMock()
        mock_connect.return_value = new_conn

        saved = db_connection.connection.copy()
        db_connection.connection['test_db'] = old_conn
        try:
            result = reconnect('test_db')
            assert result is new_conn
        finally:
            db_connection.connection = saved


# ===========================================================================
# get_connection() tests
# ===========================================================================

class TestGetConnection:
    """Tests for the get_connection() caching behavior."""

    @patch('db_connection.pymysql.connect')
    def test_caches_connection(self, mock_connect):
        """Second call returns cached connection without calling pymysql.connect again."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        saved = db_connection.connection.copy()
        db_connection.connection.clear()
        try:
            conn1 = get_connection('cache_test_db')
            conn2 = get_connection('cache_test_db')
            assert conn1 is conn2
            mock_connect.assert_called_once()
        finally:
            db_connection.connection = saved

    @patch('db_connection.pymysql.connect')
    def test_creates_new_connection(self, mock_connect):
        """First call creates a connection via pymysql.connect."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        saved = db_connection.connection.copy()
        db_connection.connection.clear()
        try:
            result = get_connection('new_db')
            assert result is mock_conn
            mock_connect.assert_called_once()
        finally:
            db_connection.connection = saved

    @patch('db_connection.pymysql.connect')
    def test_ping_called_on_healthy_cached_connection(self, mock_connect):
        """Healthy cached connection: ping is called, same conn returned, no reconnect."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        saved = db_connection.connection.copy()
        db_connection.connection['ping_test_db'] = mock_conn
        try:
            result = get_connection('ping_test_db')
            mock_conn.ping.assert_called_once_with(reconnect=False)
            assert result is mock_conn
            mock_connect.assert_not_called()  # no new connection created
        finally:
            db_connection.connection = saved

    @patch('db_connection.pymysql.connect')
    def test_reconnects_when_ping_fails(self, mock_connect):
        """Stale cached connection: ping raises, reconnect called, new conn returned."""
        stale_conn = MagicMock()
        stale_conn.ping.side_effect = Exception('Connection closed')
        new_conn = MagicMock()
        mock_connect.return_value = new_conn
        saved = db_connection.connection.copy()
        db_connection.connection['stale_db'] = stale_conn
        try:
            result = get_connection('stale_db')
            stale_conn.ping.assert_called_once_with(reconnect=False)
            assert result is new_conn
        finally:
            db_connection.connection = saved
