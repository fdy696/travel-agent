# travel-agent v4（Deep Agents 框架版）— Week 1

> 自包含工程，不依赖 `backend/app`。对应架构文档：[backend/docs/架构文档-v4-DeepAgents.md](../backend/docs/架构文档-v4-DeepAgents.md)

**Week 1 目标**：搭起最小 Deep Agent（主 Agent + get_weather / search 工具）→ **通用问答跑通**（CLI 模式）。

## 目录结构

```
backend_v4/
  config.py     # 读取仓库根 .env（与 backend 共用同一份 key）
  agent.py      # create_deep_agent 主 Agent + @tool 业务工具 + System Prompt
  cli.py        # CLI 入口（REPL 交互 / 单次问答）
  tools/        # 底层 API 实现（复制自 backend/app/agents/tools/，改为独立依赖）
    weather.py  #   和风天气
    search.py   #   Tavily 搜索
    route.py    #   高德路线
  pyproject.toml  # 独立工程依赖
  README.md
```

## 首次安装 & 运行

需要：本机已装 `uv`；仓库根 `.env` 已配置 DEEPSEEK / QWEATHER / TAVILY / AMAP key。

```bash
cd backend_v4
uv sync                      # 安装依赖到 backend_v4/.venv
uv run python -m cli                                   # 交互式 REPL
uv run python -m cli --message "北京今天天气怎么样？"    # 单次问答
# Windows 控制台若中文/emoji 乱码，加 PYTHONIOENCODING=utf-8
```

交互命令：输入问题回车；`/quit`、`/exit`、`q`、`退出` 结束。

## 已验证（2026-08-06 真实 API 调用）

| 场景 | 示例 | 结果 |
|---|---|---|
| 闲聊直答 | "你好，简单介绍下你能帮我做什么" | ✅ 直接回答，不调工具 |
| 天气工具 | "北京今天天气怎么样？" | ✅ 调 get_weather（和风） |
| 搜索工具 | "丽江有哪些必去的景点？" | ✅ 调 search_travel_info（Tavily） |
| 路线工具 | "从北京西站到首都机场怎么走？" | ✅ 调 search_maps（高德） |

## 范围说明

**已实现（Week 1）**：
- `create_deep_agent` 主 Agent（ReAct + tool-calling，无前置意图路由）
- 3 个只读业务工具（weather / search / maps）
- System Prompt 定义工具使用规则与回复风格
- CLI 交互入口

**明确不做（后续周次）**：
- Week 2：`travel_planning_agent` 子 Agent + 虚拟文件系统（StoreBackend）→ 首次规划
- Week 3：`modify_travel_plan` 工具 + `TravelStateMiddleware` → 修改流程 + 状态感知
- Week 4：`interrupt_on` + `permissions` + Golden 测试集 → 生产化护栏
- Week 5：Memory（AGENTS.md）+ Skills → 长期偏好与领域扩展

## 说明

- `.env` 从仓库根读取（`config.py` 上溯 1 级），与 `backend` 共用同一份 key；如需完全独立可在 `backend_v4/` 放一份 `.env` 并调整 `config.py` 的 `ENV_FILE`。
- 模型沿用 DeepSeek（`CHAT_MODEL` + `DEEPSEEK_API_KEY`）；v4 文档示例为 claude-sonnet-4，切换模型改配置即可。
