import pytest


def test_control_object_can_be_followed_by_discarded_prose_without_500():
    from app.workflow.agent import parse_terminal
    terminal=parse_terminal('  {"disposition":"answer","suggested_actions":[]} 后面意外混入客服正文')
    assert terminal.disposition=='answer' and not terminal.suggested_actions


@pytest.mark.parametrize('content',['直接返回的客服正文','{"suggested_actions":["delete_everything"]}','{"disposition":"answer"'])
def test_invalid_control_cannot_enable_actions(content):
    from app.workflow.agent import parse_terminal
    terminal=parse_terminal(content)
    assert terminal.disposition=='answer' and terminal.suggested_actions==[] and terminal.refund_eligibility=='unknown'
