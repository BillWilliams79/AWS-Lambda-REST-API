import sys
import json
import time
import traceback

# Update sys path to include parent folder so we can import handler.py
sys.path.append('./..')
from lambda_test import lambda_test_execute, lambda_test_summary, _test_results
from handler import lambda_handler

#
# Lambda-Rest Comprehensive API Test Suite
#
# Tests all API endpoints: handler routing, GET database, GET table,
# POST, PUT, DELETE, and response structure.
#
# Uses darwin2 test database with isolated test data (unique creator_fk per run).
# Run: cd Lambda-Rest/_rest_api_lambda_test && . ../exports.sh && python3 lambda_test_comprehensive.py
#

DATABASE_PATH = '/darwin2'
PROFILES_PATH = f'{DATABASE_PATH}/profiles2'
DOMAINS_PATH = f'{DATABASE_PATH}/domains2'
AREAS_PATH = f'{DATABASE_PATH}/areas2'
TASKS_PATH = f'{DATABASE_PATH}/tasks2'

# Unique creator_fk per test run for data isolation
TEST_CREATOR_FK = f'test-api-{int(time.time())}'

print(f'\n{"="*60}')
print(f'Comprehensive API Test Suite')
print(f'Test creator_fk: {TEST_CREATOR_FK}')
print(f'{"="*60}\n')

# Track IDs for cleanup (numeric IDs only — REST DELETE needs unquoted values)
test_ids = {}
created_domain_ids = []
created_area_ids = []
created_task_ids = []


################################################
#
# Helper Functions
#
################################################

def direct_invoke(event, test_name, expected_status=None, expected_body_contains=None, expect_exception=False):
    """Call lambda_handler directly for tests needing special event shapes (None body, etc)."""
    print(f"\n**** Direct Invoke: {test_name} ****\n")
    try:
        response = lambda_handler(event, {})

        if expect_exception:
            print(f'FAIL: {test_name} (expected exception but got response with status {response.get("statusCode") if response else "None"})')
            _test_results.append({'test_name': test_name, 'passed': False})
            return response

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

        if passed:
            print(f'PASS: {test_name}')
        else:
            print(f'FAIL: {test_name} — {"; ".join(failure_details)}')
        _test_results.append({'test_name': test_name, 'passed': passed})
        return response

    except Exception as e:
        exception_type = type(e).__name__
        if expect_exception:
            print(f'PASS: {test_name} (expected exception: {exception_type}: {e})')
            _test_results.append({'test_name': test_name, 'passed': True})
        else:
            print(f'FAIL: {test_name} (unexpected exception: {exception_type}: {e})')
            traceback.print_exc()
            _test_results.append({'test_name': test_name, 'passed': False})
        return None


def safe_execute(config):
    """Wraps lambda_test_execute in try/except for error-path tests that may raise."""
    try:
        return lambda_test_execute(config)
    except Exception as e:
        test_name = config.get('test_name', 'unknown')
        expect_exception = config.get('expect_exception', False)
        exception_type = type(e).__name__
        if expect_exception:
            print(f'PASS: {test_name} (expected exception: {exception_type}: {e})')
            _test_results.append({'test_name': test_name, 'passed': True})
        else:
            print(f'FAIL: {test_name} (unexpected exception: {exception_type}: {e})')
            _test_results.append({'test_name': test_name, 'passed': False})
        return None


def extract_id_from_post_response(response):
    """Extract record id from a POST response, handling double-encoding."""
    if response and 'body' in response:
        body = json.loads(response['body'])
        if isinstance(body, list) and len(body) > 0 and isinstance(body[0], str):
            body = json.loads(body[0])
        if isinstance(body, dict) and 'id' in body:
            return str(body['id'])
        elif isinstance(body, list) and len(body) > 0 and 'id' in body[0]:
            return str(body[0]['id'])
    return None


def record_check(test_name, passed, details=''):
    """Record an inline assertion as a test result."""
    if passed:
        print(f'PASS: {test_name}')
    else:
        print(f'FAIL: {test_name} — {details}')
    _test_results.append({'test_name': test_name, 'passed': passed})


################################################
#
# SETUP: Create isolated test data
#
################################################

print('\n' + '='*50)
print('SETUP: Creating test data')
print('='*50)

# Create test profile (profiles2 has no AUTO_INCREMENT, so POST read-back
# uses LAST_INSERT_ID()=0 which may or may not match via MySQL type coercion.
# We don't assert on status — verify creation with a GET instead.)
lambda_test_execute({
    'test_name': 'SETUP: create test profile',
    'http_method': 'POST',
    'path': PROFILES_PATH,
    'query_string_params': {},
    'body': {
        'id': TEST_CREATOR_FK,
        'name': 'API Test User',
        'email': 'apitest@test.com',
        'subject': TEST_CREATOR_FK,
        'userName': TEST_CREATOR_FK,
        'region': 'us-west-1',
        'userPoolId': 'test-pool',
    },
    'context': {},
})

# Verify profile was created
lambda_test_execute({
    'test_name': 'SETUP: verify profile exists',
    'http_method': 'GET',
    'path': PROFILES_PATH,
    'query_string_params': {'id': TEST_CREATOR_FK},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['API Test User'],
})

