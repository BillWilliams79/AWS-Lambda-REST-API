import json

def varDump(some_value, name=''):
    # in honor of PHP lmao
    sv_type = type(some_value)
    print(f'Name:\t{name}\t\ttype:\t\t{sv_type}')
    print(f"{some_value}")
    #print(f'{json.dumps(some_value,indent=4)}')
    print('')

def pretty_print_sql(sql_statement, method=''):
        pretty_sql = ' '.join(sql_statement.split())
        print(f"{method} SQL statement is: {pretty_sql}")
