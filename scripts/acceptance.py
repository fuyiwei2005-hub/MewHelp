"""Exercise the running HTTP service; never reads or prints API credentials."""
import argparse
import json
from pathlib import Path
from time import perf_counter

import httpx
from app.config import ROOT


def read_chat(client: httpx.Client, base_url: str, payload: dict, show_stream: bool = False) -> dict:
    start = perf_counter()
    result = {"conversation_id": None, "text": "", "token_events": 0, "first_token_seconds": None}
    complete, event_name = False, None
    with client.stream("POST", base_url.rstrip("/") + "/chat", json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
                if event_name == "meta":
                    result["conversation_id"] = data["conversation_id"]
                elif event_name == "token":
                    if result["first_token_seconds"] is None:
                        result["first_token_seconds"] = round(perf_counter() - start, 3)
                    result["text"] += data["text"]
                    result["token_events"] += 1
                    if show_stream:
                        print(data["text"], end="", flush=True)
                elif event_name == "error":
                    raise ValueError("SSE error: " + data.get("code", "unknown"))
                elif event_name == "done":
                    complete = data.get("finish_reason") == "stop"
    if show_stream:
        print()
    if not complete or not result["conversation_id"] or not result["token_events"]:
        raise ValueError("Incomplete conversation stream")
    result["elapsed_seconds"] = round(perf_counter() - start, 3)
    return result


def run(base_url: str, output: Path, show_stream: bool) -> int:
    with httpx.Client(timeout=90, trust_env=False) as client:
        first = read_chat(client, base_url, {"message": "我的订单号是DS20261019001，收到的杯子破损了，想换货。请记住订单号。"}, show_stream)
        second = read_chat(client, base_url, {
            "message": "刚才我的订单号是什么？", "conversation_id": first["conversation_id"]}, show_stream)
        response = client.post(base_url.rstrip("/") + "/after-sales/extract",
                               json={"description": "订单DS20261019001收到破损，请换同款新的"})
        response.raise_for_status()
        extraction = response.json()
    checks = {
        "streaming": first["token_events"] > 1,
        "context": "DS20261019001" in second["text"],
        "structured_json": extraction == {
            "order_id": "DS20261019001", "request_type": "换货", "expected_solution": "换同款新的"},
    }
    report = {"checks": checks, "first_turn": first, "second_turn": second, "extraction": extraction}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/acceptance.json")
    parser.add_argument("--show-stream", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.base_url, args.output, args.show_stream))