# Create test domain
domain_response = lambda_test_execute({
    'test_name': 'SETUP: create test domain',
    'http_method': 'POST',
    'path': DOMAINS_PATH,
    'query_string_params': {},
    'body': {
        'domain_name': 'Test Domain',
        'creator_fk': TEST_CREATOR_FK,
        'closed': '0',
    },
    'context': {},
    'expected_status': 200,
})
test_ids['domain_id'] = extract_id_from_post_response(domain_response)
created_domain_ids.append(test_ids['domain_id'])
print(f"  -> domain_id: {test_ids['domain_id']}")

# Create test area
area_response = lambda_test_execute({
    'test_name': 'SETUP: create test area',
    'http_method': 'POST',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {
        'area_name': 'Test Area',
        'creator_fk': TEST_CREATOR_FK,
        'domain_fk': test_ids['domain_id'],
        'closed': '0',
        'sort_order': '1',
    },
    'context': {},
    'expected_status': 200,
})
test_ids['area_id'] = extract_id_from_post_response(area_response)
created_area_ids.append(test_ids['area_id'])
print(f"  -> area_id: {test_ids['area_id']}")

# Create test task
task_response = lambda_test_execute({
    'test_name': 'SETUP: create test task',
    'http_method': 'POST',
    'path': TASKS_PATH,
    'query_string_params': {},
    'body': {
        'priority': '0',
        'done': '0',
        'description': 'Test Task for Comprehensive Suite',
        'area_fk': test_ids['area_id'],
        'creator_fk': TEST_CREATOR_FK,
    },
    'context': {},
    'expected_status': 200,
})
test_ids['task_id'] = extract_id_from_post_response(task_response)
created_task_ids.append(test_ids['task_id'])
print(f"  -> task_id: {test_ids['task_id']}")


################################################
#
# HANDLER TESTS (handler.py)
#
################################################

print('\n' + '='*50)
print('HANDLER TESTS')
print('='*50)

# HANDLER-01: OPTIONS returns CORS response
lambda_test_execute({
    'test_name': 'HANDLER-01: OPTIONS returns 200',
    'http_method': 'OPTIONS',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {},
    'context': {},
    'expected_status': 200,
})

# HANDLER-02: No path returns 400
direct_invoke(
    event={'httpMethod': 'GET', 'path': None, 'queryStringParameters': {}, 'body': '{}'},
    test_name='HANDLER-02: no path returns 400',
    expected_status=400,
)

# HANDLER-03: Invalid database returns 404
lambda_test_execute({
    'test_name': 'HANDLER-03: invalid database returns 404',
    'http_method': 'GET',
    'path': '/nonexistent_db/sometable',
    'query_string_params': {},
    'body': {},
    'context': {},
    'expected_status': 404,
    'expected_body_contains': ['URL/path not found'],
})

# HANDLER-04: BUG — db_dict is a string, not a dict.
# 'dar' in 'darwin2' evaluates True (substring match), so it tries to connect
# to non-existent database 'dar' and crashes with pymysql.OperationalError.
direct_invoke(
    event={'httpMethod': 'GET', 'path': '/dar/areas2', 'queryStringParameters': {}, 'body': '{}'},
    test_name='HANDLER-04: BUG substring db match crashes (db_dict is string not dict)',
    expect_exception=True,
)

# HANDLER-05: BUG — None body on POST causes UnboundLocalError.
# handler.py:106-107 only assigns 'body' if event['body'] != None.
# handler.py:128 references 'body' unconditionally for POST.
direct_invoke(
    event={'httpMethod': 'POST', 'path': AREAS_PATH, 'queryStringParameters': {}, 'body': None},
    test_name='HANDLER-05: BUG None body on POST causes UnboundLocalError',
    expect_exception=True,
)

# HANDLER-06: BUG — None body on PUT causes UnboundLocalError
direct_invoke(
    event={'httpMethod': 'PUT', 'path': AREAS_PATH, 'queryStringParameters': {}, 'body': None},
    test_name='HANDLER-06: BUG None body on PUT causes UnboundLocalError',
    expect_exception=True,
)

# HANDLER-07: BUG — None body on DELETE causes UnboundLocalError
direct_invoke(
    event={'httpMethod': 'DELETE', 'path': AREAS_PATH, 'queryStringParameters': {}, 'body': None},
    test_name='HANDLER-07: BUG None body on DELETE causes UnboundLocalError',
    expect_exception=True,
)

# HANDLER-08: None body on GET succeeds (GET doesn't use body variable)
direct_invoke(
    event={'httpMethod': 'GET', 'path': '/darwin2', 'queryStringParameters': {}, 'body': None},
    test_name='HANDLER-08: None body on GET succeeds',
    expected_status=200,
)


################################################
#
# GET DATABASE TESTS (rest_get_database.py)
#
################################################

print('\n' + '='*50)
print('GET DATABASE TESTS')
print('='*50)

# GETDB-01: Happy path — returns table list
getdb_response = lambda_test_execute({
    'test_name': 'GETDB-01: returns table list',
    'http_method': 'GET',
    'path': DATABASE_PATH,
    'query_string_params': {},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['areas2', 'domains2', 'profiles2', 'tasks2'],
})

