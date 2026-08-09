# Selective Delegation Eval Cases

这些 Case 用于人工 / LangSmith trajectory eval，重点验证 Main 是否正确选择：直接回答、直接 Tool、Travel Skill、或 `task -> general-purpose`。

CLI 默认 debug，可以直接观察实际 trajectory。

## Case 1：闲聊

```text
你好
```

期望：

- 不读取 travel-planning Skill
- 不调用 Travel Tool
- 不调用 task
- 直接自然回答

## Case 2：简单实时事实

```text
东京明天天气怎么样？
```

期望：

- `get_weather`
- 不读取完整 Travel Planning Skill
- 不调用 task

## Case 3：轻量推荐

```text
推荐几个京都值得去的寺庙
```

期望：

- Main 直接回答
- 必要时少量 `search_travel_info`
- 不生成完整多日 Plan
- 不调用 task

## Case 4：普通完整规划

```text
帮我规划洛阳三日游，从北京出发，情侣，预算 3000 元，喜欢历史文化和美食。
```

期望：

- 读取 `travel-planning`
- 按需直接调用 search / maps / weather
- 通常不需要 task
- 最终遵守 Markdown Contract

## Case 5：复杂 Research，应考虑委派

```text
帮我规划日本 15 天，东京进大阪出。想去东京、箱根或河口湖（二选一）、京都、大阪。请比较箱根和河口湖，研究主要跨城交通方案、多个交通 Pass 是否值得、环球影城和热门景点预约规则，再给完整行程。我们不自驾，偏轻松旅行。
```

期望：

- 读取 `travel-planning`
- Main 判断存在相对独立、高噪声、多步骤 Research
- 出现 `task` Tool Call
- `subagent_type = general-purpose`
- description 是完整 Research Brief，不是短句
- SubAgent 内部可调用 search / maps / weather
- SubAgent 返回 Findings
- Main 做最终 Plan Synthesis

## Case 6：已有计划局部修改

前置：先完成一份东京五日游。

然后输入：

```text
把第二天换成迪士尼，其他要求尽量保持不变。
```

期望：

- 读取当前 conversation 最近完整 Plan
- 只 Research 受影响内容
- 简单修改不应无理由调用 task
- 返回新的完整 Markdown Plan，而不是 diff

## Case 7：复杂修改，可委派受影响 Research

前置：已有日本多城市计划。

然后输入：

```text
我不买 JR Pass 了，重新比较东京到箱根、箱根到京都、京都到大阪的交通组合和费用影响，再调整整份行程。
```

期望：

- 只研究受影响交通部分
- 如果需要多方案、多来源比较，可调用 `task -> general-purpose`
- Main 综合 Findings 后重新平衡路线和预算
- 返回新的完整 Plan

## 观察重点

开发 CLI 中重点确认：

```text
MAIN
→ Tool Call / read skill
→ task(subagent_type="general-purpose")（仅复杂 case）
→ SUBAGENT namespace
→ SubAgent Tool Calls / Results
→ task ToolMessage Research Findings
→ MAIN final model call
→ Final Answer
```

若普通简单 Case 频繁调用 task，说明 delegation prompt 过度；若复杂 Case 长期完全不委派，则需要调整 Main Prompt 中的复杂 Research 描述，而不是增加 Python Router。
