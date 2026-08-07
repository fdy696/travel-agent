# backend_v4 Week 2 实现补丁

本目录是相对 `backend_v4/` 的覆盖补丁。

## 新增/替换

```text
agent.py                  # 替换：挂载 CompiledSubAgent + InMemorySaver
cli.py                    # 替换：同一 REPL thread_id 保持多轮对话
planning/
  models.py               # Requirements / PlanDraft / PlanningTask / PlanDocument
  validator.py            # 纯代码 Validator
  repository.py           # SQLite 业务事实源（生产换 PostgreSQL）
  intelligence.py         # LLM 抽取 / Research Agent / Generate / Repair
  workflow.py             # LangGraph 确定性 Planning Workflow
  __init__.py
tools/
  agent_tools.py          # 从旧 agent.py 抽出的 @tool 包装，主 Agent/Workflow 复用
tests/
  test_models.py
  test_validator.py
  test_repository.py
  test_workflow.py
```

原有以下文件保持不变：

```text
config.py
tools/weather.py
tools/search.py
tools/route.py
```

## 依赖

Week 2 代码使用当前 Deep Agents / LangChain API：

- `deepagents`（当前参考 API 0.6.x）
- `langchain` 1.x
- `langgraph` 1.x
- `langchain-deepseek` 1.x
- `pydantic` 2.x
- `pytest` + `pytest-asyncio`（测试）

如果你的 `pyproject.toml` 已由 `deepagents` 间接安装 LangChain/LangGraph，仍建议把直接 import 的包列为项目直接依赖，避免未来依赖树变化。

示例：

```bash
uv add "deepagents>=0.6,<0.7" "langchain>=1,<2" "langgraph>=1,<2" "langchain-deepseek>=1,<2" "pydantic>=2,<3"
uv add --dev pytest pytest-asyncio
```

> 如果你当前锁文件已经验证了其他兼容版本，不要为了版本号好看盲目升级。软件版本号这种东西，最擅长在周五下午教育人类。

## 数据

默认 SQLite：

```text
backend_v4/.data/travel_agent.db
```

可通过环境变量覆盖：

```bash
TRAVEL_PLANNING_DB=/path/to/travel_agent.db
```

SQLite 只用于 Week 2 CLI/MVP。Repository 边界已经独立，生产环境替换 PostgreSQL 时不需要重写 Planning Workflow。

## 运行

```bash
uv run python -m cli
```

推荐测试：

```text
你：帮我规划云南5日游
助手：...询问出行人数...
你：2个人，10月1日出发，预算每人5000
助手：...Research → Generate → Validate → Plan V1...
```

普通问答仍应正常：

```text
你：丽江今天冷吗？
你：北京西站到首都机场多久？
```

## 测试

```bash
uv run pytest -q
```

测试分层：

- models：需求合并、日期计算、必填判断
- validator：时间冲突、预算、稳定 ID 等硬规则
- repository：PlanningTask 与 Plan V1 持久化
- workflow：使用 FakeIntelligence，不请求真实 LLM/API，验证“收集 → 补充 → repair → 完成”状态链

## Week 2 明确不做

- 已交付计划局部修改（Week 3/4）
- PostgreSQL 正式 Repository
- 多用户认证与 namespace
- Memory / Skills
- HITL / permissions
- 生产持久化 checkpointer
- TravelStateMiddleware
- SSE 前端事件协议

## 关键实现说明

1. `CompiledSubAgent` 的 runnable state 包含 `messages`，满足 Deep Agents task handoff 契约。
2. Main Agent 使用 `TravelRuntimeContext(user_id, session_id)`；Deep Agents 会把 runtime context 传给同步 Subagent，Workflow 用它定位 PlanningTask。
3. Planning graph 设置 `output_schema=MessagesState`，只把最终消息交还父 Agent，内部 task/research/draft 状态不会污染主 Agent state。
4. Subagent 本身每次调用仍是短生命周期；跨轮续接依赖 SQLite `planning_tasks`，不是依赖 Subagent 常驻。
5. Main Agent 的多轮聊天上下文由 `InMemorySaver` 保存，仅用于当前 CLI 进程。
6. Plan stable ID 由代码统一分配，不把唯一性寄托在 LLM 的心情上。
7. Validator 最多允许 2 次语义 repair；仍失败则任务进入 `failed`。
