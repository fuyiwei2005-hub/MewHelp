import asyncio,json


def test_bare_loop_observes_order_before_choosing_logistics():
    from app.workflow.bare import run_bare
    seen=[]
    async def call(messages,schemas):
        results=[m for m in messages if m['role']=='tool']
        if not results:name='query_order'
        elif len(results)==1:
            assert json.loads(results[0]['content'])['status']=='已发货'
            name='query_logistics'
        else:return {'content':'订单已发货，物流在上海。'}
        return {'content':'','tool_calls':[{'id':str(len(results)),'type':'function','function':{'name':name,'arguments':'{"order_id":"1001"}'}}]}
    async def execute(call):
        seen.append(call['name']);return {'ok':True,'status':'已发货'}
    result=asyncio.run(run_bare(call,execute,[{'role':'user','content':'先查订单再查物流'}],[]))
    assert seen==['query_order','query_logistics'] and result['stop_reason']=='completed'


def test_bare_loop_refuses_write_tool_and_stops_repetition():
    from app.workflow.bare import run_bare
    async def call(messages,schemas):return {'content':'','tool_calls':[{'id':'a','type':'function','function':{'name':'create_ticket','arguments':'{}'}}]}
    async def execute(call):raise AssertionError('Agent cannot write tickets')
    result=asyncio.run(run_bare(call,execute,[{'role':'user','content':'投诉'}],[]))
    assert result['stop_reason']=='forbidden_tool'


def test_bare_loop_checks_budget_before_model_call():
    from app.workflow.bare import run_bare
    async def call(*args):raise AssertionError('Over budget must not call model')
    result=asyncio.run(run_bare(call,None,[{'role':'user','content':'x'*100}],[],token_budget=20))
    assert result['stop_reason']=='token_budget'