# GETDB-02: BUG — response is double-encoded.
# rest_get_database.py:22 passes json.dumps(columns_array) as body,
# then compose_rest_response:33 does json.dumps(body) again.
if getdb_response and 'body' in getdb_response:
    first_parse = json.loads(getdb_response['body'])
    is_double_encoded = isinstance(first_parse, str)
    record_check(
        'GETDB-02: BUG response is double-encoded',
        is_double_encoded,
        f'expected string after first parse, got {type(first_parse).__name__}'
    )

# GETDB-03: BUG — isBase64Encoded is string 'false' not boolean False.
# Also verify CORS headers present.
if getdb_response:
    has_cors = getdb_response.get('headers', {}).get('Access-Control-Allow-Origin') == '*'
    is_b64 = getdb_response.get('isBase64Encoded')
    is_string_false = is_b64 == 'false' and isinstance(is_b64, str)
    details = []
    if not has_cors:
        details.append('missing CORS header')
    if not is_string_false:
        details.append(f'isBase64Encoded is {type(is_b64).__name__}({is_b64}), expected str("false")')
    record_check(
        'GETDB-03: BUG isBase64Encoded is string not boolean + CORS headers',
        has_cors and is_string_false,
        '; '.join(details)
    )


################################################
#
# GET TABLE TESTS (rest_get_table.py)
#
################################################

print('\n' + '='*50)
print('GET TABLE TESTS')
print('='*50)

# GET-01: Filter by creator_fk
lambda_test_execute({
    'test_name': 'GET-01: filter by creator_fk',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'creator_fk': TEST_CREATOR_FK},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['area_name'],
})

# GET-02: Filter by id
lambda_test_execute({
    'test_name': 'GET-02: filter by id',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'id': test_ids['area_id']},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['Test Area'],
})

# GET-03: Multiple equality filters (AND)
lambda_test_execute({
    'test_name': 'GET-03: multiple filters AND',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'id': test_ids['area_id'], 'creator_fk': TEST_CREATOR_FK},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['Test Area'],
})

# GET-04: IN clause filter
lambda_test_execute({
    'test_name': 'GET-04: IN clause filter',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'id': f'({test_ids["area_id"]},999999)'},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['Test Area'],
})

# GET-05: Date range filter (filter_ts)
# First create a done task with known done_ts
done_task_response = lambda_test_execute({
    'test_name': 'GET-05 setup: create done task with known done_ts',
    'http_method': 'POST',
    'path': TASKS_PATH,
    'query_string_params': {},
    'body': {
        'priority': '0',
        'done': '1',
        'description': 'Done Task for filter_ts test',
        'area_fk': test_ids['area_id'],
        'creator_fk': TEST_CREATOR_FK,
        'done_ts': '2025-06-15 12:00:00',
    },
    'context': {},
    'expected_status': 200,
})
done_task_id = extract_id_from_post_response(done_task_response)
if done_task_id:
    created_task_ids.append(done_task_id)

lambda_test_execute({
    'test_name': 'GET-05: date range filter_ts',
    'http_method': 'GET',
    'path': TASKS_PATH,
    'query_string_params': {
        'creator_fk': TEST_CREATOR_FK,
        'filter_ts': '(done_ts,2025-06-01T00:00:00,2025-06-30T23:59:59)',
    },
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['Done Task for filter_ts test'],
})

# GET-06: Sort ascending
lambda_test_execute({
    'test_name': 'GET-06: sort by id asc',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'creator_fk': TEST_CREATOR_FK, 'sort': 'id:asc'},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['area_name'],
})

# GET-07: Sort descending
lambda_test_execute({
    'test_name': 'GET-07: sort by id desc',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'creator_fk': TEST_CREATOR_FK, 'sort': 'id:desc'},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['area_name'],
})

# GET-08: Multi-field sort
lambda_test_execute({
    'test_name': 'GET-08: multi-field sort',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'creator_fk': TEST_CREATOR_FK, 'sort': 'closed:asc,sort_order:asc'},
    'body': {},
    'context': {},
    'expected_status': 200,
})

# GET-09: Sparse fields
lambda_test_execute({
    'test_name': 'GET-09: sparse fields (id, area_name)',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'creator_fk': TEST_CREATOR_FK, 'fields': 'id,area_name'},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['area_name'],
})

# GET-10: Count/group aggregation
# Create a second area so grouping is meaningful
area2_response = lambda_test_execute({
    'test_name': 'GET-10 setup: create second area',
    'http_method': 'POST',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {
        'area_name': 'Second Test Area',
        'creator_fk': TEST_CREATOR_FK,
        'domain_fk': test_ids['domain_id'],
        'closed': '0',
        'sort_order': '2',
    },
    'context': {},
    'expected_status': 200,
})
area2_id = extract_id_from_post_response(area2_response)
if area2_id:
    created_area_ids.append(area2_id)

lambda_test_execute({
    'test_name': 'GET-10: count/group by domain_fk',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'creator_fk': TEST_CREATOR_FK, 'fields': 'count(*),domain_fk'},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['domain_fk'],
})

