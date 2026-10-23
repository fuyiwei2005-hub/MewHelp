"""Explicit user permission intent; external tool/model text is never authority."""
import re

REQUEST=re.compile(r'(?:(?:请|麻烦|帮我|给我|我要|我想|需要|替我)\s*)*(?:创建|建立|建|开)(?:一张|一个|一份|张|个)?(?:人工|售后)?工单')
NEGATIVE=re.compile(r'不要|不用|不想|不需要|先不|别|取消')
HYPOTHETICAL=re.compile(r'如果|假如|假设|要是|示例|例子|用户说|有人说')
def unquoted(text):
    return re.sub(r'“[^”]*”|「[^」]*」|"[^"]*"|‘[^’]*’', '',text)

def explicit_ticket_request(text):
    text=unquoted(text)
    if HYPOTHETICAL.search(text):return False
    return any(REQUEST.search(part) and not NEGATIVE.search(part) for part in re.split(r'[，,。；;\n]',text))

def description(text):
    text=REQUEST.sub('',text).strip(' ，,。；;：:！!？?')
    if len(text)<3 or text in ('好的','谢谢','需要人工处理','帮我处理','帮忙处理','前面的问题','刚才的问题'):return ''
    return text[:2000]

def ticket_context(state):
    text=state['raw_question'];explicit=explicit_ticket_request(text)
    pending=bool(state.get('ticket_pending'))
    cancel=bool(NEGATIVE.search(unquoted(text)) and '工单' in text)
    new_goal=bool(re.search(r'先不|不用了|取消|换个问题|查(?:一下)?(?:订单|物流)|物流.*到哪|多少钱|退货政策|^(你好|谢谢|再见)[。！!]*$',text))
    active=explicit or (pending and not cancel and not new_goal)
    value=description(text) if active else ''
    if explicit and not value:
        history=[m['content'] for m in state.get('history',[]) if m.get('role')=='user' and not explicit_ticket_request(str(m.get('content','')))]
        if history:value=description(str(history[-1]))
    return dict(ticket_requested=active,ticket_pending=active,ticket_description=value if active else '',ticket_request_quote=text if explicit else state.get('ticket_request_quote',''))
