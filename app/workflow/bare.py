"""Framework-free control loop over OpenAI protocol dictionaries."""
import json
from .budget import Budget,BudgetExceeded,size_of
from .rules import FALLBACK

READ_TOOLS={'query_order','query_product','query_logistics','query_faq'}

async def run_bare(call,execute,messages,schemas,max_steps=6,token_budget=24000):
    messages=list(messages);trace=[];seen=set();budget=Budget(token_budget)
    for step in range(max_steps):
        size=size_of(messages)+size_of(schemas)
        try:budget.reserve(size)
        except BudgetExceeded:return dict(answer=FALLBACK,trace=trace,stop_reason='token_budget')
        response=await call(messages,schemas);budget.charge(size,response)
        message=response.get('message',response);calls=message.get('tool_calls') or []
        if not calls:return dict(answer=message.get('content',''),trace=trace,stop_reason='completed',usage=budget.used)
        messages.append({'role':'assistant','content':message.get('content') or '', 'tool_calls':calls})
        for index,item in enumerate(calls):
            function=item['function'];name=function['name']
            if name not in READ_TOOLS:return dict(answer=FALLBACK,trace=trace,stop_reason='forbidden_tool')
            try:args=json.loads(function['arguments'])
            except (ValueError,TypeError):args=None
            key=(name,json.dumps(args,sort_keys=True,ensure_ascii=False))
            if index==0 and key in seen:return dict(answer=FALLBACK,trace=trace,stop_reason='repeated_call')
            if index:result={'ok':False,'error':{'code':'one_tool_per_step'}}
            else:
                seen.add(key)
                result=await execute(dict(name=name,args=args,id=item['id']))
                trace.append({'step':step+1,'tool':name,'call_id':item['id']})
            messages.append({'role':'tool','tool_call_id':item['id'],'content':json.dumps(result,ensure_ascii=False)})
    return dict(answer=FALLBACK,trace=trace,stop_reason='step_limit')
