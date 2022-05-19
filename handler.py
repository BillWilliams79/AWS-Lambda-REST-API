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
# HTTP Response Code
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
FAAS ENTRY POINT: the AWS Lambda function is configured to call this function. Lambdas
design paradigm is event driven software. Lambdas are called internally by AWS services
using an event to pass in data. A second context object is provided and it

Near replica of Felix Yu Youtube video: https://youtu.be/9eHh946qTIk
TODO: Full definition of event and context, are there other parameters for the handler?
"""
def lambda_handler(event, context): 
    
    """logging and debug
    logger.info(event)
    varDump(event,'http event from lambda_handler')
    varDump(context, 'context from lambda_handler)
    """

    # FILTER BY REST PATH (URI endpoint?)
    path = event['path'] 
    if path == mathUserPath:
        response = restApiFromTable(event, mathUserTable)
    elif path == resultPath:
        response = restApiFromTable(event, resultTable)
    else:
        response = composeJsonResponse(404, 'Not Found')

    # return http response
    return response 

 
def restApiFromTable(event, table):

    """
    Implement rest API for a given SQL Table.
        JSON REST API CRUD (JRAC)

    Create  -> PUT
    Read    -> GET
    Update  -> POST
    Delete  -> DELETE

    JSON input/output

    MAJOR TODO: Open API headers, Hatteos links and pathing for FK, 

    """

    httpMethod = event['httpMethod']
    if 'body' in event:
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

            sqlCommand = f"""
                INSERT INTO {table} ({sql_key_list}) 
                VALUES ({sql_value_list});
            """
            cursor = connection.cursor()
            cursor.execute(sqlCommand)
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

        # GET -> Read one Row by Id
        Id = event['queryStringParameters']['Id']

        try:
            # read table definition
            cursor = connection.cursor()
            cursor.execute(f""" DESC {table}; """)
            rows = cursor.fetchall()
            desc_string = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)
        except pymysql.Error as e:
            errorMsg = f"HTTP {putMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', {'error': errorMsg})

        try:
            # read row and format as JSON
            sqlCommand = f"""
                SELECT 
                    JSON_ARRAYAGG(JSON_OBJECT({desc_string}))
                FROM
                    {table}
                WHERE
                    Id={Id}
            """
            cursor.execute(sqlCommand)
            row = cursor.fetchone()
            if row[0] != None:
                return composeJsonResponse('200', row[0])
            else:
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
                return composeJsonResponse('200')
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
                return composeJsonResponse('200')

        except:
            errorMsg = f"HTTP {putMethod} SQL FAILED: {e.args[0]} {e.args[1]}"
            print(errorMsg)
            return composeJsonResponse('500', {'error': errorMsg})
