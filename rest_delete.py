import pymysql
import json
from rest_api_utils import compose_rest_response
from classifier import varDump, pretty_print_sql
from auth_utils import CREATOR_FK_TABLES, PROFILE_TABLE

def rest_delete(delete_method, conn, table, body, authenticated_user=None):
       
    if not body:
        return compose_rest_response(400, '', 'BAD REQUEST')

    # if multple key/value are provided in body default is to AND them together
    keys = list(body.keys())
    values = list(body.values())
    where_clause = ' AND '.join(f"{key} = %s" for key in keys)

    # Add creator_fk scoping for user-owned tables
    if authenticated_user is not None:
        if table in CREATOR_FK_TABLES:
            where_clause += ' AND creator_fk = %s'
            values.append(authenticated_user)
        elif table == PROFILE_TABLE:
            where_clause += ' AND id = %s'
            values.append(authenticated_user)

    try:
        sql_statement = f"""
            DELETE FROM {table}
            WHERE
                {where_clause};
        """
        pretty_print_sql(sql_statement, delete_method)

        with conn.cursor() as cursor:
            affected_rows = cursor.execute(sql_statement, tuple(values))

        if affected_rows == 0:
            errorMsg = f"Affected_rows = 0, 404 time"
            print(errorMsg)
            return compose_rest_response(404, '', 'NOT FOUND')
        else:
            conn.commit()
            return compose_rest_response(200, '', 'OK')

    except pymysql.Error as e:
        errorMsg = f"HTTP {delete_method} SQL FAILED: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response(500, '', errorMsg)
