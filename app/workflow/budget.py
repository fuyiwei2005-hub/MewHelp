import json
from dataclasses import dataclass

class BudgetExceeded(Exception):pass

@dataclass
class Budget:
    limit:int=24000
    used:int=0
    calls:int=0
    def reserve(self,size,output=1024):
        if self.used+size+output>self.limit:raise BudgetExceeded('token_budget')
    def charge(self,size,response):
        usage=getattr(response,'usage_metadata',None) or (response.get('usage') if isinstance(response,dict) else None)
        actual=usage.get('total_tokens') if usage else None
        amount=actual if isinstance(actual,int) and actual>=0 else size+len(str(getattr(response,'content',response)).encode('utf-8'))
        self.used+=amount;self.calls+=1
        return {'tokens':amount,'estimated':actual is None}

def size_of(value):return len(json.dumps(value,ensure_ascii=False,default=str).encode('utf-8'))
