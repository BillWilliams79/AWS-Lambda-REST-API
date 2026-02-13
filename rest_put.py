import pymysql
import json
from rest_api_utils import compose_rest_response
from classifier import varDump, pretty_print_sql
        
def rest_put(put_method, conn, table, body_list):

    if not body_list:
        print('HTTP PUT with error 400: body not included')
        return compose_rest_response(400, '', 'BAD REQUEST')

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
            conn.commit()
            return compose_rest_response('200', '', 'OK')
        else:
            errorMsg = f"HTTP {put_method}: NO DATA CHANGED"
            print(errorMsg)
            return compose_rest_response('204', 'NO DATA CHANGED', 'NO DATA CHANGED')

    except pymysql.Error as e:
        errorMsg = f"HTTP {put_method} SQL FAILED: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('500', '', errorMsg)
