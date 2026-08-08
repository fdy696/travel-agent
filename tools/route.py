"""路线 / 交通工具（高德地图 Web API）。文档：https://lbs.amap.com/api/webservice/guide/api"""
import asyncio

import httpx

from config import require_key

AMAP_HOST = "https://restapi.amap.com"

# 高德 Web 服务 key 默认 QPS=3；并发打接口会收到 CUQPS_HAS_EXCEEDED_THE_LIMIT
# 并静默失败，因此所有请求串行发出并带上最小间隔。
GEOCODE_DELAY = 0.4


async def _geocode_candidates(
    address: str,
    client: httpx.AsyncClient,
) -> list[dict]:
    """地址 → 全部地理编码候选。每个候选 {"location": "lng,lat", "city": "..."}。

    泛称（如“颐和园”“故宫”）高德会返回全国同名地点，默认取第一个可能命中
    错误城市（如颐和园 → 山东枣庄）。返回全部候选，由调用方根据两端城市
    交集选择真实城市，避免被单个错误候选带偏。

    status != 1 时返回 []（QPS 超限、无候选等）。
    """
    key = require_key("AMAP_API_KEY")
    resp = await client.get(
        f"{AMAP_HOST}/v3/geocode/geo",
        params={"address": address, "key": key},
    )
    data = resp.json()
    if data.get("status") != "1" or not data.get("geocodes"):
        return []

    return [
        {
            "location": g["location"],
            "city": (g.get("city") or "").replace("市", ""),
        }
        for g in data["geocodes"]
    ]


def _pick_candidate(candidates: list[dict], prefer_city: str = "") -> dict | None:
    """从候选里选出城市与 prefer_city 一致的第一个；无提示或都不匹配时取第一个。"""
    if not candidates:
        return None
    if prefer_city:
        for c in candidates:
            if c["city"] and (c["city"] in prefer_city or prefer_city in c["city"]):
                return c
    return candidates[0]


async def get_route(
    origin: str,
    destination: str,
    mode: str = "driving",
) -> str:
    """查询两点间路线。

    Args:
        origin: 起点地址，如 "北京西站"
        destination: 终点地址，如 "北京首都国际机场"
        mode: driving（驾车，默认）/ transit（公交）
    """
    key = require_key("AMAP_API_KEY")

    async with httpx.AsyncClient(timeout=10) as client:
        # 串行 geocode 以规避高德 QPS 限制（并发会收到 CUQPS_HAS_EXCEEDED_THE_LIMIT）。
        start_candidates = await _geocode_candidates(origin, client)
        await asyncio.sleep(GEOCODE_DELAY)
        end_candidates = await _geocode_candidates(destination, client)
        if not start_candidates or not end_candidates:
            return "未能解析起点或终点的经纬度。"

        # 两端泛称可能各自命中不同城市的同名地点（颐和园→枣庄、故宫→北京）。
        # 路线两端几乎总在同一城市：取候选城市的交集，若无交集则退回各自第一个。
        start_cities = {c["city"] for c in start_candidates if c["city"]}
        end_cities = {c["city"] for c in end_candidates if c["city"]}
        common = start_cities & end_cities
        prefer = next(iter(common)) if common else ""

        start = _pick_candidate(start_candidates, prefer)
        end = _pick_candidate(end_candidates, prefer)

        if mode == "transit":
            resp = await client.get(
                f"{AMAP_HOST}/v3/direction/transit",
                params={
                    "origin": start["location"],
                    "destination": end["location"],
                    "city": (start["city"] or "北京") + "市",  # 公交接口要求“北京市”格式
                    "key": key,
                },
            )
            data = resp.json()
            if data.get("status") != "1":
                return f"公交路线查询失败：{data.get('info')}"
            transit = data["route"]["transits"][0]
            duration = int(transit["duration"]) / 60
            cost = transit.get("cost")
            walking = int(transit.get("walking_distance", 0)) / 1000

            legs = []
            for seg in transit.get("segments", []):
                for bus in seg.get("bus", []):
                    name = bus.get("name") or bus.get("busline", {}).get("name", "")
                    if name:
                        legs.append(f"乘坐 {name}")
                if seg.get("walking", {}).get("distance"):
                    legs.append("步行接驳")

            lines = [
                f"{origin} → {destination}（公交）",
                f"预计 {duration:.0f} 分钟，费用 {cost} 元，步行 {walking:.1f} 公里",
            ]
            lines.extend(f"- {s}" for s in legs[:8])
            return "\n".join(lines)

        # ── 驾车（默认）──
        resp = await client.get(
            f"{AMAP_HOST}/v3/direction/driving",
            params={
                "origin": start["location"],
                "destination": end["location"],
                "key": key,
            },
        )
        data = resp.json()
        if data.get("status") != "1":
            return f"驾车路线查询失败：{data.get('info')}"

        path = data["route"]["paths"][0]
        distance = int(path["distance"]) / 1000
        duration = int(path["duration"]) / 60
        steps = [s["instruction"] for s in path.get("steps", [])[:5]]

        lines = [
            f"{origin} → {destination}（驾车）",
            f"距离：{distance:.1f} 公里，预计 {duration:.0f} 分钟",
            "路线：",
        ]
        lines.extend(f"- {s}" for s in steps)
        return "\n".join(lines)
