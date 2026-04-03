import pymysql
import json
from rest_api_utils import compose_rest_response
from classifier import varDump, pretty_print_sql
from auth_utils import CREATOR_FK_TABLES, PROFILE_TABLE

def rest_post(post_method, conn, database, table, body, authenticated_user=None):

    if not body:
        return compose_rest_response(400, '', 'BAD REQUEST')

    # Bulk POST: if body is a list, insert each item and return count
    if isinstance(body, list):
        return _rest_post_bulk(post_method, conn, table, body, authenticated_user)

    # Override creator_fk with authenticated user from JWT
    if authenticated_user is not None:
        if table in CREATOR_FK_TABLES:
            body['creator_fk'] = authenticated_user
        elif table == PROFILE_TABLE:
            body['id'] = authenticated_user

    varDump(body, 'body inside rest_post')
    # Assemble list of keys and values for use in SQL
    keys = list(body.keys())
    values = [None if v == "NULL" else v for v in body.values()]

    sql_key_list = ', '.join(keys)
    placeholders = ', '.join(['%s'] * len(values))

    try:
        # insert row into table
        sql_statement = f"""
                    INSERT INTO {table} ({sql_key_list})
                    VALUES ({placeholders});
        """
        pretty_print_sql(sql_statement, post_method)

        with conn.cursor() as cursor:
            affected_post_rows = cursor.execute(sql_statement, tuple(values))

        if affected_post_rows > 0:
            pass
        else:
            errorMsg = f"HTTP {post_method} failed no rows affected"
            print(errorMsg)
            return compose_rest_response(500, '', "NO DATA SAVED")

    except pymysql.Error as e:
        errorMsg = f"HTTP {post_method} failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response(500, '', errorMsg)

    try:
        # retrieve ID of newly created row
        sql_statement= f"""SELECT LAST_INSERT_ID()"""
        with conn.cursor() as cursor:
            affected_rows = cursor.execute(sql_statement)

            if affected_rows > 0:
                newId = cursor.fetchone()
            else:
                print(f"HTTP {post_method} FAILED to read last_insert_id.")
                return compose_rest_response(201, '', 'CREATED')

    except pymysql.Error as e:
        print(f"HTTP {post_method} FAILED to read last_insert_id: {e.args[0]} {e.args[1]}")
        return compose_rest_response(201, '', 'CREATED')

    try:
        # retrieve table description and create json object and sql columns
        with conn.cursor() as cursor:
            cursor.execute(f""" DESC {table}; """)
            rows = cursor.fetchall()

        json_object_columns = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)

        sql_columns = []
        for row in rows:
            sql_columns.append(row[0])
        
    except pymysql.Error as e:
        errorMsg = f"HTTP {post_method} helper DESC SQL command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response(201, '', 'CREATED')

    try:
        # read row(s) and format as JSON
        sql_statement = f"""SELECT
                                CONCAT('[',
                                    GROUP_CONCAT(
                                        JSON_OBJECT({json_object_columns})
                                        SEPARATOR ', ')
                                ,']')
                            FROM
                                {table}
                            WHERE id={newId[0]}
        """
        pretty_print_sql(sql_statement, post_method)

        with conn.cursor() as cursor:
            cursor.execute(sql_statement)
            row = cursor.fetchall()

        #varDump(row, 'row data from read table AFTER post')

        if row[0][0]:
            return compose_rest_response(200, json.loads(row[0][0]), 'CREATED')
        else:
            print(f"HTTP {post_method} helper SELECT after WRITE SQL command failed")
            return compose_rest_response(201, '', 'CREATED')

    except pymysql.Error as e:
        errorMsg = f"HTTP {post_method} helper SELECT after WRITE SQL command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response(500, '', errorMsg)

    return compose_rest_response(500, '', 'INVALID PATH')


def _rest_post_bulk(post_method, conn, table, body_list, authenticated_user):
    """Insert multiple rows via single multi-value INSERT. Returns 201 with inserted count and first_id."""

    if not body_list:
        return compose_rest_response(400, '', 'BAD REQUEST')

    # Override creator_fk on each item before building SQL
    if authenticated_user is not None and table in CREATOR_FK_TABLES:
        for item in body_list:
            item['creator_fk'] = authenticated_user

    # All items must have the same keys (same columns)
    keys = list(body_list[0].keys())
    sql_key_list = ', '.join(keys)
    row_placeholder = '(' + ', '.join(['%s'] * len(keys)) + ')'

    # Flatten all values into a single tuple for one execute call
    all_values = []
    for item in body_list:
        all_values.extend(None if v == "NULL" else v for v in (item[k] for k in keys))

    placeholders = ', '.join([row_placeholder] * len(body_list))
    sql_statement = f"INSERT INTO {table} ({sql_key_list}) VALUES {placeholders}"
    pretty_print_sql(sql_statement, post_method)

    try:
        with conn.cursor() as cursor:
            cursor.execute(sql_statement, tuple(all_values))

        # Retrieve first auto-increment ID from the multi-row INSERT.
        # MySQL guarantees consecutive IDs for a single multi-value INSERT statement.
        result = {"inserted": len(body_list)}
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT LAST_INSERT_ID()")
                row = cursor.fetchone()
                if row and row[0]:
                    result["first_id"] = row[0]
        except pymysql.Error:
            pass  # Non-fatal: callers can fall back to individual inserts

        return compose_rest_response(201, result, 'CREATED')

    except pymysql.Error as e:
        conn.rollback()
        errorMsg = f"HTTP {post_method} bulk failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response(500, '', errorMsg)