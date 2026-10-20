"""Conservative UTF-8 byte-based estimates, not a provider tokenizer."""
import json
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


class ContextTooLarge(Exception):
    pass


def estimate_tokens(messages: list[BaseMessage]) -> int:
    return 3 + sum(8 + len(str(message.content).encode("utf-8")) + len(json.dumps(getattr(message, "tool_calls", []) or [], ensure_ascii=False).encode("utf-8")) + len(str(getattr(message, "tool_call_id", "")).encode("utf-8")) for message in messages)


def trim_history(history: list[BaseMessage], budget: int) -> list[BaseMessage]:
    kept = list(history)
    while kept and estimate_tokens(kept) > budget:
        del kept[:2]
    return kept


def prepare_messages(system: str, history: list[BaseMessage], user: str,
                     input_budget: int) -> list[BaseMessage]:
    first, last = SystemMessage(content=system), HumanMessage(content=user)
    if estimate_tokens([first, last]) > input_budget:
        raise ContextTooLarge()
    kept = list(history)
    while estimate_tokens([first, *kept, last]) > input_budget:
        del kept[:2]
    return [first, *kept, last]

