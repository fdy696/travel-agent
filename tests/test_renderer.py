"""Rich PlanDraft 的确定性 Markdown 渲染测试。"""
from datetime import date

from planning.models import (
    Accommodation,
    AccommodationRecommendation,
    Activity,
    AttractionGuide,
    BudgetBreakdown,
    DayPlan,
    FoodRecommendation,
    PlanDraft,
    Poi,
    TransportationGuide,
    TravelRequirements,
    Transportation,
    WeatherReference,
)
from planning.renderer import render_plan_markdown


def _rich_plan() -> PlanDraft:
    req = TravelRequirements(
        destinations=["南京"],
        start_date=date(2026, 6, 1),
        end_date=date(2026, 7, 31),
        duration_days=3,
        traveler_count=2,
        budget_per_person_cny=2000,
        notes="自然Citywalk、走街串巷、网红打卡、吃美食拍美照",
        accommodation_preference="靠近老门东/夫子庙，方便逛吃夜景",
    )
    return PlanDraft(
        title="南京暑期逛吃攻略",
        subtitle="2026年6-7月 · 情侣二人",
        requirements=req,
        overview="以老门东和夫子庙为核心的一条松弛 Citywalk 线。",
        weather_summary="夏季闷热，早晚略凉。",
        weather_details=[
            WeatherReference(month="6月", summary="降雨天数预计在3-14天，最高温34-36℃。"),
            WeatherReference(month="7月", summary="上旬最高温35-37℃，午后多阵雨。"),
        ],
        weather_tip="实际天气请以临近官方预警为准，请携带防晒用品、雨具并及时补水。",
        schedule=[
            DayPlan(
                day=1,
                day_id="d1",
                city="南京",
                title="老门东夫子庙 Citywalk",
                summary="下午到晚上逛老门东与夫子庙。",
                activities=[
                    Activity(
                        activity_id="d1_a1",
                        period="下午",
                        start_time="14:30",
                        end_time="17:00",
                        title="老门东深度 Citywalk",
                        location="老门东",
                        description="沿历史街区逛吃。",
                        route=["武定门 → 老门东牌坊 → 箍桶巷"],
                        highlights=["金陵墙", "芥子园", "先锋书店"],
                        photo_spots=["傍晚老门东牌坊"],
                        booking_notes=["无需预约"],
                        alternatives=["雨天改为室内逛先锋书店"],
                        pois=[Poi(name="老门东历史街区", address="秦淮区剪子巷54号")],
                        transportation="地铁 3 号线武定门站步行",
                        estimated_cost="约90元",
                        tips=["傍晚光线适合拍照"],
                    )
                ],
                transportation=[
                    Transportation(
                        trans_id="d1_t1",
                        from_location="夫子庙",
                        to_location="老门东",
                        mode="步行",
                        estimated_duration_minutes=15,
                        estimated_cost="免费",
                    )
                ],
                accommodation=Accommodation(
                    acc_id="d1_acc",
                    area="夫子庙附近",
                    type="舒适型酒店",
                    name="某酒店",
                    estimated_cost="约400元/晚",
                ),
                day_tips=["雨天建议带伞"],
            )
        ],
        food_recommendations=[
            FoodRecommendation(
                name="蒋有记",
                category="老门东必吃小吃",
                area="老门东",
                address="箍桶巷内",
                recommended_dishes=["牛肉锅贴", "牛肉馄饨"],
                price_reference="牛肉锅贴约12元/份",
                description="百年清真老字号，锅贴外皮酥脆爆汁。",
                best_time="下午茶时段",
            )
        ],
        food_route=["早餐:科巷/红庙 → 锅贴配鸭血汤", "晚间:南京大牌档 → 美龄粥、盐水鸭"],
        attraction_guides=[
            AttractionGuide(
                name="夫子庙",
                introduction="秦淮河北岸的重要历史文化地标。",
                history="始建于宋，是江南贡院所在地。",
                highlights=["大成殿", "江南贡院", "乌衣巷"],
                recommended_duration="约2小时",
                ticket_info="免费",
                opening_hours="08:30-22:00",
                booking_info="旺季建议提前预约",
                photo_spots=["文德桥适合拍秦淮河夜景"],
                best_visit_time="日落后蓝调时刻",
            )
        ],
        accommodation_recommendations=[
            AccommodationRecommendation(
                name="某民宿",
                area="夫子庙附近",
                address="平江府路",
                type="民宿",
                price_reference="约300元/晚",
                description="闹中取静，步行可达秦淮河。",
            )
        ],
        transportation_guide=[
            TransportationGuide(
                from_location="北京",
                to_location="南京",
                mode="高铁",
                duration="约4小时",
                price="约500元/人",
                departure_station="北京南站",
                arrival_station="南京南站",
                suggestion="提前订票",
            )
        ],
        budget_breakdown=[
            BudgetBreakdown(item="住宿", per_person="约800元"),
            BudgetBreakdown(item="餐饮", per_person="约600元"),
            BudgetBreakdown(item="景点", per_person="约200元"),
            BudgetBreakdown(item="市内交通", per_person="约100元"),
            BudgetBreakdown(item="城际交通", per_person="约1000元"),
        ],
        budget_total="两人约5400元（不含大交通）",
        booking_tips=["热门景点旺季需提前预约"],
        transportation_tips=["市内地铁可达大部分景点"],
        clothing_tips=["夏季注意防晒防暑"],
        photo_tips=["清晨人少适合拍建筑"],
        budget_tips=["美食人均约100元/餐"],
        warnings=["谨防景区周边低价一日游套路"],
        assumptions=["价格为估算，以当天为准"],
    )


