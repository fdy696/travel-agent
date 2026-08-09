# 行伴 Travel Agent v6

当前实现对应架构的前三个开发阶段：

1. **V6 基线**：去掉 Planning Workflow / Plan CRUD / Renderer。
2. **Main Agent + Travel Planning Skill**：Main 直接完成 Final Plan Synthesis，输出完整 Markdown，并支持同一会话自然语言修改。
3. **Travel Tools**：接入已有 Tavily Search、和风天气、高德路线工具。

当前暂不包含 Travel Researcher、Redis/Postgres 持久化、Streaming、Evals。

## 架构

```text
User
  │
  ▼
Main Agent
  ├── travel-planning Skill
  ├── search_travel_info
  ├── get_weather
  └── search_maps
  │
  ▼
Final Plan Synthesis
  │
  ▼
Full Markdown Plan
```

修改计划仍由 Main Agent 完成：

```text
Conversation + Previous Markdown Plan + New User Request
                         ↓
                      Main Agent
                         ↓
                 New Full Markdown Plan
```

不使用 `update_plan()` / Patch / Plan DB。

## 安装

Python 3.11+：

```bash
uv sync
```

复制环境变量：

```bash
cp .env.example .env
```

配置：

- `DEEPSEEK_API_KEY`
- `TAVILY_API_KEY`
- `QWEATHER_API_KEY`
- `AMAP_API_KEY`

## 运行

推荐使用交互模式验证连续修改：

```bash
uv run python cli.py
```

示例：

```text
你：北京三日游，情侣，预算 3000

# Agent 返回完整 Markdown Plan

你：第二天不要原来的安排了，换成环球影城，预算不要增加太多

# Agent 基于同一 thread 中上一版 Plan，重新输出完整修改版 Plan
```

单次调用：

```bash
uv run python cli.py -m "成都四日游，两个人，偏美食和慢节奏"
```

## 当前会话机制

CLI 使用 `InMemorySaver`，作用是验证“同一 thread 连续规划与修改”的正确性：

- 同一 CLI 进程内：可以连续修改。
- CLI 退出后：会话消失。

这是刻意的阶段边界。生产 Redis/Postgres Checkpointer 放到后续 Runtime 阶段，不在当前版本提前引入。

## 关键文件

```text
agent.py
cli.py
config.py

skills/
└── travel-planning/
    └── SKILL.md

tools/
├── agent_tools.py
├── search.py
├── weather.py
└── route.py
```

## 当前明确不做

- Planning Graph
- Planning / Modify / Writer Agent
- PlanContent / PlanDocument
- Plan CRUD / Repository / Database
- Renderer
- Validator / Repair Workflow
- Travel Researcher（下一阶段再加）
