# Travel Agent v5

面向 C 端用户的对话式旅游助手。当前架构基线：

- **Main Deep Agent**：唯一核心业务 Agent，负责普通问答、闲聊、旅游规划与 Plan 修改。
- **Travel Planning Skill**：按需加载旅游规划 procedure，不把规划流程硬编码成 Workflow。
- **Travel Researcher SubAgent**：只读 Research Worker，用于隔离大量 Search / Weather / Map 中间结果。
- **Domain Tools + SQLite**：Requirements 与 Current Plan 的 canonical business state。
- **Redis Checkpointer**：持久化 LangGraph conversation/thread state。
- **Deterministic Renderer**：Plan JSON -> 完整 Markdown，避免 Main Agent 二次压缩。

## 架构

```text
User
  |
  v
Main Deep Agent
  |-- Chat / QA
  |-- Travel Planning Skill
  |-- search / weather / maps
  |-- Plan Domain Tools
  |     |-- update_requirements
  |     |-- get_current_plan
  |     |-- create_plan
  |     `-- update_plan
  |
  `-- travel-researcher
        |-- search
        |-- weather
        `-- maps
             |
             `-- concise Research Brief -> Main Agent

Conversation / Thread -> Redis Checkpointer
Requirements / Current Plan -> SQLite
```

## 目录

```text
.
├── agent.py
├── cli.py
├── config.py
├── persistence.py
├── docker-compose.yml
├── .env.example
│
├── planning/
│   ├── models.py
│   ├── domain.py
│   ├── domain_tools.py
│   ├── repository.py
│   ├── renderer.py
│   └── runtime.py
│
├── subagents/
│   └── research.py
│
├── skills/
│   └── travel-planning/
│       ├── SKILL.md
│       └── references/
│           └── plan-schema.md
│
├── tools/
│   ├── agent_tools.py
│   ├── search.py
│   ├── weather.py
│   └── route.py
│
└── tests/
```

## 1. 解压

假设当前目录是空目录：

```bash
unzip travel-agent-v5-full.zip -d .
```

如果 ZIP 在 Windows `D:\\download`，WSL 下：

```bash
unzip "/mnt/d/download/travel-agent-v5-full.zip" -d .
```

## 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
DEEPSEEK_API_KEY=...
CHAT_MODEL=deepseek-v4-flash

TAVILY_API_KEY=...

QWEATHER_API_KEY=...
QWEATHER_API_HOST=你的专属APIHost，例如 abc1234xyz.def.qweatherapi.com

AMAP_API_KEY=...

REDIS_URL=redis://localhost:6379
```

说明：QWeather 2026 推荐使用账号专属 API Host，不再依赖旧 `devapi.qweather.com` / `geoapi.qweather.com` 公共域名。

## 3. 启 Redis

```bash
docker compose up -d
```

检查：

```bash
docker compose ps
docker exec travel-agent-redis redis-cli ping
```

预期：

```text
PONG
```

Redis 使用 named volume + AOF：

```text
travel_agent_redis_data
```

所以应用进程或 Redis 容器重启后 thread checkpoint 仍可恢复。

## 4. 安装依赖

需要 Python 3.11+ 与 uv：

```bash
uv sync
```

关键快速迭代依赖已锁定到当前稳定版本区间中的具体版本：

```text
deepagents 0.6.12
langchain 1.3.14
langgraph 1.2.9
langchain-deepseek 1.1.0
langgraph-checkpoint-redis 0.5.1
tavily-python 0.7.26
```

## 5. 跑测试

```bash
uv run pytest -q
```

## 6. 启动 CLI

```bash
uv run python -m cli --session-id demo
```

单次问答：

```bash
uv run python -m cli --session-id demo -m "帮我规划云南5天"
```

复用同一个 `--session-id`，Redis 会恢复 conversation/thread checkpoint。

## SQLite 数据

默认数据库：

```text
.data/travel_agent.db
```

保存：

```text
planning_requirements
plans
```

如果要换路径：

```env
TRAVEL_PLANNING_DB=/your/path/travel_agent.db
```

注意：**Redis 存 conversation；SQLite 存业务事实。** 两者不要混。

## 推荐验收场景

### 普通聊天

```text
用户：大理和丽江哪个更适合情侣？
预期：Main Agent 直接回答；需要实时事实时调用工具。
```

### 新建 Plan，缺需求

```text
用户：帮我规划云南5天
预期：update_requirements -> 缺 traveler_count -> 只追问人数，不保存 Plan。
```

### 补齐需求

```text
用户：2个人
预期：requirements complete -> Research（按需要）-> create_plan。
```

### Plan 追问

```text
用户：第二天住哪？
预期：当前 conversation 足够时 Main Agent 直接回答，不为了形式强制读 DB。
```

### 简单修改

```text
用户：第一天轻松一点
预期：Main Agent 使用 travel-planning Skill -> semantic edit -> update_plan。
```

### 同一旅行重规划

```text
用户：这个行程重新规划一下，节奏轻松点
预期：保留当前目的地/天数/人数，不 reset requirements。
```

### 高输出 Research

```text
用户：规划新疆12天，并深入查独库路况、天气、交通、预约和住宿区域
预期：Main Agent 可自动委派 travel-researcher；大量中间 Tool Results 留在 child context，只返回 Research Brief。
```

## 关键设计边界

```text
语义理解 / 怎么规划 / 怎么修改 / 查什么
-> Model

Requirements 完整性 / Schema / IDs / canonical state / Persistence
-> Domain Code

大量一次性 Research 上下文
-> Travel Researcher SubAgent

长期 conversation/thread state
-> Redis Checkpointer

Current Plan / Requirements
-> SQLite Repository
```

`planning/plan_agent.py`、`planning/workflow.py`、Validator/Repair Agent、Create/Modify Agent 都不属于当前架构。
