import json
from handler import lambda_handler
from classifier import varDump

#
# Generic Lambda Rest API test execututor. Uses a dictionary to pass parameters. 
#
def LambdaTestExecute(config):
    
    testHttpMethod = config['testHttpMethod']

    print(f"\n**** Execute Lambda Test: { config['testPath'] }.{ testHttpMethod } ****\n")

    testEvent = {
            'httpMethod': testHttpMethod,
            'path': config['testPath'],
            'queryStringParameters': config['queryStringParameters'],}

    testEvent['body'] = json.dumps(config['testBody'])
    
    context = config['context']

    responseJson = lambda_handler(testEvent, context)
    print(f"{config['testPath']}.{testHttpMethod} Test Response:\n{json.dumps(responseJson,indent=4)}")

    if responseJson != None and 'body' in responseJson:
        body = json.loads(responseJson['body'])
        print(f'{testHttpMethod} body:\t{body}')

    print("")
