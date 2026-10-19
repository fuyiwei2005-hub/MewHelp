"""Read model IDs without logging keys or upstream error bodies."""
import asyncio
import json
import sys
import httpx
from app.config import Settings


async def check() -> int:
    settings = Settings()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                settings.llm_base_url.rstrip("/") + "/models",
                headers={"Authorization": "Bearer " + settings.llm_api_key.get_secret_value()},
            )
            if response.status_code != 200:
                print(json.dumps({"ok": False, "http_status": response.status_code}))
                return 1
            ids = [row["id"] for row in response.json()["data"]]
            print(json.dumps({"ok": True, "models": ids}, ensure_ascii=False))
            return 0
    except Exception:
        print(json.dumps({"ok": False, "error": "model_discovery_failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(check()))

