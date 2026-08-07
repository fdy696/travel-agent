"""天气工具（和风天气 QWeather）。文档：https://dev.qweather.com"""
import httpx

from config import require_key

QWEATHER_DEV_HOST = "https://devapi.qweather.com"  # 天气数据
QWEATHER_GEO_HOST = "https://geoapi.qweather.com"  # 地理编码（城市搜索）


async def _geo_lookup(city: str, client: httpx.AsyncClient) -> str | None:
    """城市名 → 和风 LocationID。注意：地理编码用的是 geoapi 主机。"""
    key = require_key("QWEATHER_API_KEY")
    resp = await client.get(
        f"{QWEATHER_GEO_HOST}/v2/city/lookup",
        params={"location": city, "key": key},
    )
    data = resp.json()
    if data.get("code") == "200" and data.get("location"):
        return data["location"][0]["id"]
    return None


async def get_weather(city: str, forecast: bool = False) -> str:
    """获取城市当前天气；forecast=True 时附加未来 3 天预报。

    Args:
        city: 城市名，如 "北京"、"上海"
        forecast: 是否返回未来 3 天预报（规划行程时很有用）
    """
    key = require_key("QWEATHER_API_KEY")

    async with httpx.AsyncClient(timeout=10) as client:
        loc_id = await _geo_lookup(city, client)
        if not loc_id:
            return f"未能解析城市：{city}"

        # ── 当前天气 ──
        now_resp = await client.get(
            f"{QWEATHER_DEV_HOST}/v7/weather/now",
            params={"location": loc_id, "key": key},
        )
        now_data = now_resp.json()
        if now_data.get("code") != "200":
            return f"查询天气失败：{now_data.get('code')}"

        now = now_data.get("now", {})
        lines = [
            f"{city} 当前天气：{now.get('text', '未知')}，"
            f"{now.get('temp', '?')}℃（体感 {now.get('feelsLike', '?')}℃），"
            f"湿度 {now.get('humidity', '?')}%，风向 {now.get('windDir', '?')}。"
        ]

        # ── 未来 3 天预报 ──
        if forecast:
            fc_resp = await client.get(
                f"{QWEATHER_DEV_HOST}/v7/weather/3d",
                params={"location": loc_id, "key": key},
            )
            fc_data = fc_resp.json()
            if fc_data.get("code") == "200":
                lines.append("\n未来 3 天预报：")
                for d in fc_data.get("daily", []):
                    lines.append(
                        f"- {d.get('fxDate')}: {d.get('textDay')}，"
                        f"{d.get('tempMin')}~{d.get('tempMax')}℃"
                    )
        return "\n".join(lines)
