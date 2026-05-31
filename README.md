# 🧠 Trading Mind Care

> 一个懂交易的 AI 心理教练 — 记住你每一次的计划和每一次的违背，用数据和逻辑逼你直面自己的弱点。

## 核心功能

- **📋 计划管理**：每日交易计划 + 高频弱点预警
- **🔥 复盘拷打**：AI 交叉审计计划 vs 实际，毒舌但不侮辱
- **📊 弱点矩阵**：自动提取心理弱点，权重随时间演进
- **📢 飞书通知**：每日推送计划 + 弱点警告

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

## 技术栈

- Python 3.11 + FastAPI + Uvicorn
- SQLite (aiosqlite, WAL mode)
- Vanilla HTML/JS/CSS
- APScheduler (定时任务)
- PyInstaller (打包为 .exe)

## 目录结构

```
├── app/
│   ├── main.py          # FastAPI 入口
│   ├── database.py      # 数据库初始化
│   ├── llm.py           # LLM 适配层
│   ├── feishu.py        # 飞书通知
│   ├── scheduler.py     # 定时任务
│   ├── routes/          # API 路由
│   └── static/          # 前端文件
├── run.py               # 启动脚本
├── requirements.txt
├── TradingMindCare.spec # PyInstaller 配置
├── DECISIONS.md         # 设计决策记录
└── EVOLUTION_REPORT.md  # 演进报告
```

## 数据存储

- Windows: `%LOCALAPPDATA%\TradingMindCare\mind_care.db`
- Linux/macOS: `~/.trading_mind_care/mind_care.db`

升级软件不会丢失数据。
