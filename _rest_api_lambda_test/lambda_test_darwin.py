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
# areas GET (READ) REST API calls
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
# areas POST (CREATE) REST API calls
# 
post_one_area = {
    'http_method': 'POST',
    'path': areas_path,
    'query_string_params': {},
    'body': {'area_name': 'George Kittle',
             'creator_fk': '3af9d78e-db31-4892-ab42-d1a731b724dd',
             'closed': '0',
             'sort_order': '85',
             'domain_fk': '2',
            },
    'context': {},
}

################################################
#
# areas PUT (UPDATE) REST API calls
# 
put_one_area = {
    'http_method': 'PUT',
    'path': areas_path,
    'query_string_params': {},
    'body': [
                {
                 'id': '8',
                 'area_name': 'Steve Young, HOF',
                 'sort_order': '8'
                },
            ],
    'context': {},
}
put_multi_area = {
    'http_method': 'PUT',
    'path': areas_path,
    'query_string_params': {},
    'body': [
                {
                 'id': '2',
                 'area_name': 'David Akers',
                },
                {
                 'id': '4',
                 'area_name': 'Andy Lee!',
                 'sort_order': 44,
                },
                {
                 'id': '8',
                 'area_name': 'Steve Young!',
                 'closed': '0',
                 'sort_order': "NULL",
                },
                {
                 'id': '9',
                 'domain_fk': '1',
                },
            ],
    'context': {},
}

################################################
#
# areas DELETE (delete) REST API calls
# 
delete_one_area = {
    'http_method': 'DELETE',
    'path': areas_path,
    'query_string_params': {},
    'body': {'id': '6',
            },
    'context': {},
}


#lambda_test_execute(get_database_darwin) # read database tables
#lambda_test_execute(get_one_area) # read one Area
#lambda_test_execute(get_all_area) # read all Areas
#lambda_test_execute(put_one_area) # update one area
lambda_test_execute(put_multi_area) # update multiple areas
#lambda_test_execute(post_one_area) # create one area
#lambda_test_execute(delete_one_area) # delete one area
