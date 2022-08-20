test_urls = {
'url_db_only': "/hello",
'url_db_table': "/hello/world",
'rca': '/rest_crud_api',
'rca_user': '/rest_crud_api/user',
'rca_rest_api': '/rest_crud_api/rest_api',
'math_app': '/math_app',
'ma_user': '/math_app/user',
'ma_result': '/math_app/result',
}

def parsePath(path):
    splitPath = path[1:].split('/')
    database = splitPath[0]
    table = splitPath[1] if len(splitPath) > 1 else ''
    return {'database': database, 'table': table,}

for url_key in test_urls:
    print(parsePath(test_urls[url_key]))





