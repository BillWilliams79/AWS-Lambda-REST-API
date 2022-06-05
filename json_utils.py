import json
from classifier import  varDump

#
# json response utility function
#
def composeJsonResponse(statusCode, body='', httpMessage=''):

    #print(f'composeJsonResponse: statusCode {statusCode} body {body}')

    #
    # HTTP status code, json content type and CORS access control '*'
    #
    jsonResponseDict = {
        'isBase64Encoded': 'true',
        'statusCode': statusCode,
        # try to add anything here and the api calls fail
        #'statusMessage': httpMessage,
        'headers' : {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'body, Content-Type, Access-Control-Allow-Headers, Access-Control-Allow-Origin, Access-Control-Allow-Methods',
            'Access-Control-Allow-Methods': 'PUT, GET, POST, DELETE, OPTIONS',
            #'Status-Text': httpMessage, # can put headers here, but they don't show up in the fetch response
        }
    }

    varDump(statusCode, 'statusCode')
    if statusCode != '200' and statusCode != '201':
        print(f"message becomes body {body} : {httpMessage}")
        body = json.dumps(httpMessage)
        
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

