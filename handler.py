import json
import pymysql
import logging
import boto3

from decimal_encoder import DecimalEncoder
from classifier import classifier, varDump
from json_utils import composeJsonResponse
from mathapp_rds import *

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
 
# initialize logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

"""
connect to the RDS database using pymsql. 
Connection establishment outside the lambda_handler is seen as efficient
TODO: there is no error handling if connect doesn't work
"""
connection = pymysql.connect(host = endpoint,
                             user = username,
                             password = password,
                             database = db_name,)

"""
FAAS ENTRY POINT: the AWS Lambda function is configured to call this function by name.
"""
def lambda_handler(event, context):
    
    #print("First MathAppTestLambda Start")

    # Filter events based on API endpoint
    path = event['path']
    #varDump(event, "event @ lambda_handler start")

    if path == mathUserPath:
        response = restApiFromTable(event, mathUserTable)
    elif path == resultPath:
        response = restApiFromTable(event, resultTable)
    else:
        response = composeJsonResponse(404, 'Not Found')

    # return http response
    return response 

 
def restApiFromTable(event, table):
 
    httpMethod = event['httpMethod']
    print(f'Lambda start with method: {httpMethod}')

    if event['body'] != None:
        body = json.loads(event['body'])
        print(f"event has body of {body}")
    #else:
        #print('there is no body?')
        #varDump(event, 'event so we can inspect body')
        

    #
    # FILTER BY HTTP METHOD
    #
    if httpMethod == putMethod:
    
        #varDump(event, 'event at start of PUT')
        #varDump(body, 'body at start of PUT')
        # PUT -> Create one Row
        sql_key_list = ', '.join(f'{key}' for key in body.keys())
        sql_value_list = ', '.join(f"'{value}'" for value in body.values())

        try:
            # insert row into table

            sqlStatement = f"""
                INSERT INTO {table} ({sql_key_list}) 
                VALUES ({sql_value_list});
            """
            cursor = connection.cursor()
            cursor.execute(sqlStatement)
            connection.commit()
        except pymysql.Error as e:
            print(f"HTTP {putMethod} FAILED: {e.args[0]} {e.args[1]}")
            return composeJsonResponse('500', f"{e.args[0]} {e.args[1]}")

        try:
            # retrieve ID of newly created row

            cursor.execute('SELECT LAST_INSERT_ID();')
            newId = cursor.fetchone()
        except pymysql.Error as e:
            print(f"HTTP {putMethod} FAILED: {e.args[0]} {e.args[1]}")
            return composeJsonResponse('201', {'Id': 'Not available'})

        return composeJsonResponse('201', {'Id': newId[0]})

    elif httpMethod == getMethod:

        # GET -> read one row by ID or read all rows. Supports sort queryStringParameters

        # Process Id query string params and build sql qualifier
        Id = event.get('queryStringParameters').get('Id')
        if (Id):
            sqlIdQualifier = f"WHERE Id={Id}"
        else:
            sqlIdQualifier = ""
        
        # Process SORT query string params and build SQL qualifier
        sortParams = event.get('queryStringParameters').get('sort')
        
        if (sortParams):
            sortDict = dict(x.split(":") for x in sortParams.split(","))
    
            sortQualifier = ""
            sortSeparator = ""
            
            while sortDict:
                key, value = sortDict.popitem()
                sortQualifier = f"{key} {value}{sortSeparator}{sortQualifier}"
                sortSeparator = ", "
                
            sortQualifier = f" ORDER BY {sortQualifier}"


        # read SQL table definition
        try:
            cursor = connection.cursor()
            cursor.execute("SET SESSION group_concat_max_len = 65536")
            cursor.execute(f""" DESC {table}; """)
            rows = cursor.fetchall()
            
            desc_string = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)
            #desc_string = ', '.join(f"{row[0]}" for row in rows)
            
        except pymysql.Error as e:
            errorMsg = f"HTTP {putMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', {'error': errorMsg})

        # execute API requested read and process all return values
        try:

            # read row and format as JSON
            sqlStatement = f"""
                select 
            concat('[',
                GROUP_CONCAT(
                    JSON_OBJECT(    
                        'Id', Id
                        ,'Name', Name
                        ,'Favorite_Color', Favorite_Color
                        )
                    {sortQualifier}    
                    SEPARATOR ', ')
            ,']')
            from Math_User ;
            """
            varDump(sqlStatement, "sql statement")

            cursor.execute(sqlStatement)
            row = cursor.fetchall()

            varDump(row, 'Get SQL row Data')
            varDump(row[0], 'Get SQL row[0] Data')

            # the return data is wrapped in every available type it would seem
            if row[0][0]:
                print('get: 200')
                return composeJsonResponse('200', row[0])
            else:
                print('get: 404')
                errorMsg = f"row[0], no data to read bro"
                print(errorMsg)
                return composeJsonResponse('404', {'error': errorMsg})

        except pymysql.Error as e:
            errorMsg = f"HTTP {putMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', {'error': errorMsg})
        
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
                return composeJsonResponse('200', '')
            else:
                errorMsg = f"HTTP {putMethod}: no data to update"
                print(errorMsg)
                return composeJsonResponse('404', {'error': errorMsg})

        except pymysql.Error as e:
            errorMsg = f"HTTP {putMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
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
                errorMsg = f"Affected_rows = 0, no delete bro"
                print(errorMsg)
                return composeJsonResponse('404', {'error': errorMsg})
            else:
                return composeJsonResponse('200', '')

        except:
            errorMsg = f"HTTP {putMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', {'error': errorMsg})
            
    elif httpMethod == optionsMethod:
        #varDump(event, 'OPTIONS event dumps')
        return composeJsonResponse('200','')
