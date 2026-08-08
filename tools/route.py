"""路线 / 交通工具（高德地图 Web API）。文档：https://lbs.amap.com/api/webservice/guide/api"""
import asyncio

import httpx

from config import require_key

AMAP_HOST = "https://restapi.amap.com"


async def _geocode(address: str, client: httpx.AsyncClient) -> dict | None:
    """地址 → 经纬度 + 城市。返回 {"location": "lng,lat", "city": "..."}"""
    key = require_key("AMAP_API_KEY")
    resp = await client.get(
        f"{AMAP_HOST}/v3/geocode/geo",
        params={"address": address, "key": key},
    )
    data = resp.json()
    if data.get("status") == "1" and data.get("geocodes"):
        g = data["geocodes"][0]
        return {"location": g["location"], "city": g.get("city") or ""}
    return None


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
        start, end = await asyncio.gather(
            _geocode(origin, client),
            _geocode(destination, client),
        )
        if not start or not end:
            return "未能解析起点或终点的经纬度。"

        if mode == "transit":
            resp = await client.get(
                f"{AMAP_HOST}/v3/direction/transit",
                params={
                    "origin": start["location"],
                    "destination": end["location"],
                    "city": start["city"] or "北京",  # 公交接口要求出发城市
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
