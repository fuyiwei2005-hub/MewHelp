def test_rules_distinguish_faq_from_order_and_whole_greeting():
    from app.workflow.rules import route,is_greeting
    assert route('退款退货','退货政策是什么')=='knowledge'
    assert route('退款退货','订单1001能退吗')=='refund'
    assert route('售后','这个坏了要维修')=='refund'
    assert route('售后','保修规则是什么')=='knowledge'
    assert route('物流','订单1001到哪了')=='agent'
    assert route('投诉','我要投诉')=='complaint'
    assert route('其他','让月亮变方的')=='other'
    assert is_greeting('你好！') and not is_greeting('你好，帮查订单1001')


def test_policy_query_removes_order_identity_but_preserves_eligibility_constraints():
    from app.workflow.rules import policy_query
    q=policy_query('订单1001的MH-W20已使用15天，不能无理由退货吗','退款退货')
    assert '1001' not in q and all(x in q for x in ['MH-W20','已使用15天','不能','退货'])
