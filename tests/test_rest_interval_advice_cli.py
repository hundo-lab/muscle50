"""`analytics snapshot` with Rest Interval Advice v1: text, JSON, independence from heart rate, read-only.

Every run uses a temporary MUSCLE50_HOME and synthetic values.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from strength_set_timing_builders import (
    Active,
    Rest,
    build_session,
    details_payload,
    heart_rate_samples,
    save_with_details,
    strength_activity,
)
from test_rest_interval_advice import (
    EXPECTED_BLOCK_LINES,
    EXPECTED_PAYLOAD,
    banned_hits,
    evidence_tag_failures,
    happy_rows,
    json_keys,
    json_strings,
)

from muscle50 import cli
from muscle50.application import strength_set_timing as set_timing_use_case
from muscle50.application.strength_set_timing import BuildSnapshotWithSetTiming
from muscle50.application.training_snapshot import BuildTrainingSnapshot
from muscle50.cli import main
from muscle50.domain.strength_set_timing import HeartRateLoad
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.analytics_reader import SqliteAnalyticsReader
from muscle50.presentation.terminal import render_training_snapshot, render_training_snapshot_json

AS_OF = "2026-03-14"
SRC = Path(__file__).resolve().parents[1] / "src" / "muscle50"
_PULL_UP: dict[str, Any] = {"category": "PULL_UP", "name": "WIDE_GRIP_PULL_UP"}


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("rest advice must not use Garmin")
    )
    monkeypatch.setattr(RawStore, "preserve", lambda *args, **kwargs: pytest.fail("rest advice must not write RAW"))
    monkeypatch.setattr(
        RawStore, "preserve_snapshot", lambda *args, **kwargs: pytest.fail("rest advice must not write RAW")
    )
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 3, 14))
    return root


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _store(home: Path, rows: list[Active | Rest], *, details: object | None = None) -> None:
    save_with_details(home, strength_activity("9101", build_session(rows)), details)


def _normal(**overrides: Any) -> Active:
    fields: dict[str, Any] = {"reps": 10, "seconds": 20.0}
    fields.update(overrides)
    return Active(**fields)


NO_SUSPECT_ROWS: list[Active | Rest] = [_normal(), Rest(50.0), _normal(), Rest(56.0), _normal()]


def _old_snapshot(home: Path) -> Any:
    reader = SqliteAnalyticsReader(home / "db" / "muscle50.sqlite3")
    return BuildTrainingSnapshot(reader).execute(date(2026, 3, 14), 28)


def _block_start(lines: list[str]) -> int:
    return lines.index(EXPECTED_BLOCK_LINES[0])


def _advice_block(text: str) -> list[str]:
    lines = text.splitlines()
    start = _block_start(lines)
    end = lines.index("", start)
    return lines[start:end]


# AC1, AC9: text position and content


def test_text_adds_the_block_after_the_set_timing_block(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store(home, happy_rows())

    code, out, err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28")

    assert (code, err) == (0, "")
    assert out.isascii()
    lines = out.splitlines()
    start = _block_start(lines)
    end = start + len(EXPECTED_BLOCK_LINES)
    assert lines[start:end] == EXPECTED_BLOCK_LINES
    assert lines[start - 1].startswith("  Rest between sets (same exercise; recorded, estimated where available)")
    assert lines[end : end + 2] == ["", "Swimming: 0 sessions"]
    timing = next(index for index, line in enumerate(lines) if line.startswith("  Set timing ["))
    # Removing the Set timing block and the advice block gives exactly the old text.
    assert "\n".join(lines[:timing] + lines[end:]) == render_training_snapshot(_old_snapshot(home))


def test_text_without_a_suspect_set_adds_only_the_block(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store(home, NO_SUSPECT_ROWS)

    code, out, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28")

    assert code == 0
    assert "Set timing" not in out
    lines = out.splitlines()
    start = _block_start(lines)
    block = _advice_block(out)
    assert block[1] == "    compound: median 53 s from 2 rests (band short <= 60 s) [REST-01; groups REST-07, design]"
    assert lines[start - 1].startswith("      ")  # the last taxonomy label line
    assert "\n".join(lines[:start] + lines[start + len(block) :]) == render_training_snapshot(_old_snapshot(home))


# AC9, AC10: JSON key position and exact payload


def test_json_appends_the_key_after_strength_set_timing(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store(home, happy_rows())
    old = json.loads(render_training_snapshot_json(_old_snapshot(home)))

    code, out, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28", "--json")

    assert code == 0
    payload = json.loads(out)
    assert list(payload) == [*old, "strength_set_timing", "rest_interval_advice"]
    assert out == json.dumps(payload, indent=2) + "\n"
    advice = payload.pop("rest_interval_advice")
    payload.pop("strength_set_timing")
    assert payload == old
    assert advice == EXPECTED_PAYLOAD
    assert json.dumps(advice, indent=2) == json.dumps(EXPECTED_PAYLOAD, indent=2)


def test_json_without_a_suspect_set_appends_the_key_after_quality_issues(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _store(home, NO_SUSPECT_ROWS)
    old = json.loads(render_training_snapshot_json(_old_snapshot(home)))

    code, out, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28", "--json")

    assert code == 0
    payload = json.loads(out)
    assert list(old)[-1] == "quality_issues"
    assert list(payload) == [*old, "rest_interval_advice"]
    assert out == json.dumps(payload, indent=2) + "\n"
    advice = payload.pop("rest_interval_advice")
    assert payload == old
    assert advice["groups"]["compound"] == {"median_seconds": 53.0, "rest_count": 2, "band": "short"}
    assert advice["options"] == [{"group": "compound", "code": "rest_longer_or_match_volume_load"}]


def test_no_triple_keeps_text_and_json_byte_identical(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store(home, [_normal(), Rest(40.0)])
    snapshot = _old_snapshot(home)

    _code, text, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28")
    _code, document, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28", "--json")

    assert text == render_training_snapshot(snapshot) + "\n"
    assert document == render_training_snapshot_json(snapshot) + "\n"
    assert "Rest advice" not in text
    assert "rest_interval_advice" not in document


# AC3: text and JSON agree


def test_text_and_json_counts_agree(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store(home, happy_rows())

    _code, text, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28")
    _code, document, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28", "--json")

    advice = json.loads(document)["rest_interval_advice"]
    block = _advice_block(text)
    excluded = next(line for line in block if line.startswith("    excluded: "))
    assert [int(value) for value in re.findall(r"\b(\d+)\b", excluded)] == list(advice["excluded"].values())
    for name, group in advice["groups"].items():
        line = next(line for line in block if line.startswith(f"    {name}: "))
        if group["median_seconds"] is None:
            assert line == f"    {name}: unavailable ({group['rest_count']})"
        else:
            assert f"median {group['median_seconds']:.0f} s from {group['rest_count']} rests" in line
    for exercise in advice["exercises"]:
        label = f"{exercise['exercise_category']}/{exercise['exercise_name'] or '-'} ({exercise['group']})"
        assert f"    {label}: median {exercise['median_seconds']:.0f} s from {exercise['rest_count']} rests" in block


# AC2: recorded rest only, independent of the heart-rate estimates


def _set_timing_session_rows() -> list[Active | Rest]:
    """The set-timing CLI session: PULL_UP sets, a 50 s REST before a late-pressed set, then an unchecked set."""
    rows: list[Active | Rest] = [Active(5, 1.699, **_PULL_UP)]
    for _ in range(4):
        rows.extend((Rest(40.0), Active(10, 20.0, **_PULL_UP)))
    rows.extend((Rest(50.0), Active(4, 1.629, hidden_s=20.0, **_PULL_UP), Rest(40.0), Active(None, 20.0, **_PULL_UP)))
    return rows


def test_payload_is_byte_equal_whatever_the_heart_rate(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    session = build_session(_set_timing_session_rows())
    variants = {
        "estimated": details_payload(heart_rate_samples(session)),
        "no details": None,
        "shifted clock": details_payload(heart_rate_samples(session, clock_shift_ms=600_000)),
    }
    documents: dict[str, dict[str, Any]] = {}
    for name, details in variants.items():
        root = tmp_path / name.replace(" ", "-")
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        save_with_details(root, strength_activity("9101", session), details)
        code, out, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28", "--json")
        assert code == 0
        documents[name] = json.loads(out)

    timings = [json.dumps(document["strength_set_timing"]) for document in documents.values()]
    advices = {json.dumps(document["rest_interval_advice"], indent=2) for document in documents.values()}
    # Sanity: the estimates really differ between the three homes.
    assert len(set(timings)) == 3
    assert [item["method"] for item in documents["estimated"]["strength_set_timing"]["suspect_sets"]] == [
        "none",
        "heart_rate",
    ]
    assert len(advices) == 1
    advice = documents["estimated"]["rest_interval_advice"]
    # The REST before the estimated suspect set counts as suspect_set, never as its 30 s estimate.
    assert advice["groups"]["unclassified"] == {"median_seconds": 40.0, "rest_count": 4, "band": "short"}
    assert advice["excluded"] == {"label_change_or_unknown": 0, "unchecked": 1, "suspect_set": 1, "missing_duration": 0}


# AC6, AC7, AC8: evidence tags, banned words, no verdict keys


def test_block_lines_carry_evidence_and_no_banned_word(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows: list[Active | Rest] = [
        _normal(category="SHOULDER_PRESS", name="DUMBBELL_SHOULDER_PRESS"),
        Rest(50.0),
        _normal(category="SHOULDER_PRESS", name="DUMBBELL_SHOULDER_PRESS"),
        *happy_rows(),
    ]
    _store(home, rows)

    _code, text, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28")
    _code, document, _err = _run(capsys, "analytics", "snapshot", "--date", AS_OF, "--days", "28", "--json")

    block = _advice_block(text)
    advice = json.loads(document)["rest_interval_advice"]
    assert "    SHOULDER_PRESS/DUMBBELL_SHOULDER_PRESS (compound): median 50 s from 1 rests" in block
    assert evidence_tag_failures(block) == []
    joined = "\n".join(block)
    assert set(re.findall(r"[A-Z]+-\d{2}", joined)) == {f"REST-0{number}" for number in (1, 2, 4, 5, 6, 7, 8)}
    assert "REST-09" not in text and "TEMPO-01" not in text
    assert {line: banned_hits(line) for line in block if banned_hits(line)} == {}
    strings = json_strings(advice)
    assert {item: banned_hits(item) for item in strings if banned_hits(item)} == {}
    assert advice["advice_only"] is True
    assert [key for key in json_keys(advice) if re.search(r"score|grade|warning|level|verdict", key)] == []


def test_only_the_snapshot_path_imports_the_advice_modules() -> None:
    pattern = re.compile(
        r"^\s*(from|import)\s+muscle50\.(domain\.rest_interval_advice|presentation\.rest_advice_terminal)"
    )
    importers = sorted(
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if any(pattern.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    )

    assert importers == [
        "application/strength_set_timing.py",
        "presentation/rest_advice_terminal.py",
        "presentation/terminal.py",
    ]


def test_recommend_does_not_use_the_advice(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _store(home, happy_rows())
    argvs = (("recommend", "--date", AS_OF), ("recommend", "--date", AS_OF, "--json"))
    before = [_run(capsys, *argv) for argv in argvs]
    monkeypatch.setattr(
        set_timing_use_case, "summarize_rest_intervals", lambda *args, **kwargs: pytest.fail("recommend used it")
    )

    after = [_run(capsys, *argv) for argv in argvs]

    assert after == before
    assert before[0][0] == 0
    assert "Rest advice" not in before[0][1]
    assert "rest_interval_advice" not in before[1][1]


# AC10, AC11: determinism, read-only, no heart-rate read


def test_output_is_deterministic(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store(home, happy_rows())

    for argv in (
        ("analytics", "snapshot", "--date", AS_OF, "--days", "28"),
        ("analytics", "snapshot", "--date", AS_OF, "--days", "28", "--json"),
    ):
        first = _run(capsys, *argv)
        second = _run(capsys, *argv)
        assert first == second
        assert first[1].isascii()


def _tree(root: Path) -> tuple[dict[str, tuple[str, int]], list[str]]:
    files = {
        path.relative_to(root).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        # A WAL reader may leave empty -wal/-shm files next to the database (accepted reader behaviour).
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }
    directories = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir())
    return files, directories


def test_snapshot_changes_nothing(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _store(home, happy_rows())
    before = _tree(home)

    for argv in (
        ("analytics", "snapshot", "--date", AS_OF, "--days", "28"),
        ("analytics", "snapshot", "--date", AS_OF, "--days", "28", "--json"),
    ):
        code, out, _err = _run(capsys, *argv)
        assert code == 0
        assert "Rest advice" in out or "rest_interval_advice" in out

    assert _tree(home) == before
    wal = home / "db" / "muscle50.sqlite3-wal"
    assert not wal.exists() or wal.stat().st_size == 0


class _SpyHeartRate:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def load(self, source_activity_id: str) -> HeartRateLoad:
        self.calls.append(source_activity_id)
        pytest.fail("no suspect set: the heart-rate series must not be read")


def test_no_heart_rate_read_without_a_suspect_set(home: Path) -> None:
    session = build_session(NO_SUSPECT_ROWS)
    save_with_details(home, strength_activity("9101", session), details_payload(heart_rate_samples(session)))
    spy = _SpyHeartRate()

    result = BuildSnapshotWithSetTiming(SqliteAnalyticsReader(home / "db" / "muscle50.sqlite3"), spy).execute(
        date(2026, 3, 14), 28
    )

    assert spy.calls == []
    assert result.set_timing is None
    assert result.rest_advice is not None
    assert result.rest_advice.compound.rest_count == 2