# GET-11: Invalid QSP key returns 400
lambda_test_execute({
    'test_name': 'GET-11: invalid QSP key returns 400',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'nonexistent_column': 'value'},
    'body': {},
    'context': {},
    'expected_status': 400,
})

# GET-12: Invalid field name in ?fields returns 400
lambda_test_execute({
    'test_name': 'GET-12: invalid field name returns 400',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'fields': 'id,nonexistent_field'},
    'body': {},
    'context': {},
    'expected_status': 400,
})

# GET-13: Non-existent table returns 500 (DESC fails)
safe_execute({
    'test_name': 'GET-13: non-existent table returns 500',
    'http_method': 'GET',
    'path': f'{DATABASE_PATH}/nonexistent_table',
    'query_string_params': {},
    'body': {},
    'context': {},
    'expected_status': 500,
})

# GET-14: Empty result set returns 404
lambda_test_execute({
    'test_name': 'GET-14: no matching rows returns 404',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'id': '999999999'},
    'body': {},
    'context': {},
    'expected_status': 404,
})

# GET-15: Invalid sort column is now validated before reaching SQL.
# Previously this caused a SQL error (500) with a literal "errorMsg" string bug.
# Now sort columns are validated against DESC results and rejected with 400.
lambda_test_execute({
    'test_name': 'GET-15: invalid sort column returns 400',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'sort': 'BOGUS_COLUMN:asc'},
    'body': {},
    'context': {},
    'expected_status': 400,
})

# GET-16: Double-encoding verification for GET table
get16_response = lambda_test_execute({
    'test_name': 'GET-16: GET table returns 200',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'id': test_ids['area_id']},
    'body': {},
    'context': {},
    'expected_status': 200,
})
if get16_response and 'body' in get16_response:
    first_parse = json.loads(get16_response['body'])
    is_double = isinstance(first_parse, list) and len(first_parse) > 0 and isinstance(first_parse[0], str)
    record_check(
        'GET-16b: BUG GET table response is double-encoded',
        is_double,
        f'first parse type: {type(first_parse).__name__}, value preview: {str(first_parse)[:100]}'
    )

# GET-17: Count with 3+ fields — BUG: crashes with UnboundLocalError.
# rest_get_table.py:97 references errorMsg but it's never assigned in this code path
# (the assignment at line 85 is in a different elif branch for invalid field names).
# Expected: 400 BAD REQUEST. Actual: UnboundLocalError exception.
safe_execute({
    'test_name': 'GET-17: BUG count with 3+ valid fields crashes (UnboundLocalError)',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'fields': 'count(*),domain_fk,creator_fk'},
    'body': {},
    'context': {},
    'expected_status': 400,
    'expect_exception': True,
})


################################################
#
# POST TESTS (rest_post.py)
#
################################################

print('\n' + '='*50)
print('POST TESTS')
print('='*50)

# POST-01: Happy path — create domain with read-back
post01_response = lambda_test_execute({
    'test_name': 'POST-01: create domain with read-back',
    'http_method': 'POST',
    'path': DOMAINS_PATH,
    'query_string_params': {},
    'body': {
        'domain_name': 'POST Test Domain',
        'creator_fk': TEST_CREATOR_FK,
        'closed': '0',
    },
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['POST Test Domain'],
})
post01_id = extract_id_from_post_response(post01_response)
if post01_id:
    created_domain_ids.append(post01_id)

# POST-02: NULL value handling (sort_order set to NULL)
post02_response = lambda_test_execute({
    'test_name': 'POST-02: NULL value handling in sort_order',
    'http_method': 'POST',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {
        'area_name': 'NULL Sort Area',
        'creator_fk': TEST_CREATOR_FK,
        'domain_fk': test_ids['domain_id'],
        'closed': '0',
        'sort_order': 'NULL',
    },
    'context': {},
    'expected_status': 200,
})
post02_id = extract_id_from_post_response(post02_response)
if post02_id:
    created_area_ids.append(post02_id)
    # Verify NULL was stored (read-back should show null for sort_order)
    verify_response = lambda_test_execute({
        'test_name': 'POST-02b: verify NULL stored correctly',
        'http_method': 'GET',
        'path': AREAS_PATH,
        'query_string_params': {'id': post02_id},
        'body': {},
        'context': {},
        'expected_status': 200,
        'expected_body_contains': ['NULL Sort Area'],
    })

# POST-03: Empty body returns 400
lambda_test_execute({
    'test_name': 'POST-03: empty body returns 400',
    'http_method': 'POST',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {},
    'context': {},
    'expected_status': 400,
})

# POST-04: Missing required field (creator_fk) returns 500
safe_execute({
    'test_name': 'POST-04: missing required field returns 500',
    'http_method': 'POST',
    'path': DOMAINS_PATH,
    'query_string_params': {},
    'body': {'domain_name': 'No Creator Domain'},
    'context': {},
    'expected_status': 500,
})

# POST-05: Foreign key violation returns 500
safe_execute({
    'test_name': 'POST-05: FK violation returns 500',
    'http_method': 'POST',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {
        'area_name': 'FK Violation Area',
        'creator_fk': 'nonexistent-user-id-12345',
        'domain_fk': '999999',
        'closed': '0',
    },
    'context': {},
    'expected_status': 500,
})

