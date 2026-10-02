"""`muscle50 nutrition food fact add`: append-only nutrition fact versions for an existing food.

Runs over a temporary MUSCLE50_HOME / temporary SQLite database only. All nutrition values are
synthetic test numbers. The central guarantee: adding a fact version never changes a meal that
was already logged, and only meals logged afterwards use the new active fact.
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
    AddFood,
    AddFoodFact,
    NewFood,
    NewFoodFact,
    NutritionLoggingError,
    ShowFood,
)
from muscle50.cli import main
from muscle50.domain.nutrition import (
    Accuracy,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository

KST = timezone(timedelta(hours=9))
CREATED_AT = datetime(2026, 10, 1, 21, 0, tzinfo=KST)

# v1 as currently stored for the user: protein only, per 200 g.
V1 = (
    ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "200", "g"]
    + ["--kcal", "unknown", "--protein", "36", "--carbs", "unknown", "--fat", "unknown"]
    + ["--source", "user_provided", "--accuracy", "exact"]
)
# v2 from the task: per 100 g, every nutrient known, a lower-priority source than v1.
V2 = (
    ["chicken-breast", "--per", "100", "g"]
    + ["--kcal", "120", "--protein", "18", "--carbs", "2", "--fat", "4"]
    + ["--source", "food_database", "--accuracy", "estimated"]
    + ["--source-ref", "generic lightly seasoned chicken breast estimate"]
)
OLD_DAY = "2026-10-01"
NEW_DAY = "2026-10-02"


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
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 2))
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


def _json(capsys: pytest.CaptureFixture[str], *argv: str) -> Any:
    return json.loads(_ok(capsys, *argv, "--json"))


def _log(capsys: pytest.CaptureFixture[str], day: str, meal: str, *, additional: bool = False) -> None:
    extra = ["--additional"] if additional else []
    _ok(capsys, "nutrition", "log", "--date", day, "--meal", meal, "--item", "chicken-breast", "200", "g", *extra)


def _snapshot(capsys: pytest.CaptureFixture[str], day: str) -> tuple[str, ...]:
    """Every read-only view of a day, text and JSON, byte for byte."""
    return tuple(
        _ok(capsys, "nutrition", command, "--date", day, *flags)
        for command in ("day", "status")
        for flags in ((), ("--json",))
    )


def _row_counts(database: Path) -> tuple[int, ...]:
    connection = sqlite3.connect(database)
    try:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("nutrition_food_profiles", "nutrition_meals", "nutrition_meal_items", "nutrition_facts")
        )
    finally:
        connection.close()


def _setup_v1_with_targets(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *V1)
    _ok(capsys, "nutrition", "target", "set", "protein", "--range", "150", "170")
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")


def _nutrient(payload: dict[str, Any], nutrient: str) -> Any:
    (meal,) = payload["meals"]
    (item,) = meal["items"]
    return item["nutrients"][nutrient]


# --- A: versioning --------------------------------------------------------------------------


def test_a_v2_is_appended_active_and_v1_is_kept(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _ok(capsys, "nutrition", "food", "add", *V1)
    v1_before = _json(capsys, "nutrition", "food", "show", "chicken-breast")["facts"][0]

    out = _ok(capsys, "nutrition", "food", "fact", "add", *V2)

    assert out.startswith(
        "Added fact food:chicken-breast:2 to chicken-breast; it replaces food:chicken-breast:1 for meals logged "
        "from now on.\nMeals already logged keep the facts they were logged with.\n"
    )
    food = _json(capsys, "nutrition", "food", "show", "chicken-breast")
    assert food["food_id"] == "chicken-breast"
    assert food["name"] == "닭가슴살"
    v1, v2 = food["facts"]
    assert v1 == {**v1_before, "active": False}
    assert v2["fact_id"] == "food:chicken-breast:2"
    assert v2["active"] is True
    assert v2["supersedes_fact_id"] == "food:chicken-breast:1"
    assert (v2["basis_quantity"], v2["basis_unit"]) == ("100", "g")
    assert v2["values"] == {"calories_kcal": "120", "protein_g": "18", "carbohydrate_g": "2", "fat_g": "4"}
    assert (v2["source_type"], v2["accuracy"]) == ("food_database", "estimated")
    assert v2["source_reference"] == "generic lightly seasoned chicken breast estimate"
    assert _row_counts(database) == (1, 0, 0, 2)
    # Same food identity: still one food, and list shows only the active fact.
    (listed,) = _json(capsys, "nutrition", "food", "list")["foods"]
    assert [fact["fact_id"] for fact in listed["facts"] if fact["active"]] == ["food:chicken-breast:2"]
    text_list = _ok(capsys, "nutrition", "food", "list")
    assert "per 100 g: kcal 120 | P 18 g | C 2 g | F 4 g  [food_database/estimated]" in text_list
    assert "per 200 g" not in text_list


def test_a_v3_replaces_v2_and_keeps_the_whole_history(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *V1)
    _ok(capsys, "nutrition", "food", "fact", "add", *V2)
    v3 = ["chicken-breast", "--per", "100", "g", "--kcal", "115", "--protein", "23", "--carbs", "0", "--fat", "2"]

    _ok(capsys, "nutrition", "food", "fact", "add", *v3, "--source", "nutrition_label", "--accuracy", "exact")

    facts = _json(capsys, "nutrition", "food", "show", "chicken-breast")["facts"]
    assert [(fact["fact_id"], fact["active"], fact["supersedes_fact_id"]) for fact in facts] == [
        ("food:chicken-breast:1", False, None),
        ("food:chicken-breast:2", False, "food:chicken-breast:1"),
        ("food:chicken-breast:3", True, "food:chicken-breast:2"),
    ]
    assert facts[2]["source_reference"] == "entered with muscle50 nutrition food fact add"


# --- B / C / D: historical meals never change ---------------------------------------------


def test_b_meal_logged_before_v2_is_unchanged_in_every_view(capsys: pytest.CaptureFixture[str]) -> None:
    _setup_v1_with_targets(capsys)
    _log(capsys, OLD_DAY, "breakfast")
    before = _snapshot(capsys, OLD_DAY)
    recommend_before = tuple(_ok(capsys, "recommend", "--date", OLD_DAY, *flags) for flags in ((), ("--json",)))
    assert "== Nutrition" in recommend_before[0]

    _ok(capsys, "nutrition", "food", "fact", "add", *V2)

    assert _snapshot(capsys, OLD_DAY) == before
    assert recommend_before == tuple(_ok(capsys, "recommend", "--date", OLD_DAY, *flags) for flags in ((), ("--json",)))
    day = _json(capsys, "nutrition", "day", "--date", OLD_DAY)
    protein = _nutrient(day, "protein_g")
    assert protein["value"] == "36"
    assert protein["fact_id"] == "2026-10-01-breakfast-1:1:food:chicken-breast:1"
    assert (protein["source_type"], protein["accuracy"]) == ("user_provided", "exact")
    assert day["total"]["estimated_fields"] == []


def test_c_meal_logged_after_v2_uses_v2(capsys: pytest.CaptureFixture[str]) -> None:
    _setup_v1_with_targets(capsys)
    _ok(capsys, "nutrition", "food", "fact", "add", *V2)

    _log(capsys, NEW_DAY, "lunch")

    day = _json(capsys, "nutrition", "day", "--date", NEW_DAY)
    for nutrient, value in (("calories_kcal", "240"), ("protein_g", "36"), ("carbohydrate_g", "4"), ("fat_g", "8")):
        selected = _nutrient(day, nutrient)
        assert selected["value"] == value
        # Protein equals v1's number (0.18 g/g both ways): the fact ID proves v2 was used.
        assert selected["fact_id"] == "2026-10-02-lunch-1:1:food:chicken-breast:2"
        assert (selected["source_type"], selected["accuracy"]) == ("food_database", "estimated")
    assert day["total"]["incomplete_fields"] == []
    assert day["total"]["estimated_fields"] == ["calories_kcal", "protein_g", "carbohydrate_g", "fat_g"]
    text = _ok(capsys, "nutrition", "day", "--date", NEW_DAY)
    assert "1. 닭가슴살 (chicken-breast) 200 g: kcal 240 | P 36 g | C 4 g | F 8 g" in text
    # Only the fact the values came from, not the superseded v1 also kept on the item.
    assert "     source: food_database/estimated\n" in text


def test_d_unknown_in_v1_stays_unknown_for_old_meals_and_known_for_new_ones(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup_v1_with_targets(capsys)
    _log(capsys, NEW_DAY, "breakfast")
    before_breakfast = _json(capsys, "nutrition", "day", "--date", NEW_DAY)["meals"][0]

    _ok(capsys, "nutrition", "food", "fact", "add", *V2)
    _log(capsys, NEW_DAY, "lunch")

    day = _json(capsys, "nutrition", "day", "--date", NEW_DAY)
    breakfast, lunch = day["meals"]
    assert breakfast == before_breakfast
    (old_item,) = breakfast["items"]
    assert old_item["missing_fields"] == ["calories_kcal", "carbohydrate_g", "fat_g"]
    assert old_item["nutrients"]["calories_kcal"] is None
    (new_item,) = lunch["items"]
    assert new_item["missing_fields"] == []
    assert new_item["nutrients"]["calories_kcal"]["value"] == "240"
    # The day stays incomplete for kcal/carbs/fat because of the old meal only.
    assert day["total"]["incomplete_fields"] == ["calories_kcal", "carbohydrate_g", "fat_g"]
    assert day["total"]["known_subtotals"]["calories_kcal"] == "240"
    text = _ok(capsys, "nutrition", "day", "--date", NEW_DAY)
    assert "  kcal: 2026-10-02-breakfast-1 item 1 닭가슴살 (chicken-breast)\n" in text
    status = _json(capsys, "nutrition", "status", "--date", NEW_DAY)
    kcal = status["nutrients"]["calories_kcal"]
    assert kcal["consumed"] is None
    assert [item["meal_id"] for item in kcal["missing_items"]] == ["2026-10-02-breakfast-1"]


# --- E: history display --------------------------------------------------------------------


def test_e_food_show_text_lists_every_version_and_marks_the_active_one(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *V1)
    _ok(capsys, "nutrition", "food", "fact", "add", *V2)

    lines = _ok(capsys, "nutrition", "food", "show", "chicken-breast").splitlines()

    assert lines[0] == "Food chicken-breast: 닭가슴살"
    assert lines[1] == "  fact food:chicken-breast:1 (superseded)"
    assert lines[2] == "    per 200 g: kcal unknown | P 36 g | C unknown | F unknown  [user_provided/exact]"
    assert lines[3] == "    reference: entered with muscle50 nutrition food add"
    assert lines[5] == "  fact food:chicken-breast:2 (active, replaces food:chicken-breast:1)"
    assert lines[6] == "    per 100 g: kcal 120 | P 18 g | C 2 g | F 4 g  [food_database/estimated]"
    assert lines[7] == "    reference: generic lightly seasoned chicken breast estimate"
    assert lines[8].startswith("    recorded: ")
    assert len(lines) == 9


# --- F: refused versions change nothing ----------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ["no-such-food", "--per", "100", "g", "--kcal", "1", "--protein", "1", "--carbs", "1", "--fat", "1"],
            "no food with id 'no-such-food'",
        ),
        (
            ["chicken-breast", "--per", "1", "pack", "--kcal", "1", "--protein", "1", "--carbs", "1", "--fat", "1"],
            "has nutrition per g, not per pack",
        ),
        (
            ["chicken-breast", "--per", "100", "g"]
            + ["--kcal", "unknown", "--protein", "unknown", "--carbs", "unknown", "--fat", "unknown"],
            "at least one of kcal/protein/carbohydrate/fat must be a number",
        ),
        (
            ["chicken-breast", "--per", "100", "g", "--kcal", "120", "--protein", "unknown"]
            + ["--carbs", "2", "--fat", "4"],
            "has a value for protein; a new version must give a number for it too",
        ),
        (
            ["chicken-breast", "--per", "0", "g", "--kcal", "1", "--protein", "1", "--carbs", "1", "--fat", "1"],
            "--per quantity must be greater than 0",
        ),
        (
            ["chicken-breast", "--per", "100", "g", "--kcal", "-5", "--protein", "1", "--carbs", "1", "--fat", "1"],
            "--kcal must be a plain non-negative number",
        ),
        (
            ["chicken-breast", "--per", "200", "g", "--kcal", "unknown", "--protein", "36"]
            + ["--carbs", "unknown", "--fat", "unknown", "--source-ref", "entered with muscle50 nutrition food add"],
            "the new fact is the same as the current fact food:chicken-breast:1; nothing was changed",
        ),
    ],
)
def test_f_invalid_version_is_refused_without_any_write(
    capsys: pytest.CaptureFixture[str], database: Path, argv: list[str], message: str
) -> None:
    _ok(capsys, "nutrition", "food", "add", *V1)
    _log(capsys, OLD_DAY, "breakfast")
    shown = _ok(capsys, "nutrition", "food", "show", "chicken-breast", "--json")
    counts = _row_counts(database)
    source = ["--source", "user_provided", "--accuracy", "exact"]

    code, out, err = _run(capsys, "nutrition", "food", "fact", "add", *argv, *source)

    assert code == 1
    assert out == ""
    assert message in err
    assert _row_counts(database) == counts
    assert _ok(capsys, "nutrition", "food", "show", "chicken-breast", "--json") == shown


def test_f_estimate_sources_and_missing_flags_are_argparse_errors(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *V1)
    base = ["nutrition", "food", "fact", "add", "chicken-breast", "--per", "100", "g", "--kcal", "1"]

    with pytest.raises(SystemExit) as missing:
        main([*base, "--source", "food_database", "--accuracy", "estimated"])
    with pytest.raises(SystemExit) as estimate:
        main([*base, "--protein", "1", "--carbs", "1", "--fat", "1", "--source", "visual_estimate"])

    assert missing.value.code == 2
    assert estimate.value.code == 2
    capsys.readouterr()
    assert [fact["fact_id"] for fact in _json(capsys, "nutrition", "food", "show", "chicken-breast")["facts"]] == [
        "food:chicken-breast:1"
    ]


def test_f_storage_failure_rolls_back_and_keeps_the_active_fact(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _ok(capsys, "nutrition", "food", "add", *V1)
    shown = _ok(capsys, "nutrition", "food", "show", "chicken-breast", "--json")
    counts = _row_counts(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TRIGGER fail_fact_insert BEFORE INSERT ON nutrition_facts "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END"
    )
    connection.commit()
    connection.close()
    repository = SqliteFoodNutritionRepository(database)
    new = NewFoodFact(
        "chicken-breast",
        Decimal("100"),
        QuantityUnit.GRAM,
        NutritionValue(Decimal("120"), Decimal("18"), Decimal("2"), Decimal("4")),
        NutritionSourceType.FOOD_DATABASE,
        Accuracy.ESTIMATED,
        "synthetic",
    )

    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        AddFoodFact(repository, clock=lambda: CREATED_AT).execute(new)

    connection = sqlite3.connect(database)
    connection.execute("DROP TRIGGER fail_fact_insert")
    connection.commit()
    connection.close()
    assert _row_counts(database) == counts
    assert _ok(capsys, "nutrition", "food", "show", "chicken-breast", "--json") == shown


# --- semantics guard for histories not created by the CLI ----------------------------------


def _repository_with(tmp_path: Path, *facts: NutritionFact) -> SqliteFoodNutritionRepository:
    repository = SqliteFoodNutritionRepository(tmp_path / "guard" / "muscle50.sqlite3")
    repository.migrate()
    AddFood(repository, clock=lambda: CREATED_AT).execute(
        NewFood(
            "rice",
            "rice",
            Decimal("100"),
            QuantityUnit.GRAM,
            NutritionValue(Decimal("130"), Decimal("3"), None, None),
            NutritionSourceType.NUTRITION_LABEL,
            Accuracy.EXACT,
            "synthetic",
        )
    )
    for fact in facts:
        repository.append_nutrition_fact("rice", fact)
    return repository


def _fact(fact_id: str, values: NutritionValue, supersedes: str | None) -> NutritionFact:
    return NutritionFact(
        fact_id,
        values,
        Decimal("100"),
        QuantityUnit.GRAM,
        NutritionProvenance(NutritionSourceType.FOOD_DATABASE, Accuracy.ESTIMATED, "synthetic", CREATED_AT),
        supersedes_fact_id=supersedes,
    )


def _new_rice(values: NutritionValue) -> NewFoodFact:
    return NewFoodFact(
        "rice", Decimal("100"), QuantityUnit.GRAM, values, NutritionSourceType.FOOD_DATABASE, Accuracy.ESTIMATED, "v"
    )


def test_version_that_would_lose_to_an_older_fact_is_refused(tmp_path: Path) -> None:
    # A protein-only correction added in code leaves rice:1 active for kcal. A new version
    # superseding rice:2 would not exclude rice:1 for kcal, and rice:1 (label/exact) would
    # still win kcal over it on source priority, so it is refused instead of half-applied.
    repository = _repository_with(
        tmp_path, _fact("food:rice:2", NutritionValue(None, Decimal("4"), None, None), "food:rice:1")
    )

    with pytest.raises(NutritionLoggingError, match="would not be the active fact for kcal"):
        AddFoodFact(repository, clock=lambda: CREATED_AT).execute(
            _new_rice(NutritionValue(Decimal("140"), Decimal("4"), Decimal("28"), Decimal("0.3")))
        )

    assert [fact.fact_id for fact in ShowFood(repository).execute("rice").facts] == ["food:rice:1", "food:rice:2"]


def test_two_current_facts_in_one_unit_are_ambiguous(tmp_path: Path) -> None:
    repository = _repository_with(
        tmp_path, _fact("food:rice:extra", NutritionValue(Decimal("1"), None, None, None), None)
    )

    with pytest.raises(NutritionLoggingError, match="has 2 current facts per g"):
        AddFoodFact(repository, clock=lambda: CREATED_AT).execute(
            _new_rice(NutritionValue(Decimal("140"), Decimal("4"), Decimal("28"), Decimal("0.3")))
        )


# --- G: determinism ------------------------------------------------------------------------


def test_g_text_and_json_are_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    _setup_v1_with_targets(capsys)
    _log(capsys, NEW_DAY, "breakfast")
    _ok(capsys, "nutrition", "food", "fact", "add", *V2)
    _log(capsys, NEW_DAY, "lunch")

    views = [
        ("nutrition", "food", "show", "chicken-breast"),
        ("nutrition", "food", "list"),
        ("nutrition", "day", "--date", NEW_DAY),
        ("nutrition", "status", "--date", NEW_DAY),
    ]
    for view in views:
        assert _ok(capsys, *view) == _ok(capsys, *view)
        first = _ok(capsys, *view, "--json")
        assert first == _ok(capsys, *view, "--json")
        assert first.isascii()


def test_fact_add_json_prints_the_stored_food(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *V1)

    added = _ok(capsys, "nutrition", "food", "fact", "add", *V2, "--json")

    assert added == _ok(capsys, "nutrition", "food", "show", "chicken-breast", "--json")
