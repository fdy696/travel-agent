# Implementation Notes

## Current architecture

- Main Agent: user intent, necessary clarification, final route/plan decisions, final answer.
- `travel-planning` Skill: planning method + Markdown output contract.
- `travel-researcher`: dedicated multi-topic Research SubAgent with isolated tool context.
- Travel Tools: search / weather / maps.
- Runtime clock middleware: current date, weekday, time, timezone, year on every model call.
- CLI: concise trace in terminal; full raw stream events in `logs/`.

## Planning flow

```text
Main
→ necessary clarification
→ travel-planning Skill
→ travel-researcher
→ Research Findings
→ Markdown Contract
→ Main Final Synthesis
```

If route-defining conditions are still ambiguous, Main asks first and does not start Research.

## Search environments

`APP_ENV` is the only switch:

```text
development → DuckDuckGo only
test        → FakeSearch only
production  → Tavily → DuckDuckGo fallback
```

This guarantees local development does not consume Tavily quota even when `TAVILY_API_KEY`
exists in the machine environment.

Switch by restarting the process with a different value:

```bash
APP_ENV=development uv run python cli.py
APP_ENV=test uv run python cli.py
APP_ENV=production uv run python cli.py
```

or set the value in `.env`.

## Dependency / lockfile note

`ddgs>=9.14.4` was added to `pyproject.toml`.
Run `uv sync` after applying this patch; `uv` will refresh `uv.lock` locally.

## 2026-08 Model / Budget / FX integration

- Keep CLI as the only runtime interface for the current stage; no FastAPI layer yet.
- Model construction moved to `models/factory.py`; `LLM_PROVIDER` is independent from `APP_ENV`.
- `travel-researcher` keeps only Research tools. Budget and currency tools are Main-only deterministic capabilities.
- `calculate_budget` has no built-in travel prices. It only aggregates the final selected items and supports ranges / people / categories.
- `convert_currency` uses a current Frankfurter reference rate outside test mode; test mode is offline and deterministic.
- Main must not pre-decide JR Pass / other pass economics before Research comparison.

