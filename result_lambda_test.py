from lambda_test import LambaTestExecute
#
# TODO: the path info is in the wrong spot
#
from handler import mathUserPath, resultPath

# PUT TEST
resultPutConfig = {
    'testHttpMethod': 'PUT',
    'testPath': resultPath,
    'queryStringParameters': {},
    'testBody': {'Score': 10,
                 'Tries': 11,
                 'User_Id': 6,
                 },
    'context': {},
    'expected_result': {},
}

# GET TEST
resultGetConfig = {
    'testHttpMethod': 'GET',
    'testPath': resultPath,
    'queryStringParameters': {'Id': 4},
    'testBody': {},
    'context': {},
    'expected_result': {},
}

# POST TEST
resultPostConfig = {
    'testHttpMethod': 'POST',
    'testPath': resultPath,
    'queryStringParameters': {},
    'testBody': {'Id': 4,
                 'Score': 20,
                 'Tries': 21,
                 'User_Id': 6,
                 },
    'context': {},
    'expected_result': {},
}

# DELETE TEST
resultDeleteConfig = {
    'testHttpMethod': 'DELETE',
    'testPath': resultPath,
    'queryStringParameters': {},
    'testBody': {'Id': 4},
    'context': {},
    'expected_result': {},
}

LambaTestExecute(resultPutConfig)
LambaTestExecute(resultGetConfig)
LambaTestExecute(resultPostConfig)
LambaTestExecute(resultDeleteConfig)
