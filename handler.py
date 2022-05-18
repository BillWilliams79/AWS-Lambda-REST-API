import json
import pymysql
import logging
import boto3

from decimal_encoder import DecimalEncoder
from classifier import classifier, miniClassifier
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
# hand coded paths. hand coded execution patter
#
mathUserPath = '/math_user'
resultPath = '/result'




#
# initialize logging
#
logger = logging.getLogger()
logger.setLevel(logging.INFO)

#
# connect to the RDS database using pymsql. 
# Connection establishment outside the lambda_handler is seen as efficient
# TODO: there is no error handling if connect doesn't work
#
connection = pymysql.connect(host = endpoint,
                             user = username,
                             password = password,
                             database = db_name,)

#
# FAAS ENTRY POINT: the AWS Lambda function is configured to call this function. It can be any name so 
# long as they are consistent (function name, aws lambda name). It is given event and context.
#
# Near replica of Felix Yu Youtube video: https://youtu.be/9eHh946qTIk
# TODO: Full definition of event and context, are there other parameters for the handler?
#
def lambda_handler(event, context): 

    #print('start lambda handler')
    #
    # using logging instead of console.log for debug
    # TODO: read this information in the eventlog, whereever that is
    #
    logger.info(event)
    #classifier(event,'http event from handler')

    #
    # Parse event for data
    # TODO: make httpMethod enum - is in enum? is that the check
    # TODO: Should I process the string futher?
    #
    #httpMethod = event['httpMethod'] # GET, POST, PATCH, DELETE, OPTIONS
    path = event['path'] # API path

    #
    # FILTER ZERO: filter traffic by path
    #
    if path == mathUserPath:
        response = rest_Api_MathUser(event,)
    elif path == resultPath:
        #response = rest_api_result()
        pass
    elif path == resultPath:
        #response = rest_api_results()
        pass
    else:
        response = composeJsonResponse(404, 'Not Found')

    #
    # Utimately the lambda return's a response with an optional body.
    #
    return response

 
def rest_Api_MathUser(event):
    #
    # implement rest API for SQL table MathUser
    # CRUD - Create, Read, Update, Delete
    # Create => POST, Read => GET, Update => PATCH, Delete => DELETE 
    #
    httpMethod = event['httpMethod']
    
    if httpMethod == postMethod:
        #
        # Create MathUser
        # input: event body in json format. Convert to dict via json.loads.
        # execute sql: table desc, create list of keys that NULL = No,
        #   check NULL=No Keys are all in the sql_key_list or fail request
        #
        bodydict = json.loads(event['body'])
        #classifier(bodydict, 'event[body] from post mathuser rest api')

        try:

            #
            # the body is a dictionary of key value pairs. The names exactly match what's in SQL, by design.
            # we insert into SQL row. You specify the key list and then the value list.
            # SQL expect: key_list - a list of comma separate key names: key, key, key
            # SQL expect: value_list - list of comma separate key names, single quoted: 'value', 'value, 'value'
            #
            sql_key_list = ', '.join(f'{key}' for key in bodydict.keys())
            #print(f'sql_key_list:\t {sql_key_list}')

            sql_value_list = ', '.join(f"'{value}'" for value in bodydict.values())
            #print(f'sql_value_list:\t {sql_value_list}')

            #
            # produces properly formatted SQL string to insert your object with key:value pair
            #
            sqlCommand = f"""
                INSERT INTO Math_User ({sql_key_list}) 
                VALUES ({sql_value_list});
            """
            #print(f'sql string:\t {sqlCommand}')
            cursor = connection.cursor()
            affected_rows = cursor.execute(sqlCommand)
            #print(f'POST: affected_rows:\t{affected_rows}')
            connection.commit()
            return composeJsonResponse('200')
        except:
            logger.exception(f'Unable to complete SQL command {sqlCommand}')

    elif httpMethod == getMethod:
        #
        # read MathUser SQL row
        # Sets custom SQL string, cursor executes SQL, fetches row and responds
        #
        try:
            sqlCommand = f"""
                SELECT 
                    JSON_ARRAYAGG(JSON_OBJECT('Id', Id, 'Name', Name))
                FROM
                    Math_User 
                WHERE
                    Id=16
            """
            #
            # CRUD
            # CREATE - POST body
            # READ - GET ?id=1
            # UPDATE - PUT body (less often PATCH, no longer level 3 MM REST API)
            # DELETE - DELETE body
            # OPTIONS
            #
            # URI
            #
            # /task?id=1 (body or params) GET ONE
            # /tasks GET ALL
            #
            # /tasks?id=1   READ - with id, read one; else read all
            #

            cursor = connection.cursor()
            cursor.execute(sqlCommand)
            row = cursor.fetchone()
            return composeJsonResponse('200', row[0])
        except:
            logger.exception(f'Unable to complete SQL command {sqlCommand}')

    elif httpMethod == putMethod:

        #
        # Update MathUser
        #
        #miniClassifier(event, 'why is no body home')
        bodydict = json.loads(event['body'])

        try:

            Id = bodydict.get('Id', '')
            bodydict.pop('Id')
            
            sql_kv_string = ', '.join(f"{key} = '{value}'" for key, value in bodydict.items())
            #print(f'PUT: sql_kv_string:\t {sql_kv_string}')

            sqlStatement = f"""
                UPDATE Math_User
                SET 
                    {sql_kv_string}
                WHERE
                    Id = {Id};
            """
            #print(f'PUT: sql string:\t {sqlStatement}')
            cursor = connection.cursor()
            affected_rows = cursor.execute(sqlStatement)
            #print(f'PUT: affected_rows:\t{affected_rows}')
            connection.commit()
            return composeJsonResponse('200')
        except:
            logger.exception(f'Unable to complete SQL command {sqlCommand}')


    elif httpMethod == deleteMethod:

        bodydict = json.loads(event['body'])

        try:

            Id = bodydict.get('Id', '')
            bodydict.pop('Id')

            sqlStatement = f"""
                DELETE FROM Math_User 
                WHERE
                    Id = {Id};
            """

            cursor = connection.cursor()
            affected_rows = cursor.execute(sqlStatement)
            connection.commit()
            return composeJsonResponse('200')
        except:
            logger.exception(f'Unable to complete SQL command {sqlCommand}')



