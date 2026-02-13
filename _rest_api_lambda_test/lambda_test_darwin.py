import sys
import json
# update sys path  to include parent folder so lambda_test can import handler.py
sys.path.append('./..')
from lambda_test import lambda_test_execute, lambda_test_summary

database_path = '/darwin2'
areas_path = f'{database_path}/areas2'


################################################
#
# database get request (returns dict of tables in db)
#
get_database_darwin = {
    'test_name': 'get_database_darwin',
    'http_method': 'GET',
    'path': database_path,
    'query_string_params': {},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['areas2', 'domains2', 'profiles2', 'tasks2'],
}

################################################
#
# areas GET (READ) REST API calls
#
get_one_area = {
    'test_name': 'get_one_area',
    'http_method': 'GET',
    'path': areas_path,
    'query_string_params': {'id': '1',},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['area_name'],
}

get_all_area = {
    'test_name': 'get_all_area',
    'http_method': 'GET',
    'path': areas_path,
    'query_string_params': {'creator_fk': '3af9d78e-db31-4892-ab42-d1a731b724dd',},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['area_name'],
}


################################################
#
# CUD lifecycle test: POST → PUT → GET → DELETE
# Creates a record, updates it, verifies, then deletes it.
#
def run_cud_lifecycle_test():
    # POST: create a new area
    post_config = {
        'test_name': 'cud_lifecycle: POST create area',
        'http_method': 'POST',
        'path': areas_path,
        'query_string_params': {},
        'body': {'area_name': 'CUD Lifecycle Test Record',
                 'creator_fk': '3af9d78e-db31-4892-ab42-d1a731b724dd',
                 'closed': '0',
                 'sort_order': '99',
                 'domain_fk': '2',
                },
        'context': {},
        'expected_status': 200,
    }
    post_response = lambda_test_execute(post_config)

    # Extract the new record's id from the response
    # The response body may be double-JSON-encoded (SQL builds a JSON string,
    # then compose_rest_response wraps it with json.dumps again).
    new_id = None
    if post_response and 'body' in post_response:
        body = json.loads(post_response['body'])
        # Unwrap: if body is a list whose first element is a JSON string, parse it
        if isinstance(body, list) and len(body) > 0 and isinstance(body[0], str):
            body = json.loads(body[0])
        if isinstance(body, dict) and 'id' in body:
            new_id = str(body['id'])
        elif isinstance(body, list) and len(body) > 0 and 'id' in body[0]:
            new_id = str(body[0]['id'])

    if not new_id:
        print('FAIL: cud_lifecycle — could not extract id from POST response')
        return

    # PUT: update the record
    put_config = {
        'test_name': 'cud_lifecycle: PUT update area',
        'http_method': 'PUT',
        'path': areas_path,
        'query_string_params': {},
        'body': [{'id': new_id, 'area_name': 'CUD Lifecycle Updated'}],
        'context': {},
        'expected_status': 200,
    }
    lambda_test_execute(put_config)

    # GET: verify the update
    get_config = {
        'test_name': 'cud_lifecycle: GET verify update',
        'http_method': 'GET',
        'path': areas_path,
        'query_string_params': {'id': new_id},
        'body': {},
        'context': {},
        'expected_status': 200,
        'expected_body_contains': ['CUD Lifecycle Updated'],
    }
    lambda_test_execute(get_config)

    # DELETE: clean up
    delete_config = {
        'test_name': 'cud_lifecycle: DELETE area',
        'http_method': 'DELETE',
        'path': areas_path,
        'query_string_params': {},
        'body': {'id': new_id},
        'context': {},
        'expected_status': 200,
    }
    lambda_test_execute(delete_config)


################################################
#
# CUD lifecycle test with special characters (apostrophes, backslashes, quotes)
# Verifies parameterized queries handle SQL-breaking characters correctly.
#
def run_special_char_lifecycle_test():
    special_name = "O'Brien's \"Test\" Area\\Path"

    # POST: create area with special characters
    post_config = {
        'test_name': 'special_char: POST create area with apostrophes',
        'http_method': 'POST',
        'path': areas_path,
        'query_string_params': {},
        'body': {'area_name': special_name,
                 'creator_fk': '3af9d78e-db31-4892-ab42-d1a731b724dd',
                 'closed': '0',
                 'sort_order': '99',
                 'domain_fk': '2',
                },
        'context': {},
        'expected_status': 200,
        'expected_body_contains': ["O'Brien"],
    }
    post_response = lambda_test_execute(post_config)

    # Extract new record id
    new_id = None
    if post_response and 'body' in post_response:
        body = json.loads(post_response['body'])
        if isinstance(body, list) and len(body) > 0 and isinstance(body[0], str):
            body = json.loads(body[0])
        if isinstance(body, dict) and 'id' in body:
            new_id = str(body['id'])
        elif isinstance(body, list) and len(body) > 0 and 'id' in body[0]:
            new_id = str(body[0]['id'])

    if not new_id:
        print('FAIL: special_char — could not extract id from POST response')
        return

    # PUT: update with different special characters
    put_config = {
        'test_name': 'special_char: PUT update with apostrophes',
        'http_method': 'PUT',
        'path': areas_path,
        'query_string_params': {},
        'body': [{'id': new_id, 'area_name': "It's a test; DROP areas2;--"}],
        'context': {},
        'expected_status': 200,
    }
    lambda_test_execute(put_config)

    # GET: verify the special characters round-tripped correctly
    get_config = {
        'test_name': 'special_char: GET verify special chars preserved',
        'http_method': 'GET',
        'path': areas_path,
        'query_string_params': {'id': new_id},
        'body': {},
        'context': {},
        'expected_status': 200,
        'expected_body_contains': ["It's a test; DROP areas2;--"],
    }
    lambda_test_execute(get_config)

    # DELETE: clean up
    delete_config = {
        'test_name': 'special_char: DELETE area',
        'http_method': 'DELETE',
        'path': areas_path,
        'query_string_params': {},
        'body': {'id': new_id},
        'context': {},
        'expected_status': 200,
    }
    lambda_test_execute(delete_config)


################################################
#
# Run all tests
#
lambda_test_execute(get_database_darwin)
lambda_test_execute(get_one_area)
lambda_test_execute(get_all_area)
run_cud_lifecycle_test()
run_special_char_lifecycle_test()
lambda_test_summary()