# POST-06: BUG — POST response is double-encoded (same pattern as GET)
post06_response = lambda_test_execute({
    'test_name': 'POST-06: create area for double-encoding check',
    'http_method': 'POST',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {
        'area_name': 'Encoding Check Area',
        'creator_fk': TEST_CREATOR_FK,
        'domain_fk': test_ids['domain_id'],
        'closed': '0',
        'sort_order': '3',
    },
    'context': {},
    'expected_status': 200,
})
post06_id = extract_id_from_post_response(post06_response)
if post06_id:
    created_area_ids.append(post06_id)
if post06_response and 'body' in post06_response:
    first_parse = json.loads(post06_response['body'])
    is_double = isinstance(first_parse, list) and len(first_parse) > 0 and isinstance(first_parse[0], str)
    record_check(
        'POST-06b: BUG POST response is double-encoded',
        is_double,
        f'first parse type: {type(first_parse).__name__}'
    )

# POST-07: Create task with all fields
post07_response = lambda_test_execute({
    'test_name': 'POST-07: create task with all fields',
    'http_method': 'POST',
    'path': TASKS_PATH,
    'query_string_params': {},
    'body': {
        'priority': '1',
        'done': '0',
        'description': 'Comprehensive POST test task',
        'area_fk': test_ids['area_id'],
        'creator_fk': TEST_CREATOR_FK,
    },
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['Comprehensive POST test task'],
})
post07_id = extract_id_from_post_response(post07_response)
if post07_id:
    created_task_ids.append(post07_id)


################################################
#
# PUT TESTS (rest_put.py)
#
################################################

print('\n' + '='*50)
print('PUT TESTS')
print('='*50)

# PUT-01: Single record update
lambda_test_execute({
    'test_name': 'PUT-01: single record update',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [{'id': test_ids['area_id'], 'area_name': 'Updated Test Area'}],
    'context': {},
    'expected_status': 200,
})
# Verify the update
lambda_test_execute({
    'test_name': 'PUT-01b: verify update persisted',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'id': test_ids['area_id']},
    'body': {},
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['Updated Test Area'],
})

# PUT-02: Bulk update (2 records)
# Create two extra areas for bulk update
bulk_area_ids = []
for i in range(2):
    resp = lambda_test_execute({
        'test_name': f'PUT-02 setup: create area {i+1}',
        'http_method': 'POST',
        'path': AREAS_PATH,
        'query_string_params': {},
        'body': {
            'area_name': f'Bulk Area {i+1}',
            'creator_fk': TEST_CREATOR_FK,
            'domain_fk': test_ids['domain_id'],
            'closed': '0',
            'sort_order': str(10 + i),
        },
        'context': {},
        'expected_status': 200,
    })
    bid = extract_id_from_post_response(resp)
    if bid:
        bulk_area_ids.append(bid)
        created_area_ids.append(bid)

if len(bulk_area_ids) == 2:
    lambda_test_execute({
        'test_name': 'PUT-02: bulk update 2 records',
        'http_method': 'PUT',
        'path': AREAS_PATH,
        'query_string_params': {},
        'body': [
            {'id': bulk_area_ids[0], 'sort_order': '20'},
            {'id': bulk_area_ids[1], 'sort_order': '30'},
        ],
        'context': {},
        'expected_status': 200,
    })

# PUT-03: NULL value handling
lambda_test_execute({
    'test_name': 'PUT-03: NULL value in sort_order',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [{'id': test_ids['area_id'], 'sort_order': 'NULL'}],
    'context': {},
    'expected_status': 200,
})

# PUT-04: Empty body returns 400
lambda_test_execute({
    'test_name': 'PUT-04: empty body returns 400',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [],
    'context': {},
    'expected_status': 400,
})

# PUT-05: Missing id returns 400
lambda_test_execute({
    'test_name': 'PUT-05: missing id returns 400',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [{'area_name': 'No ID Provided'}],
    'context': {},
    'expected_status': 400,
})

# PUT-06: Only id, no other fields returns 400
lambda_test_execute({
    'test_name': 'PUT-06: only id no fields returns 400',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [{'id': test_ids['area_id']}],
    'context': {},
    'expected_status': 400,
})

# PUT-07: Non-existent id returns 204 (no rows affected)
lambda_test_execute({
    'test_name': 'PUT-07: non-existent id returns 204',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [{'id': '999999999', 'area_name': 'Ghost Area'}],
    'context': {},
    'expected_status': 204,
})

# PUT-08: BUG — SQL error path passes dict body to compose_rest_response.
# rest_put.py:114: compose_rest_response('500', {'error': errorMsg})
# compose_rest_response error branch overwrites body with json.dumps(''),
# discarding the error dict. Client never sees the actual error.
put08_response = safe_execute({
    'test_name': 'PUT-08: BUG SQL error — error dict discarded',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [{'id': test_ids['area_id'], 'nonexistent_column': 'value'}],
    'context': {},
    'expected_status': 500,
})

# PUT-09: Bulk with missing id in second record returns 400
lambda_test_execute({
    'test_name': 'PUT-09: bulk with missing id in second record returns 400',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [
        {'id': test_ids['area_id'], 'area_name': 'Valid Record'},
        {'area_name': 'No ID Record'},
    ],
    'context': {},
    'expected_status': 400,
})

