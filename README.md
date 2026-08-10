# 行伴 Travel Agent v6

Main Agent + Travel Planning Skill + dedicated Travel Researcher + Travel Tools.

## Local development

```bash
cp .env.example .env
# fill DEEPSEEK / QWeather / AMAP keys
# APP_ENV defaults to development => DuckDuckGo search only
uv sync
uv run python cli.py
```

Search mode is controlled by `APP_ENV`:

- `development`: DuckDuckGo only; no Tavily request.
- `test`: deterministic FakeSearch; no network search.
- `production`: Tavily primary, DuckDuckGo fallback.

The CLI prints the active environment and search strategy at startup.