def test_render_plan_covers_all_rich_fields():
    md = render_plan_markdown(_rich_plan())
    sections = [
        "南京暑期逛吃攻略",
        "2026年6-7月 · 情侣二人",
        "## 📋 出行基础信息",
        "出行时间",
        "出行人数：2 人",
        "预算：人均 2000 元",
        "目的地：南京",
        "出行偏好：自然Citywalk、走街串巷、网红打卡、吃美食拍美照",
        "住宿倾向：靠近老门东/夫子庙，方便逛吃夜景",
        "## 🌤️ 天气参考",
        "**6月** 降雨天数预计在3-14天，最高温34-36℃。",
        "**7月** 上旬最高温35-37℃，午后多阵雨。",
        "实际天气请以临近官方预警为准",
        "## 📋 行程规划与路线安排",
        "## 🗓️ 每日行程",
        "### Day 1: · 老门东夫子庙 Citywalk",
        "#### 14:30-17:00 [下午] 老门东深度 Citywalk",
        "**推荐路线**",
        "**怎么玩 / 看什么**",
        "**涉及地点**",
        "- 老门东历史街区（秦淮区剪子巷54号）",
        "**交通** 地铁 3 号线武定门站步行",
        "**费用** 约90元",
        "**📸 推荐打卡**",
        "**🎫 预约/购票**",
        "**备选方案**",
        "**💡 小贴士**",
        "🚄 交通：夫子庙 → 老门东，步行，约 15 分钟（免费）",
        "#### 🏨 今日住宿",
        "- 推荐区域：夫子庙附近",
        "## 🍜 特色美食探店推荐",
        "#### 老门东必吃小吃",
        "**蒋有记**",
        "🍴 推荐：牛肉锅贴、牛肉馄饨",
        "💰 参考价格：牛肉锅贴约12元/份",
        "#### 美食逛吃路线参考",
        "- 早餐:科巷/红庙 → 锅贴配鸭血汤",
        "## 🚄 城际交通",
        "### 北京 → 南京",
        "- 方式：高铁",
        "- 用时：约4小时",
        "- 价格：约500元/人",
        "- 出发站：北京南站",
        "- 到达站：南京南站",
        "- 建议：提前订票",
        "## 🏛️ 核心景点攻略",
        "### 夫子庙",
        "**看什么 / 核心看点**",
        "**📸 拍照位置**",
        "## 🏨 住宿建议",
        "### 夫子庙附近",
        "- 某民宿 · 民宿 · 约300元/晚",
        "📍 平江府路",
        "## 💰 预算参考",
        "| 住宿 | 约800元 |",
        "| 城际交通 | 约1000元 |",
        "预计总计：两人约5400元（不含大交通）",
        "## 🎒 出行准备",
        "#### 🎫 预约",
        "#### 🚌 交通",
        "#### 👕 穿搭",
        "#### 📷 拍照",
        "#### ⚠️ 避坑",
        "## 📝 假设 / 说明",
    ]
    for section in sections:
        assert section in md, f"缺少段落: {section}"

    # 整个 Plan 只应有一个 H1（计划标题），其余章节都是 H2
    h1_lines = [l for l in md.splitlines() if l.startswith("# ")]
    assert len(h1_lines) == 1, f"应只有 1 个 H1，实际 {len(h1_lines)} 个: {h1_lines}"