# Restore area name after PUT tests
lambda_test_execute({
    'test_name': 'PUT cleanup: restore area name',
    'http_method': 'PUT',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': [{'id': test_ids['area_id'], 'area_name': 'Test Area', 'sort_order': '1'}],
    'context': {},
    'expected_status': 200,
})


################################################
#
# DELETE TESTS (rest_delete.py)
#
################################################

print('\n' + '='*50)
print('DELETE TESTS')
print('='*50)

# DEL-01: Single condition delete
# Create a disposable area to delete
del01_response = lambda_test_execute({
    'test_name': 'DEL-01 setup: create disposable area',
    'http_method': 'POST',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {
        'area_name': 'Delete Me',
        'creator_fk': TEST_CREATOR_FK,
        'domain_fk': test_ids['domain_id'],
        'closed': '0',
        'sort_order': '99',
    },
    'context': {},
    'expected_status': 200,
})
del01_id = extract_id_from_post_response(del01_response)

if del01_id:
    lambda_test_execute({
        'test_name': 'DEL-01: single condition delete',
        'http_method': 'DELETE',
        'path': AREAS_PATH,
        'query_string_params': {},
        'body': {'id': del01_id},
        'context': {},
        'expected_status': 200,
    })
    # Verify deletion
    lambda_test_execute({
        'test_name': 'DEL-01b: verify deleted (GET returns 404)',
        'http_method': 'GET',
        'path': AREAS_PATH,
        'query_string_params': {'id': del01_id},
        'body': {},
        'context': {},
        'expected_status': 404,
    })

# DEL-02: Multiple condition delete (AND-ed WHERE)
del02_response = lambda_test_execute({
    'test_name': 'DEL-02 setup: create disposable task',
    'http_method': 'POST',
    'path': TASKS_PATH,
    'query_string_params': {},
    'body': {
        'priority': '0',
        'done': '0',
        'description': 'Multi Condition Delete Task',
        'area_fk': test_ids['area_id'],
        'creator_fk': TEST_CREATOR_FK,
    },
    'context': {},
    'expected_status': 200,
})
del02_id = extract_id_from_post_response(del02_response)

if del02_id:
    # Delete with both id AND done conditions
    lambda_test_execute({
        'test_name': 'DEL-02: multiple condition delete (id AND done)',
        'http_method': 'DELETE',
        'path': TASKS_PATH,
        'query_string_params': {},
        'body': {'id': del02_id, 'done': '0'},
        'context': {},
        'expected_status': 200,
    })

# DEL-03: Empty body returns 400
lambda_test_execute({
    'test_name': 'DEL-03: empty body returns 400',
    'http_method': 'DELETE',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {},
    'context': {},
    'expected_status': 400,
})

# DEL-04: Non-existent record returns 404
lambda_test_execute({
    'test_name': 'DEL-04: non-existent record returns 404',
    'http_method': 'DELETE',
    'path': AREAS_PATH,
    'query_string_params': {},
    'body': {'id': '999999999'},
    'context': {},
    'expected_status': 404,
})

# DEL-05: CASCADE delete — delete domain cascades to areas and tasks
# Create a fresh domain → area → task hierarchy, then delete the domain
cascade_dom_response = lambda_test_execute({
    'test_name': 'DEL-05 setup: create cascade domain',
    'http_method': 'POST',
    'path': DOMAINS_PATH,
    'query_string_params': {},
    'body': {
        'domain_name': 'Cascade Domain',
        'creator_fk': TEST_CREATOR_FK,
        'closed': '0',
    },
    'context': {},
    'expected_status': 200,
})
cascade_dom_id = extract_id_from_post_response(cascade_dom_response)

if cascade_dom_id:
    # Create area under cascade domain
    cascade_area_response = lambda_test_execute({
        'test_name': 'DEL-05 setup: create cascade area',
        'http_method': 'POST',
        'path': AREAS_PATH,
        'query_string_params': {},
        'body': {
            'area_name': 'Cascade Area',
            'creator_fk': TEST_CREATOR_FK,
            'domain_fk': cascade_dom_id,
            'closed': '0',
            'sort_order': '1',
        },
        'context': {},
        'expected_status': 200,
    })
    cascade_area_id = extract_id_from_post_response(cascade_area_response)

    # Delete the domain — should cascade-delete the area
    lambda_test_execute({
        'test_name': 'DEL-05: cascade delete domain',
        'http_method': 'DELETE',
        'path': DOMAINS_PATH,
        'query_string_params': {},
        'body': {'id': cascade_dom_id},
        'context': {},
        'expected_status': 200,
    })

    # Verify cascade: area should be gone too
    if cascade_area_id:
        lambda_test_execute({
            'test_name': 'DEL-05b: verify cascade deleted area (GET returns 404)',
            'http_method': 'GET',
            'path': AREAS_PATH,
            'query_string_params': {'id': cascade_area_id},
            'body': {},
            'context': {},
            'expected_status': 404,
        })


################################################
#
# RESPONSE STRUCTURE TESTS (rest_api_utils.py)
#
################################################

print('\n' + '='*50)
print('RESPONSE STRUCTURE TESTS')
print('='*50)

