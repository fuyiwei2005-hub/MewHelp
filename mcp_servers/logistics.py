import random
from mcp.server.fastmcp import FastMCP

def create_server(port=18011):
    server=FastMCP('logistics',host='127.0.0.1',port=port,stateless_http=True,json_response=True)
    @server.tool()
    def query_logistics(order_id:str)->dict:
        """直接按订单号查询物流位置、状态和物流轨迹。仅随机演示数据，无需先查询订单。"""
        place=random.choice(['上海转运中心','杭州配送站','北京转运中心'])
        return dict(ok=True,demo=True,order_id=order_id,status='in_transit',location=place,events=[{'status':'已揽收'},{'status':'运输中','location':place}])
    return server
