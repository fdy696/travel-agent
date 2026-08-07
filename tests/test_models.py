from datetime import date

from planning.models import (
    RequirementsPatch,
    TravelRequirements,
    merge_requirements,
    missing_required_fields,
)


def test_merge_requirements_computes_duration_and_default_pace():
    current = TravelRequirements(destinations=["云南"])
    patch = RequirementsPatch(
        traveler_count=2,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
    )
    merged = merge_requirements(current, patch)
    assert merged.duration_days == 5
    assert merged.traveler_count == 2
    assert merged.pace == "moderate"
    assert missing_required_fields(merged) == []


def test_missing_fields():
    req = TravelRequirements()
    assert missing_required_fields(req) == [
        "destinations",
        "traveler_count",
        "duration_or_dates",
    ]
