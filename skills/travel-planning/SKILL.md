---
name: travel-planning
description: Create, modify, extend, shorten, rearrange, or replan the user's complete multi-day travel plan in the main conversation.
---

# Travel Planning

This Skill is the planning playbook for the Main Agent. Travel planning stays in the main conversation so user requirements, follow-up answers, plan questions, and later modifications share one continuous context.

Use an adaptive agent loop: understand the request, gather only the context you need, research when needed, then commit through Domain Tools.

## Create a new trip

1. Convert only the user's explicit or directly inferable trip requirements into an `update_requirements` patch.
2. When the user clearly starts a different/new trip, call `update_requirements(..., reset=true)`.
3. When the user is answering a previous missing-info question, use `reset=false`.
4. Inspect `missing_fields` returned by the tool.
5. If blocking fields are missing, ask only for them and stop. Do not research or submit a Plan yet.
6. Once requirements are complete, research current/external facts as needed.
7. For simple research, call search/weather/maps directly.
8. When research is substantial and would fill the main context with large intermediate tool results, delegate it to `travel-researcher` and use its Research Brief.
9. Before constructing the final Plan, read `/skills/travel-planning/references/plan-schema.md`.
10. Produce a complete Rich Plan, not a short itinerary summary.
11. Call `create_plan` when there is no current Plan.
12. If the user is intentionally replacing an existing Plan with this newly collected complete Requirements Draft, call `update_plan(..., use_requirements_draft=true)` instead.
13. On success, return only the Markdown inside `<final_markdown>` markers, verbatim.

## Modify / replan the current trip

1. As soon as you semantically determine that the user wants to change the current Plan, call `begin_plan_change` before research or constructing the updated Plan. This does not modify business data; code verifies that a current Plan exists and activates the completion invariant.
2. Use the current conversation to understand the requested change. If canonical state is required or context is incomplete, call `get_current_plan`.
3. A replan of the *same trip* is a modification, not a fresh requirements reset. Preserve current destinations/dates/travelers unless the user explicitly changes them.
4. Preserve unrelated content and information density.
5. Research only when the modification depends on current/external facts.
6. Simple semantic edits should not trigger research merely because a keyword appears.
7. If the user explicitly changes trip-level requirements such as days, destinations, travelers, or dates, pass a `requirements_patch` to `update_plan`.
8. Do not use `use_requirements_draft=true` for ordinary modifications or replanning of the same trip.
9. Read `/skills/travel-planning/references/plan-schema.md` before building the final updated Plan if it has not been loaded in this task.
10. `update_plan` receives the complete updated PlanContent, never a partial patch and never a duplicated `requirements` object.
11. On success, return only the Markdown inside `<final_markdown>` markers, verbatim.

## Research

- Current/changeable facts must come from tools, not memory.
- Current/near-3-day weather can use the weather tool; later seasonal climate should use web search.
- Use maps when route/distance/time materially affects the itinerary.
- Search order and number of calls are semantic decisions; do not use hard-coded thresholds.
- Delegate to `travel-researcher` only when context isolation has clear value. One-off lookups should stay in the Main Agent.
- A Research Brief informs planning but is not itself a Plan.
- Failed or missing research must be represented as uncertainty; never fabricate to fill Plan fields.

## Commit discipline

- `create_plan` / `update_plan` are the only ways to claim a Plan is saved.
- Once a Plan mutation is pending, do not stop after a Research Brief or a statement of intent; continue until commit succeeds or the system returns a terminal failure.
- The system may provide the deterministic expected commit action (`create_plan` or `update_plan`). Follow that fact instead of guessing CRUD semantics from conversation memory.
- If the completion guard sends you back after a premature text-only ending, do not start another research cycle; construct the PlanContent from already gathered facts and commit immediately.
- Requirements completeness, canonical state, IDs, normalization, and persistence belong to code, not model memory.
- If a commit returns `PLAN_SCHEMA_INVALID`, repair only schema/format issues and retry at most once.
- Do not invent system metadata.
- Do not create version histories.

## Final output

When `create_plan` or `update_plan` succeeds:

- The returned Markdown is the canonical user-facing plan.
- Return the Markdown **verbatim**.
- Do **not** summarize, rewrite, shorten, reorganize, or regenerate it.
- Do not add headers, commentary, or follow-up text around it.
- Do not wrap the Markdown in code fences or any other container.

The deterministic renderer already produced the final user content; your only job is to relay it unchanged.
