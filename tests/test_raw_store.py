from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from muscle50.domain.normalization import normalize_activity
from muscle50.infrastructure.garmin.client import GarminRawActivity
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository


def _raw(*, splits: dict[str, object] | None, original: bytes | None, warnings: tuple[str, ...]) -> GarminRawActivity:
    return GarminRawActivity(
        summary={"activityId": 777},
        activity={"activityId": 777},
        details={"activityId": 777, "details": []},
        splits=splits,
        exercise_sets=None,
        original_archive=original,
        warnings=warnings,
    )


def test_manifest_is_atomically_recreated_when_optional_fetch_results_change(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "muscle50"
    store = RawStore(
        data_root / "raw" / "garmin" / "activities",
        data_root,
        data_root / "tmp",
    )
    first = store.preserve(
        "777",
        _raw(
            splits={"lapDTOs": []},
            original=b"synthetic-original",
            warnings=("first warning",),
        ),
    )

    second = store.preserve(
        "777",
        _raw(splits=None, original=None, warnings=("retry warning",)),
    )

    manifest_path = data_root / "raw" / "garmin" / "activities" / "777" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    kinds = {item["kind"] for item in manifest["artifacts"]}
    assert {item.kind for item in first} == {item.kind for item in second}
    assert {"summary", "activity", "details", "splits", "original_archive"} == kinds
    assert manifest["warnings"] == ["retry warning"]

    # The first preserve represents a process stopping before its DB transaction.
    # The retry can register every first-capture artifact even though optional calls failed.
    repository = ActivityRepository(data_root / "db" / "muscle50.sqlite3")
    repository.migrate()
    retry_raw = _raw(splits=None, original=None, warnings=("retry warning",))
    normalized = normalize_activity(retry_raw.summary, retry_raw.activity)
    _, created = repository.save(normalized, second)
    assert created is True
    with sqlite3.connect(data_root / "db" / "muscle50.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_artifacts").fetchone()[0] == 5
