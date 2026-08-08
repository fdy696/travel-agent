# Architecture Baseline

## Core rule

> LLM is a semantic decision engine, not the system of record.

系统只有一个核心业务 Agent：Main Deep Agent。

- 普通问答与闲聊留在 Main conversation。
- 旅游规划通过 `travel-planning` Skill 给 Main Agent 注入领域 procedure。
- 简单实时查询由 Main 直接调用 research tools。
- 大量、多源、一次性的 Research 才委派给 `travel-researcher`，目的主要是 context isolation。
- Requirements / Current Plan 由 Domain Layer + SQLite 持有 canonical state。
- Conversation / LangGraph thread checkpoint 由 Redis 持久化。

## Why no Planning SubAgent

旅游规划需要连续共享用户上下文：需求补充、追问、解释和多轮修改。把整个 Planning 放进 stateless child context 会反复搬运上下文。

## Why keep Travel Researcher

它不是第二个业务 Agent，只是 domain-specialized context-isolation worker：

```text
read-only tools = search + weather + maps
no requirements write
no plan write
no repository
```

Main Agent 根据它的 `description` 自主决定是否委派，不在业务代码中写 `if days > N` 或 `if search_count > N`。

## Persistence

```text
Redis
`-- LangGraph Checkpointer / Conversation Thread

SQLite
|-- planning_requirements
`-- plans (one current Plan per user/session)
```

## Code boundaries

- `agent.py`: composition root only.
- `skills/`: reusable planning procedure.
- `subagents/research.py`: tiny declarative research worker.
- `planning/domain.py`: deterministic business logic.
- `planning/domain_tools.py`: Agent-to-Domain adapter.
- `planning/repository.py`: persistence only.
- `planning/models.py`: Pydantic schemas + deterministic normalization.
- `planning/renderer.py`: structured Plan -> Markdown.
