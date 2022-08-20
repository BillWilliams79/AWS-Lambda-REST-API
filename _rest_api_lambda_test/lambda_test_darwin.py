import sys
# update sys path  to include parent folder so lambda_test can import handler.py
sys.path.append('./..')
from lambda_test import lambda_test_execute

database_path = '/darwin2'
areas_path = f'{database_path}/areas2'


################################################
#
# database get request (returns dict of tables in db)
# 
get_database_darwin = {
    'http_method': 'GET',
    'path': database_path,
    'query_string_params': {},
    'body': {},
    'context': {},
}

################################################
#
# areas GET requests
# 
get_one_area = {
    'http_method': 'GET',
    'path': areas_path,
    'query_string_params': {'id': '1',},
    'body': {},
    'context': {},
}

get_all_area = {
    'http_method': 'GET',
    'path': areas_path,
    'query_string_params': {'creator_fk': '3af9d78e-db31-4892-ab42-d1a731b724dd',},
    'body': {},
    'context': {},
}

################################################
#
# areas PUT requests
# 
put_one_area = {
    'http_method': 'PUT',
    'path': areas_path,
    'query_string_params': {},
    'body': {'area_name': 'Area created by test runner',
             'creator_fk': '3af9d78e-db31-4892-ab42-d1a731b724dd',
             'closed': '0',
             'sort_order': '79',
             'domain_fk': '2',
            },
    'context': {},
}

################################################
#
# areas POST requests
# 
post_one_area = {
    'http_method': 'POST',
    'path': areas_path,
    'query_string_params': {},
    'body': [
                {
                 'id': '3',
                 'area_name': 'Justin Smith',
                 'sort_order': '97'
                },
            ],
    'context': {},
}
post_multi_area = {
    'http_method': 'POST',
    'path': areas_path,
    'query_string_params': {},
    'body': [
                {
                 'id': '1',
                 'area_name': 'Jimmy Ward!',
                },
                {
                 'id': '5',
                 'area_name': 'Trey Lance!',
                 'sort_order': 1,
                },
                {
                 'id': '8',
                 'area_name': 'Steve Young!',
                 'closed': '1',
                 'sort_order': "NULL",
                },
                {
                 'id': '3',
                 'domain_fk': '2',
                },
            ],
    'context': {},
}

################################################
#
# areas DELETE requests
# 
delete_one_area = {
    'http_method': 'DELETE',
    'path': areas_path,
    'query_string_params': {},
    'body': {'id': '6',
            },
    'context': {},
}


#lambda_test_execute(get_database_darwin)
lambda_test_execute(get_one_area)
#lambda_test_execute(get_all_area)
#lambda_test_execute(put_one_area)
#lambda_test_execute(post_one_area)
#lambda_test_execute(post_multi_area)
#lambda_test_execute(delete_one_area)
