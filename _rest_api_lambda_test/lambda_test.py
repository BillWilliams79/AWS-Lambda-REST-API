import json
from handler import lambda_handler
from classifier import varDump

#
# Generic Lambda Rest API test executor. Uses a dictionary to pass parameters.
#
# Test results tracking
_test_results = []

def lambda_test_execute(config):

    http_method = config.get('http_method')
    path = config.get('path')
    test_name = config.get('test_name', f'{http_method} {path}')
    expected_status = config.get('expected_status')
    expected_body_contains = config.get('expected_body_contains', [])

    print(f"\n**** Execute Lambda Test: {test_name} ****\n")

    # setup event function similar to the ones received from API Gateway
    event = {'httpMethod': http_method,
             'path': path,
             'queryStringParameters': config.get('query_string_params'),
             'body': json.dumps(config['body']),
    }

    context = config['context']

    varDump(event, 'event from inside lambda_test')
    # Call lambda Handler
    response = lambda_handler(event, context)

    if response != None and 'body' in response:
        body = json.loads(response['body'])
        varDump(body, f'TEST RESULT: {http_method} body')

    # Assertion checking
    passed = True
    failure_details = []

    if expected_status is not None:
        actual_status = response.get('statusCode') if response else None
        if actual_status != expected_status:
            passed = False
            failure_details.append(f'expected status {expected_status}, got {actual_status}')

    if expected_body_contains and response and 'body' in response:
        body_str = response['body']
        for substring in expected_body_contains:
            if substring not in body_str:
                passed = False
                failure_details.append(f'body missing "{substring}"')

    if expected_status is not None:
        if passed:
            print(f'PASS: {test_name} (status {expected_status})')
        else:
            print(f'FAIL: {test_name} — {"; ".join(failure_details)}')
        _test_results.append({'test_name': test_name, 'passed': passed})

    print("")
    return response


def lambda_test_summary():
    total = len(_test_results)
    passed = sum(1 for r in _test_results if r['passed'])
    failed = total - passed
    print(f'\n{"="*50}')
    print(f'Test Summary: {passed} passed, {failed} failed out of {total} total')
    print(f'{"="*50}')
