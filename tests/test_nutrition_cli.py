"""`muscle50 nutrition` CLI over a temporary MUSCLE50_HOME (never the production data directory).

All nutrition values here are synthetic test numbers, not real food data.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

KST = timezone(timedelta(hours=9))
_REAL_LOCAL_TIMEZONE = cli._local_timezone

# Synthetic catalog for the acceptance scenario (not real nutrition data).
CATALOG = (
    ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g"]
    + ["--kcal", "110", "--protein", "18", "--carbs", "1", "--fat", "3"]
    + ["--source", "nutrition_label", "--accuracy", "exact", "--source-ref", "synthetic label"],
    ["--id", "egg", "--name", "계란", "--per", "1", "count"]
    + ["--kcal", "70", "--protein", "6", "--carbs", "0.5", "--fat", "5"]
    + ["--source", "user_provided", "--accuracy", "estimated"],
    ["--id", "hetbahn", "--name", "햇반", "--per", "1", "pack"]
    + ["--kcal", "300", "--protein", "5", "--carbs", "68", "--fat", "unknown"]
    + ["--source", "nutrition_label", "--accuracy", "exact"],
    ["--id", "banana", "--name", "바나나", "--per", "1", "piece"]
    + ["--kcal", "90", "--protein", "1", "--carbs", "23", "--fat", "0.3"]
    + ["--source", "user_provided", "--accuracy", "exact"],
)
BREAKFAST = (
    ["nutrition", "log", "--date", "2026-10-02", "--meal", "breakfast"]
    + ["--item", "chicken-breast", "200", "g", "--item", "egg", "2", "count"]
    + ["--item", "hetbahn", "1", "pack", "--item", "banana", "1", "piece"]
)


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


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _add_catalog(capsys: pytest.CaptureFixture[str]) -> None:
    for food in CATALOG:
        code, _, err = _run(capsys, "nutrition", "food", "add", *food)
        assert code == 0, err


def test_acceptance_breakfast_text_output(capsys: pytest.CaptureFixture[str]) -> None:
    _add_catalog(capsys)

    code, out, err = _run(capsys, *BREAKFAST)

    assert code == 0, err
    assert "Recorded meal 2026-10-02-breakfast-1." in out
    assert "1. 닭가슴살 (chicken-breast) 200 g: kcal 220 | P 36 g | C 2 g | F 6 g" in out
    assert "2. 계란 (egg) 2 count: kcal 140 | P 12 g | C 1 g | F 10 g" in out
    assert "     source: user_provided/estimated" in out
    assert "3. 햇반 (hetbahn) 1 pack: kcal 300 | P 5 g | C 68 g | F missing" in out
    assert "     missing: fat" in out
    assert "4. 바나나 (banana) 1 piece: kcal 90 | P 1 g | C 23 g | F 0.3 g" in out
    assert (
        "Meal total: kcal 750 (estimated) | P 54 g (estimated) | C 94 g (estimated) "
        "| F incomplete (known items only: 16.3 g (estimated))"
    ) in out

    code, out, err = _run(capsys, "nutrition", "day", "--date", "2026-10-02")

    assert code == 0, err
    assert "Nutrition intake 2026-10-02 (UTC+09:00)" in out
    assert "Nutrition targets and remaining amounts are not implemented." in out
    assert "Consumed (1 meal, 4 items):" in out
    assert "  kcal          750 (estimated)" in out
    assert "  Protein       54 g (estimated)" in out
    assert "  Carbohydrate  94 g (estimated)" in out
    assert "  Fat           incomplete (known items only: 16.3 g (estimated))" in out
    assert "  fat: 2026-10-02-breakfast-1 item 3 햇반 (hetbahn)" in out
    assert "target" not in out.replace("Nutrition targets and remaining amounts are not implemented.", "")


def test_acceptance_day_json_is_exact_and_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    _add_catalog(capsys)
    assert _run(capsys, *BREAKFAST)[0] == 0
    assert (
        _run(
            capsys, "nutrition", "log", "--meal", "lunch", "--time", "12:30", "--item", "chicken-breast", "150.5", "g"
        )[0]
        == 0
    )

    code, first, _ = _run(capsys, "nutrition", "day", "--date", "2026-10-02", "--json")
    _, second, _ = _run(capsys, "nutrition", "day", "--date", "2026-10-02", "--json")

    assert code == 0
    assert first == second
    assert first.isascii()
    payload = json.loads(first)
    assert payload["date"] == "2026-10-02"
    assert payload["timezone"] == "+09:00"
    assert payload["scope"] == "intake_only"
    breakfast, lunch = payload["meals"]
    assert breakfast["time_recorded"] is False
    assert lunch["time_recorded"] is True
    assert lunch["eaten_at"] == "2026-10-02T12:30:00+09:00"
    assert [item["food_name"] for item in breakfast["items"]] == ["닭가슴살", "계란", "햇반", "바나나"]
    chicken = breakfast["items"][0]
    assert chicken["quantity"] == "200"
    assert chicken["unit"] == "g"
    assert chicken["nutrients"]["protein_g"]["value"] == "36"
    assert chicken["nutrients"]["protein_g"]["source_type"] == "nutrition_label"
    assert chicken["facts"][0]["fact_id"] == "2026-10-02-breakfast-1:1:food:chicken-breast:1"
    assert chicken["facts"][0]["source_reference"] == "synthetic label"
    hetbahn = breakfast["items"][2]
    assert hetbahn["nutrients"]["fat_g"] is None
    assert hetbahn["missing_fields"] == ["fat_g"]
    assert lunch["items"][0]["nutrients"]["calories_kcal"]["value"] == "165.55"
    total = payload["total"]
    assert total["complete"] is False
    assert total["item_count"] == 5
    assert total["totals"] == {
        "calories_kcal": "915.55",
        "protein_g": "81.09",
        "carbohydrate_g": "95.505",
        "fat_g": None,
    }
    assert total["known_subtotals"]["fat_g"] == "20.815"
    assert total["incomplete_fields"] == ["fat_g"]
    assert total["estimated_fields"] == ["calories_kcal", "protein_g", "carbohydrate_g", "fat_g"]
    assert "remaining" not in first
    assert "target" not in first


def test_log_defaults_to_today_and_day_defaults_to_today(capsys: pytest.CaptureFixture[str]) -> None:
    _add_catalog(capsys)

    code, out, _ = _run(capsys, "nutrition", "log", "--meal", "snack", "--item", "banana", "1", "piece")
    assert code == 0
    assert "Recorded meal 2026-10-02-snack-1." in out

    code, out, _ = _run(capsys, "nutrition", "day")
    assert code == 0
    assert "Nutrition intake 2026-10-02" in out
    assert "[snack] 2026-10-02-snack-1 (2026-10-02, time not recorded)" in out


def test_food_list_and_show(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "nutrition", "food", "list")
    assert code == 0
    assert "No foods in the catalog yet." in out
    _add_catalog(capsys)

    code, out, _ = _run(capsys, "nutrition", "food", "list")
    assert code == 0
    assert out.index("banana  바나나") < out.index("chicken-breast  닭가슴살") < out.index("egg  계란")
    assert "per 1 pack: kcal 300 | P 5 g | C 68 g | F unknown  [nutrition_label/exact]" in out

    code, out, _ = _run(capsys, "nutrition", "food", "show", "chicken-breast")
    assert code == 0
    assert "Food chicken-breast: 닭가슴살" in out
    assert "fact food:chicken-breast:1 (active)" in out
    assert "reference: synthetic label" in out

    code, first, _ = _run(capsys, "nutrition", "food", "list", "--json")
    _, second, _ = _run(capsys, "nutrition", "food", "list", "--json")
    assert code == 0 and first == second
    foods = json.loads(first)["foods"]
    assert [food["food_id"] for food in foods] == ["banana", "chicken-breast", "egg", "hetbahn"]
    hetbahn = foods[3]
    assert hetbahn["facts"][0]["values"] == {
        "calories_kcal": "300",
        "protein_g": "5",
        "carbohydrate_g": "68",
        "fat_g": None,
    }
    assert hetbahn["facts"][0]["active"] is True

    code, out, _ = _run(capsys, "nutrition", "food", "show", "egg", "--json")
    assert code == 0
    egg = json.loads(out)
    assert egg["name"] == "계란"
    assert (egg["facts"][0]["source_type"], egg["facts"][0]["accuracy"]) == ("user_provided", "estimated")


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["nutrition", "food", "show", "nope"], "no food with id 'nope'"),
        (["nutrition", "day", "--date", "2026-13-01"], "YYYY-MM-DD"),
        (["nutrition", "log", "--meal", "lunch", "--item", "nope", "1", "piece"], "no food with id 'nope'"),
        (["nutrition", "log", "--meal", "lunch", "--item", "banana", "1", "kg"], "unit 'kg' is not supported"),
        (["nutrition", "log", "--meal", "lunch", "--item", "banana", "0", "piece"], "must be greater than 0"),
        (["nutrition", "log", "--meal", "lunch", "--item", "banana", "-1", "piece"], "plain non-negative number"),
        (["nutrition", "log", "--meal", "lunch", "--item", "banana", "1e2", "piece"], "plain non-negative number"),
        (["nutrition", "log", "--meal", "lunch", "--item", "banana", "NaN", "piece"], "plain non-negative number"),
        (["nutrition", "log", "--meal", "lunch", "--item", "banana", ".5", "piece"], "plain non-negative number"),
        (["nutrition", "log", "--meal", "lunch", "--item", "hetbahn", "210", "g"], "units are never converted"),
        (["nutrition", "log", "--meal", "lunch", "--time", "7pm", "--item", "banana", "1", "piece"], "HH:MM"),
        (["nutrition", "log", "--meal", "lunch", "--time", "25:00", "--item", "banana", "1", "piece"], "HH:MM"),
    ],
)
def test_invalid_input_fails_with_a_clear_message(
    capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    _add_catalog(capsys)

    code, out, err = _run(capsys, *argv)

    assert code == 1
    assert out == ""
    assert message in err


def test_rejected_food_add_values_are_never_stored(capsys: pytest.CaptureFixture[str]) -> None:
    base = ["nutrition", "food", "add", "--id", "x", "--name", "엑스", "--per", "1", "piece"]
    source = ["--source", "user_provided", "--accuracy", "exact"]

    for values, message in (
        (["--kcal", "1,000", "--protein", "1", "--carbs", "1", "--fat", "1"], "--kcal must be a plain"),
        (["--kcal", "1", "--protein", "?", "--carbs", "1", "--fat", "1"], "--protein must be a plain"),
        (["--kcal", "unknown", "--protein", "unknown", "--carbs", "unknown", "--fat", "unknown"], "at least one"),
    ):
        code, _, err = _run(capsys, *base, *values, *source)
        assert code == 1
        assert message in err

    code, _, err = _run(
        capsys,
        "nutrition",
        "food",
        "add",
        *CATALOG[0][:2],
        "--name",
        "x",
        "--per",
        "0",
        "g",
        "--kcal",
        "1",
        "--protein",
        "1",
        "--carbs",
        "1",
        "--fat",
        "1",
        *source,
    )
    assert code == 1 and "--per quantity must be greater than 0" in err

    assert "No foods in the catalog yet." in _run(capsys, "nutrition", "food", "list")[1]


def test_food_add_requires_every_nutrient_and_provenance_flag(capsys: pytest.CaptureFixture[str]) -> None:
    complete = CATALOG[0]
    for flag in ("--kcal", "--protein", "--carbs", "--fat", "--source", "--accuracy", "--per"):
        index = complete.index(flag)
        width = 3 if flag == "--per" else 2
        argv = complete[:index] + complete[index + width :]
        with pytest.raises(SystemExit) as raised:
            main(["nutrition", "food", "add", *argv])
        assert raised.value.code == 2
        assert flag in capsys.readouterr().err


def test_estimate_sources_are_not_offered_by_food_add(capsys: pytest.CaptureFixture[str]) -> None:
    argv = list(CATALOG[1])
    argv[argv.index("user_provided")] = "language_estimate"
    with pytest.raises(SystemExit) as raised:
        main(["nutrition", "food", "add", *argv])
    assert raised.value.code == 2
    assert "invalid choice: 'language_estimate'" in capsys.readouterr().err


def test_duplicate_food_and_duplicate_meal_fail_without_changes(capsys: pytest.CaptureFixture[str]) -> None:
    _add_catalog(capsys)

    code, _, err = _run(capsys, "nutrition", "food", "add", *CATALOG[0])
    assert code == 1
    assert "food id 'chicken-breast' already exists; nothing was changed" in err

    assert _run(capsys, *BREAKFAST)[0] == 0
    code, _, err = _run(capsys, *BREAKFAST)
    assert code == 1
    assert "breakfast on 2026-10-02 is already recorded (2026-10-02-breakfast-1)" in err
    assert "--additional" in err
    assert "Consumed (1 meal, 4 items):" in _run(capsys, "nutrition", "day", "--date", "2026-10-02")[1]

    code, out, _ = _run(capsys, *BREAKFAST, "--additional")
    assert code == 0
    assert "Recorded meal 2026-10-02-breakfast-2." in out


def test_log_json_prints_the_persisted_meal(capsys: pytest.CaptureFixture[str]) -> None:
    _add_catalog(capsys)

    code, out, _ = _run(capsys, *BREAKFAST, "--json")

    assert code == 0
    meal = json.loads(out)
    assert meal["meal_id"] == "2026-10-02-breakfast-1"
    assert meal["original_text"] == (
        "structured entry breakfast 2026-10-02: chicken-breast 200 g; egg 2 count; hetbahn 1 pack; banana 1 piece"
    )
    assert meal["total"]["totals"]["calories_kcal"] == "750"
    assert meal["total"]["totals"]["fat_g"] is None


def test_empty_day_says_no_meals(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "nutrition", "day", "--date", "2026-10-03")

    assert code == 0
    assert "No meals recorded for this day." in out
    assert "incomplete" not in out
    payload = json.loads(_run(capsys, "nutrition", "day", "--date", "2026-10-03", "--json")[1])
    assert payload["meals"] == []
    assert payload["total"]["complete"] is False
    assert payload["total"]["item_count"] == 0


def test_text_output_is_ascii_apart_from_food_names(capsys: pytest.CaptureFixture[str]) -> None:
    _add_catalog(capsys)
    _run(capsys, *BREAKFAST)

    _, out, _ = _run(capsys, "nutrition", "day")

    for name in ("닭가슴살", "계란", "햇반", "바나나"):
        out = out.replace(name, "")
    assert out.isascii()


def test_data_lives_only_under_muscle50_home(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _add_catalog(capsys)

    assert (home / "db" / "muscle50.sqlite3").is_file()


def test_local_timezone_is_a_fixed_offset_without_a_tz_database() -> None:
    # The fixture replaces cli._local_timezone; check the real helper captured at import time.
    day = date(2026, 10, 2)
    zone = _REAL_LOCAL_TIMEZONE(day)
    assert isinstance(zone, timezone)
    assert zone.utcoffset(None) == datetime.combine(day, time(12)).astimezone().utcoffset()
