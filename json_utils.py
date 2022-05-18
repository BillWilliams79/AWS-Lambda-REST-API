import json

#
# json response utility function
#
def composeJsonResponse(statusCode, body=None):

    #print(f'composeJsonResponse: statusCode {statusCode} body {body}')

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
    #print(f'jsonResponseDict no body: {jsonResponseDict}')
    #
    # json encode body and insert into respon dict
    #
    if body is not None:
        jsonResponseDict['body'] = json.dumps(body,
                                      #cls=DecimalEncoder,
                                      indent=4,)
    
    #print(f'jsonResponseDict with body: {jsonResponseDict}')

    return jsonResponseDict

