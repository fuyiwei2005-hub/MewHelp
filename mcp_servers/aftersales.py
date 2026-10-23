import random
from mcp.server.fastmcp import FastMCP

def create_server(port=18012):
    server=FastMCP('aftersales',host='127.0.0.1',port=port,stateless_http=True,json_response=True)
    @server.tool()
    def query_warranty(order_id:str)->dict:
        """按订单号查询商品是否仍在保修期及剩余保修天数。仅随机演示，不代表真实订单。"""
        days=random.choice([0,30,120,200])
        return dict(ok=True,demo=True,order_id=order_id,status='in_warranty' if days else 'expired',remaining_days=days)
    @server.tool()
    def query_return_progress(order_id:str)->dict:
        """按订单号查询已提交退货的处理进度。仅随机演示，不执行退货退款。"""
        return dict(ok=True,demo=True,order_id=order_id,status=random.choice(['等待寄回','仓库验收中','已审核']),next_step='以平台实际售后页面为准，不承诺到账时间')
    return server
