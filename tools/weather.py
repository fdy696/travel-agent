"""天气工具（QWeather）。"""
from __future__ import annotations

import httpx

from config import require_key


def _api_host() -> str:
    host = require_key("QWEATHER_API_HOST").strip().rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        return host
    return f"https://{host}"


def _headers() -> dict[str, str]:
    return {"X-QW-Api-Key": require_key("QWEATHER_API_KEY")}


async def _geo_lookup(city: str, client: httpx.AsyncClient) -> str | None:
    """城市名 -> QWeather LocationID。"""
    resp = await client.get(
        f"{_api_host()}/geo/v2/city/lookup",
        params={"location": city},
        headers=_headers(),
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") == "200" and data.get("location"):
        return data["location"][0]["id"]
    return None


async def get_weather(city: str, forecast: bool = False) -> str:
    """获取城市当前天气；forecast=True 时附加未来 3 天预报。"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            loc_id = await _geo_lookup(city, client)
            if not loc_id:
                return f"未能解析城市：{city}"

            now_resp = await client.get(
                f"{_api_host()}/v7/weather/now",
                params={"location": loc_id},
                headers=_headers(),
            )
            now_resp.raise_for_status()
            now_data = now_resp.json()
            if now_data.get("code") != "200":
                return f"查询天气失败：{now_data.get('code')}"

            now = now_data.get("now", {})
            lines = [
                f"{city} 当前天气：{now.get('text', '未知')}，"
                f"{now.get('temp', '?')}℃（体感 {now.get('feelsLike', '?')}℃），"
                f"湿度 {now.get('humidity', '?')}%，风向 {now.get('windDir', '?')}。"
            ]

            if forecast:
                fc_resp = await client.get(
                    f"{_api_host()}/v7/weather/3d",
                    params={"location": loc_id},
                    headers=_headers(),
                )
                fc_resp.raise_for_status()
                fc_data = fc_resp.json()
                if fc_data.get("code") == "200":
                    lines.append("\n未来 3 天预报：")
                    for day in fc_data.get("daily", []):
                        lines.append(
                            f"- {day.get('fxDate')}: {day.get('textDay')}，"
                            f"{day.get('tempMin')}~{day.get('tempMax')}℃"
                        )
            return "\n".join(lines)
    except httpx.HTTPError as exc:
        return f"天气服务请求失败：{type(exc).__name__}"
