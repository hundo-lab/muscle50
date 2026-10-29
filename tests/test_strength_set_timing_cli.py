"""`analytics snapshot` with strength set timing: text, JSON, determinism, unchanged neighbours, read-only.

Every run uses a temporary MUSCLE50_HOME and synthetic values.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from strength_set_timing_builders import (
    Active,
    Rest,
    Session,
    build_session,
    details_payload,
    heart_rate_samples,
    save_with_details,
    strength_activity,
)

from muscle50 import cli
from muscle50.application.training_snapshot import BuildTrainingSnapshot
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.analytics_reader import SqliteAnalyticsReader
from muscle50.presentation.terminal import render_training_snapshot, render_training_snapshot_json

AS_OF = "2026-03-14"
_PULL_UP = {"category": "PULL_UP", "name": "WIDE_GRIP_PULL_UP"}

EXPECTED_SET_TIMING_LINES = [
    "  Set timing [design; display only, used by no rule]: 7 ACTIVE sets, 6 checked, 2 too short for their reps "
    "(< 1.0 s/rep); 1 estimated from heart rate, 1 not estimated",
    "    2026-03-12 9101 seq 1 PULL_UP/WIDE_GRIP_PULL_UP #1: 5 reps in 1.7 s -> not estimated (no_preceding_rest)",
    "    2026-03-12 9101 seq 11 PULL_UP/WIDE_GRIP_PULL_UP #6: 4 reps in 1.6 s after REST 50.0 s -> estimated work "
    "20 s (20-20) / rest 30 s (30-30) (heart_rate, low; wrist lag 8 s from 4 sets [HR-04])",
    "  Rest between sets (same exercise; recorded, estimated where available) [design]: median 40 s from 5 rests "
    "(1 estimated), compound unavailable (0), isolation unavailable (0), unclassified 40 s (5); excluded: not "
    "estimated 0, missing duration 0, label change or UNKNOWN 0, unchecked 1",
]


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("set timing must not use Garmin")
    )
    monkeypatch.setattr(RawStore, "preserve", lambda *args, **kwargs: pytest.fail("set timing must not write RAW"))
    monkeypatch.setattr(
        RawStore, "preserve_snapshot", lambda *args, **kwargs: pytest.fail("set timing must not write RAW")
    )
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 3, 14))
    return root


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _session() -> Session:
    rows: list[Active | Rest] = [Active(5, 1.699, **_PULL_UP)]  # type: ignore[arg-type]
    for _ in range(4):
        rows.extend((Rest(40.0), Active(10, 20.0, **_PULL_UP)))  # type: ignore[arg-type]
    rows.extend(
        (
            Rest(50.0),
            Active(4, 1.629, hidden_s=20.0, **_PULL_UP),  # type: ignore[arg-type]
            Rest(40.0),
            Active(None, 20.0, **_PULL_UP),  # type: ignore[arg-type]
        )
    )
    return build_session(rows)


def _store_suspect(home: Path, *, details: bool = True) -> Session:
    session = _session()
    payload = details_payload(heart_rate_samples(session)) if details else None
    save_with_details(home, strength_activity("9101", session), payload)
    return session


def _store_normal(home: Path) -> None:
    session = build_session([Active(10, 20.0), Rest(40.0), Active(10, 20.0), Rest(40.0), Active(20, 60.0)])
    save_with_details(home, strength_activity("9101", session), details_payload(heart_rate_samples(session)))


def _old_snapshot(home: Path) -> Any:
    return BuildTrainingSnapshot(SqliteAnalyticsReader(home / "db" / "muscle50.sqlite3")).execute(date(2026, 3, 14))


def test_text_adds_the_set_timing_block_at_the_end_of_the_strength_section(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _store_suspect(home)

    code, out, err = _run(capsys, "analytics", "snapshot", "--date", AS_OF)

    assert (code, err) == (0, "")
    lines = out.splitlines()
    start = lines.index(EXPECTED_SET_TIMING_LINES[0])
    assert lines[start : start + 4] == EXPECTED_SET_TIMING_LINES
    assert lines[start - 1].startswith("      ")  # the last taxonomy label line
    assert lines[start + 4 : start + 6] == ["", "Swimming: 0 sessions"]
    assert out.isascii()
    # Removing the block gives exactly the old text.
    assert "\n".join(lines[:start] + lines[start + 4 :]) + "\n" == render_training_snapshot(_old_snapshot(home)) + "\n"


def test_json_appends_one_trailing_key(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store_suspect(home)
    old = json.loads(render_training_snapshot_json(_old_snapshot(home)))

    code, out, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--json")

    assert code == 0
    payload = json.loads(out)
    assert list(payload) == [*old, "strength_set_timing"]
    timing = payload.pop("strength_set_timing")
    assert payload == old
    assert out == json.dumps({**payload, "strength_set_timing": timing}, indent=2) + "\n"
    assert list(timing) == [
        "set_timing_version",
        "display_only",
        "rules",
        "evidence",
        "active_set_count",
        "checked_set_count",
        "unchecked_set_count",
        "suspect_set_count",
        "estimated_set_count",
        "not_estimated_set_count",
        "sessions",
        "suspect_sets",
        "rest_between_sets",
    ]
    assert timing["display_only"] is True
    assert timing["sessions"] == [
        {
            "source_activity_id": "9101",
            "local_date": "2026-03-12",
            "suspect_set_sequences": [1, 11],
            "heart_rate": {
                "status": "available",
                "artifact_relative_path": "raw/garmin/activities/9101/details.json",
                "sample_count": 483,
            },
            "lag": {
                "status": "calibrated",
                "median_seconds": 8.0,
                "min_seconds": 8.0,
                "max_seconds": 8.0,
                "calibration_set_sequences": [3, 5, 7, 9],
            },
        }
    ]
    estimated = timing["suspect_sets"][1]
    assert estimated == {
        "source_activity_id": "9101",
        "local_date": "2026-03-12",
        "sequence": 11,
        "exercise_category": "PULL_UP",
        "exercise_name": "WIDE_GRIP_PULL_UP",
        "label_set_number": 6,
        "reps": 4,
        "recorded_seconds": 1.629,
        "preceding_rest_sequence": 10,
        "recorded_rest_seconds": 50.0,
        "method": "heart_rate",
        "not_estimated_reason": None,
        "heart_rate_onset_at_utc": "2026-03-12T01:04:40.000+00:00",
        "estimated_start_at_utc": "2026-03-12T01:04:32.000+00:00",
        "estimated_work_seconds": 20.0,
        "estimated_work_range_seconds": [20.0, 20.0],
        "estimated_rest_seconds": 30.0,
        "estimated_rest_range_seconds": [30.0, 30.0],
        "confidence": "low",
    }
    not_estimated = timing["suspect_sets"][0]
    assert (not_estimated["method"], not_estimated["not_estimated_reason"]) == ("none", "no_preceding_rest")
    assert all(not_estimated[key] is None for key in not_estimated if key.startswith("estimated_"))
    assert not_estimated["heart_rate_onset_at_utc"] is None and not_estimated["confidence"] is None
    assert timing["rest_between_sets"]["unclassified"] == {
        "median_seconds": 40.0,
        "rest_count": 5,
        "estimated_rest_count": 1,
    }
    assert timing["rest_between_sets"]["compound"] == {
        "median_seconds": None,
        "rest_count": 0,
        "estimated_rest_count": 0,
    }


def test_output_is_deterministic(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store_suspect(home)

    for argv in (("analytics", "snapshot", "--date", AS_OF), ("analytics", "snapshot", "--date", AS_OF, "--json")):
        first = _run(capsys, *argv)
        second = _run(capsys, *argv)
        assert first == second


def test_no_heart_rate_value_is_printed(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    session = _store_suspect(home)
    bpm_texts = {repr(sample.bpm) for sample in heart_rate_samples(session)}

    _code, text, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF)
    _code, document, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--json")

    assert "91.25" in bpm_texts
    for value in bpm_texts:
        assert value not in text
        assert value not in document


def test_missing_details_still_exits_zero_with_a_reason(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store_suspect(home, details=False)

    code, out, err = _run(capsys, "analytics", "snapshot", "--date", AS_OF)

    assert (code, err) == (0, "")
    assert "    2026-03-12 9101 seq 11 PULL_UP/WIDE_GRIP_PULL_UP #6: 4 reps in 1.6 s after REST 50.0 s -> " in out
    assert "-> not estimated (heart_rate_raw_missing)" in out
    _code, document, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--json")
    session = json.loads(document)["strength_set_timing"]["sessions"][0]
    assert session["heart_rate"] == {"status": "raw_missing", "artifact_relative_path": None, "sample_count": 0}
    assert session["lag"] is None


def test_no_suspect_set_keeps_text_and_json_byte_identical(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store_normal(home)
    snapshot = _old_snapshot(home)

    _code, text, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF)
    _code, document, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--json")

    assert text == render_training_snapshot(snapshot) + "\n"
    assert document == render_training_snapshot_json(snapshot) + "\n"
    assert "Set timing" not in text
    assert "strength_set_timing" not in document


def _recommend_outputs(capsys: pytest.CaptureFixture[str]) -> tuple[tuple[int, str, str], tuple[int, str, str]]:
    return (
        _run(capsys, "recommend", "--date", AS_OF),
        _run(capsys, "recommend", "--date", AS_OF, "--json"),
    )


def test_recommend_is_identical_with_and_without_details(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _store_suspect(home)
    with_details = _recommend_outputs(capsys)
    other = tmp_path / "other-home"
    monkeypatch.setenv("MUSCLE50_HOME", str(other))
    _store_suspect(other, details=False)

    without_details = _recommend_outputs(capsys)

    assert with_details == without_details
    assert with_details[0][0] == 0
    assert "Set timing" not in with_details[0][1]
    assert "strength_set_timing" not in with_details[1][1]


def _tree(root: Path) -> tuple[dict[str, tuple[str, int]], list[str]]:
    files = {
        path.relative_to(root).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        # A WAL reader may leave empty -wal/-shm files next to the database (accepted reader behaviour).
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }
    directories = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir())
    return files, directories


def test_snapshot_reads_raw_only_and_changes_nothing(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store_suspect(home)
    before = _tree(home)

    for argv in (("analytics", "snapshot", "--date", AS_OF), ("analytics", "snapshot", "--date", AS_OF, "--json")):
        code, out, _err = _run(capsys, *argv)
        assert code == 0
        assert "heart_rate" in out

    assert _tree(home) == before
    wal = home / "db" / "muscle50.sqlite3-wal"
    assert not wal.exists() or wal.stat().st_size == 0
