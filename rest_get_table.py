import pymysql
from json_utils import composeJsonResponse
from classifier import varDump, pretty_print_sql
        
def rest_get_table(event, table, conn, getMethod):

    # STEP 1: Execute helper SQL commands: build list of columns for the SQL
    #         command and allow for larger group concat. Build a list of columns
    #         to verify correct QSP
    try:
        cursor = conn.cursor()
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
    where_clause = "WHERE"
    where_connector = ""
    where_count = 0
    order_by = ""
    qsp = event.get('queryStringParameters')

    if qsp:
        for key, value in qsp.items():
    
            if key in sql_columns:
                where_count = where_count + 1
                where_clause = f"{where_clause}{where_connector} {key}='{value}'"
                where_connector = " AND"
    
            elif key == 'sort':
                sort_dict = dict(x.split(":") for x in value.split(","))
                order_by = ', '.join(f"{sort_key} {sort_value}" for sort_key, sort_value in sort_dict.items())
                order_by = f" ORDER BY {order_by}"                
    
            else:
                # JSON API document allows api implementation to ignore an improperly formed request
                errorMsg = f"HTTP {getMethod} invalid query string parameter {key} {value}"
                print(errorMsg)
                return composeJsonResponse('400', '', "BAD REQUEST")
    
    # zero out where clause if there were no QSPs
    if where_count == 0:
        where_clause = ""

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
        pretty_print_sql(sql_statement, getMethod)
        
        cursor.execute(sql_statement)
        row = cursor.fetchall()

        varDump(row, 'row data from read table')

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