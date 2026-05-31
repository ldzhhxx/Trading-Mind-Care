"""LLM API adapter with retry logic and streaming support."""
import httpx
import time
import json
import asyncio
from typing import AsyncGenerator
from app.database import get_db

_config_cache: dict = {}


async def _load_config() -> dict:
    global _config_cache
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM sys_config WHERE key IN ('base_url', 'api_key', 'model_name')")
        rows = await cursor.fetchall()
        _config_cache = {row["key"]: row["value"] for row in rows}
    finally:
        await db.close()
    return _config_cache


async def call_llm(messages: list[dict]) -> str:
    """Call LLM API. Returns response text or raises exception."""
    config = await _load_config()
    base_url = config.get("base_url", "").rstrip("/")
    api_key = config.get("api_key", "")
    model = config.get("model_name", "")

    if not all([base_url, api_key, model]):
        raise ValueError("LLM 未配置完整，请在设置页填写 API 信息")

    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "stream": False}

    last_error = None
    for attempt, delay in enumerate([0, 1, 3]):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError) as e:
            last_error = e

    raise last_error


async def call_llm_stream(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Call LLM API with streaming. Yields text chunks."""
    config = await _load_config()
    base_url = config.get("base_url", "").rstrip("/")
    api_key = config.get("api_key", "")
    model = config.get("model_name", "")

    if not all([base_url, api_key, model]):
        raise ValueError("LLM 未配置完整，请在设置页填写 API 信息")

    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def test_llm_connection(base_url: str, api_key: str, model_name: str) -> dict:
    """Test LLM connection. Returns {success, ttft_ms, model, error}."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": [{"role": "user", "content": "Hi"}], "stream": False}

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            ttft = int((time.time() - start) * 1000)
            resp.raise_for_status()
            data = resp.json()
            return {"success": True, "ttft_ms": ttft, "model": data.get("model", model_name)}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "超时（10s）"}
    except Exception as e:
        return {"success": False, "error": str(e)}
