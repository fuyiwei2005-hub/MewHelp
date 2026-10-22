import json
from types import SimpleNamespace
from langchain_core.messages import AIMessage
from app.gateway import StreamPiece
from app.config import Settings
from app.workflow.language import Resolution,Intent,Queries,order_ids
from app.knowledge.query import QueryPlan
from app.knowledge.quality import Assessment

class Repo:
    def __init__(self):self.offers={};self.logs=[];self.runs={}
    async def orders(self):return [dict(order_id='1001',product='陶瓷杯',demo=True,status='已签收')]
    async def user_order(self,oid):return dict(ok=True,demo=True,order_id=oid,status='已签收',product='陶瓷杯',signed_days=2) if oid=='1001' else None
    async def offer(self,cid,tid,kind,payload):
        id=tid+'-'+kind
        self.offers.setdefault(id,dict(id=id,turn_id=tid,kind=kind,payload=payload,status='pending',result=None))
        return self.offers[id]
    async def get_offer(self,cid,id):return self.offers.get(id)
    async def complete_offer(self,cid,id,result):self.offers[id].update(status='done',result=result);return result
    async def audit(self,state,status='completed'):
        self.logs.append((state,status));self.runs[state['turn_id']]={'status':status,'data':state}
    async def start(self,cid,tid,q):self.runs[tid]={'status':'running','data':{'question':q}}
    async def run(self,cid,tid):return self.runs.get(tid)
    async def expire_selections(self,cid):
        for offer in self.offers.values():
            if offer['kind']=='order_selection' and offer['status']=='pending':offer['status']='superseded'
    async def confirmed_actions(self,cid):return []
    async def mysql_history(self,cid):return []
    async def refund(self,cid,oid,reason):
        row=self.offers[oid]
        if row['status']=='done':return row['result']
        row.update(status='done',result={'application_id':'RTEST','status':'submitted_demo','reason':reason,'demo':True});return row['result']

class Audit:
    def __init__(self):self.low=[];self.snapshots=[]
    async def record_low(self,*args):self.low.append(args)
    async def save_evidence(self,cid,tid,rows):self.snapshots=rows

class Language:
    def __init__(self):self.calls=[]
    async def resolve(self,q,history,budget=None,**kwargs):
        self.calls.append('resolve');ids=order_ids(q)
        return Resolution(resolved_question=q,retrieval_query=q,referenced_order_id=next(iter(ids)) if len(ids)==1 else None)
    async def classify(self,q,budget=None,**kwargs):
        self.calls.append('classify')
        value='投诉' if '投诉' in q else ('退款退货' if '退' in q else ('物流' if '物流' in q else '商品咨询'))
        return Intent(intent=value,confidence=.98)
    async def expand(self,q,order,budget=None,**kwargs):self.calls.append('expand');return Queries(queries=['退货条件','退货运费'])

class Retrieval:
    def __init__(self):self.calls=[]
    async def retrieve(self,q,*args,**kw):
        from app.knowledge.hybrid_retrieval import EvidenceBundle
        self.calls.append(q)
        rows=[dict(chunk_id='a',number=1,answer='未使用商品可在签收7天内申请退货，需完整包装。',question='退货条件',category='售后',section_path='售后 / 退货条件',source_id='demo',content_hash='a',score=.99)]
        return EvidenceBundle(QueryPlan(q,q,[]),rows,rows)

class Gate:
    sufficient=True
    async def assess(self,q,evidence):return Assessment(sufficient=self.sufficient,supported_facts=['未使用7天内可申请'],evidence_ids=[1],reason='测试证据')

class Gateway:
    def __init__(self):self.calls=0;self.final_calls=0
    async def decide(self,messages,tools):
        self.calls+=1
        if tools and not any(m.type=='tool' for m in messages):return AIMessage(content='',tool_calls=[dict(name='query_logistics',args={'order_id':'1001'},id='call1',type='tool_call')])
        return AIMessage(content='{"disposition":"answer","suggested_actions":[],"refund_eligibility":"conditional"}')
    async def final_stream(self,messages,tools):
        self.final_calls+=1;yield StreamPiece('这是演示回答，符合政策条件时可申请。[1]');yield StreamPiece(finish_reason='stop')

def deps():
    return SimpleNamespace(cfg=Settings(_env_file=None,llm_api_key='fake',llm_model='fake'),repo=Repo(),audit=Audit(),language=Language(),retriever=Retrieval(),multi=Retrieval(),gate=Gate(),gateway=Gateway(),business_repo=None,knowledge_parent=None)

def input_state(question,tid='t1',cid='c1',history=None):
    return dict(conversation_id=cid,turn_id=tid,raw_question=question,history=history or [],turn_messages=[dict(role='user',content=question)],trace=[],usage={'tokens':0,'calls':0},product_category=None)
