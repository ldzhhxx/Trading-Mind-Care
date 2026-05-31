"""LLM API adapter with retry logic and streaming support."""
import httpx
import time
import json
import logging
import asyncio
from typing import AsyncGenerator
from app.database import get_db

logger = logging.getLogger(__name__)

_config_cache: dict = {}
_config_cache_time: float = 0
_CACHE_TTL = 60  # seconds


async def _load_config() -> dict:
    """Load LLM config from database with TTL cache."""
    global _config_cache, _config_cache_time
    now = time.time()
    if _config_cache and (now - _config_cache_time) < _CACHE_TTL:
        return _config_cache

    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM sys_config WHERE key IN ('base_url', 'api_key', 'model_name')")
        rows = await cursor.fetchall()
        _config_cache = {row["key"]: row["value"] for row in rows}
        _config_cache_time = now
    finally:
        await db.close()
    return _config_cache


def _validate_config(config: dict) -> None:
    """Raise ValueError if LLM config is incomplete."""
    base_url = config.get("base_url", "")
    api_key = config.get("api_key", "")
    model = config.get("model_name", "")
    if not all([base_url, api_key, model]):
        raise ValueError("LLM 未配置完整，请在设置页填写 Base URL、API Key 和模型名称")


async def call_llm(messages: list[dict], timeout: float = 30.0) -> str:
    """Call LLM API with retry. Returns response text or raises exception."""
    config = await _load_config()
    _validate_config(config)

    base_url = config["base_url"].rstrip("/")
    api_key = config["api_key"]
    model = config["model_name"]

    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "stream": False}

    last_error = None
    for attempt, delay in enumerate([0, 1, 3]):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            last_error = e
            logger.warning(f"LLM HTTP error (attempt {attempt+1}): {e.response.status_code}")
            if e.response.status_code in (401, 403):
                raise ValueError(f"API 认证失败 (HTTP {e.response.status_code})，请检查 API Key")
        except httpx.TimeoutException:
            last_error = TimeoutError("LLM 请求超时，请稍后重试")
            logger.warning(f"LLM timeout (attempt {attempt+1})")
        except httpx.RequestError as e:
            last_error = e
            logger.warning(f"LLM request error (attempt {attempt+1}): {e}")
        except (KeyError, IndexError) as e:
            last_error = ValueError("LLM 返回格式异常")
            logger.error(f"LLM response parse error: {e}")
            break  # Don't retry parse errors

    if isinstance(last_error, ValueError):
        raise last_error
    raise ValueError(f"LLM 调用失败（已重试3次）: {last_error}")


async def call_llm_stream(messages: list[dict], timeout: float = 60.0) -> AsyncGenerator[str, None]:
    """Call LLM API with streaming. Yields text chunks."""
    config = await _load_config()
    _validate_config(config)

    base_url = config["base_url"].rstrip("/")
    api_key = config["api_key"]
    model = config["model_name"]

    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "stream": True}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
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
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            raise ValueError("API 认证失败，请检查 API Key")
        raise ValueError(f"LLM 服务返回错误 (HTTP {e.response.status_code})")
    except httpx.TimeoutException:
        raise ValueError("LLM 请求超时，请稍后重试或检查网络")
    except httpx.RequestError as e:
        raise ValueError(f"网络连接失败: {e}")


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
