from enum import Enum, unique, auto

# Docs: https://docs.python.org/3.11/howto/enum.html
#
# Enum will enforce unique or one key per value. No aliases.
#
@unique


#
# define enums as a class. You can assign items an id number by hand or use auto()
#
class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3


class httpResponseEnum(Enum):
    #
    # user defined auto inserts ENUM name as string
    #
    def _generate_next_value_(name, start, count, last_values):
        return name

    GET = auto()
    POST = auto()
    PATCH = auto()
    DELETE = auto()
    OPTIONS = auto()

    def instanceCheckbyString(checkString):

        check_name_list = []

        for name, member in httpResponseEnum.__members__.items():
            check_name_list.append(member.name)

        print(f'instance check name_list:\t {check_name_list}')

        return checkString in check_name_list


#
# determine if user string is httpResponseEnum
#
correctSampleResponse = 'GET'
incorrectSampleResponse = 'GUMBO'

#
# determine if in enum by this bullshit: create list of names, check "in" vs string
#
name_list = []
for name, member in httpResponseEnum.__members__.items():
    name_list.append(member.name)

print(f'name_list:\t {name_list}')

print(f'custom func correct: {httpResponseEnum.instanceCheckbyString(correctSampleResponse)}')
print(f'custom func incorrect: {httpResponseEnum.instanceCheckbyString(incorrectSampleResponse)}')
#print(f'incorrect: {incorrectSampleResponse in name_list}')

# no workie obviously, its' not a dict
# if "key" in d
#
#print(f'key in d, correct: {correctSampleResponse in httpResponseEnum}')



print(f'correct: {isinstance(httpResponseEnum(correctSampleResponse), httpResponseEnum)}')
#print(f'incorrect: {isinstance(httpResponseEnum(incorrectSampleResponse), httpResponseEnum)}')

#print(f'incorrect: {httpResponseEnum(incorrectSampleResponse)}')


#if isinstance(httpResponseEnum(sampleResponse), httpResponseEnum)


#
# Access individual items
#
print(f'Color.RED: {Color.RED}')
print(f'Color.GREEN: {Color.GREEN}')
print(f'Color.BLUE: {Color.BLUE}')

#
# Boolean comparison/expressions
#
"""
>>> Color.RED is Color.RED
True
>>> Color.RED is Color.BLUE
False
>>> Color.RED is not Color.BLUE
True

>>> Color.BLUE == Color.RED
False
>>> Color.BLUE != Color.RED
True
>>> Color.BLUE == Color.BLUE
True

>>> Color.BLUE == 2
False
"""


#
# can use as an iterator
# print and repr() print
# repr() calls the __repr()__ function of the object

print('')
print('httpResponseEnum Enumeration')
print('')
for response in httpResponseEnum:
    print(f'name\t:\t {response.name}')
    print(f'value\t:\t {response.value}')
    print(f'String\t:\t {response}')
    print(f'repr()\t:\t {repr(response)} ')
    print(f'type\t:\t {type(response)}')
    print(f'isins()\t:\t {isinstance(response, httpResponseEnum)}\t=> isinstance(response, httpResponseEnum)')
    print('')
#
# assignments can be of any number when handled manually
# (python doc example exactly)
# two enum with same value are allowed
# one enum with two values is NOT allowed
#
class Shake(Enum):
    VANILLA = 7
    CHOCOLATE = 4
    COOKIES = 9
    MINT = 3

print('Enumerations are in iteration order')
for shake in Shake:
    print(f'Shake enum:  {repr(shake)}')
#
# print as list()
#
print('')
print('list() print in enumeration order')
print(f'list(Shake)\t:\t {list(Shake)}')

#
# __members__ print
#
print('')
print('__members__ readonly ordered mapping of names to numbers')
for name, member in Shake.__members__.items():
    print(f'Shake => name, member, member.value, member.name:\t {name}, {member}, {member.value}, {member.name}')





# NO WORKIE
# use __members__ to make a dictionary of an enum
#
#ShakeEnumDic = {}
#for name, member in Shake.__members__.items():
#    ShakeEnumDic.update({f"'{member.name}', '{member.value}'"})
#
#print(f'ShakeEnumDic:\t {ShakeEnumDic}')

