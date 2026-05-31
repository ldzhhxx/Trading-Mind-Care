"""Review templates - predefined frameworks for structured reviews (v8.0)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from app.database import get_db

router = APIRouter(prefix="/api/review-templates", tags=["review-templates"])

# Built-in templates
BUILTIN_TEMPLATES = [
    {
        "id": "quick",
        "name": "快速复盘",
        "description": "30秒完成，适合忙碌时",
        "prompts": ["今天盈亏多少？", "一句话总结今天", "明天要注意什么？"],
        "builtin": True,
    },
    {
        "id": "standard",
        "name": "标准复盘",
        "description": "完整的交易日复盘",
        "prompts": [
            "今天执行了哪些计划？哪些没执行？",
            "最大的一笔交易是什么？为什么进场？",
            "有没有违反纪律的行为？",
            "情绪状态如何？有没有影响决策？",
            "明天的改进点是什么？",
        ],
        "builtin": True,
    },
    {
        "id": "loss",
        "name": "亏损日复盘",
        "description": "专门针对亏损日的深度反思",
        "prompts": [
            "亏损的根本原因是什么？（市场/策略/心态/执行）",
            "是否存在报复性交易？",
            "止损是否执行到位？",
            "如果重来一次，你会怎么做？",
            "这次亏损暴露了什么弱点？",
        ],
        "builtin": True,
    },
    {
        "id": "win",
        "name": "盈利日复盘",
        "description": "盈利时更要冷静分析",
        "prompts": [
            "盈利是因为运气还是实力？",
            "有没有过度自信的迹象？",
            "是否严格按计划执行？",
            "盈利后是否有加仓冲动？",
            "如何保持这种状态？",
        ],
        "builtin": True,
    },
    {
        "id": "weekly",
        "name": "周末总结",
        "description": "每周回顾整体表现",
        "prompts": [
            "本周总盈亏和胜率如何？",
            "本周最好的一笔交易和最差的一笔？",
            "计划执行率满意吗？",
            "弱点有改善还是恶化？",
            "下周的重点改进方向？",
        ],
        "builtin": True,
    },
]


class TemplateCreate(BaseModel):
    name: str
    description: str = ""
    prompts: list[str]

    @field_validator("name")
    @classmethod
    def name_valid(cls, v):
        v = v.strip()
        if not v or len(v) > 50:
            raise ValueError("名称1-50字")
        return v

    @field_validator("prompts")
    @classmethod
    def prompts_valid(cls, v):
        if not v or len(v) > 10:
            raise ValueError("提示问题1-10条")
        return [p.strip() for p in v if p.strip()]


@router.get("")
async def list_review_templates():
    """List all review templates (builtin + custom)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM review_templates ORDER BY id DESC")
        custom = [dict(r) for r in await cursor.fetchall()]
        # Parse prompts from JSON string
        import json
        for t in custom:
            t["prompts"] = json.loads(t["prompts"]) if t.get("prompts") else []
            t["builtin"] = False
        return BUILTIN_TEMPLATES + custom
    finally:
        await db.close()


@router.post("")
async def create_review_template(tpl: TemplateCreate):
    """Create a custom review template."""
    import json
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO review_templates (name, description, prompts) VALUES (?, ?, ?)",
            (tpl.name, tpl.description, json.dumps(tpl.prompts, ensure_ascii=False)),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{tpl_id}")
async def delete_review_template(tpl_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM review_templates WHERE id = ?", (tpl_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="模板不存在")
        return {"ok": True}
    finally:
        await db.close()


@router.post("/ai-recommend")
async def ai_recommend_template():
    """AI recommends which review template to use based on today's context."""
    from datetime import date
    db = await get_db()
    try:
        today = date.today().isoformat()
        # Check if there are recent losses
        cursor = await db.execute(
            "SELECT pnl FROM reviews WHERE pnl IS NOT NULL ORDER BY trade_date DESC LIMIT 3"
        )
        recent_pnls = [r["pnl"] for r in await cursor.fetchall()]

        # Check plan execution
        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(done) as completed FROM plans WHERE trade_date = ? AND plan_type='today'",
            (today,)
        )
        plan_row = await cursor.fetchone()
    finally:
        await db.close()

    # Simple rule-based recommendation
    if not recent_pnls:
        return {"template_id": "standard", "reason": "首次复盘，建议使用标准模板"}

    last_pnl = recent_pnls[0] if recent_pnls else 0
    consecutive_losses = sum(1 for p in recent_pnls if p < 0)

    if consecutive_losses >= 2:
        return {"template_id": "loss", "reason": f"连续{consecutive_losses}天亏损，建议深度反思"}
    if last_pnl < 0:
        return {"template_id": "loss", "reason": "今日亏损，建议使用亏损日模板"}
    if last_pnl > 0 and all(p > 0 for p in recent_pnls[:3]):
        return {"template_id": "win", "reason": "连续盈利，警惕过度自信"}
    if plan_row and plan_row["total"] == 0:
        return {"template_id": "quick", "reason": "今日无计划，快速记录即可"}

    from datetime import date as d
    if d.today().weekday() >= 4:  # Friday+
        return {"template_id": "weekly", "reason": "周末了，适合做周度总结"}

    return {"template_id": "standard", "reason": "常规交易日，标准复盘"}
