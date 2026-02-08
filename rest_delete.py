import pymysql
import json
from rest_api_utils import compose_rest_response
from classifier import varDump, pretty_print_sql
        
def rest_delete(delete_method, conn, table, body):
       
    if not body:
        return compose_rest_response(400, '', 'BAD REQUEST')

    # if multple key/value are provided in body default is to AND them together
    where_clause = ' AND '.join(f"{key}={value}" for key, value in body.items())
    
    try:
        sql_statement = f"""
            DELETE FROM {table} 
            WHERE
                {where_clause};
        """
        pretty_print_sql(sql_statement, delete_method)

        with conn.cursor() as cursor:
            affected_rows = cursor.execute(sql_statement)

        if affected_rows == 0:
            errorMsg = f"Affected_rows = 0, 404 time"
            print(errorMsg)
            return compose_rest_response('404', '', 'NOT FOUND')
        else:
            conn.commit()
            return compose_rest_response('200', '', 'OK')

    except pymysql.Error as e:
        errorMsg = f"HTTP {delete_method} SQL FAILED: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('500', '', errorMsg)
