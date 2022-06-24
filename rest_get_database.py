import json
import pymysql
from json_utils import composeJsonResponse
from classifier import varDump
        
def rest_get_database(event, database, conn, getMethod):

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
            return composeJsonResponse('200', json.dumps(columns_array), 'OK')
        else:
            print('HTTP GET: show tables command failed')
            return composeJsonResponse('404',  '', 'NOT FOUND')

    except pymysql.Error as e:
        errorMsg = f"HHTTP GET: show tables command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return composeJsonResponse('500', '', "errorMsg")
