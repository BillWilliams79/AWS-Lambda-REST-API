import pymysql
from json_utils import composeJsonResponse
from classifier import varDump
        
def rest_get_table(event, table, conn, getMethod):

    # STEP 1: Execute helper SQL commands: build list of columns for the SQL
    #         command and allow for larger group concat. Build a list of columns
    #         to verify correct QSP
    try:
        cursor = conn.cursor()
        cursor.execute("SET SESSION group_concat_max_len = 65536")
        cursor.execute(f""" DESC {table}; """)
        rows = cursor.fetchall()
        
        json_object_columns = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)

        sql_columns = []
        for row in rows:
            sql_columns.append(row[0])
        
    except pymysql.Error as e:
        errorMsg = f"HTTP {getMethod} helper SQL command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return composeJsonResponse('500', '', errorMsg)

    # STEP 2: iterate over query string parameters 
    where_clause = ""
    order_by = ""
    qsp = event.get('queryStringParameters')

    if qsp:
        for key, value in qsp.items():
    
            if key in sql_columns:
                where_clause = f"{where_clause} WHERE {key}='{value}'"
    
            elif key == 'sort':
                sort_dict = dict(x.split(":") for x in value.split(","))
                order_by = ', '.join(f"{sort_key} {sort_value}" for sort_key, sort_value in sort_dict.items())
                order_by = f" ORDER BY {order_by}"                
    
            else:
                # JSON API document allows api implementation to ignore an impro
                errorMsg = f"HTTP {getMethod} invalid query string parameter {key} {value}"
                print(errorMsg)
                return composeJsonResponse('400', '', "BAD REQUEST")            

    # STEP 3: execute API read and process all return values
    try:

        # read row(s) and format as JSON
        sql_statement = f"""
                            SELECT 
                                CONCAT('[',
                                    GROUP_CONCAT(
                                        JSON_OBJECT({json_object_columns})
                                        {order_by}    
                                        SEPARATOR ', ')
                                ,']')
                            FROM 
                                {table}
                            {where_clause}
        """
        
        prettySql = ' '.join(sql_statement.split())
        print(f"{getMethod} SQL statement is:")
        print(prettySql)

        cursor.execute(sql_statement)
        row = cursor.fetchall()

        if row[0][0]:
            return composeJsonResponse('200', row[0], 'OK')
        else:
            print('get: 404')
            errorMsg = f"No data"
            print(errorMsg)
            return composeJsonResponse('404',  '', 'NOT FOUND')

    except pymysql.Error as e:
        errorMsg = f"HTTP {getMethod} actual SQL select statement failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return composeJsonResponse('500', '', "errorMsg")
