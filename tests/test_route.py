"""路线工具的 geocoding 消歧逻辑单元测试（不调用真实高德 API）。

核心场景：泛称（“颐和园”“故宫”）高德会返回全国同名地点，默认取第一个可能
命中错误城市（如颐和园 → 山东枣庄），导致路线距离异常（如八达岭→颐和园 719 公里）。
通过候选城市交集选择真实城市，取回正确点位。
"""
import pytest

from tools.route import _pick_candidate


CANDIDATES_颐和园 = [
    {"location": "117.261376,34.816069", "city": "枣庄"},
    {"location": "113.992625,22.531559", "city": "深圳"},
    {"location": "116.275179,39.999617", "city": "北京"},
]

CANDIDATES_故宫 = [
    {"location": "116.397029,39.917839", "city": "北京"},
]

CANDIDATES_八达岭 = [
    {"location": "116.016802,40.356188", "city": "北京"},
]


def test_city_intersection_picks_beijing_for_yihe_yuan():
    """起点八达岭(北京) 与终点颐和园候选城市交集为北京，应选中北京海淀颐和园。"""
    # 模拟 get_route 里八达岭 → 颐和园：两端候选城市交集
    start_cities = {c["city"] for c in CANDIDATES_八达岭 if c["city"]}
    end_cities = {c["city"] for c in CANDIDATES_颐和园 if c["city"]}
    common = start_cities & end_cities
    prefer = next(iter(common))

    picked = _pick_candidate(CANDIDATES_颐和园, prefer)

    assert picked["location"] == "116.275179,39.999617"  # 北京海淀，非枣庄


def test_fallback_to_first_when_no_common_city():
    """两端候选无共同城市时退回各自第一个候选，保证不报错。"""
    assert _pick_candidate(CANDIDATES_颐和园, "")["city"] == "枣庄"
    assert _pick_candidate(CANDIDATES_故宫, "枣庄")["city"] == "北京"


def test_prefer_city_when_city_in_candidate():
    picked = _pick_candidate(CANDIDATES_颐和园, "北京")
    assert picked["city"] == "北京"
    assert picked["location"] == "116.275179,39.999617"


def test_empty_candidates_returns_none():
    assert _pick_candidate([], "北京") is None
