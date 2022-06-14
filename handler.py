import json
import pymysql

from classifier import varDump
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

#
# TODO: HTTP Response Code definitions
#

# USER: REST API endpoints. Correspond directly to database tables.
mathUserPath = '/math_user'
mathUserTable = 'Math_User'

resultPath = '/results'
resultTable = 'Results'

restApiPath = '/rest_crud_app/user'
restApiTable = 'user'

 
"""
connect to the RDS database using pymsql. 
Connection establishment outside the lambda_handler is seen as efficient
TODO: there is no error handling if connect doesn't work
"""

connection = dict()

for db in db_dict:
    
    print('attempting database connection...')
    connection[db] = pymysql.connect(host = endpoint,
                                 user = username,
                                 password = password,
                                 database = db,)

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
    
    #hack: remove after api gateway re-organize for mathapp
    if database == 'math_user':
        table = 'Math_User'
        database = 'Math_App'
    
    conn = connection[database] if database in connection else ''
        
    return {'path': path, 'database': database, 'table': table, 'conn': conn}


"""
FAAS ENTRY POINT: the AWS Lambda function is configured to call this function by name.
"""
def lambda_handler(event, context):
    
    print(f"Lambda Handler Invoked for HTTP Method {event['httpMethod']}")
    #varDump(event, "event at lambda invocation")
    
    path = event.get('path')

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
    
        # PUT -> Create one Row
        sql_key_list = ', '.join(f'{key}' for key in body.keys())
        sql_value_list = ', '.join(f"'{value}'" for value in body.values())

        try:
            # insert row into table

            sqlStatement = f"""
                INSERT INTO {table} ({sql_key_list}) 
                VALUES ({sql_value_list});
            """
            cursor = connection['Math_App'].cursor()
            cursor.execute(sqlStatement)
            connection.commit()
        except pymysql.Error as e:
            errorMsg = f"HTTP {putMethod} failed: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', '', errorMsg)

        try:
            # retrieve ID of newly created row

            cursor.execute('SELECT LAST_INSERT_ID();')
            newId = cursor.fetchone()
        except pymysql.Error as e:
            print(f"HTTP {putMethod} FAILED: {e.args[0]} {e.args[1]}")
            return composeJsonResponse('201', {'Id': 'Not available'}, 'CREATED')

        return composeJsonResponse('201', {'Id': newId[0]}, 'CREATED')

    elif httpMethod == getMethod:
        
        if table:
            return rest_get_table(event, table, conn, getMethod)
        else:
            return rest_get_database(event, database, conn, getMethod)

        
    elif httpMethod == postMethod:

        # POST - Update one Row
        Id = body.get('Id', '')
        body.pop('Id')
        
        sql_kv_string = ', '.join(f"{key} = '{value}'" for key, value in body.items())

        try:
            sqlStatement = f"""
                UPDATE {table}
                SET 
                    {sql_kv_string}
                WHERE
                    Id = {Id};
            """
            cursor = connection.cursor()
            affected_rows = cursor.execute(sqlStatement)
            if affected_rows > 0:
                connection.commit()
                return composeJsonResponse('200', '', 'OK')
            else:
                errorMsg = f"HTTP {postMethod}: no data changed"
                print(errorMsg)
                return composeJsonResponse('204', '', errorMsg)

        except pymysql.Error as e:
            errorMsg = f"HTTP {postMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', {'error': errorMsg})

    elif httpMethod == deleteMethod:

        # DELETE - Delete one Row by Id
        Id = body.get('Id', '')
        body.pop('Id')

        try:
            sqlStatement = f"""
                DELETE FROM {table} 
                WHERE
                    Id = {Id};
            """
            cursor = connection.cursor()
            affected_rows = cursor.execute(sqlStatement)
            connection.commit()

            if affected_rows == 0:
                errorMsg = f"Affected_rows = 0, 404 time"
                print(errorMsg)
                return composeJsonResponse('404', '', 'NOT FOUND')
            else:
                return composeJsonResponse('200', '', 'OK')

        except:
            errorMsg = f"HTTP {deleteMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', '', errorMsg)
            
    elif httpMethod == optionsMethod:
        #varDump(event, 'OPTIONS event dumps')
        return composeJsonResponse('200','')
