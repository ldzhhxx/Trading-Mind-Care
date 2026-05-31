# 🧠 Trading Mind Care

> 一个懂交易的 AI 心理教练 — 记住你每一次的计划和每一次的违背，用数据和逻辑逼你直面自己的弱点。

## 核心功能

- **📋 计划管理**：每日交易计划 + 模板 + 高频弱点预警 + AI 模糊表述检测
- **🔥 复盘拷打**：AI 流式交叉审计计划 vs 实际，5 级毒舌强度可调 + 快速复盘模式
- **📊 弱点矩阵**：自动提取心理弱点，权重随时间演进，AI 模式分析 + 弱点关联分析
- **📏 交易纪律**：自定义规则 + AI 个性化生成，复盘时自动检查是否违反
- **📈 统计面板**：盈亏/胜率/回撤/情绪相关性/星期几表现 + 计划执行率趋势 + 情绪趋势
- **🔬 深度分析**：盈亏分布/情绪相关性/计划执行率相关性/弱点时间线/交易时段分析
- **🤖 AI 增强**：本周vs上周对比/危险信号识别/弱点深度关联/个性化纪律生成
- **🗓️ 交易日历**：月度 PnL 可视化 + 计划完成状态
- **📢 飞书通知**：每日推送 + 连亏预警 + 大额提醒 + 计划未完成提醒 + 可配置时间
- **📓 交易日记**：自由记录市场观察和教训
- **💾 数据安全**：自动备份（每日）+ 手动备份 + 全量导入导出 + 崩溃恢复

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动（自动打开浏览器）
python run.py
```

访问 http://127.0.0.1:18088

## 首次使用

1. 进入 **设置** 页面，填写 LLM API 配置（Base URL / API Key / Model）
2. 点击"测试连接"确认可用
3. 回到 **计划** 页面，写下今日交易计划
4. 盘后进入 **复盘** 页面，输入盈亏和交易感受，接受 AI 拷打
5. 查看 **弱点矩阵**，了解系统对你的弱点画像

## LLM 配置说明

支持任何 OpenAI 兼容 API：
- OpenAI (gpt-4o-mini, gpt-4o)
- DeepSeek (deepseek-chat)
- 通义千问 (qwen-plus)
- 本地 Ollama (http://localhost:11434/v1)

填写 Base URL（如 `https://api.openai.com/v1`）、API Key 和模型名称即可。

## 打包为 .exe

```bash
pip install pyinstaller
pyinstaller TradingMindCare.spec
```

生成的 `dist/TradingMindCare.exe` 为单文件可执行程序，双击即可运行。

## 技术栈

- Python 3.11+ / FastAPI / Uvicorn
- SQLite (aiosqlite, WAL mode, busy_timeout)
- Vanilla HTML/JS/CSS（无框架依赖）
- APScheduler（定时任务）
- httpx（异步 HTTP 客户端）
- PyInstaller（打包为 .exe）

## 目录结构

```
├── app/
│   ├── main.py          # FastAPI 入口 + 日志配置
│   ├── database.py      # 数据库初始化 + 迁移
│   ├── llm.py           # LLM 适配层（重试 + 流式 + 缓存）
│   ├── feishu.py        # 飞书通知（富文本卡片）
│   ├── scheduler.py     # 定时任务（衰减/通知/提醒）
│   ├── routes/          # API 路由（14 个模块）
│   └── static/          # 前端文件（HTML/CSS/JS）
├── run.py               # 启动脚本
├── requirements.txt     # 依赖（锁定版本）
├── TradingMindCare.spec # PyInstaller 配置
├── DECISIONS.md         # 设计决策记录
└── EVOLUTION_REPORT.md  # 演进报告
```

## 数据存储

- Windows: `%LOCALAPPDATA%\TradingMindCare\mind_care.db`
- Linux/macOS: `~/.trading_mind_care/mind_care.db`

升级软件不会丢失数据。支持通过设置页导出全量 JSON 备份。

## API 文档

启动后访问 http://127.0.0.1:18088/docs 查看自动生成的 OpenAPI 文档。

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `1`-`7` | 切换标签页 |
| `Enter` | 提交计划（在输入框中） |
| `?` | 显示快捷键帮助 |

## 版本历史

- **v5.0.0** — 深度功能扩展：深度分析/AI增强/快速复盘/自动备份/崩溃恢复
- **v4.0.0** — 商用级打磨：稳定性/日志/错误处理/打包修复
- **v3.0.0** — 60+ 功能完成：日历/月报/日记/数据健康检查
- **v2.0.0** — 流式输出/弱点矩阵/飞书通知
- **v1.0.0** — 核心闭环：计划 → 复盘 → 弱点提取
