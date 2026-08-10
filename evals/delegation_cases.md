# Travel Agent v6 Eval Cases

用于 CLI 人工 trajectory eval，重点验证需求澄清、Research 隔离、预算计算、币种和模型 / 环境策略。

## Case 1：闲聊

```text
你好
```

期望：不读 Skill、不调用 Researcher、不调用旅行 Tool，直接回答。

## Case 2：普通旅行事实

```text
东京明天天气怎么样？
```

期望：Main 可直接调用 `get_weather`；不读完整 Planning Contract；不委派 Researcher。

## Case 3：信息不足的完整规划

```text
帮我规划日本5天游，东京进
```

期望：Main 先澄清会改变整体方案的关键条件；关键条件明确前不委派 Researcher。

## Case 4：完整跨城规划

```text
2026年8月20日东京进，8月24日大阪出，2人，舒适型，其他你安排。
```

期望轨迹：

```text
Main
→ Skill: travel-planning
→ task(subagent_type="travel-researcher")
→ Research Findings
→ calculate_budget（存在多项费用时）
→ convert_currency（需要人民币辅助参考时）
→ Markdown Contract
→ Final Plan
```

Researcher 内只出现 search / maps / weather，不出现 `calculate_budget` / `convert_currency`。

## Case 5：JR Pass 不得提前假设

同 Case 4。

期望：Main 在 Research 前不得把“购买 JR Pass”写成默认交通结论。Research Brief 应要求比较单程购票 / Pass 等合理方案，Research 后再决定。

## Case 6：预算一致性

日本路线包含：东京→京都、京都→大阪、住宿、餐饮、门票。

期望：

- 最终预算只汇总最终采用方案
- 不把“京都→大阪新干线备选价”和“JR 新快速最终价”同时混进总额
- 总额 / 人均以 `calculate_budget` 结果为准

## Case 7：币种

期望：

- 不出现裸 `¥14,000`
- 使用 `14,000 日元` 或 `JPY 14,000`
- 如出现人民币参考，来自 `convert_currency`
- 汇率服务失败时只保留当地货币

## Case 8：模型切换

```env
LLM_PROVIDER=deepseek
```

和：

```env
LLM_PROVIDER=ollama
```

期望：无需修改 Agent / Skill / Tool 代码；CLI 启动栏显示实际 provider/model。

## Case 9：搜索环境

- development：DDGS，不请求 Tavily
- test：FakeSearch，不联网
- production：Tavily primary，失败后 DDGS fallback
