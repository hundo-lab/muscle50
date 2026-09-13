from __future__ import annotations

import pytest

from muscle50.domain.activity import ActivityType
from muscle50.domain.normalization import NormalizationError, activity_id_from, canonical_type


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("trail_running", ActivityType.RUNNING),
        ("open_water_swimming", ActivityType.SWIMMING),
        ("strength_training", ActivityType.STRENGTH),
        ("cardio_training", ActivityType.OTHER),
        ("future_garmin_type", ActivityType.OTHER),
    ],
)
def test_activity_type_mapping(source: str, expected: ActivityType) -> None:
    assert canonical_type(source) is expected


@pytest.mark.parametrize("value", [None, True, 0, -1, "bad"])
def test_invalid_activity_id_is_rejected(value: object) -> None:
    with pytest.raises(NormalizationError):
        activity_id_from({"activityId": value})
