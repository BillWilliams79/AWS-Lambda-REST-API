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

        sql_kv_string = ', '.join(f"{key} = '{value}'" for key, value in body.items())

        # NULL handling: mySQL requires no quotes around NULL values
        sql_kv_string = sql_kv_string.replace("'NULL'", "NULL")

        sql_statement = f"""
            UPDATE {table}
            SET 
                {sql_kv_string}
            WHERE
                id = {id};
        """
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

            # iterate over key value pairs creating dict of WHEN/THEN statements
            # stored by column name
            for key, value in body.items():
                 case_string = column_dict.get(key, '')
                 case_string = f"{case_string} WHEN {id} THEN '{value}'"
                 column_dict[key] = case_string

        case_string = ', '.join(f"{key} = CASE id {value} ELSE {key} END" for key, value in column_dict.items())

        # NULL handling: mySQL requires no quotes around NULL values
        case_string = case_string.replace("'NULL'", "NULL")

        id_string = ', '.join(f"{id}" for id in id_list)

        sql_statement = f"""
            UPDATE {table} SET
                {case_string}
            WHERE id in ({id_string});
        """

    try:
        pretty_print_sql(sql_statement, put_method)

        cursor = conn.cursor()
        affected_rows = cursor.execute(sql_statement)
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
        return compose_rest_response('500', {'error': errorMsg})
