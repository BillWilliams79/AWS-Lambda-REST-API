import pymysql
import json
from rest_api_utils import compose_rest_response
from classifier import varDump, pretty_print_sql
        
def rest_get_table(get_method, conn, table, event):

    # STEP 1: Execute helper SQL commands: build list of columns for the SQL
    #         command and allow for larger group concat. Build a list of columns
    #         to verify correct QSP
    try:
        with conn.cursor() as cursor:
            cursor.execute(f""" DESC {table}; """)
            rows = cursor.fetchall()

        # default value used in queries to retrieve all fields, overwritten below with
        # more specific values as needed.
        columns_select = ', '.join(f"'{row[0]}', {row[0]}" for row in rows)

        sql_columns = []
        for row in rows:
            sql_columns.append(row[0])

    except pymysql.Error as e:
        errorMsg = f"HTTP {get_method} helper SQL command failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('500', '', errorMsg)

    # STEP 2: iterate over query string parameters 
    where_clause = "WHERE"
    where_connector = ""
    where_count = 0
    order_by = ""
    count_syntax = 0
    group_by = ""
    qsp = event.get('queryStringParameters')

    if qsp:
        for key, value in qsp.items():

            if key in sql_columns:
                # if key is valid SQL column, it is a filter or part of the where clause
                # ?area_fk=(1,2,4) translates to "area_fk IN 1,2,4"
                if (value.startswith('(') and value.endswith(')')):
                    where_clause = f"{where_clause}{where_connector} {key} in {value}"
                else:
                    where_clause = f"{where_clause}{where_connector} {key}='{value}'"
                where_count = where_count + 1
                where_connector = " AND"

            elif key == 'filter_ts':
                # filter_ts=(done_ts,2022-08-06T07:00:00,2022-08-07T07:00:00)
                # SQL => WHERE done_ts BETWEEN '2022-08-06T07:00:00' AND '2022-08-07T07:00:00'
                remove_txt = ('(', ')')
                for rem_txt in remove_txt:
                    value = value.replace(rem_txt, '')
                sql_vals = value.split(',')
                where_clause = f"{where_clause}{where_connector} {sql_vals[0]} BETWEEN '{sql_vals[1]}' AND '{sql_vals[2]}'"
                varDump(where_clause, "where clause after ts_filter insertion")
                where_count = where_count + 1
                where_connector = " AND"

            elif key == 'sort':
                # parse data sorting options
                # format is ?sort=field1:asc,field2:desc,field3:asc
                sort_dict = dict(x.split(":") for x in value.split(","))
                order_by = ', '.join(f"{sort_key} {sort_value}" for sort_key, sort_value in sort_dict.items())
                order_by = f" ORDER BY {order_by}"

            elif key == 'fields':
                # sparse fields support - return only the fields/columns required
                # format is ?fields=field1,field2,field3
                #  - or -
                # count format is ?fields=count(*),group_by_field
                # NB: count syntax mandates only two fields and count(*) is first
                for field in value.split(","):

                    if field == 'count(*)':
                        # alternate count aggregation syntax
                        count_syntax = count_syntax + 1
                        continue

                    if field not in sql_columns:
                        # if field is not an SQL column, this is an improperly formed request, fail 400
                        errorMsg = f"HTTP {get_method} invalid query string parameter FIELDS: {key} {value}"
                        print(errorMsg)
                        return compose_rest_response('400', '', "BAD REQUEST")

                    else:
                        # a count(*) syntax limits to a single extra field which becomes the group by field
                        if count_syntax == 1:
                            group_by = f"GROUP BY {field}"
                            count_syntax = count_syntax + 1

                        elif count_syntax > 1:
                            # error condition count(*) requires only two fields params: count(*) and colu
                            print(errorMsg)
                            return compose_rest_response('400', '', "BAD REQUEST")

                columns_select = ', '.join(f"'{field}', {field}" for field in value.split(","))

            else:
                # JSON API document allows api implementation to ignore an improperly formed request
                errorMsg = f"HTTP {get_method} invalid query string parameter {key} {value}"
                print(errorMsg)
                return compose_rest_response('400', '', "BAD REQUEST")

    # zero out where clause if there were no QSPs
    if where_count == 0:
        where_clause = ""

    # STEP 3: execute API read and process all return values
    try:
        # read row(s) and format as JSON
        if count_syntax == 0:
            sql_statement = f"""
                                SELECT
                                    CONCAT('[',
                                        GROUP_CONCAT(
                                            JSON_OBJECT({columns_select})
                                            {order_by}
                                            SEPARATOR ', ')
                                    ,']')
                                FROM
                                    {table}
                                {where_clause}
            """
        else:
            # read and count records syntax
            sql_statement = f"""
                                SELECT
                                    JSON_OBJECT({columns_select})
                                FROM
                                    {table}
                                {where_clause}
                                {group_by}
            """

        pretty_print_sql(sql_statement, get_method)

        with conn.cursor() as cursor:
            cursor.execute(sql_statement)
            row = cursor.fetchall()

        if row[0][0]:
            if count_syntax == 0:
                return compose_rest_response('200', row[0], 'OK')
            else:
                # count(*) data has to be massaged into an array of dict
                # it comes back as a tuple of tuples, each having a dict in json format
                return_value = []
                for tuple_dict in row:
                    return_value.append(json.loads(tuple_dict[0]))
                varDump(json.dumps(return_value), 'json dump tuple_dict')
                return compose_rest_response('200', json.dumps(return_value), 'OK')

        else:
            print('get: 404')
            errorMsg = f"No data"
            print(errorMsg)
            return compose_rest_response('404',  '', 'NOT FOUND')

    except pymysql.Error as e:
        errorMsg = f"HTTP {get_method} actual SQL select statement failed: {e.args[0]} {e.args[1]}"
        print(errorMsg)
        return compose_rest_response('500', '', "errorMsg")
