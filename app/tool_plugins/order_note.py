"""Trusted local registration example; no core Agent changes."""
from app.tooling.catalog import ToolSpec

async def query(args,ctx):
    return {'order_id':args['order_id'],'note':'演示订单备注：易碎品，请轻放。','demo':True}

def register(catalog):
    catalog.register(ToolSpec('query_order_note','查询订单备注及包装要求。用户问订单备注时调用此工具。',
        {'type':'object','properties':{'order_id':{'type':'string'}},'required':['order_id'],'additionalProperties':False},
        'builtin',query))
