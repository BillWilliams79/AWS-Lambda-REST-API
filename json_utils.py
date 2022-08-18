import json
from classifier import varDump

#
# json response utility function
#
def rest_api_response(status_code, body='', http_message=''):

    #
    # HTTP status code, json content type and CORS access control '*'
    #
    print(f"HTTP Status Code: {status_code}")
    rest_api_response = {
        'isBase64Encoded': 'true',
        'statusCode': status_code,
        'headers' : {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'body, Content-Type, Access-Control-Allow-Headers, Access-Control-Allow-Origin, Access-Control-Allow-Methods',
            'Access-Control-Allow-Methods': 'PUT, GET, POST, DELETE, OPTIONS',
        }
    }

    if status_code != '200' and status_code != '201' and status_code != '204':
        print(f"Error message inserted into body.  {body} : {http_message}")
        body = json.dumps(http_message)
        
    #
    # json encode body and insert into response dict
    #
    #print('about to process body')
    if body is not None:
        rest_api_response['body'] = json.dumps(body)
    else:
        print('body is empty')

    varDump(rest_api_response, 'rest_api_response')

    return rest_api_response

