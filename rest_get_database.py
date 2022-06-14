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

        # data returned as a tuple of tuples, each tuple being table name string
        #table_list = ', '.join(f"{rows[0]}" for rows in rows)

        columns_array = []
        for row in rows:
            columns_array.append(row[0])

        if columns_array:
            return composeJsonResponse('200', columns_array, 'OK')
        else:
            print('get: 404')
            errorMsg = f"No data"
            print(errorMsg)
            return composeJsonResponse('404',  '', 'NOT FOUND')

    except pymysql.Error as e:
        errorMsg = f"HTTP {getMethod} actual SQL select statement failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return composeJsonResponse('500', '', "errorMsg")