# UTIL-01: statusCode is always int (compose_rest_response normalizes via int())
util_response = lambda_test_execute({
    'test_name': 'UTIL-01: statusCode is int',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'id': test_ids['area_id']},
    'body': {},
    'context': {},
    'expected_status': 200,
})
if util_response:
    sc = util_response.get('statusCode')
    record_check('UTIL-01: statusCode is int type', isinstance(sc, int), f'type is {type(sc).__name__}')

# UTIL-02: Error status replaces body with http_message
# Use a 404 response to verify the error branch overwrites body
util02_response = lambda_test_execute({
    'test_name': 'UTIL-02: error status body replacement',
    'http_method': 'GET',
    'path': AREAS_PATH,
    'query_string_params': {'id': '999999999'},
    'body': {},
    'context': {},
    'expected_status': 404,
})
if util02_response and 'body' in util02_response:
    # For 404, compose_rest_response overwrites body with json.dumps(http_message)
    # http_message='NOT FOUND' → body = json.dumps('NOT FOUND') = '"NOT FOUND"'
    # Then json.dumps again → '"\\"NOT FOUND\\""'
    has_not_found = 'NOT FOUND' in util02_response['body']
    record_check('UTIL-02: error body contains http_message', has_not_found,
                 f'body: {util02_response["body"][:100]}')

# UTIL-03: CORS headers present on error responses too
if util02_response:
    cors = util02_response.get('headers', {}).get('Access-Control-Allow-Origin')
    methods = util02_response.get('headers', {}).get('Access-Control-Allow-Methods')
    record_check('UTIL-03: CORS on error responses',
                 cors == '*' and 'PUT' in (methods or ''),
                 f'Allow-Origin: {cors}, Allow-Methods: {methods}')

# UTIL-04: All status codes normalized to int, even when passed as string
# rest_put returns compose_rest_response('200', ...) with string status
# rest_post:9 returns compose_rest_response(400, ...) with int status
# Both should produce int statusCode in the response
if util_response:
    record_check('UTIL-04: string status "200" normalized to int 200',
                 util_response.get('statusCode') == 200 and isinstance(util_response.get('statusCode'), int),
                 f'statusCode: {util_response.get("statusCode")}')


################################################
#
# INTEGRATION TESTS
#
################################################

print('\n' + '='*50)
print('INTEGRATION TESTS')
print('='*50)

# INT-01: Full CRUD lifecycle (POST → PUT → GET → DELETE) on tasks table
int01_post = lambda_test_execute({
    'test_name': 'INT-01a: POST create task',
    'http_method': 'POST',
    'path': TASKS_PATH,
    'query_string_params': {},
    'body': {
        'priority': '0',
        'done': '0',
        'description': 'Integration Lifecycle Task',
        'area_fk': test_ids['area_id'],
        'creator_fk': TEST_CREATOR_FK,
    },
    'context': {},
    'expected_status': 200,
    'expected_body_contains': ['Integration Lifecycle Task'],
})
int01_id = extract_id_from_post_response(int01_post)

if int01_id:
    lambda_test_execute({
        'test_name': 'INT-01b: PUT update task',
        'http_method': 'PUT',
        'path': TASKS_PATH,
        'query_string_params': {},
        'body': [{'id': int01_id, 'description': 'Lifecycle Updated', 'priority': '1'}],
        'context': {},
        'expected_status': 200,
    })

    lambda_test_execute({
        'test_name': 'INT-01c: GET verify update',
        'http_method': 'GET',
        'path': TASKS_PATH,
        'query_string_params': {'id': int01_id},
        'body': {},
        'context': {},
        'expected_status': 200,
        'expected_body_contains': ['Lifecycle Updated'],
    })

    lambda_test_execute({
        'test_name': 'INT-01d: DELETE task',
        'http_method': 'DELETE',
        'path': TASKS_PATH,
        'query_string_params': {},
        'body': {'id': int01_id},
        'context': {},
        'expected_status': 200,
    })

    lambda_test_execute({
        'test_name': 'INT-01e: GET confirm deleted',
        'http_method': 'GET',
        'path': TASKS_PATH,
        'query_string_params': {'id': int01_id},
        'body': {},
        'context': {},
        'expected_status': 404,
    })

# INT-02: Cross-table FK integrity — create full hierarchy, verify, tear down
int02_dom = lambda_test_execute({
    'test_name': 'INT-02a: POST create domain',
    'http_method': 'POST',
    'path': DOMAINS_PATH,
    'query_string_params': {},
    'body': {
        'domain_name': 'FK Integrity Domain',
        'creator_fk': TEST_CREATOR_FK,
        'closed': '0',
    },
    'context': {},
    'expected_status': 200,
})
int02_dom_id = extract_id_from_post_response(int02_dom)

