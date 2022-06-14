from lambda_test import LambdaTestExecute
#
# TODO: the path info is in the wrong spot
#

user_path = '/rest_crud_app/user'
rest_api_path = '/rest_crud_app/rest_api'

################################################
#
# user requests
# 
get_one_user = {
    'testHttpMethod': 'GET',
    'testPath': user_path,
    'queryStringParameters': {'user_id': 1,},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

get_all_user = {
    'testHttpMethod': 'GET',
    'testPath': user_path,
    'queryStringParameters': {'sort': 'user_name:DESC',},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

get_user_return_404 = {
    'testHttpMethod': 'GET',
    'testPath': user_path,
    'queryStringParameters': {'user_id': 2000,},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

get_user_return_400 = {
    'testHttpMethod': 'GET',
    'testPath': user_path,
    'queryStringParameters': {'Squidward': "is very cool",},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

################################################
#
# rest api requests
# 
get_one_rest_api = {
    'testHttpMethod': 'GET',
    'testPath': rest_api_path,
    'queryStringParameters': {'rest_api_id': 1,},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

get_all_rest_api = {
    'testHttpMethod': 'GET',
    'testPath': rest_api_path,
    'queryStringParameters': {'sort': 'user_rest_name:ASC',},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

get_rest_api_return_404 = {
    'testHttpMethod': 'GET',
    'testPath': rest_api_path,
    'queryStringParameters': {'rest_api_id': 3000,},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

get_rest_api_return_400 = {
    'testHttpMethod': 'GET',
    'testPath': rest_api_path,
    'queryStringParameters': {'Barnacles': 1,},
    'testBody': {},
    'context': {},
    'expected_result': {},
}


#LambdaTestExecute(get_one_user)
#LambdaTestExecute(get_all_user)
#LambdaTestExecute(get_user_return_400)
#LambdaTestExecute(get_user_return_404)

LambdaTestExecute(get_one_rest_api)
LambdaTestExecute(get_all_rest_api)
LambdaTestExecute(get_rest_api_return_400)
LambdaTestExecute(get_rest_api_return_404)
