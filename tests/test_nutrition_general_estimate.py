"""Telegram LLM v2 (A2): `--general --general-estimate SPEC [--general-estimate-ref TEXT]`.

An estimated general meal is a general item plus one item-owned fact with ranges only (basis 1 serving,
every value unknown, an estimate source, `estimated`). Its nutrients stay unknown, so every total it is
part of stays incomplete and no target judgement or action comes from it; the ranges show up as
`estimated` ranges. Temporary MUSCLE50_HOME, synthetic values only.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.application.nutrition_logging import (
    GeneralMealEstimate,
    NutritionLoggingError,
    format_general_estimate,
    general_meal_item,
    parse_general_estimate,
)
from muscle50.cli import main
from muscle50.domain.nutrition import (
    GENERAL_MEAL_FOOD_ID,
    GENERAL_MEAL_NAME,
    Accuracy,
    MealItem,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionRange,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector

KST = timezone(timedelta(hours=9))
DAY = "2026-10-08"
NOW = datetime(2026, 10, 8, 21, 0, tzinfo=KST)
DINNER = "2026-10-08-dinner-1"
LUNCH = "2026-10-08-lunch-1"
SPEC = "visual_estimate:kcal=700-950,protein=30-45"
REF = "telegram-llm photo sha256:0123456789ab (claude sonnet)"
CHICKEN = (
    ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g"]
    + ["--kcal", "110", "--protein", "23", "--carbs", "0", "--fat", "1.5"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
ESTIMATED = ("--general", "--general-note=제육볶음", f"--general-estimate={SPEC}", f"--general-estimate-ref={REF}")


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
    return root


@pytest.fixture
def database(home: Path) -> Path:
    return home / "db" / "muscle50.sqlite3"


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return out


def _log(capsys: pytest.CaptureFixture[str], meal: str, *entries: str) -> str:
    return _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", meal, *entries)


def _tables(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    if not database.exists():
        return {}
    connection = sqlite3.connect(database)
    try:
        names = [
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        ]
        return {name: sorted(connection.execute(f"SELECT * FROM {name}").fetchall(), key=repr) for name in names}
    finally:
        connection.close()


ESTIMATED_TEXT = [
    f"Recorded meal {DINNER}.",
    "",
    f"[dinner] {DINNER} (2026-10-08, time not recorded)",
    "  1. 일반식 (general meal; note: 제육볶음): estimated kcal 700-950 | P 30-45 g | C unknown | F unknown",
    "     source: visual_estimate/estimated",
    "     missing: kcal, protein, carbohydrate, fat",
    "  Meal total: kcal incomplete (no item has a value) | P incomplete (no item has a value) | "
    "C incomplete (no item has a value) | F incomplete (no item has a value)",
    "",
    f"Whole day: muscle50 nutrition day --date {DAY}",
]


def test_estimated_general_meal_text_rows_and_provenance(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    out = _log(capsys, "dinner", *ESTIMATED)
    assert out == "\n".join(ESTIMATED_TEXT) + "\n"
    facts = _tables(database)["nutrition_facts"]
    assert facts == [
        (
            f"{DINNER}:1:estimate",
            DINNER,
            1,
            None,
            None,
            None,
            None,
            None,
            "700",
            "950",
            "30",
            "45",
            None,
            None,
            None,
            None,
            "1",
            "serving",
            "visual_estimate",
            REF,
            None,
            "estimated",
            None,
            None,
            NOW.isoformat(),
            None,
        )
    ]
    items = _tables(database)["nutrition_meal_items"]
    assert items == [(DINNER, 1, GENERAL_MEAL_NAME, GENERAL_MEAL_FOOD_ID, None, None, "제육볶음")]
    meal = _tables(database)["nutrition_meals"][0]
    assert meal[4] == (
        f"structured entry dinner {DAY}: general meal (note: 제육볶음) estimated "
        "visual_estimate:kcal=700-950,protein=30-45"
    )


def test_estimated_general_meal_json(capsys: pytest.CaptureFixture[str]) -> None:
    printed = _log(capsys, "dinner", *ESTIMATED, "--json")
    document = json.loads(printed)
    assert printed == json.dumps(document, indent=2) + "\n"
    item = document["items"][0]
    estimate = {"fact_id": f"{DINNER}:1:estimate", "source_type": "visual_estimate", "accuracy": "estimated"}
    assert item["nutrients"] == {
        "calories_kcal": {"value": None, "minimum": "700", "maximum": "950", **estimate},
        "protein_g": {"value": None, "minimum": "30", "maximum": "45", **estimate},
        "carbohydrate_g": None,
        "fat_g": None,
    }
    assert item["missing_fields"] == ["calories_kcal", "protein_g", "carbohydrate_g", "fat_g"]
    assert (item["general_meal"], item["note"], item["quantity"], item["unit"]) == (True, "제육볶음", None, None)
    assert [fact["has_estimate_range"] for fact in item["facts"]] == [True]
    total = document["total"]
    assert total["complete"] is False
    assert total["totals"] == {"calories_kcal": None, "protein_g": None, "carbohydrate_g": None, "fat_g": None}
    assert total["estimated_fields"] == ["calories_kcal", "protein_g"]
    assert total["estimate_range"] == {
        "minimum": {"calories_kcal": "700", "protein_g": "30", "carbohydrate_g": None, "fat_g": None},
        "maximum": {"calories_kcal": "950", "protein_g": "45", "carbohydrate_g": None, "fat_g": None},
    }
    assert total["uncalculated_items"] == []


def test_default_reference_and_language_estimate(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _log(capsys, "dinner", "--general", "--general-estimate", "language_estimate:fat=10-20.5")
    fact = _tables(database)["nutrition_facts"][0]
    assert (fact[14], fact[15], fact[18], fact[19]) == (
        "10",
        "20.5",
        "language_estimate",
        "nutrition log --general-estimate",
    )


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (
            "exact:kcal=1-2",
            "item 1: --general-estimate source must be visual_estimate or language_estimate, not 'exact'",
        ),
        ("nutrition_label:kcal=1-2", "item 1: --general-estimate source must be visual_estimate or language_estimate"),
        ("kcal=1-2", "item 1: --general-estimate must look like visual_estimate:kcal=700-950,protein=30-45"),
        ("visual_estimate:kcal=950-700", "item 1: --general-estimate kcal minimum 950 is above its maximum 700"),
        ("visual_estimate:kcal=abc-1", "item 1: --general-estimate kcal bounds must be plain non-negative numbers"),
        ("visual_estimate:kcal=-1-2", "item 1: --general-estimate kcal bounds must be plain non-negative numbers"),
        ("visual_estimate:sugar=1-2", "item 1: --general-estimate each range must be"),
        ("visual_estimate:kcal=5", "item 1: --general-estimate each range must be"),
        ("visual_estimate:kcal=1-2,kcal=3-4", "item 1: --general-estimate lists kcal twice"),
        ("visual_estimate:", "item 1: --general-estimate each range must be"),
    ],
)
def test_bad_estimates_are_refused_and_nothing_is_written(
    capsys: pytest.CaptureFixture[str], database: Path, spec: str, message: str
) -> None:
    _log(capsys, "lunch", "--general")
    before = _tables(database)
    code, out, err = _run(
        capsys, "nutrition", "log", "--date", DAY, "--meal", "dinner", "--general", f"--general-estimate={spec}"
    )
    assert (code, out) == (1, "")
    assert err.startswith(f"오류: {message}") and err.endswith("Nothing was changed.\n")
    assert _tables(database) == before


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("x" * 101, "must be at most 100 characters (got 101)"),
        ("a\nb", "must be a single line of text"),
        ("   ", "must not be blank"),
    ],
)
def test_bad_reference_is_refused(
    capsys: pytest.CaptureFixture[str], database: Path, reference: str, message: str
) -> None:
    argv = ("nutrition", "log", "--meal", "dinner", "--general", f"--general-estimate={SPEC}")
    code, out, err = _run(capsys, *argv, f"--general-estimate-ref={reference}")
    assert (code, out) == (1, "")
    assert err == f"오류: item 1: --general-estimate-ref {message}. Nothing was changed.\n"
    assert (
        not database.exists() or "nutrition_meals" not in _tables(database) or not _tables(database)["nutrition_meals"]
    )


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (("--general-estimate", SPEC), "argument --general-estimate: must directly follow the --general"),
        (("--item", "x", "1", "g", "--general-estimate", SPEC), "argument --general-estimate: must directly follow"),
        (("--general", "--general-estimate-ref", "x"), "argument --general-estimate-ref: must directly follow the"),
        (("--general", "--general-estimate", SPEC, "--general-estimate", SPEC), "argument --general-estimate: must"),
        (("--general", "--general-estimate", SPEC, "--general-note", "x"), "argument --general-note: must directly"),
        (
            ("--general", "--general-estimate", SPEC, "--general-estimate-ref", "a", "--general-estimate-ref", "b"),
            "argument --general-estimate-ref: must directly follow",
        ),
    ],
)
def test_misplaced_estimate_flags_are_usage_errors(
    capsys: pytest.CaptureFixture[str], home: Path, entries: tuple[str, ...], message: str
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["nutrition", "log", "--meal", "dinner", *entries])
    assert raised.value.code == 2
    assert message in capsys.readouterr().err
    assert not home.exists()


def test_status_stays_indeterminate_and_recommend_gives_no_action(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2000")
    _ok(capsys, "nutrition", "target", "set", "protein", "--exact", "120")
    _log(capsys, "dinner", *ESTIMATED)
    status = json.loads(_ok(capsys, "nutrition", "status", "--date", DAY, "--json"))
    kcal, protein = status["nutrients"]["calories_kcal"], status["nutrients"]["protein_g"]
    assert (kcal["status"], kcal["complete"], kcal["estimated"], kcal["known_subtotal"]) == (
        "indeterminate",
        False,
        True,
        None,
    )
    assert (protein["status"], protein["remaining"]) == ("indeterminate", None)
    text = _ok(capsys, "nutrition", "status", "--date", DAY)
    assert "Estimated: kcal, protein include values from facts marked estimated." in text
    recommendation = json.loads(_ok(capsys, "recommend", "--date", DAY, "--json"))
    assert recommendation["nutrition"]["actions"] == []
    assert recommendation["nutrition"]["nutrients"]["calories_kcal"]["status"] == "indeterminate"


def test_day_lists_the_estimate_as_estimated_and_incomplete(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    _log(capsys, "dinner", *ESTIMATED, "--item", "chicken-breast", "100", "g")
    text = _ok(capsys, "nutrition", "day", "--date", DAY)
    assert "  kcal          incomplete (known items only: 110 (estimated))" in text
    assert "Estimated: kcal, protein include values from facts marked estimated." in text
    day = json.loads(_ok(capsys, "nutrition", "day", "--date", DAY, "--json"))
    assert day["total"]["estimate_range"]["minimum"]["calories_kcal"] == "810"
    assert day["total"]["estimate_range"]["maximum"]["calories_kcal"] == "1060"
    assert day["total"]["known_subtotals"]["calories_kcal"] == "110"


def test_repeat_drops_the_estimate(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _log(capsys, "dinner", *ESTIMATED)
    out = _ok(capsys, "nutrition", "repeat", DINNER, "--additional")
    assert "  1. 일반식 (general meal; note: 제육볶음): nutrition unknown" in out
    assert "Nutrition facts changed" not in out
    facts = _tables(database)["nutrition_facts"]
    assert [fact[0] for fact in facts] == [f"{DINNER}:1:estimate"]


def test_merge_copies_the_estimate_and_item_edits_work(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    _log(capsys, "lunch", "--item", "chicken-breast", "100", "g")
    _log(capsys, "dinner", *ESTIMATED)
    merged = json.loads(_ok(capsys, "nutrition", "meal", "merge", LUNCH, DINNER, "--json"))
    copy = merged["items"][-1]
    assert (copy["sequence"], copy["general_meal"], copy["note"]) == (2, True, "제육볶음")
    assert copy["nutrients"]["calories_kcal"]["fact_id"] == f"{LUNCH}:2:estimate"
    assert copy["nutrients"]["calories_kcal"]["minimum"] == "700"
    added = _ok(
        capsys,
        "nutrition",
        "meal",
        "add-item",
        LUNCH,
        "--general",
        "--general-estimate=language_estimate:kcal=100-200",
    )
    assert "  3. 일반식 (general meal): estimated kcal 100-200 | P unknown | C unknown | F unknown" in added
    removed = _ok(capsys, "nutrition", "meal", "remove-item", LUNCH, "--item-number", "2")
    assert "  2. 일반식" not in removed
    replaced = _ok(
        capsys, "nutrition", "meal", "replace-item", LUNCH, "--item-number", "3", "--item", "chicken-breast", "50", "g"
    )
    assert "  4. 닭가슴살 (chicken-breast) 50 g" in replaced
    fact_ids = [fact[0] for fact in _tables(database)["nutrition_facts"]]
    assert {f"{DINNER}:1:estimate", f"{LUNCH}:2:estimate", f"{LUNCH}:3:estimate"} <= set(fact_ids)


def _estimate_fact(fact_id: str, **overrides: Any) -> NutritionFact:
    fields: dict[str, Any] = {
        "fact_id": fact_id,
        "values": NutritionValue(),
        "basis_quantity": Decimal(1),
        "basis_unit": QuantityUnit.SERVING,
        "provenance": NutritionProvenance(NutritionSourceType.VISUAL_ESTIMATE, Accuracy.ESTIMATED, "synthetic", NOW),
        "value_range": NutritionRange(
            NutritionValue(calories_kcal=Decimal(700)), NutritionValue(calories_kcal=Decimal(950))
        ),
    }
    fields.update(overrides)
    return NutritionFact(**fields)


def _general(*facts: NutritionFact) -> MealItem:
    return MealItem("m", 1, GENERAL_MEAL_NAME, None, None, GENERAL_MEAL_FOOD_ID, nutrition_facts=facts)


def test_is_general_accepts_only_one_estimate_only_fact() -> None:
    estimated = _general(_estimate_fact("m:1:estimate"))
    assert estimated.is_general
    assert estimated.general_estimate is not None
    calculated = estimated.calculated_nutrition()
    assert calculated is not None
    kcal = calculated.get(NutrientField.CALORIES_KCAL)
    assert kcal is not None and (kcal.value, kcal.minimum, kcal.maximum) == (None, Decimal(700), Decimal(950))
    assert _general().general_estimate is None and _general().calculated_nutrition() is None
    labelled = NutritionProvenance(NutritionSourceType.USER_PROVIDED, Accuracy.ESTIMATED, "synthetic", NOW)
    not_general = [
        _general(_estimate_fact("a"), _estimate_fact("b")),
        _general(_estimate_fact("a", provenance=labelled)),
        _general(_estimate_fact("a", basis_quantity=Decimal(2))),
        _general(_estimate_fact("a", basis_unit=QuantityUnit.PACK)),
        _general(
            _estimate_fact(
                "a",
                values=NutritionValue(calories_kcal=Decimal(800)),
            )
        ),
    ]
    assert [item.is_general for item in not_general] == [False] * len(not_general)


def test_spec_round_trips_and_the_item_carries_one_fact() -> None:
    estimate = parse_general_estimate("visual_estimate:protein=30-45,kcal=700.5-950", "ref", NOW, label="")
    assert estimate.ranges == (
        (NutrientField.CALORIES_KCAL, Decimal("700.5"), Decimal(950)),
        (NutrientField.PROTEIN_G, Decimal(30), Decimal(45)),
    )
    spec = format_general_estimate(estimate.source_type, estimate.ranges)
    assert spec == "visual_estimate:kcal=700.5-950,protein=30-45"
    assert parse_general_estimate(spec, "ref", NOW, label="") == estimate
    item = general_meal_item("m", 2, " 메모 ", label="item 2", estimate=estimate)
    assert item.is_general and [fact.fact_id for fact in item.nutrition_facts] == ["m:2:estimate"]
    wrong = GeneralMealEstimate(NutritionSourceType.USER_PROVIDED, estimate.ranges, "ref", NOW)
    with pytest.raises(NutritionLoggingError, match="source must be visual_estimate or language_estimate"):
        general_meal_item("m", 2, None, label="item 2", estimate=wrong)
