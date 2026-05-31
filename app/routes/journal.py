"""Journal routes - daily trading journal/notes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from datetime import date
from app.database import get_db

router = APIRouter(prefix="/api/journal", tags=["journal"])


class JournalEntry(BaseModel):
    content: str
    trade_date: str | None = None

    @field_validator("content")
    @classmethod
    def content_valid(cls, v):
        if not v.strip():
            raise ValueError("内容不能为空")
        if len(v) > 10000:
            raise ValueError("内容不能超过 10000 字符")
        return v.strip()


@router.get("")
async def get_journal(trade_date: str | None = None, limit: int = 10):
    db = await get_db()
    try:
        if trade_date:
            cursor = await db.execute(
                "SELECT * FROM journal WHERE trade_date = ? ORDER BY created_at DESC", (trade_date,)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM journal ORDER BY trade_date DESC, created_at DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("")
async def create_journal(entry: JournalEntry):
    trade_date = entry.trade_date or date.today().isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO journal (trade_date, content) VALUES (?, ?)",
            (trade_date, entry.content),
        )
        await db.commit()
        return {"id": cursor.lastrowid}
    finally:
        await db.close()


@router.delete("/{entry_id}")
async def delete_journal(entry_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM journal WHERE id = ?", (entry_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="记录不存在")
        return {"ok": True}
    finally:
        await db.close()


@router.post("/ai-summary")
async def journal_ai_summary():
    """AI 总结近期日记，发现模式和洞察."""
    import json
    from fastapi.responses import StreamingResponse
    from app.llm import call_llm_stream

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, content FROM journal ORDER BY trade_date DESC LIMIT 15"
        )
        entries = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if not entries:
        from fastapi.responses import StreamingResponse

        async def empty():
            yield f'data: {json.dumps({"chunk": "暂无日记记录，请先写几篇交易日记。"})}\n\n'
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    entries_text = "\n".join(f"[{e['trade_date']}] {e['content'][:200]}" for e in entries)

    messages = [
        {"role": "system", "content": "你是交易心理分析师，擅长从日记中发现隐藏的思维模式和情绪规律。分析交易员的日记，找出：1.反复出现的主题 2.情绪变化规律 3.认知偏差 4.值得强化的正面习惯。200字以内，直击要害。"},
        {"role": "user", "content": f"以下是交易员近期的日记：\n\n{entries_text}"},
    ]

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/weekly-digest")
async def journal_weekly_digest():
    """AI 生成本周日记精华摘要 + 行为模式洞察."""
    import json
    from datetime import timedelta
    from fastapi.responses import StreamingResponse
    from app.llm import call_llm_stream

    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT trade_date, content FROM journal WHERE trade_date >= ? ORDER BY trade_date",
            (week_start,)
        )
        entries = [dict(r) for r in await cursor.fetchall()]

        # Also get this week's reviews for context
        cursor = await db.execute(
            "SELECT trade_date, pnl, emotion_log FROM reviews WHERE trade_date >= ? ORDER BY trade_date",
            (week_start,)
        )
        reviews = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    if not entries and not reviews:
        async def empty():
            yield f'data: {json.dumps({"chunk": "本周暂无日记和复盘记录。"})}\n\n'
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    journal_text = "\n".join(f"[{e['trade_date']}] {e['content'][:150]}" for e in entries) or "无日记"
    review_text = "\n".join(f"[{r['trade_date']}] 盈亏{r['pnl'] or '未记录'}: {r['emotion_log'][:100]}" for r in reviews) or "无复盘"

    messages = [
        {"role": "system", "content": """你是交易心理教练，正在为交易员生成本周精华摘要。

格式：
## 📝 本周关键事件
列出2-3个最重要的交易事件

## 🧠 心理状态变化
本周情绪和心态的演变

## ⚡ 行为模式发现
本周暴露的行为模式（好的和坏的）

## 🎯 下周聚焦
一个最需要改善的点

200字以内，数据驱动。"""},
        {"role": "user", "content": f"【本周日记】\n{journal_text}\n\n【本周复盘】\n{review_text}"},
    ]

    async def stream():
        try:
            async for chunk in call_llm_stream(messages):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/search")
async def search_journal(q: str, limit: int = 20):
    """搜索日记内容."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM journal WHERE content LIKE ? ORDER BY trade_date DESC LIMIT ?",
            (f"%{q}%", limit)
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()
