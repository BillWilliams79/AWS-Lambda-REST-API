import json
import pymysql

from classifier import varDump, pretty_print_sql
from json_utils import composeJsonResponse
from mathapp_rds import *
from rest_get_database import rest_get_database
from rest_get_table import rest_get_table


print('lambda init code executing...')

#
# HTTP Method const values
#
getMethod = 'GET'
postMethod = 'POST'
putMethod = 'PUT'
deleteMethod = 'DELETE'
optionsMethod = 'OPTIONS'

connection = dict()

for db in db_dict:

    print('attempting database connection...')
    connection[db] = pymysql.connect(host = endpoint,
                                     user = username,
                                     password = password,
                                     database = db,)

    cursor = connection[db].cursor()

    try:
        # default session value "read repeatable" breaks ability to see
        # updates from back end...READ COMITTED enable select to return all 
        # committed data from all sources
        sql_statement = "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"
        no_data = cursor.execute(sql_statement)

    except pymysql.Error as e:
        errorMsg = f"Set session isolation read committed failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)

    try:
        # Required to allow large data returns for reads using group_concat_max_len
        cursor.execute("SET SESSION group_concat_max_len = 65536")
    except pymysql.Error as e:
        errorMsg = f"Set session group_concat_max_len 64k failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)


varDump(connection, 'Lambda Init: connection details')

def parse_path(path):

    #
    # Split first level of path into database. 
    # Second level of path into table.
    # Save aside the database/table connection as applicable.
    #
    splitPath = path[1:].split('/')
    database = splitPath[0]
    table = splitPath[1] if len(splitPath) > 1 else ''
    
    conn = connection[database] if database in connection else ''
        
    return {'path': path, 'database': database, 'table': table, 'conn': conn}


#FAAS ENTRY POINT: the AWS Lambda function is configured to call this function by name.
def lambda_handler(event, context):

    path = event.get('path')
    print(f"Lambda Handler Invoked for {path}.{event['httpMethod']}")

    if path:
        db_info = parse_path(path)
    else:
        return composeJsonResponse(404, '', f"No path provided")

    if db_info['database'] in db_dict:
        response = restApiFromTable(event, db_info)
    else:
        response = composeJsonResponse(404, '', f"URL/path not found: {path}")

    return response 

def restApiFromTable(event, db_info):

    #varDump(db_info, "db_info at start of restApiFromTable call")
    path = db_info['path']
    database = db_info['database']
    table = db_info['table']
    conn = db_info['conn']
    httpMethod = event.get('httpMethod')

    if event['body'] != None:
        body = json.loads(event['body'])

    if not event:
        print('no event')
        return composeJsonResponse('500', '', 'REST API call received with no event')

    if not conn:
        print('no conn')
        return composeJsonResponse('500', '', 'REST API call, no database connection')

    if not httpMethod:
        print('No HTTP method')
        return composeJsonResponse('500', '', 'REST API call received with no HTTP method')

    #
    # FILTER BY HTTP METHOD
    #
    if httpMethod == putMethod:
    
        # Assemble list of keys and values for use in SQL
        sql_key_list = ', '.join(f'{key}' for key in body.keys())
        sql_value_list = ', '.join(f"'{value}'" for value in body.values())

        try:
            # insert row into table
            sql_statement = f"""
                        INSERT INTO {table} ({sql_key_list})
                        VALUES ({sql_value_list});
            """
            pretty_print_sql(sql_statement, putMethod)

            cursor = conn.cursor()
            affected_put_rows = cursor.execute(sql_statement)

            if affected_put_rows > 0:
                conn.commit()
            else:
                errorMsg = f"HTTP {putMethod} failed no rows affected"
                print(errorMsg)
                return composeJsonResponse('500', '', "NO DATA SAVED")

        except pymysql.Error as e:
            errorMsg = f"HTTP {putMethod} failed: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', '', errorMsg)

        try:
            # retrieve ID of newly created row
            sql_statement= f"""SELECT LAST_INSERT_ID()"""
            affected_rows = cursor.execute(sql_statement)

            if affected_rows > 0:
                newId = cursor.fetchone()
                varDump(newId, 'newId after fetchone')
            else:
                print(f"HTTP {putMethod} FAILED to read last_insert_id.")
                return composeJsonResponse('201', '', 'CREATED')

        except pymysql.Error as e:
            print(f"HTTP {putMethod} FAILED to read last_insert_id: {e.args[0]} {e.args[1]}")
            return composeJsonResponse('201', '', 'CREATED')

        try:
            # retrieve table description and create json object and sql columns
            cursor.execute(f""" DESC {table}; """)
            rows = cursor.fetchall()

            json_object_columns = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)

            sql_columns = []
            for row in rows:
                sql_columns.append(row[0])
            
        except pymysql.Error as e:
            errorMsg = f"HTTP {getMethod} helper DESC SQL command failed: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('201', '', 'CREATED')

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
            pretty_print_sql(sql_statement, getMethod)

            cursor.execute(sql_statement)
            row = cursor.fetchall()
    
            varDump(row, 'row data from read table AFTER put')

            if row[0][0]:
                return composeJsonResponse('200', row[0], 'CREATED')
            else:
                print(f"HTTP {putMethod} helper SELECT after WRITE SQL command failed")
                return composeJsonResponse('201', '', 'CREATED')

        except pymysql.Error as e:
            errorMsg = f"HTTP {putMethod} helper SELECT after WRITE SQL command failed: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', '', "errorMsg")

        return composeJsonResponse('500', '', 'INVALID PATH')

    elif httpMethod == getMethod:
        
        if table:
            return rest_get_table(event, table, conn, getMethod)
        else:
            return rest_get_database(event, database, conn, getMethod)

    elif httpMethod == postMethod:

        # POST - Update one Row
        id = body.get('id', '')
        body.pop('id')
        
        sql_kv_string = ', '.join(f"{key} = '{value}'" for key, value in body.items())

        try:
            sql_statement = f"""
                UPDATE {table}
                SET 
                    {sql_kv_string}
                WHERE
                    id = {id};
            """
            pretty_print_sql(sql_statement, putMethod)

            cursor = conn.cursor()
            affected_rows = cursor.execute(sql_statement)
            if affected_rows > 0:
                conn.commit()
                return composeJsonResponse('200', '', 'OK')
            else:
                errorMsg = f"HTTP {postMethod}: NO DATA CHANGED"
                print(errorMsg)
                return composeJsonResponse('204', '', errorMsg)

        except pymysql.Error as e:
            errorMsg = f"HTTP {postMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', {'error': errorMsg})

    elif httpMethod == deleteMethod:

        if not body:
            return composeJsonResponse(400, '', 'BAD REQUEST')

        # if multple key/value are provided in body default is to AND them together
        where_clause = ' AND '.join(f"{key}={value}" for key, value in body.items())
        
        try:
            sql_statement = f"""
                DELETE FROM {table} 
                WHERE
                    {where_clause};
            """
            pretty_print_sql(sql_statement, deleteMethod)

            cursor = conn.cursor()
            affected_rows = cursor.execute(sql_statement)

            if affected_rows == 0:
                errorMsg = f"Affected_rows = 0, 404 time"
                print(errorMsg)
                return composeJsonResponse('404', '', 'NOT FOUND')
            else:
                conn.commit()
                return composeJsonResponse('200', '', 'OK')

        except pymysql.Error as e:
            errorMsg = f"HTTP {deleteMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', '', errorMsg)
            
    elif httpMethod == optionsMethod:
        #varDump(event, 'OPTIONS event dumps')
        return composeJsonResponse('200','')
