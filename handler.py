import os
import json
import re
import pymysql

from classifier import varDump, pretty_print_sql
from rest_api_utils import compose_rest_response
from rest_get_database import rest_get_database
from rest_get_table import rest_get_table
from rest_put import rest_put
from rest_post import rest_post
from rest_delete import rest_delete


#
# HTTP Method const values
#
get_method = 'GET'
post_method = 'POST'
put_method = 'PUT'
delete_method = 'DELETE'
options_method = 'OPTIONS'

# retrieve db credential environment variables
endpoint = os.environ['endpoint']
username = os.environ['username']
password = os.environ['db_password']
db_names = set(os.environ['db_name'].split(','))

print('RestApi-MySql-Lambda init code executing.')

connection = dict()

def get_connection(database):
    global connection
    if database in connection:
        try:
            connection[database].ping(reconnect=True)
            return connection[database]
        except pymysql.MySQLError:
            try:
                connection[database].close()
            except Exception:
                pass
            del connection[database]
    connection[database] = pymysql.connect(
        host=endpoint, user=username, password=password, database=database,
        connect_timeout=3, read_timeout=5, write_timeout=5)
    return connection[database]

SAFE_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def parse_path(path):

    #
    # Split first level of path into database.
    # Second level of path into table.
    # Save aside the database/table connection as applicable.
    #
    split_path = path[1:].split('/')
    database = split_path[0]
    table = split_path[1] if len(split_path) > 1 else ''

    if table and not SAFE_NAME_RE.match(table):
        return {'path': path, 'database': database, 'table': '', 'conn': '', 'error': f"Invalid table name: {table}"}

    conn = get_connection(database) if database in db_names else ''

    #varDump({'path': path, 'database': database, 'table': table}, 'parse_path results', 'json')
    return {'path': path, 'database': database, 'table': table, 'conn': conn}


#FAAS ENTRY POINT: the AWS Lambda function is configured to call this function by name.
def lambda_handler(event, context):

    #varDump(event, 'lambda_handler dump event')
    #varDump(context, 'lambda_handler context')
    path = event.get('path')
    print(f"Lambda Handler Invoked for {path}.{event['httpMethod']}")

    if path:
        db_info = parse_path(path)
    else:
        return compose_rest_response(400, '', f"No path provided")

    if 'error' in db_info:
        return compose_rest_response(400, '', db_info['error'])

    if db_info['database'] in db_names:
        response = rest_api_from_table(event, db_info)
    else:
        response = compose_rest_response(404, '', f"URL/path not found: {path}")

    return response 

def rest_api_from_table(event, db_info):

    #varDump(db_info, "db_info at start of rest_api_from_table call")
    database = db_info['database']
    table = db_info['table']
    conn = db_info['conn']
    http_method = event.get('httpMethod')

    if not event:
        print('no event')
        return compose_rest_response(500, '', 'REST API call received with no event')

    if not conn:
        print('no conn')
        return compose_rest_response(500, '', 'REST API call, no database connection')

    if not http_method:
        print('No HTTP method')
        return compose_rest_response(500, '', 'REST API call received with no HTTP method')

    body = None
    if event['body'] is not None:
        body = json.loads(event['body'])

    #
    # FILTER BY HTTP METHOD
    #
    if http_method == put_method:

        # PUT Method
        return rest_put(put_method, conn, table, body)

    elif http_method == get_method:

        # GET Method
        if table:
            return rest_get_table(get_method, conn, table, event)
        else:
            return rest_get_database(get_method, conn, database)

    elif http_method == post_method:

        # POST Method
        return rest_post(post_method, conn, table, body)

    elif http_method == delete_method:

        # DELETE Method
        return rest_delete(delete_method, conn, table, body)

    elif http_method == options_method:
        #varDump(event, 'OPTIONS event dumps')
        return compose_rest_response(200, '', '')
