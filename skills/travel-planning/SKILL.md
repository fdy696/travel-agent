---
name: travel-planning
description: Create or modify the user's complete multi-day travel plan. Use for itinerary creation, replanning, extending/shortening, destination changes, activity changes, budget/pace/accommodation changes.
---

# Travel Planning

You own mutations to the user's current travel Plan. Use an adaptive agent loop: gather context, research when needed, commit only when ready.

## New plan / replan

1. Convert only the user's explicit or directly inferable requirements into an `update_requirements` patch.
2. For an explicit fresh/replan request, call `update_requirements(..., reset=true)`. For a follow-up answer to your previous missing-info question, use `reset=false`.
3. Inspect `missing_fields` returned by the tool.
4. If anything blocking is missing, ask only for those fields and stop. Do not research or submit a Plan yet.
5. Once complete, research external/changeable facts as needed with weather/search/maps.
6. Before constructing the final Plan, read `/skills/travel-planning/references/plan-schema.md`.
7. Produce a complete Rich Plan, not a short itinerary summary.
8. Call `create_plan`. If it says a current Plan already exists because this is a replan, call `update_plan` instead.
9. On success, return only the Markdown inside `<final_markdown>` markers.

## Modify existing plan

1. Call `get_current_plan` first. Repository state is canonical; chat history is not.
2. Understand the user's requested semantic change.
3. Preserve unrelated content and information density.
4. Research only when the modification depends on current/external facts. Simple semantic edits should not trigger research just because a keyword exists.
5. If the request changes trip-level requirements (days, destinations, travelers, dates, etc.), provide `requirements_patch` to `update_plan`.
6. Read `/skills/travel-planning/references/plan-schema.md` before building the final updated Plan if you have not already loaded it in this task.
7. `update_plan` receives the complete updated Plan, never a partial patch.
8. On success, return only the Markdown inside `<final_markdown>` markers.

## Research

- Current/changeable facts must come from tools, not memory.
- Current/near-3-day weather can use the weather tool; later seasonal climate should use web search.
- Use maps when route/distance/time materially affects the itinerary.
- You decide search order and number of calls based on the task.
- Failed or missing research must be represented as uncertainty; never fabricate to fill Plan fields.

## Commit discipline

- `create_plan` / `update_plan` are the only ways to claim a Plan is saved.
- If a commit returns `PLAN_SCHEMA_INVALID`, repair only schema/format issues and retry at most once.
- Do not invent system metadata.
- Do not create version histories.
- Do not summarize the deterministic Markdown returned by a successful commit.