###########################################################################################
#
# Test httpMethod's
#
###########################################################################################

#
# Generic Lambda Rest API test execututor. Uses a dictionary to pass parameters. 
#
def LambaTestExecute(config):
    
    testHttpMethod = config['testHttpMethod']

    print(f"\n**** Execute Lambda Test: { config['testPath'] } { testHttpMethod } ****")

    testEvent = {
            'httpMethod': testHttpMethod,
            'path': config['testPath'],
            'queryStringParameters': config['queryStringParameters'],}

    testEvent['body'] = json.dumps(config['testBody'])

    context = config['context']

    responseJson = lambda_handler(testEvent, context)
    print(f"{config['testPath']}.{testHttpMethod} Test Response: {json.dumps(responseJson,indent=4)}")

    if 'body' in responseJson:
        bodyDict = json.loads(responseJson['body'])
        print(f'{testHttpMethod}: body, Dict: {bodyDict}')

    print("")

# POST TEST
mathUserPostConfig = {
    'testHttpMethod': 'POST',
    'testPath': mathUserPath,
    'queryStringParameters': {},
    'testBody': {'name': 'Fred Fox',
                 'favorite_color': 'Sky Blue'},
    'context': {},
    'expected_result': {},
}

# GET TEST
mathUserGetConfig = {
    'testHttpMethod': 'GET',
    'testPath': mathUserPath,
    'queryStringParameters': {},
    'testBody': {'name': 'Fred Fox',
                 'favorite_color': 'Sky Blue'},
    'context': {},
    'expected_result': {},
}

# PUT TEST
mathUserPutConfig = {
    'testHttpMethod': 'PUT',
    'testPath': mathUserPath,
    'queryStringParameters': {'Id': 16,},
    'testBody': {'Id': 14,
                 'name': 'asdf King',
                 'favorite_color': 'Bluey it your way'},
    'context': {},
    'expected_result': {},
}

# DELETE TEST
mathUserDeleteConfig = {
    'testHttpMethod': 'DELETE',
    'testPath': mathUserPath,
    'queryStringParameters': {'Id': 16,},
    'testBody': {'Id': 15},
    'context': {},
    'expected_result': {},
}

LambaTestExecute(mathUserPutConfig)
LambaTestExecute(mathUserGetConfig)
LambaTestExecute(mathUserPostConfig)
LambaTestExecute(mathUserDeleteConfig)
