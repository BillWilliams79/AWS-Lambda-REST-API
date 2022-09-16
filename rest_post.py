import pymysql
import json
from rest_api_utils import compose_rest_response
from classifier import varDump, pretty_print_sql

def rest_post(post_method, conn, table, body):

    if not body:
        return compose_rest_response(400, '', 'BAD REQUEST')
    varDump(body, 'body inside rest_post')
    # Assemble list of keys and values for use in SQL
    sql_key_list = ', '.join(f'{key}' for key in body.keys())
    sql_value_list = ', '.join(f"'{value}'" for value in body.values())

    # NULL handling: mySQL requires no quotes around NULL values
    sql_value_list = sql_value_list.replace("'NULL'", "NULL")

    try:
        # insert row into table
        sql_statement = f"""
                    INSERT INTO {table} ({sql_key_list})
                    VALUES ({sql_value_list});
        """
        pretty_print_sql(sql_statement, post_method)

        cursor = conn.cursor()
        affected_post_rows = cursor.execute(sql_statement)

        if affected_post_rows > 0:
            conn.commit()
        else:
            errorMsg = f"HTTP {post_method} failed no rows affected"
            print(errorMsg)
            return compose_rest_response('500', '', "NO DATA SAVED")

    except pymysql.Error as e:
        errorMsg = f"HTTP {post_method} failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('500', '', errorMsg)

    try:
        # retrieve ID of newly created row
        sql_statement= f"""SELECT LAST_INSERT_ID()"""
        affected_rows = cursor.execute(sql_statement)

        if affected_rows > 0:
            newId = cursor.fetchone()
            #varDump(newId, 'newId after fetchone')
        else:
            print(f"HTTP {post_method} FAILED to read last_insert_id.")
            return compose_rest_response('201', '', 'CREATED')

    except pymysql.Error as e:
        print(f"HTTP {post_method} FAILED to read last_insert_id: {e.args[0]} {e.args[1]}")
        return compose_rest_response('201', '', 'CREATED')

    try:
        # retrieve table description and create json object and sql columns
        cursor.execute(f""" DESC {table}; """)
        rows = cursor.fetchall()

        json_object_columns = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)

        sql_columns = []
        for row in rows:
            sql_columns.append(row[0])
        
    except pymysql.Error as e:
        errorMsg = f"HTTP {post_method} helper DESC SQL command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('201', '', 'CREATED')

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

        cursor.execute(sql_statement)
        row = cursor.fetchall()

        #varDump(row, 'row data from read table AFTER post')

        if row[0][0]:
            return compose_rest_response('200', row[0], 'CREATED')
        else:
            print(f"HTTP {post_method} helper SELECT after WRITE SQL command failed")
            return compose_rest_response('201', '', 'CREATED')

    except pymysql.Error as e:
        errorMsg = f"HTTP {post_method} helper SELECT after WRITE SQL command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('500', '', "errorMsg")

    return compose_rest_response('500', '', 'INVALID PATH')