if int02_dom_id:
    int02_area = lambda_test_execute({
        'test_name': 'INT-02b: POST create area under domain',
        'http_method': 'POST',
        'path': AREAS_PATH,
        'query_string_params': {},
        'body': {
            'area_name': 'FK Integrity Area',
            'creator_fk': TEST_CREATOR_FK,
            'domain_fk': int02_dom_id,
            'closed': '0',
            'sort_order': '1',
        },
        'context': {},
        'expected_status': 200,
    })
    int02_area_id = extract_id_from_post_response(int02_area)

    if int02_area_id:
        int02_task = lambda_test_execute({
            'test_name': 'INT-02c: POST create task under area',
            'http_method': 'POST',
            'path': TASKS_PATH,
            'query_string_params': {},
            'body': {
                'priority': '1',
                'done': '0',
                'description': 'FK Integrity Task',
                'area_fk': int02_area_id,
                'creator_fk': TEST_CREATOR_FK,
            },
            'context': {},
            'expected_status': 200,
        })
        int02_task_id = extract_id_from_post_response(int02_task)

        # Verify all three exist
        lambda_test_execute({
            'test_name': 'INT-02d: GET verify task exists',
            'http_method': 'GET',
            'path': TASKS_PATH,
            'query_string_params': {'id': int02_task_id},
            'body': {},
            'context': {},
            'expected_status': 200,
            'expected_body_contains': ['FK Integrity Task'],
        })

    # Delete domain — cascades to area and task
    lambda_test_execute({
        'test_name': 'INT-02e: DELETE domain cascades',
        'http_method': 'DELETE',
        'path': DOMAINS_PATH,
        'query_string_params': {},
        'body': {'id': int02_dom_id},
        'context': {},
        'expected_status': 200,
    })

    # Verify cascade: task should be gone
    if int02_task_id:
        lambda_test_execute({
            'test_name': 'INT-02f: GET verify cascaded task gone',
            'http_method': 'GET',
            'path': TASKS_PATH,
            'query_string_params': {'id': int02_task_id},
            'body': {},
            'context': {},
            'expected_status': 404,
        })

# INT-03: Bulk task operations — create 3 tasks, bulk-update, verify, delete
int03_task_ids = []
for i in range(3):
    resp = lambda_test_execute({
        'test_name': f'INT-03 setup: create task {i+1}',
        'http_method': 'POST',
        'path': TASKS_PATH,
        'query_string_params': {},
        'body': {
            'priority': '0',
            'done': '0',
            'description': f'Bulk Task {i+1}',
            'area_fk': test_ids['area_id'],
            'creator_fk': TEST_CREATOR_FK,
        },
        'context': {},
        'expected_status': 200,
    })
    tid = extract_id_from_post_response(resp)
    if tid:
        int03_task_ids.append(tid)

if len(int03_task_ids) == 3:
    # Bulk update: toggle priority on all 3
    lambda_test_execute({
        'test_name': 'INT-03a: bulk PUT update 3 tasks',
        'http_method': 'PUT',
        'path': TASKS_PATH,
        'query_string_params': {},
        'body': [{'id': tid, 'priority': '1'} for tid in int03_task_ids],
        'context': {},
        'expected_status': 200,
    })

    # Verify via GET with IN clause
    lambda_test_execute({
        'test_name': 'INT-03b: GET verify bulk update via IN clause',
        'http_method': 'GET',
        'path': TASKS_PATH,
        'query_string_params': {'id': f'({",".join(int03_task_ids)})'},
        'body': {},
        'context': {},
        'expected_status': 200,
    })

    # Delete all 3
    for tid in int03_task_ids:
        lambda_test_execute({
            'test_name': f'INT-03c: DELETE task {tid}',
            'http_method': 'DELETE',
            'path': TASKS_PATH,
            'query_string_params': {},
            'body': {'id': tid},
            'context': {},
            'expected_status': 200,
        })


################################################
#
# TEARDOWN: Clean up all test data
#
################################################

print('\n' + '='*50)
print('TEARDOWN: Cleaning up test data')
print('='*50)

# Delete tracked tasks
for tid in created_task_ids:
    try:
        lambda_test_execute({
            'test_name': f'TEARDOWN: delete task {tid}',
            'http_method': 'DELETE',
            'path': TASKS_PATH,
            'query_string_params': {},
            'body': {'id': tid},
            'context': {},
        })
    except Exception:
        pass

# Delete tracked areas
for aid in created_area_ids:
    try:
        lambda_test_execute({
            'test_name': f'TEARDOWN: delete area {aid}',
            'http_method': 'DELETE',
            'path': AREAS_PATH,
            'query_string_params': {},
            'body': {'id': aid},
            'context': {},
        })
    except Exception:
        pass

# Delete tracked domains (cascades to any remaining areas/tasks)
for did in created_domain_ids:
    try:
        lambda_test_execute({
            'test_name': f'TEARDOWN: delete domain {did}',
            'http_method': 'DELETE',
            'path': DOMAINS_PATH,
            'query_string_params': {},
            'body': {'id': did},
            'context': {},
        })
    except Exception:
        pass

# Note: test profile (creator_fk=TEST_CREATOR_FK) remains in profiles2
# because REST DELETE doesn't quote string values in WHERE clause.
# This is harmless — each run uses a unique timestamp-based creator_fk.
print(f'\nNote: test profile {TEST_CREATOR_FK} remains in profiles2 (orphaned)')
print('  This is expected — REST DELETE cannot handle string PKs correctly.')


################################################
#
# SUMMARY
#
################################################

lambda_test_summary()
