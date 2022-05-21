import json
from classifier import classifier

def jDump(something, description=""):
    #print(f"Description:\t{description}")
    print("")
    print(f"Print:\n{something}")
    print(f'json.dumps/indent:\n{json.dumps(something,indent=4)}')
    return


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

dict = {
    'another_dict': {
        'keys1': 'item1',
        'keys2': 'item2'
    },
    'another_dict2': {
        'keys21': 'item1',
        'keys22': 'item2'
    }
}
jDump(stringy, 'string bill')
jDump(floaty, 'float 79.79')
jDump(integery, 'integer 52')
jDump(listy, 'list of items')
jDump(dicty, 'dictionary of humans')
jDump(dict, 'dictionary of dictionaries')


