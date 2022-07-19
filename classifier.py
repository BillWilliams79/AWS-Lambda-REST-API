import json

def varDump(some_value, description='', dump_type='print'):
    # in honor of PHP lmao
    sv_type = type(some_value)
    print('')
    print(f'{description}\t\ttype:\t\t{sv_type}')
    if dump_type == 'json':
        print(f'{json.dumps(some_value,indent=4)}')
    else:
        # so pretty much dump_type other than json prints the value straight up
        print(f"{some_value}")

def pretty_print_sql(sql_statement, method=''):
        pretty_sql = ' '.join(sql_statement.split())
        print(f"{method} SQL statement is: {pretty_sql}")