#
# examples_dict
#empty dictionary
dict = {}
#insert by key
dict['stringyk'] = 'alpha'
dict['floatyk'] = 22.16
dict['intyk'] = 20

#
#
#


dict2 = {
    'key-string': 'value',
    'key-integer': 2,
    'key-float': 22.16
}

"""
#protect against key error
f 'notakey' in dict:
   print(dict['notakey'])
f 'stringyk' in dict:
   print(f'stringky check and print:\t {dict["stringyk"]}')
"""

key_list = dict.keys()
#print(dict.keys())
#classifier(key_list, 'dict.keys()')
#print(f'keys list:\t{key_list}')

values_list = dict.values()
#classifier(values_list, 'dict.values()')
#print(f'values list:\t{values_list}')

items_list = dict.items()
#classifier(items_list, 'dict.items()')
#print(f'items list:\t{items_list}')

classifier(dict, 'initial dict')

#for index, key in enumerate(dict):
#    print(f'key:\t{key}\tindex:\t{index}\tdict["{key}""]\t {dict[key]}')

#for key in sorted(dict.keys()):
#    print (f'key, dict[key]:\t {key}: {dict[key]}')


"""
                INSERT INTO Math_User (Name, Favorite_Color) 
                VALUES ('Lia', 'Orange');
            """
#for key, value in dict.items():
#    print(f'{key} > {value}')

#table_columns = ''
#table_values = ''
#for key, value in dict.items():
#    table_columns = table_columns + f'{key}, '
#    table_values = table_values + f"'{value}', "
#    cols = ', '.join(f'{key}')
#    vals = ', '.join(f"'{value}'")

#key_join_list = ', '.join(f'{key}' for key in dict.keys())
#print(f'key_join_list:\t {key_join_list}')

#value_join_list = ', '.join(f"'{value}'" for value in dict.values())
#print(f'value_join_list:\t {value_join_list}')

#print(table_columns)
#print(cols)
#print(table_values)
#print(vals)

