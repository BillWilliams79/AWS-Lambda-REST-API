import json

def varDump(some_value, name=''):
    # in honor of PHP lmao
    sv_type = type(some_value)
    print(f'Name:\t{name}\t\ttype:\t{sv_type}')
    #print(f'type:\t\t{sv_type}')
    print(f"{some_value}")
    #print(f'{json.dumps(some_value,indent=4)}')
    print('')


def classifier(some_value, name=''):

    # string types for comparison
    list_type = type(list())
    dict_type = type(dict())

    # LIST - type specific handler
    def list_type_handler():
        print('list type handler:')
        print(f'list length:\t {len(some_value)}')
        for index, item in enumerate(some_value):
            print(f'item:\t{item}\tindex:\t{index}\ttype\t{type(item)}\tlist[{index}]\t{some_value[index]}')
        list_join_string = ', '.join(str(item) for item in some_value)
        classifier(list_join_string, 'string produced from list using str.join')
        #hand method, use join dude.
        #list_to_string = str()
        #for item in some_value:
        #    list_to_string += f'{item}, '
        #list_to_string = list_to_string[:-2] # strip last two bytes, drops unneeded ', '
        #classifier(list_to_string, 'list convert to string')
        # only works if all list values are strings
        # classifier(''.join(some_value), 'join list')
        # best: convert everything to string, join with ', '


    # DICT - type specific handler
    def dict_type_handler(dict):
        print('dict type handler:')
        print(f'dict length:\t {len(dict)}')
        for index, key in enumerate(dict):
            print(f'key:\t{key}\tindex:\t{index}\tdict["{key}""]\t {dict[key]}')
        #for key in dict:
        #    print(f'dict key:\t {key}\tdict["{key}""]\t {dict[key]}')
        #
        # dict.keys join
        key_join_list = ', '.join(f'{key}' for key in dict.keys())
        print(f'key_join_list:\t {key_join_list}')

        # dict.values join
        value_join_list = ', '.join(f"'{value}'" for value in dict.values())
        print(f'value_join_list:\t {value_join_list}')

        # dict.items join
        kv_join_list = ', '.join(f'\nk:v {key}: {value}' for key, value in dict.items())
        print(f'kv_join_list:\t {kv_join_list}')


    #data prep
    sv_type = type(some_value)

    #prints
    print(f'Name:\t\t {name}')
    print(f'type:\t\t {sv_type}')
    print(f'print:\t\t {some_value}')
    print(f'json.dumps:\t {json.dumps(some_value)}')
    print(f'json.dumps/indent\n {json.dumps(some_value,indent=4)}')
    print("")
    # execute type specific handlers
    if sv_type == list_type:
        list_type_handler()
    elif sv_type == dict_type:
        dict_type_handler(some_value)
