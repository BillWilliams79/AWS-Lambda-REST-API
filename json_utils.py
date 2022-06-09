import json
from classifier import  varDump

#
# json response utility function
#
def composeJsonResponse(statusCode, body='', httpMessage=''):

    #
    # HTTP status code, json content type and CORS access control '*'
    #
    print(f"HTTP Status Code: {statusCode}")
    jsonResponseDict = {
        'isBase64Encoded': 'true',
        'statusCode': statusCode,
        'headers' : {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'body, Content-Type, Access-Control-Allow-Headers, Access-Control-Allow-Origin, Access-Control-Allow-Methods',
            'Access-Control-Allow-Methods': 'PUT, GET, POST, DELETE, OPTIONS',
        }
    }

    if statusCode != '200' and statusCode != '201' and statusCode != '204':
        print(f"Error message inserted into body.  {body} : {httpMessage}")
        body = json.dumps(httpMessage)
        
    #
    # json encode body and insert into response dict
    #
    if body is not None:
        jsonResponseDict['body'] = json.dumps(body,
                                      #cls=DecimalEncoder,
                                      indent=4,)
    
    #varDump(jsonResponseDict, "JSON response dict with headers etc.")
    return jsonResponseDict

