import os
import pymysql

# DB credentials from environment
endpoint = os.environ['endpoint']
username = os.environ['username']
password = os.environ['db_password']

# Connection cache keyed by database name
connection = dict()

# pymysql error codes indicating a stale/dead connection
STALE_CONNECTION_ERRORS = (2006, 2013)


def get_connection(database):
    """Return a live connection — pings cached connection; reconnects if stale."""
    if database in connection:
        try:
            connection[database].ping(reconnect=False)
            return connection[database]
        except Exception:
            return reconnect(database)
    connection[database] = pymysql.connect(
        host=endpoint, user=username, password=password, database=database,
        connect_timeout=3, read_timeout=3, write_timeout=3)
    return connection[database]


def reconnect(database):
    """Close the stale connection and create a fresh one."""
    if database in connection:
        try:
            connection[database].close()
        except Exception:
            pass
        del connection[database]
    return get_connection(database)


def _is_connection_error(exc):
    """Return True if the exception indicates a dead/stale connection worth retrying."""
    if isinstance(exc, pymysql.InterfaceError):
        return True
    if isinstance(exc, pymysql.OperationalError) and exc.args[0] in STALE_CONNECTION_ERRORS:
        return True
    return False


def with_retry(conn, database, operation):
    """Execute operation(conn). On stale connection error, reconnect and retry once.

    Returns (result, conn) — conn may be a new connection after retry.
    """
    try:
        result = operation(conn)
        return result, conn
    except pymysql.Error as e:
        if not _is_connection_error(e):
            raise
        print(f"Connection error ({type(e).__name__} {e.args[0]}), reconnecting...")
        conn = reconnect(database)
        result = operation(conn)
        return result, conn
