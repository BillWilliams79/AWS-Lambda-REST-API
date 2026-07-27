import pymysql
import json
from rest_api_utils import (compose_rest_response, compose_conflict_response,
                            error_detail, integrity_errno)
from classifier import varDump, pretty_print_sql
from auth_utils import CREATOR_FK_TABLES, PROFILE_TABLE, junction_scope_clause

def _unknown_columns(conn, table, keys):
    """The body keys that are not real columns on `table`.

    A DELETE body's key becomes a SQL identifier, so this is the boundary between
    a filter and an injection — see the call site for the payload it stops.

    Raises `pymysql.Error` rather than swallowing it, and is called from INSIDE
    the statement's own try block for that reason: a failed `DESC` means the
    database is unreachable, not that the caller sent a bad key, and answering
    400 there would tell the client to fix a request that was fine
    (`tests/test_unit_error_detail_wiring.py` holds this to a 500).
    """
    with conn.cursor() as cursor:
        cursor.execute(f""" DESC {table}; """)
        columns = {row[0] for row in cursor.fetchall()}
    return [key for key in keys if key not in columns]


def rest_delete(delete_method, conn, database, table, body, authenticated_user=None):
       
    if not body:
        return compose_rest_response(400, '', 'BAD REQUEST')

    # Bulk DELETE: if body is a list, delete by id IN (...) — mirror rest_post bulk path
    if isinstance(body, list):
        return _rest_delete_bulk(delete_method, conn, table, body, authenticated_user)

    # if multple key/value are provided in body default is to AND them together
    keys = list(body.keys())
    values = list(body.values())

    try:
        # Every key is interpolated straight into the WHERE clause, so a key is
        # SQL. Unvalidated, `{"id = 1 OR 1=1 OR id": 1}` renders as
        #   WHERE id = 1 OR 1=1 OR id = %s AND creator_fk = %s
        # which MySQL parses as `id=1 OR TRUE OR (...)` — AND binds tighter than
        # OR — while the placeholder and argument counts still balance, so it
        # executes and deletes EVERY row in the table, every creator's. Measured
        # against darwin_dev: it cancels the req #3122 junction predicate and the
        # pre-existing `creator_fk` scoping alike, on every table.
        # `rest_get_table` has validated its keys this way since it was written;
        # this one never did.
        unknown = _unknown_columns(conn, table, keys)
        if unknown:
            print(f"HTTP {delete_method} invalid body key(s) for {table}: {unknown}")
            return compose_rest_response(400, '', 'BAD REQUEST')

        where_clause = ' AND '.join(f"{key} = %s" for key in keys)

        # Add creator_fk scoping for user-owned tables
        if authenticated_user is not None:
            if table in CREATOR_FK_TABLES:
                where_clause += ' AND creator_fk = %s'
                values.append(authenticated_user)
            elif table == PROFILE_TABLE:
                where_clause += ' AND id = %s'
                values.append(authenticated_user)
            else:
                # req #3122 — join-through scoping for tables with no creator_fk.
                # This is the branch that used to let `DELETE /darwin/
                # pipeline_step_deps {"id": <theirs>}` remove another user's gate,
                # and `{"step_fk": <theirs>}` strip a whole step's dependencies.
                junction_clause = junction_scope_clause(table)
                if junction_clause:
                    where_clause += f' AND {junction_clause}'
                    values.append(authenticated_user)

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
        errno, detail = error_detail(e)
        errorMsg = f"HTTP {delete_method} SQL FAILED: {errno} {detail}"
        print(errorMsg)
        if integrity_errno(e):
            return compose_conflict_response(table, e, errorMsg)
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
        else:
            junction_clause = junction_scope_clause(table)
            if junction_clause:
                where_clause += f' AND {junction_clause}'
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
        errno, detail = error_detail(e)
        errorMsg = f"HTTP {delete_method} bulk SQL FAILED: {errno} {detail}"
        print(errorMsg)
        if integrity_errno(e):
            return compose_conflict_response(table, e, errorMsg)
        return compose_rest_response(500, '', errorMsg)
