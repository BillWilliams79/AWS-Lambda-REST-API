from lambda_test import LambaTestExecute
#
# TODO: the path info is in the wrong spot
#
from handler import mathUserPath

# PUT TEST
mathUserPutConfig = {
    'testHttpMethod': 'PUT',
    'testPath': mathUserPath,
    'queryStringParameters': {},
    'testBody': {'name': 'altuve ',
                 'favorite_color': 'he swing'},
    'context': {},
    'expected_result': {},
}

# GET TEST
mathUserGetConfig = {
    'testHttpMethod': 'GET',
    'testPath': mathUserPath,
    'queryStringParameters': {'Id': 79},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

# POST TEST
mathUserPostConfig = {
    'testHttpMethod': 'POST',
    'testPath': mathUserPath,
    'queryStringParameters': {'Id': 16,},
    'testBody': {'Id': 81,
                 'name': 'Billy E Williams',
                 'favorite_color': 'Offensive Tackle'},
    'context': {},
    'expected_result': {},
}

# DELETE TEST
mathUserDeleteConfig = {
    'testHttpMethod': 'DELETE',
    'testPath': mathUserPath,
    'queryStringParameters': {},
    'testBody': {'Id': 111},
    'context': {},
    'expected_result': {},
}

LambaTestExecute(mathUserPutConfig)
LambaTestExecute(mathUserGetConfig)
LambaTestExecute(mathUserPostConfig)
LambaTestExecute(mathUserDeleteConfig)
