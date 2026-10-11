"""`nutrition food fact add ... --new-unit`: the first fact in a unit a food has no fact for yet.

Everyday units (pack, count, animal) come from the catalog, never from a conversion: the new unit's
fact sits next to the existing units' facts, which stay unchanged. Without the flag every behaviour
and refusal text is the same as before. Temporary MUSCLE50_HOME, synthetic values only.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 8, 21, 0, tzinfo=KST)
DAY = "2026-10-08"
COMMON = ["--source", "nutrition_label", "--accuracy", "exact"]
CHICKEN = ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g"]
CHICKEN += ["--kcal", "110", "--protein", "23", "--carbs", "0", "--fat", "1.5", *COMMON]
PACK = ["--per", "1", "pack", "--kcal", "165", "--protein", "34.5", "--carbs", "0", "--fat", "unknown", *COMMON]


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FixedDateTime:
        return cls.fromisoformat(NOW.isoformat()) if tz is None else cls.fromisoformat(NOW.astimezone(tz).isoformat())


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("nutrition must not use Garmin")
    )

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 8))
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "datetime", _FixedDateTime)
    return root


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return out


def _facts(home: Path) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(home / "db" / "muscle50.sqlite3")
    try:
        return sorted(connection.execute("SELECT * FROM nutrition_facts").fetchall(), key=repr)
    finally:
        connection.close()


def test_new_unit_adds_the_first_fact_next_to_the_existing_unit(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    out = _ok(capsys, "nutrition", "food", "fact", "add", "chicken-breast", *PACK, "--new-unit")
    assert out.split("\n")[:8] == [
        "Added fact food:chicken-breast:2 to chicken-breast as its first fact per pack; facts per other units are "
        "unchanged.",
        "Food chicken-breast: 닭가슴살",
        "  fact food:chicken-breast:1 (active)",
        "    per 100 g: kcal 110 | P 23 g | C 0 g | F 1.5 g  [nutrition_label/exact]",
        "    reference: entered with muscle50 nutrition food add",
        f"    recorded: {NOW.isoformat()}",
        "  fact food:chicken-breast:2 (active)",
        "    per 1 pack: kcal 165 | P 34.5 g | C 0 g | F unknown  [nutrition_label/exact]",
    ]
    rows = {row[0]: row for row in _facts(home)}
    assert rows["food:chicken-breast:2"][-1] is None  # supersedes nothing
    pack = json.loads(
        _ok(
            capsys,
            "nutrition",
            "log",
            "--date",
            DAY,
            "--meal",
            "lunch",
            "--item",
            "chicken-breast",
            "2",
            "pack",
            "--json",
        )
    )
    assert pack["items"][0]["nutrients"]["calories_kcal"]["value"] == "330"
    assert pack["items"][0]["nutrients"]["calories_kcal"]["fact_id"] == "2026-10-08-lunch-1:1:food:chicken-breast:2"
    grams = json.loads(
        _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "dinner", "--item", "닭가슴살", "200", "g", "--json")
    )
    assert grams["items"][0]["nutrients"]["calories_kcal"]["value"] == "220"
    assert grams["items"][0]["nutrients"]["calories_kcal"]["fact_id"] == "2026-10-08-dinner-1:1:food:chicken-breast:1"


def test_json_is_the_unchanged_food_document(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    printed = _ok(capsys, "nutrition", "food", "fact", "add", "chicken-breast", *PACK, "--new-unit", "--json")
    assert printed == _ok(capsys, "nutrition", "food", "show", "chicken-breast", "--json")
    assert [fact["active"] for fact in json.loads(printed)["facts"]] == [True, True]


def test_new_unit_for_an_existing_unit_is_refused(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    before = _facts(home)
    grams = ["--per", "100", "g", "--kcal", "120", "--protein", "24", "--carbs", "0", "--fat", "1", *COMMON]
    code, out, err = _run(capsys, "nutrition", "food", "fact", "add", "chicken-breast", *grams, "--new-unit")
    assert (code, out) == (1, "")
    assert err == (
        "오류: food 'chicken-breast' already has nutrition per g; run without --new-unit to add a new version. "
        "Nothing was changed.\n"
    )
    assert _facts(home) == before


def test_without_the_flag_a_new_unit_keeps_the_old_refusal(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    before = _facts(home)
    code, out, err = _run(capsys, "nutrition", "food", "fact", "add", "chicken-breast", *PACK)
    assert (code, out) == (1, "")
    assert err == (
        "오류: food 'chicken-breast' has nutrition per g, not per pack; a new fact version must use the same unit as "
        "the fact it replaces. Nothing was changed.\n"
    )
    assert _facts(home) == before


@pytest.mark.parametrize(
    ("food_id", "message"),
    [
        ("missing", "no food with id 'missing'; add it first with `muscle50 nutrition food add`. Nothing was changed."),
        (
            "general-meal",
            "'general-meal' is the general meal (일반식), not a catalog food: it has no nutrition facts and none can "
            "be added. Nothing was changed.",
        ),
    ],
)
def test_new_unit_refuses_unknown_and_general_foods(
    capsys: pytest.CaptureFixture[str], food_id: str, message: str
) -> None:
    code, out, err = _run(capsys, "nutrition", "food", "fact", "add", food_id, *PACK, "--new-unit")
    assert (code, out, err) == (1, "", f"오류: {message}\n")


def test_new_unit_then_a_normal_version_supersedes_only_that_unit(
    capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    _ok(capsys, "nutrition", "food", "fact", "add", "chicken-breast", *PACK, "--new-unit")
    newer = ["--per", "1", "pack", "--kcal", "170", "--protein", "35", "--carbs", "0", "--fat", "1", *COMMON]
    out = _ok(capsys, "nutrition", "food", "fact", "add", "chicken-breast", *newer)
    assert out.startswith(
        "Added fact food:chicken-breast:3 to chicken-breast; it replaces food:chicken-breast:2 for meals logged from "
        "now on.\n"
    )
    shown = _ok(capsys, "nutrition", "food", "show", "chicken-breast")
    assert "  fact food:chicken-breast:1 (active)" in shown
    assert "  fact food:chicken-breast:2 (superseded)" in shown
