import json
from classifier import varDump

#
# json response utility function
#
def compose_rest_response(status_code, body='', http_message=''):

    #
    # Compose AWS Lambda proxy response format
    # https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-output-format
    #
    print(f"HTTP Status Code: {status_code}")

    lambda_rest_api_response = {
        'isBase64Encoded': False,
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'body, Content-Type, Access-Control-Allow-Headers, Access-Control-Allow-Origin, Access-Control-Allow-Methods',
                    'Access-Control-Allow-Methods': 'PUT, GET, POST, DELETE, OPTIONS',
        }
    }

    if status_code not in (200, 201, 204):
        print(f"Error message inserted into body.  {body} : {http_message}")
        body = http_message
 
    #
    # json encode body, insert into response
    #
    if body is not None:
        lambda_rest_api_response['body'] = json.dumps(body)
    else:
        print('body is empty')

    #varDump(lambda_rest_api_response, 'Lambda proxy response')

    return lambda_rest_api_response
