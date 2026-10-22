import itertools
from dataclasses import dataclass
from langchain_core.messages.utils import trim_messages


def msg_id(message):return int(message.id)

def turns(messages):
    return [list(items) for _,items in itertools.groupby(messages,key=lambda m:m.additional_kwargs.get('turn_id',m.id))]

def validate_protocol(group):
    pending=set()
    for m in group:
        if m.type=='tool':
            if m.tool_call_id not in pending:raise ValueError('tool_protocol: orphan result')
            pending.remove(m.tool_call_id)
        else:
            if pending:raise ValueError('tool_protocol: missing result')
            pending={c['id'] for c in getattr(m,'tool_calls',[]) or []}
    if pending:raise ValueError('tool_protocol: incomplete call')

def compact(group):
    names={call['id']:call['name'] for m in group for call in getattr(m,'tool_calls',[]) or []}
    result=[]
    for m in group:
        if m.type=='human':result.append(m)
        elif m.type=='tool':result.append(m.model_copy(update={'content':'[工具结果 '+names.get(m.tool_call_id,'tool')+' / '+m.tool_call_id+']'}))
        else:result.append(m.model_copy(update={'content':str(m.content)[:60]}))
    return result

@dataclass
class LayerView:
    middle:list
    recent:list
    layer1_from:int|None
    layer2_tokens:int
    events:list
    @property
    def window(self):return self.middle+self.recent


def partition(messages,summary_upto,layer1_from,plan,counter):
    groups=turns([m for m in messages if msg_id(m)>summary_upto]);events=[]
    for group in groups:validate_protocol(group)
    old=layer1_from or (min(map(msg_id,groups[0])) if groups else None)
    middle_groups=[g for g in groups if layer1_from and min(map(msg_id,g))<layer1_from]
    recent_groups=[g for g in groups if not layer1_from or min(map(msg_id,g))>=layer1_from]
    while len(recent_groups)>1 and counter.messages(sum(recent_groups,[]))>plan.layer1:
        middle_groups.append(recent_groups.pop(0))
    recent=sum(recent_groups,[])
    if recent and counter.messages(recent)>plan.history:raise ValueError('上下文预算不足：最新完整回合过大')
    boundary=min(map(msg_id,recent)) if recent else old
    if boundary and old and boundary>old:events.append(dict(event='layer1_degrade',old=old,new=boundary))
    if recent and counter.messages(recent)>plan.layer1:events.append(dict(event='layer1_borrow',tokens=counter.messages(recent)))
    middle=sum([compact(g) for g in middle_groups],[])
    return LayerView(middle,recent,boundary,counter.messages(middle) if middle else 0,events)


def fit_view(view,budget,counter):
    # trim_messages does not mutate State; snap its selection back to complete turns.
    selected=trim_messages(view.window,max_tokens=budget,token_counter=counter.messages,strategy='last',start_on='human',allow_partial=False)
    ids={m.id for m in selected};groups=turns(view.window)
    return sum([g for g in groups if all(m.id in ids for m in g)],[])
