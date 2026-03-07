import json
import pymysql
from rest_api_utils import compose_rest_response
from classifier import varDump
from db_connection import with_retry

def rest_get_database(get_method, conn, database):

    # rest api GET executed against the database returns a list of tables in the database
    try:

        sql_statement = f"""SHOW tables"""

        def execute_show_tables(c):
            with c.cursor() as cursor:
                cursor.execute(sql_statement)
                return cursor.fetchall()

        rows, conn = with_retry(conn, database, execute_show_tables)

        columns_array = []
        for row in rows:
            columns_array.append(row[0])

        if columns_array:
            return compose_rest_response(200, columns_array, 'OK')
        else:
            print(f'HTTP {get_method}: show tables command failed')
            return compose_rest_response(404,  '', 'NOT FOUND')

    except pymysql.Error as e:
        errorMsg = f"HTTP {get_method}: show tables command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response(500, '', errorMsg)
