import json
from classifier import classifier

param1 = ['foo', {'bar': ('baz', None, 1.0, 2)}]
#
# basic types
#
stringy = 'bill'
floaty = 79.79
integery = 52

listy = ['item0guy', 'item1guy', 'banana2guy', 4, 5, 2.0]

dicty = { 
    'bill': 'Williams',
    'mahatma': 'Ghandi',
    'toshiro': 'Mfuni',
    'arnold': 'Ziffel'
}

#classifier(stringy, 'string bill')
#classifier(floaty, 'float 79.79')
#classifier(integery, 'integer 52')
#classifier(listy, 'list of items')
#classifier(dicty, 'dictionary of humans')


#
# examples_dict
#
dict = {}
dict['stringyk'] = 'alpha'
dict['floatyk'] = 22.16
dict['intyk'] = 20
# protect against key error
#if 'notakey' in dict:
#    print(dict['notakey'])
#if 'stringyk' in dict:
#    print(f'stringky check and print:\t {dict["stringyk"]}')

#classifier(dict, "initial dict")
#print('')
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

