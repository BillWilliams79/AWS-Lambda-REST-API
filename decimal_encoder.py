import json
from decimal import Decimal

class DecimalEncoder(json.JSONEncoder):

    def default(self, object):
        #
        # json encoder cannot encode decimal. Hence we convert to float. Could be string...
        #
        if isinstance(object, Decimal):
            #
            # decimal to float conversion occurs here
            #
            return (float(object))
        
        #
        # return result of running defaul encoder on the object. What a delight
        #
        return json.JSONEncoder.default(self, object)
