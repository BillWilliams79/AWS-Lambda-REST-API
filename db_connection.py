import os
import pymysql

# DB credentials from environment
endpoint = os.environ['endpoint']
username = os.environ['username']
password = os.environ['db_password']


def get_connection(database):
    """Return a fresh DB connection for this invocation.

    New connection per invocation — eliminates stale connection and zombie
    transaction bugs entirely. Within-VPC connect time is ~5-15ms, negligible
    vs Lambda cold start and network RTT.
    """
    return pymysql.connect(
        host=endpoint,
        user=username,
        password=password,
        database=database,
        autocommit=True,
        connect_timeout=5,
        read_timeout=15,
        write_timeout=15,
    )
