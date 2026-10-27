import json
import os
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

# req #4021 — varDump and pretty_print_sql are success-path DEBUG output: the
# full POST body and every SQL statement, on every request. They were ~82% of
# Lambda-Rest's CloudWatch log bytes (req #4019). Both are silent unless the
# Lambda env var `debug_log` is set to 1/true/yes. Error-path logging is plain
# print() at the call sites and is unaffected.
def debug_log_enabled():
    return os.environ.get('debug_log', '').strip().lower() in ('1', 'true', 'yes')

def varDump(some_value, description='', dump_type='print'):
    # in honor of PHP lmao
    if not debug_log_enabled():
        return
    sv_type = type(some_value)
    print('')
    print(f'{description}\t\ttype:\t{sv_type}')
    if dump_type == 'json':
        print(f'{json.dumps(some_value,indent=4)}')
    else:
        # so pretty much dump_type other than json prints the value straight up
        print(f"{some_value}")

def pretty_print_sql(sql_statement, method=''):
        if not debug_log_enabled():
            return
        pretty_sql = ' '.join(sql_statement.split())
        print(f"{method} SQL statement is: {pretty_sql}")

# The ERROR-path counterpart, never gated: the statement that just failed. Only
# placeholders are interpolated, so it carries no values. Capped: a failed bulk
# statement grows with its row count, and the head (table, columns) is the part
# that diagnoses it.
FAILED_SQL_MAX_CHARS = 2000

def print_failed_sql(sql_statement, method=''):
    if sql_statement:
        sql = ' '.join(sql_statement.split())
        if len(sql) > FAILED_SQL_MAX_CHARS:
            sql = f"{sql[:FAILED_SQL_MAX_CHARS]}…(+{len(sql) - FAILED_SQL_MAX_CHARS} chars)"
        print(f"{method} FAILED SQL statement was: {sql}")
