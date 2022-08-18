import json
import pymysql
from rest_api_utils import compose_rest_response
from classifier import varDump
        
def rest_get_database(get_method, conn, database):

    # rest api GET executed against the database returns a list of tables in the database
    try:

        sql_statement = f"""SHOW tables"""

        cursor = conn.cursor()
        cursor.execute(sql_statement)
        rows = cursor.fetchall()

        columns_array = []
        for row in rows:
            columns_array.append(row[0])

        if columns_array:
            return compose_rest_response('200', json.dumps(columns_array), 'OK')
        else:
            print('HTTP {get_method}: show tables command failed')
            return compose_rest_response('404',  '', 'NOT FOUND')

    except pymysql.Error as e:
        errorMsg = f"HTTP {get_method}: show tables command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('500', '', "errorMsg")
