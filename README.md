# Travel Agent — Claude Code-style Agent Harness Refactor

这份代码是针对 `week_03` 的重构实现，不再使用 `planning/workflow.py` 作为主要控制器。

## 架构

```text
User
 ↓
Main Deep Agent
 ├─ 普通 QA / weather / search / maps
 ├─ Plan 简单追问：conversation context 优先
 ├─ context 不足时：get_current_plan fallback
 └─ Plan mutation
      ↓
   travel-planning declarative SubAgent
      ├─ Skill: procedural playbook
      ├─ Research tools: agent 自主决定调用路径
      └─ Domain tools
           ├─ update_requirements
           ├─ get_current_plan
           ├─ create_plan
           └─ update_plan
                ↓
          Pydantic + normalize + Repository + Renderer
```

## 核心变化

1. 删除 create/modify 的 Graph 二次意图识别。
2. 一个 Travel Plan Agent 同时负责 create / modify；Agent 边界按领域/上下文划分，不按 CRUD 划分。
3. `planning_requirements` 外部化未完成需求，因此 SubAgent 每次 task 都可以是新的 isolated context。
4. Research 不再嵌套一个 Research Agent；Travel Plan Agent 自己调用 weather/search/maps。
5. 最终 Plan 不再由额外 `structured_generate` 调用产生，而是 Agent 调用 `create_plan/update_plan` 时提交完整对象；Domain Tool 用 Pydantic 校验。
6. Schema 错误直接作为 Tool feedback 返回，Agent 最多修一次，不再建 Repair Workflow。
7. Main Agent 对“第二天住哪？”这类问题优先使用 conversation context，不强制读 DB。
8. Repository 只保留 current Plan，无版本链；`(user_id, session_id)` 唯一。

## 从 week_03 删除

```text
planning/workflow.py
planning/intelligence.py
planning/llm_json.py
```

如果你想保留 `llm_json.py` 给别的功能用也无妨，但这套 Plan Agent 不再依赖它。

## 运行

把本目录覆盖到当前 `week_03` 对应文件后：

```bash
uv sync
uv run pytest
uv run python -m cli --session-id demo
```

`.env` 继续沿用当前项目：`DEEPSEEK_API_KEY / TAVILY_API_KEY / QWEATHER_API_KEY / AMAP_API_KEY`。

## 建议测试会话

```text
帮我规划云南5天
→ 应只追问人数，不 Research/保存

2个人
→ 继续 requirements draft，Research，保存完整 Plan

第二天住哪？
→ Main 基于 conversation context 直接回答

第二天轻松一点
→ Travel Plan Agent get_current_plan → semantic edit → update_plan

延长到7天，加香格里拉，查一下最新交通
→ get_current_plan → Agent 自主 search/maps → update_plan
```
