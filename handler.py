import json
import pymysql
import boto3

from decimal_encoder import DecimalEncoder
from classifier import varDump
from json_utils import composeJsonResponse
from mathapp_rds import *

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
    
    print('attempting connection...')
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
    
    print(f"Lambda Handler Invoked {event['httpMethod']}")

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
    
    if not event:
        print('no event')
        return composeJsonResponse('500', '', 'REST API call received with no event')
 
    httpMethod = event.get('httpMethod')
    print(f'restApiFromTable start with method: {httpMethod}')
    if not httpMethod:
        print('No HTTP method')
        return composeJsonResponse('500', '', 'REST API call received with no HTTP method')


    if event['body'] != None:
        body = json.loads(event['body'])

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

        # Process Id query string param and build related sql qualifier
        Id = event.get('queryStringParameters').get('Id')
        if (Id):
            sqlIdQualifier = f"WHERE Id={Id}"
        else:
            sqlIdQualifier = ""
        
        # Process SORT query string params and build related SQL qualifier
        sortParams = event.get('queryStringParameters').get('sort')
        
        sortQualifier = ""
        if (sortParams):

            separator = ""
            sortDict = dict(x.split(":") for x in sortParams.split(","))
            
            while sortDict:
                key, value = sortDict.popitem()
                sortQualifier = f"{key} {value}{separator}{sortQualifier}"
                separator = ", "
                
            sortQualifier = f" ORDER BY {sortQualifier}"

        # read SQL table definition
        try:
            cursor = conn.cursor()
            cursor.execute("SET SESSION group_concat_max_len = 65536")
            cursor.execute(f""" DESC {table}; """)
            rows = cursor.fetchall()
            
            desc_string = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)
            
        except pymysql.Error as e:
            errorMsg = f"HTTP {getMethod} helper SQL commands failed: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', '', errorMsg)

        # execute API read and process all return values
        try:

            # read row(s) and format as JSON
            sqlStatement = f"""
                                SELECT 
                                    CONCAT('[',
                                        GROUP_CONCAT(
                                            JSON_OBJECT({desc_string})
                                            {sortQualifier}    
                                            SEPARATOR ', ')
                                    ,']')
                                FROM 
                                    {table}
                                {sqlIdQualifier}
            """
            
            prettySql = ' '.join(sqlStatement.split())
            print(f"{getMethod} SQL statement is:")
            print(prettySql)

            cursor.execute(sqlStatement)
            row = cursor.fetchall()

            if row[0][0]:
                return composeJsonResponse('200', row[0], 'OK')
            else:
                print('get: 404')
                errorMsg = f"No data"
                print(errorMsg)
                return composeJsonResponse('404',  '', 'NOT FOUND')

        except pymysql.Error as e:
            errorMsg = f"HTTP {getMethod} acutal SQL select statement failed: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', '', errorMsg)
        
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
