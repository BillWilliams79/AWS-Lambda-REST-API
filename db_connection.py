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
    """Return a cached connection or create a new one. No ping — callers use with_retry."""
    if database in connection:
        return connection[database]
    connection[database] = pymysql.connect(
        host=endpoint, user=username, password=password, database=database,
        connect_timeout=3, read_timeout=8, write_timeout=5)
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


def with_retry(conn, database, operation):
    """Execute operation(conn). On stale connection error, reconnect and retry once.

    Returns (result, conn) — conn may be a new connection after retry.
    """
    try:
        result = operation(conn)
        return result, conn
    except pymysql.OperationalError as e:
        if e.args[0] in STALE_CONNECTION_ERRORS:
            print(f"Stale connection detected (error {e.args[0]}), reconnecting...")
            conn = reconnect(database)
            result = operation(conn)
            return result, conn
        raise
