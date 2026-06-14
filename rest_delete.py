import pymysql
import json
from rest_api_utils import compose_rest_response
from classifier import varDump, pretty_print_sql
from auth_utils import CREATOR_FK_TABLES, PROFILE_TABLE

def rest_delete(delete_method, conn, database, table, body, authenticated_user=None):
       
    if not body:
        return compose_rest_response(400, '', 'BAD REQUEST')

    # Bulk DELETE: if body is a list, delete by id IN (...) — mirror rest_post bulk path
    if isinstance(body, list):
        return _rest_delete_bulk(delete_method, conn, table, body, authenticated_user)

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
            return compose_rest_response(200, '', 'OK')

    except pymysql.Error as e:
        errorMsg = f"HTTP {delete_method} SQL FAILED: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response(500, '', errorMsg)


def _rest_delete_bulk(delete_method, conn, table, body_list, authenticated_user):
    """Delete multiple rows via single DELETE ... WHERE id IN (...). Returns 200 / 404.

    Each item in body_list must carry an 'id'. Mirrors the array-body bulk path in
    rest_post.py — one round trip regardless of row count. Applies creator_fk scoping
    for user-owned tables exactly as the single-object delete above.
    """

    if not body_list:
        return compose_rest_response(400, '', 'BAD REQUEST')

    # Every item must supply an 'id' — malformed bulk body is a client error
    try:
        ids = [item['id'] for item in body_list]
    except (KeyError, TypeError):
        return compose_rest_response(400, '', 'BAD REQUEST')

    placeholders = ', '.join(['%s'] * len(ids))
    where_clause = f"id IN ({placeholders})"
    values = list(ids)

    # Add creator_fk scoping for user-owned tables (same policy as single-object delete)
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
            print(f"Bulk DELETE affected_rows = 0, 404 time")
            return compose_rest_response(404, '', 'NOT FOUND')
        else:
            return compose_rest_response(200, '', 'OK')

    except pymysql.Error as e:
        conn.rollback()
        errorMsg = f"HTTP {delete_method} bulk SQL FAILED: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response(500, '', errorMsg)
