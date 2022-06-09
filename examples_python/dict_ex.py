from classifier import varDump
#
# python dict examples
#

dict = {}
varDump(dict, 'empty dictionary')

#see all methods of empty dict
print(dir(dict))
print('\n')

dict['a_string'] = 'alpha'
dict['a_float'] = 22.16
dict['an_int'] = 99
varDump(dict, 'Insert by key: string, float and integer')

dict2 = {
    'my_string': 'live long and prosper',
    'my_integer': 11,
    'my_float': 22.8
}
varDump(dict2, 'declare dictionary with key:val pairs')


#protect against key error
if 'a_bool' in dict:
    varDump(dict['a_bool'], 'a_bool was a key in dict')
else:
    print('a_bool was not a key in this dict')

print('\nnow add a_bool to dict and rerun test...\n')
dict['a_bool'] = True

if 'a_bool' in dict:
    varDump(dict['a_bool'], 'a_bool was a key in dict')
else:
    print('a_bool was not a key in dict')

# .keys(), .values(), items()
key_list = dict2.keys()
varDump(key_list, 'dict2.keys() - list of keys')

values_list = dict2.values()
varDump(key_list, 'dict2.values() - list of values')

# .items()
items_list = dict2.items()
varDump(items_list, 'dict2.items() - item list')

print('\niterate over dict.items key/value')
for key, value in dict.items():
    print(f'{key} > {value}')


# enumerate: key, index
print('\nenumerate dict2 using enumerate, which produces key and index')
for index, key in enumerate(dict2):
    print(f'key:\t{key}\tindex:\t{index}\tdict["{key}"]\t {dict2[key]}')

print('\ndict sorted by keys')
for key in sorted(dict.keys()):
    print (f'key, dict[key]:\t {key}: {dict[key]}')


table_columns = ''
table_values = ''
for key, value in dict.items():
    table_columns = table_columns + f'{key}, '
    table_values = table_values + f"'{value}', "
print(table_columns)
print(table_values)

key_join_list = ', '.join(f'{key}' for key in dict.keys())
print(f'key_join_list:\t {key_join_list}')

value_join_list = ', '.join(f"'{value}'" for value in dict.values())
print(f'value_join_list:\t {value_join_list}')


