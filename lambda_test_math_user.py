from lambda_test import LambdaTestExecute
#
# TODO: the path info is in the wrong spot
#
from handler import restApiPath

# PUT TEST
restApiPutConfig = {
    'testHttpMethod': 'PUT',
    'testPath': restApiPath,
    'queryStringParameters': {},
    'testBody': {'name': 'altuve ',
                 'favorite_color': 'he swing'},
    'context': {},
    'expected_result': {},
}

# GET TEST
restApiGetConfig = {
    'testHttpMethod': 'GET',
    'testPath': restApiPath,
    'queryStringParameters': {'Id': 79,
                              'sort': 'Name:DESC,Favorite_Color:ASC,Id:DESC',},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

# GET ALL VALUES TEST
restApiGetAllConfig = {
    'testHttpMethod': 'GET',
    'testPath': restApiPath,
    'queryStringParameters': {'sort': 'Name:ASC,Favorite_Color:DESC,Id:ASC',},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

# GET ALL VALUES TEST
restApiGetErrorConfig = {
    'testHttpMethod': 'GET',
    'testPath': restApiPath,
    'queryStringParameters': {'Id': 79,
                              'sort': 'Name:DESC,Favorite_Color:ASC,Id:DESC',
                              'Ukraine': "Russia says may I have it?",},
    'testBody': {},
    'context': {},
    'expected_result': {},
}


# POST TEST
restApiPostConfig = {
    'testHttpMethod': 'POST',
    'testPath': restApiPath,
    'queryStringParameters': {},
    'testBody': {'Id': 81,
                 'name': 'Billy E Williams',
                 'favorite_color': 'Offensive Tackle'},
    'context': {},
    'expected_result': {},
}

# DELETE TEST
restApiDeleteConfig = {
    'testHttpMethod': 'DELETE',
    'testPath': restApiPath,
    'queryStringParameters': {},
    'testBody': {'Id': 111},
    'context': {},
    'expected_result': {},
}

#LambdaTestExecute(restApiPutConfig)
#LambdaTestExecute(restApiGetConfig)
#LambdaTestExecute(restApiPostConfig)
#LambdaTestExecute(restApiDeleteConfig)
LambdaTestExecute(restApiGetAllConfig)
#LambdaTestExecute(restApiGetErrorConfig)

