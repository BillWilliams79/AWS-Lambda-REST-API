import json
from handler import lambda_handler
from classifier import varDump, get_var_name

#
# Generic Lambda Rest API test execututor. Uses a dictionary to pass parameters. 
#
def lambda_test_execute(config):
    



    http_method = config.get('http_method')
    path = config.get('path')

    #varDump(locals(), 'lambda_test_execute loals')
    #print(get_variable_name(http_method))
    get_var_name(http_method)
    return

    print(f"\n**** Execute Lambda Test: {http_method} @ {path} ****\n")

    # setup event function similar to the ones received from API Gatway
    event = {'httpMethod': http_method,
             'path': path,
             'queryStringParameters': config.get('query_string_params'),
             'body': json.dumps(config['body']),
    }

    context = config['context']

    # Call lambda Handler
    response_json = lambda_handler(event, context)

    if response_json != None and 'body' in response_json:
        body = json.loads(response_json['body'])
        varDump(body, f'TEST RESULT: {http_method} body')

    print("")
