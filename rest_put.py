import pymysql
import json
from rest_api_utils import (compose_rest_response, compose_conflict_response,
                            error_detail, integrity_errno, parent_reference_guard)
from classifier import varDump, pretty_print_sql
from auth_utils import (CREATOR_FK_TABLES, PROFILE_TABLE, body_column,
                        check_body_keys, force_column, junction_scope_clause)

def rest_put(put_method, conn, database, table, body_list, authenticated_user=None):

    if not body_list:
        print('HTTP PUT with error 400: body not included')
        return compose_rest_response(400, '', 'BAD REQUEST')

    # req #3125 — the keys become the SET clause, and every check below reads
    # them back as exact Python strings. MySQL does not match column names that
    # way. This is worse on PUT than on POST, because a body can name the same
    # column twice in two spellings and MySQL applies the LAST one: the guard
    # would check `test_plan_fk` and the statement would apply `TEST_PLAN_FK`.
    # Both are refused here, before anything reads a key.
    refusal = check_body_keys(table, body_list)
    if refusal is not None:
        return compose_rest_response(refusal[0], '', refusal[1])

    if authenticated_user is not None:
        # An UPDATE may not hand a row to another creator. The WHERE clauses below
        # scope on the row's parent as it stands BEFORE the statement; the SET
        # clause is built from every key in the body, so without these two guards
        # `PUT [{"id": <my row>, "<scope column>": <their parent>}]` passes the
        # predicate and then reassigns the row — verified against darwin_dev,
        # which is how it defeated the equivalent POST guard by the other door.
        if table in CREATOR_FK_TABLES:
            # Mirror rest_post: creator_fk is forced from the token, never taken
            # from the body. Writing it to its current value is a harmless no-op
            # for every legitimate caller (none send it), and it stops
            # `PUT [{"id": <my task>, "creator_fk": "<their sub>"}]` from pushing
            # a row into somebody else's account.
            #
            # Matched case-insensitively (req #3125): `'creator_fk' in body` is a
            # Python string test and MySQL's column lookup is not, so
            # `{"CREATOR_FK": "<their sub>"}` slipped past this override entirely
            # — the WHERE clause matched on the row's current owner and the SET
            # clause then handed the row to the victim. Verified against
            # darwin_dev: a row given away through a 200.
            for body in body_list:
                if body_column(body, 'creator_fk')[0]:
                    force_column(body, 'creator_fk', authenticated_user)

        # Then check what the row POINTS AT, for EVERY table — not just the ones
        # with no creator_fk.
        #
        # req #3125: this call used to be the `else` of the branch above, so no
        # creator_fk-bearing table ever reached it. Forcing `creator_fk` settles
        # whose row it is and leaves its `*_fk` columns untouched, which is
        # exactly the gap: `PUT /darwin/test_runs [{"id": <my run>,
        # "test_plan_fk": <their plan>}]` passed the `creator_fk = %s` predicate
        # on a row the caller genuinely owns and then re-pointed it at the
        # victim's plan. `fk_test_runs_plan` is ON DELETE RESTRICT, so the victim
        # permanently loses the ability to delete their own plan — and PUT is the
        # door that stays open if only POST is guarded, the same way it did for
        # junctions in req #3122.
        #
        # `require_scope=False`: on an UPDATE an absent reference means
        # "unchanged", which is the common case — PriorityCard.jsx bulk-PUTs
        # {id, sort_order} on every hand-sort save, and `PUT /darwin/tasks
        # [{"id": 5, "done": 1}]` names no parent at all (the guard returns
        # without opening a cursor for those).
        refusal = parent_reference_guard(conn, table, body_list,
                                         authenticated_user, put_method,
                                         require_scope=False)
        if refusal is not None:
            return refusal

    # use the simple, more typical 'update' SQL syntax when updating a single record
    if len(body_list) == 1:

        body = body_list[0]

        # id used to identify the record, is not part of the columns updated
        id = body.get('id')

        if id == None:
            print('HTTP PUT with error 400: id not included in request')
            return compose_rest_response(400, '', 'BAD REQUEST')

        body.pop('id')

        if len(body) == 0:
            print('HTTP PUT with error 400: only id included in request')
            return compose_rest_response(400, '', 'BAD REQUEST')

        keys = list(body.keys())
        values = [None if v == "NULL" else v for v in body.values()]

        set_clause = ', '.join(f"{key} = %s" for key in keys)

        # Add creator_fk scoping for user-owned tables
        if authenticated_user is not None and table in CREATOR_FK_TABLES:
            sql_statement = f"""
                UPDATE {table}
                SET
                    {set_clause}
                WHERE
                    id = %s AND creator_fk = %s;
            """
            put_params = tuple(values) + (id, authenticated_user)
        elif authenticated_user is not None and table == PROFILE_TABLE:
            sql_statement = f"""
                UPDATE {table}
                SET
                    {set_clause}
                WHERE
                    id = %s AND id = %s;
            """
            put_params = tuple(values) + (id, authenticated_user)
        elif authenticated_user is not None and junction_scope_clause(table):
            # req #3122 — a table with no creator_fk is scoped through its
            # parent. Without this branch a junction PUT fell into the unscoped
            # `else` below, and `PUT /darwin/pipeline_step_deps [{"id":<theirs>}]`
            # rewrote another user's dependency gate. The subquery names the
            # PARENT table, never the one being updated, so MySQL 1093 (self-
            # reference in an UPDATE subquery) does not apply.
            sql_statement = f"""
                UPDATE {table}
                SET
                    {set_clause}
                WHERE
                    id = %s AND {junction_scope_clause(table)};
            """
            put_params = tuple(values) + (id, authenticated_user)
        else:
            sql_statement = f"""
                UPDATE {table}
                SET
                    {set_clause}
                WHERE
                    id = %s;
            """
            put_params = tuple(values) + (id,)
    else:
        # when PUT receives multiple records, use case syntax. Here's an example:
        # UPDATE areas SET
        #    sort_order = CASE id
        #       WHEN 1 THEN 0
        #       WHEN 2 THEN 1
        #       ELSE sort_order
        #       END,
        #    area_name = CASE id
        #      WHEN 9 THEN 'React'
        #      WHEN 10 THEN 'Lambda'
        #      ELSE area_name
        #      END
        #   WHERE id in (1,2,9,10);

        id_list = list()
        column_dict = dict()

        for body in body_list:
            # id used to identify the record, is not part of the columns updated
            id = body.get('id')

            if id == None:
                print('HTTP PUT with error 400: id not included in request')
                return compose_rest_response(400, '', 'BAD REQUEST')

            body.pop('id')

            if len(body) == 0:
                print('HTTP PUT with error 400: only id included in request')
                return compose_rest_response(400, '', 'BAD REQUEST')

            # creating list of id's, later convert to id string for the IN clause
            id_list.append(id)

            # iterate over key value pairs creating list of (id, value) tuples
            # stored by column name
            for key, value in body.items():
                if key not in column_dict:
                    column_dict[key] = []
                column_dict[key].append((id, None if value == "NULL" else value))

        # Build parameterized CASE expressions
        put_params = []
        case_parts = []
        for col_name, when_list in column_dict.items():
            when_clause = ' '.join(['WHEN %s THEN %s'] * len(when_list))
            case_parts.append(f"{col_name} = CASE id {when_clause} ELSE {col_name} END")
            for id_val, col_val in when_list:
                put_params.extend([id_val, col_val])

        set_clause = ', '.join(case_parts)
        id_placeholders = ', '.join(['%s'] * len(id_list))
        put_params.extend(id_list)

        # Add creator_fk scoping for user-owned tables
        if authenticated_user is not None and table in CREATOR_FK_TABLES:
            sql_statement = f"""
                UPDATE {table} SET
                    {set_clause}
                WHERE id in ({id_placeholders}) AND creator_fk = %s;
            """
            put_params.append(authenticated_user)
        elif authenticated_user is not None and table == PROFILE_TABLE:
            sql_statement = f"""
                UPDATE {table} SET
                    {set_clause}
                WHERE id in ({id_placeholders}) AND id = %s;
            """
            put_params.append(authenticated_user)
        elif authenticated_user is not None and junction_scope_clause(table):
            # req #3122 — same join-through scoping on the bulk CASE path. The
            # frontend's hand-sort save (PriorityCard.jsx) is a bulk PUT to
            # `priority_card_order`, so this branch is live traffic, not just the
            # pipeline case.
            sql_statement = f"""
                UPDATE {table} SET
                    {set_clause}
                WHERE id in ({id_placeholders}) AND {junction_scope_clause(table)};
            """
            put_params.append(authenticated_user)
        else:
            sql_statement = f"""
                UPDATE {table} SET
                    {set_clause}
                WHERE id in ({id_placeholders});
            """

    try:
        pretty_print_sql(sql_statement, put_method)

        with conn.cursor() as cursor:
            affected_rows = cursor.execute(sql_statement, tuple(put_params))

        if affected_rows > 0:
            return compose_rest_response(200, '', 'OK')
        else:
            errorMsg = f"HTTP {put_method}: NO DATA CHANGED"
            print(errorMsg)
            return compose_rest_response(204, 'NO DATA CHANGED', 'NO DATA CHANGED')

    except pymysql.Error as e:
        errno, detail = error_detail(e)
        errorMsg = f"HTTP {put_method} SQL FAILED: {errno} {detail}"
        print(errorMsg)
        if integrity_errno(e):
            return compose_conflict_response(table, e, errorMsg)
        return compose_rest_response(500, '', errorMsg)
