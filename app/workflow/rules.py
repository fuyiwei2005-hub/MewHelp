import re

INTENTS=('物流','订单','商品咨询','退款退货','售后','投诉','闲聊','其他')
REASONS=('不想要了','质量问题','运输破损','发错商品','少件漏发','其他')
GREETINGS={'你好','您好','嗨','哈喽','谢谢','谢谢你','再见','拜拜','早上好','晚上好'}
FALLBACK='抱歉，目前无法可靠完成这个请求，请补充必要信息或选择联系人工客服。'
COMPLAINT='很抱歉给您带来不好的体验。您可以选择转人工客服，或单独创建工单；也可以继续告诉我具体情况。'
SMALLTALK='您好，我是客服小猫，可以帮您查询商品、订单物流和退换货问题。'


def is_greeting(question):return re.sub(r'[\s，。！？!?~～]+','',question) in GREETINGS


def general_faq(question):
    concrete=bool(re.search(r'订单\s*[A-Za-z0-9]|这[一]?单|这[个件款]|那[个件单]|我的|我[要想]|坏了|能退吗|能换吗',question))
    return not concrete and bool(re.search(r'政策|规则|流程|条件|如何|怎么|多久|期限|保修|运费|发票',question))


def route(intent,question):
    if intent in ('退款退货','售后'):return 'knowledge' if general_faq(question) else 'refund'
    return {'商品咨询':'knowledge','物流':'agent','订单':'agent','投诉':'complaint','闲聊':'smalltalk'}.get(intent,'other')


def policy_query(question,intent):
    # Order identity selects the order; eligibility constraints remain in retrieval.
    import re
    content=re.sub(r'订单(?:号)?[:：\s]*[A-Za-z0-9-]+','商品',question)
    return ('售后维修政策与条件：' if intent=='售后' else '退货申请政策与条件：')+content
