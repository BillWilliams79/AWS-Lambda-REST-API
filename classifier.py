import json
#import inspect
#from executing import Source

# NB: borrowed this code from substack. Requires executing and asttokens.
# if included inline in varDump, would allow retrieval of variable name
# and its value. So could be used to get varname...
#def get_var_name(var):
#    callFrame = inspect.currentframe().f_back
#    callNode = Source.executing(callFrame).node
#    source = Source.for_frame(callFrame)
#    expression = source.asttokens().get_text(callNode.args[0])
#    print(expression, '=', var)
    
def varDump(some_value, description='', dump_type='print'):
    # in honor of PHP lmao
    sv_type = type(some_value)
    print('')
    print(f'{description}\t\ttype:\t{sv_type}')
    if dump_type == 'json':
        print(f'{json.dumps(some_value,indent=4)}')
    else:
        # so pretty much dump_type other than json prints the value straight up
        print(f"{some_value}")

def pretty_print_sql(sql_statement, method=''):
        pretty_sql = ' '.join(sql_statement.split())
        print(f"{method} SQL statement is: {pretty_sql}")