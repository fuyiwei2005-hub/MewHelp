"""Optional trusted MCP demo extension."""
import random
def register(server):
    @server.tool()
    def query_delivery_eta(order_id:str)->dict:
        """查询订单的预计配送时间；仅演示预测，不保证实际到达时间。"""
        return {'order_id':order_id,'estimated_days':random.randint(1,3),'demo':True,'notice':'演示预测，不承诺实际配送时效'}
