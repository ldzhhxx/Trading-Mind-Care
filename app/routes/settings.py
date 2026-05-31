"""Settings routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database import get_db
from app.llm import test_llm_connection

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LLMConfig(BaseModel):
    base_url: str
    api_key: str
    model_name: str


class FeishuConfig(BaseModel):
    feishu_webhook: str
    notify_time: str = "08:30"
    reminder_time: str = "20:00"


class ExtraConfig(BaseModel):
    critique_intensity: str = "3"


class DecayConfig(BaseModel):
    decay_rate: str = "0.98"


@router.get("")
async def get_settings():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM sys_config")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        await db.close()


@router.post("/llm")
async def save_llm_settings(config: LLMConfig):
    db = await get_db()
    try:
        for key, value in config.model_dump().items():
            await db.execute(
                "INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/test-llm")
async def test_llm(config: LLMConfig):
    result = await test_llm_connection(config.base_url, config.api_key, config.model_name)
    return result


@router.post("/feishu")
async def save_feishu_settings(config: FeishuConfig):
    db = await get_db()
    try:
        for key, value in config.model_dump().items():
            await db.execute(
                "INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/llm-extra")
async def save_extra_settings(config: ExtraConfig):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)",
            ("critique_intensity", config.critique_intensity),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/decay")
async def save_decay_settings(config: DecayConfig):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)",
            ("decay_rate", config.decay_rate),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()
