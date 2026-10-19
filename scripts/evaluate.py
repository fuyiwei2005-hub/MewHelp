"""Run labeled prompts against the configured real provider; semantic results require review."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import ROOT, Settings
from app.gateway import OpenAICompatibleGateway, UpstreamError
from app.prompts import render_system


async def evaluate(output: Path) -> int:
    config = Settings()
    report = {"model": config.llm_model, "extraction": [], "chat": [], "semantic_review": "pending"}
    async with httpx.AsyncClient(timeout=config.llm_timeout_seconds) as client:
        gateway = OpenAICompatibleGateway(config, http_client=client)
        for line in (ROOT / "evals/after_sales.jsonl").read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            try:
                actual = (await gateway.extract(case["input"])).model_dump()
                case["actual"] = actual
                case["discrete_fields_match"] = all(actual[k] == case["expected"][k] for k in ["order_id", "request_type"])
                case["solution_exact_match"] = actual["expected_solution"] == case["expected"]["expected_solution"]
            except UpstreamError as error:
                case["error"] = error.code
                case["discrete_fields_match"] = False
            report["extraction"].append(case)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print("extraction:", case["id"], case["discrete_fields_match"], flush=True)
        for line in (ROOT / "evals/chat.jsonl").read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            try:
                parts, finish = [], None
                async for piece in gateway.stream([SystemMessage(content=render_system()), HumanMessage(content=case["input"])]):
                    parts.append(piece.text)
                    finish = piece.finish_reason or finish
                case["actual"] = "".join(parts)
                case["finish_reason"] = finish
            except UpstreamError as error:
                case["error"] = error.code
            report["chat"].append(case)
            print("chat:", case["id"], flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved", str(output), flush=True)
    return 0 if all(c["discrete_fields_match"] for c in report["extraction"]) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/prompt-evaluation.json")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(evaluate(args.output)))

