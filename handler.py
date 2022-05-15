import pymysql
import boto3
import json
import logging
from decimal_encoder import DecimalEncoder

#
# initialize logging
#
logger = logging.getLogger()
logger.setLevel(logging.INFO)

#
# Full RDS database characterization
# DATABSE: Simple Math App
#
endpoint = 'mathapp.cp32ihh1pwgf.us-west-1.rds.amazonaws.com'
username = 'admin'
password = 'yfbQJnm65amq6d4U'
db_name = 'Math_App'

#
# connect to the RDS database using pymsql. 
# Connection establishment outside the lambda_handler is seen as efficient
# TODO: there is no error handling if connect doesn't work
#
connection = pymysql.connect(host = endpoint,
                             user= username,
                             password = password,
                             database = db_name,)

#
# Setup const values
#
getMethod = 'GET'
postMethod = 'POST'
patchMethod = 'PATCH'
deleteMethod = 'DELETE'
optionsMethod = 'OPTIONS'
healthPath = '\HEALTH'
productPath = '\PRODUCT'
productsPath = '\PRODUCTS'
mathUserPath = '\mathapp'



#
# AWS lambda handler code
# Near replica of Felix Yu Youtube video: https://youtu.be/9eHh946qTIk
# TODO: Full definition of event and context, are there other parameters for the handler?
#
def lambda_handler(event, context): 

    print('start lambda handler')
    #
    # using logging instead of console.log for debug
    # TODO: read this information in the eventlog, whereever that is
    #
    logger.info(event)

    #
    # Parse Event
    # TODO: make httpMethod enum - is in enum? is that the check
    # TODO: Should I process the string futher?
    #
    httpMethod = event['httpMethod'] # GET, POST, PATCH, DELETE, OPTIONS
    path = event['path'] # API path

    if (httpMethod == getMethod) and (path == healthPath):
        response = composeJsonResponse(200)
        
    elif httpMethod == getMethod and path == mathUserPath:
        response = getMath_User(event['queryStringParameters']['Id'])

        """ 
        elif httpMethod == getMethod and path == productsPath:
            response = getProducts()

        elif httpMethod == postMethod and path == productPath:
            response = saveProduct(json.loads(event['body']))

        elif httpMethod == patchMethod and path == productPath:
            requestBody = json.loads(event[' body'])
            response = modifyProduct (requestBody['productId'], requestBody['updatekey'], requestBody['updatevalue'])

        elif httpMethod == deleteMethod and path == productPath:
            requestBody = json.loads(event[' body'])
            response = deleteProduct(requestBody['productId'])
        """

    else:
        response = composeJsonResponse(404, 'Not Found')

    return response


def composeJsonResponse(statusCode, body=None):

    print(f'composeJsonResponse: statusCode {statusCode} body {body}')

    #
    # HTTP status code, json content type and CORS access control '*'
    #
    jsonResponseDict = {
        'isBase64Encoded': 'true',
        'statusCode': statusCode,
        'headers' : {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        }
    }
    print(f'jsonResponseDict no body: {jsonResponseDict}')
    #
    # json encode body and insert into respon dict
    #
    if body is not None:
        jsonResponseDict['body'] = json.dumps(body,
                                      #cls=DecimalEncoder,
                                      indent=4,)
    
    print(f'jsonResponseDict with body: {jsonResponseDict}')

    return jsonResponseDict

 
def getMath_User(productId):
    try:
        cursor = connection.cursor()
        #cursor.execute('SELECT * FROM Math_User')
        #
        # incredible SQL code borrowed from here: https://stackoverflow.com/a/41760134
        #
        # GET a Single User ID
        sqlGetUserSingleUserId = f"""
            SELECT 
                JSON_ARRAYAGG(JSON_OBJECT('Id', Id, 'Name', Name))
            FROM
                Math_User 
            WHERE
                Id={productId}
        """
        
        cursor.execute(sqlGetUserSingleUserId)

        # IMPORTANT: Following select statement returns all data for all users ID
        # cursor.execute("SELECT JSON_ARRAYAGG(JSON_OBJECT('Id', Id, 'Name', Name)) from Math_User")
        #cursor.execute("SELECT JSON_OBJECT('Id', Id, 'Name', Name) from Math_User")

        #rows = cursor.fetchall()
        #TODO: Error handling for fetchone
        rowfo = cursor.fetchone()

        print(f'fetchone row: {rowfo[0]}')

        #for row in rows:
        #    print(f'Array of dictionaries {row[0]}')

        #if 'Item' in response:
        return composeJsonResponse('200', rowfo[0])

        #else:
        #    return composeJsonResponse('404', {'Message': 'getProduct: productID: %s not found' % productId})
    except:
        logger.exception('getting data failed somehow....log your err message')

""" 
#
# Test code for the mathUserPath
#
event = {
        'httpMethod': 'GET',
        'path': mathUserPath,
        'queryStringParameters': {
            'Id': 1,
        }
}
context = {
}
jsonData = lambda_handler(event, context)
print(f'jsonData: {jsonData}')

jsonDataDict = json.loads(jsonData['body'])
print(f'jsonData as a python Dict: {jsonDataDict}')
  """