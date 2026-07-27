import pymysql
import json
from rest_api_utils import (compose_rest_response, compose_conflict_response,
                            error_detail, integrity_errno, junction_write_guard)
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

    # req #3122 — a table with no creator_fk has nothing to override, so its
    # INSERT is authorized by checking the parents it references instead. Without
    # this, `POST /darwin/pipeline_step_deps {"step_fk": <somebody else's step>}`
    # injected a dependency gate into another user's plan.
    refusal = junction_write_guard(conn, table, [body], authenticated_user,
                                   post_method)
    if refusal is not None:
        return refusal

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
        errno, detail = error_detail(e)
        errorMsg = f"HTTP {post_method} failed: {errno} {detail}"
        print(errorMsg)
        if integrity_errno(e):
            return compose_conflict_response(table, e, errorMsg)
        return compose_rest_response(500, '', errorMsg)

    # The INSERT has committed (autocommit). Everything below is the read-back,
    # which is a convenience for the caller — never a reason to report failure.
    try:
        # retrieve table description and create json object and sql columns
        with conn.cursor() as cursor:
            cursor.execute(f""" DESC {table}; """)
            rows = cursor.fetchall()

        json_object_columns = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)

        sql_columns = []
        for row in rows:
            sql_columns.append(row[0])

        # DESC column 6 (`Extra`) reads `auto_increment` exactly when MySQL
        # GENERATES the id. That — not the mere presence of an `id` column — is
        # what makes LAST_INSERT_ID() meaningful below (req #3094). Taken off
        # the DESC rows already in hand, so no extra round trip.
        id_is_auto_increment = any(
            row[0] == 'id' and len(row) > 5 and str(row[5]).lower() == 'auto_increment'
            for row in rows
        )

    except pymysql.Error as e:
        # `{e}` not `{e.args[0]} {e.args[1]}` — see the read-back handler below.
        print(f"HTTP {post_method} helper DESC SQL command failed: {e}")
        return compose_rest_response(201, '', 'CREATED')

    # No `id` column means the read-back below (`WHERE id=...`) cannot be built.
    # That is every junction table (composite PK). The row is already committed,
    # so the only correct answer is 201 CREATED without a body — reporting the
    # missing column as a 500 told callers a successful write had failed
    # (req #3057). Callers that need the row read it back by its composite key.
    if 'id' not in sql_columns:
        print(f"HTTP {post_method}: {table} has no id column, skipping read-back.")
        return compose_rest_response(201, '', 'CREATED')

    # Which id identifies the row that was just written?
    #
    # The id the BODY supplied wins over LAST_INSERT_ID(). It is the only correct
    # answer when MySQL did not generate the id — `profiles.id` is a varchar(64)
    # Cognito sub with no AUTO_INCREMENT — and it is also right when a caller
    # writes an explicit id into an AUTO_INCREMENT column, because MySQL only
    # sets LAST_INSERT_ID() for a value it generated itself.
    #
    # req #3094: before this, the read-back ran LAST_INSERT_ID() for any table
    # with an `id` column. On `profiles` that returned 0 (the connection is new
    # per invocation, so nothing had generated an id on it) and the read-back
    # became `WHERE id=0`. MySQL coerces the VARCHAR column to a number for that
    # comparison, so EVERY id not starting with a digit coerced to 0 and matched
    # — measured 2026-07-26 at 5 of 11 rows in darwin_dev and 5 of 17 in darwin —
    # and GROUP_CONCAT with no GROUP BY collapsed them into one array. The POSTing
    # caller got 200 plus five other users' profiles. A cross-tenant read out of
    # a write endpoint.
    #
    # A FALSY id is no id. Darwin's "type into the blank row" pattern POSTs the
    # spread template object, and every one of those templates carries `id: ''`
    # (AreaTabPanel/TaskCard/CategoryCard/ProjectEdit/DomainEdit/...). MySQL
    # coerces '' to 0 on an AUTO_INCREMENT column and generates a real id, so the
    # body's '' names nothing — reading back on it would match no row and turn a
    # 200-with-the-row into a 201-with-no-body, which those callers handle only
    # by invalidating a query (losing the new id, the pending-mutation replay,
    # and the post-create navigate). `"NULL"` is the caller's explicit-NULL
    # sentinel and is truthy, so it needs its own check.
    newId = body.get('id')
    if not newId or newId == "NULL":
        newId = None

    if newId is None:
        if not id_is_auto_increment:
            # Nothing identifies the new row. Same call as the `id`-less
            # junction path above: the row is committed, so 201 without a body.
            print(f"HTTP {post_method}: {table}.id is not auto_increment and the "
                  f"body supplied no id, skipping read-back.")
            return compose_rest_response(201, '', 'CREATED')

        try:
            # retrieve ID of newly created row
            sql_statement= f"""SELECT LAST_INSERT_ID()"""
            with conn.cursor() as cursor:
                affected_rows = cursor.execute(sql_statement)

                if affected_rows > 0:
                    id_row = cursor.fetchone()
                    newId = id_row[0] if id_row else None
                else:
                    print(f"HTTP {post_method} FAILED to read last_insert_id.")
                    return compose_rest_response(201, '', 'CREATED')

        except pymysql.Error as e:
            print(f"HTTP {post_method} FAILED to read last_insert_id: {e}")
            return compose_rest_response(201, '', 'CREATED')

        if not newId:
            # 0 means MySQL generated nothing on this connection. Never let that
            # reach the read-back as `WHERE id=0` — that is the req #3094 bug.
            print(f"HTTP {post_method}: last_insert_id is 0, skipping read-back.")
            return compose_rest_response(201, '', 'CREATED')

    # Bind it, never interpolate it: the id can be a Cognito sub. A non-generated
    # id goes down as a STRING so MySQL compares varchar to varchar — passing a
    # number would make it coerce the COLUMN instead, which is the bug above.
    lookup_id = newId if id_is_auto_increment else str(newId)

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
                            WHERE id=%s
        """
        pretty_print_sql(sql_statement, post_method)

        with conn.cursor() as cursor:
            cursor.execute(sql_statement, (lookup_id,))
            row = cursor.fetchall()

        #varDump(row, 'row data from read table AFTER post')

        if row[0][0]:
            return compose_rest_response(200, json.loads(row[0][0]), 'CREATED')
        else:
            print(f"HTTP {post_method} helper SELECT after WRITE SQL command failed")
            return compose_rest_response(201, '', 'CREATED')

    except (pymysql.Error, ValueError, TypeError, IndexError, KeyError) as e:
        # The row committed under autocommit before this SELECT ran, so NO
        # failure here is a failed write — 500 would repeat req #3057's defect
        # under a different error code (a lost connection or a read timeout
        # between the INSERT and the read-back reaches exactly this line). The
        # cause is logged; the caller is told the truth, which is CREATED.
        # `{e}` not `{e.args[0]} {e.args[1]}`: InterfaceError carries a single
        # arg, and indexing args[1] raised IndexError out of the except block.
        #
        # req #3059 deliberately does NOT map an integrity errno to 409 here.
        # Only the INSERT above can reject a write; by this line the row exists,
        # and a conflict status would be a lie about what happened.
        #
        # Wider than `pymysql.Error` (req #3094): passing args to execute() puts
        # pymysql on its `query % escaped_args` path, so the SQL text is now a
        # FORMAT STRING. `json_object_columns` is built from live DESC output, and
        # a column name containing `%` raises ValueError out of a block whose
        # entire thesis is that nothing after the INSERT reports failure — verified
        # by POSTing to a scratch table with a `pct%` column, which returned 503 on
        # a committed row before this line was widened. No such column exists in
        # darwin or darwin_dev today; the promise should not depend on that staying
        # true. TypeError/IndexError/KeyError cover the same shape of hazard around
        # `row[0][0]` and `json.loads`.
        #
        # Deliberately NOT bare `Exception`: a NameError or AttributeError here is
        # a coding mistake, and silently answering 201 forever would hide it.
        print(f"HTTP {post_method} helper SELECT after WRITE SQL command failed: "
              f"{type(e).__name__}: {e}")
        return compose_rest_response(201, '', 'CREATED')

    return compose_rest_response(500, '', 'INVALID PATH')


def _rest_post_bulk(post_method, conn, table, body_list, authenticated_user):
    """Insert multiple rows via single multi-value INSERT. Returns 201 with inserted count and first_id."""

    if not body_list:
        return compose_rest_response(400, '', 'BAD REQUEST')

    # Override creator_fk on each item before building SQL
    if authenticated_user is not None and table in CREATOR_FK_TABLES:
        for item in body_list:
            item['creator_fk'] = authenticated_user

    # req #3122 — EVERY row is checked, not a sample. The statement is one
    # multi-value INSERT that lands or rolls back as a unit, so a single foreign
    # reference anywhere in the batch must refuse the whole batch. `map_coordinates`
    # imports arrive here thousands of rows at a time; the check still costs one
    # SELECT, because it groups the distinct parent ids across all of them.
    refusal = junction_write_guard(conn, table, body_list, authenticated_user,
                                   post_method)
    if refusal is not None:
        return refusal

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
        errno, detail = error_detail(e)
        errorMsg = f"HTTP {post_method} bulk failed: {errno} {detail}"
        print(errorMsg)
        if integrity_errno(e):
            return compose_conflict_response(table, e, errorMsg)
        return compose_rest_response(500, '', errorMsg)