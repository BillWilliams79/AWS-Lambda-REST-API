import pymysql
import json
from rest_api_utils import compose_rest_response
from classifier import varDump, pretty_print_sql
        
def rest_post(post_method, conn, table, body):

    # POST - Update one Row
    if not body:
        return compose_rest_response(400, '', 'BAD REQUEST')

    id = body.get('id', '')
    body.pop('id')
    
    sql_kv_string = ', '.join(f"{key} = '{value}'" for key, value in body.items())

    # NULL handling: mySQL requires no quotes around NULL values
    sql_kv_string = sql_kv_string.replace("'NULL'", "NULL")

    try:
        sql_statement = f"""
            UPDATE {table}
            SET 
                {sql_kv_string}
            WHERE
                id = {id};
        """
        pretty_print_sql(sql_statement, post_method)

        cursor = conn.cursor()
        affected_rows = cursor.execute(sql_statement)
        if affected_rows > 0:
            conn.commit()
            return compose_rest_response('200', '', 'OK')
        else:
            errorMsg = f"HTTP {post_method}: NO DATA CHANGED"
            print(errorMsg)
            return compose_rest_response('204', 'NO DATA CHANGED', 'NO DATA CHANGED')

    except pymysql.Error as e:
        errorMsg = f"HTTP {post_method} SQL FAILED: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('500', {'error': errorMsg})
