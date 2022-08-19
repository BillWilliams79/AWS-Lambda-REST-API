from classifier import varDump
from ast import literal_eval

fruit = {}
fruit['apple'] = 'ripe'

#print(fruit['apple'])

ready = fruit.get('apple')
print(ready)
ready = fruit.get('pear', 'too green')
print(ready)

event = {
"version": "1",
"region": "us-west-1",
"userPoolId": "us-west-1_jqN0WLASK",
"userName": "41ed1d40-fc89-476d-ad87-b1f73345e137",
"callerContext": {"awsSdkVersion": "aws-sdk-unknown-unknown",
                  "clientId": "4qv8m44mllqllljbenbeou4uis"},
"triggerSource": "PostConfirmation_ConfirmSignUp",
"request": {"userAttributes": {"sub": "41ed1d40-fc89-476d-ad87-b1f73345e137",
                                "email_verified": "true",
                                "cognito:user_status": "CONFIRMED", 
                                "cognito:email_alias": "darwintestuser@proton.me",
                                "name": "Darwin Guy",
                                "email": "darwintestuser@proton.me"}},
            "response": {}}


# the following all works correctly. handing back a {} for a missed key allows the chain to result
# in a none type from the end/tip of the chain, even when deeply nested.
##first = event.get('version')
#print(first)
#second = event.get('callerContext', {}).get('clientId')
##print(second)
#third = event.get('request', {}).get('userAttributes', {}).get('sub')
#print(third)

value = '(done_ts,2022-08-06T07:00:00,2022-08-07T07:00:00)'
varDump(value, 'value is dumped')
#le = eval(value);
#varDump(le, 'literal_eval value')

#splits = value.replace('(','').replace(')','').split(',')
#varDump(splits, 'splits')
#for val in splits:
#    print(val)

remove_txt = ('(', ')')
for rem_txt in remove_txt:
    value = value.replace(rem_txt, '')
sql_vals = value.split(',')
#for val in sql_vals:
#    print(val)
print(sql_vals[0])
print(sql_vals[1])
print(sql_vals[2])

