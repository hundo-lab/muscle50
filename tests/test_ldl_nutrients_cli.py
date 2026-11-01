"""LDL Nutrients v1 through the CLI, over a temporary MUSCLE50_HOME.

All foods, amounts and targets are synthetic test numbers, not real food data or the user's
targets. The production data directory is never touched and Garmin is never contacted.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

KST = timezone(timedelta(hours=9))
DAY = "2026-11-05"
_LABEL = ("--source", "nutrition_label", "--accuracy", "exact")
OATS: tuple[str, ...] = ("--id", "syn-oats", "--name", "SynOats", "--per", "40", "g", "--kcal", "150", "--protein", "5")
OATS += ("--carbs", "27", "--fat", "3", "--satfat", "0.5", "--fiber", "4", *_LABEL)
RICE: tuple[str, ...] = (
    "--id",
    "syn-rice",
    "--name",
    "SynRice",
    "--per",
    "1",
    "pack",
    "--kcal",
    "300",
    "--protein",
    "5",
)
RICE += ("--carbs", "66", "--fat", "1", "--fiber", "1.2", *_LABEL)
BUTTER: tuple[str, ...] = (
    "--id",
    "syn-butter",
    "--name",
    "SynButter",
    "--per",
    "10",
    "g",
    "--kcal",
    "70",
    "--protein",
    "0",
)
BUTTER += ("--carbs", "0", "--fat", "8", "--satfat", "5", "--fiber", "0", *_LABEL)
PLAIN: tuple[str, ...] = (
    "--id",
    "syn-plain",
    "--name",
    "SynPlain",
    "--per",
    "100",
    "g",
    "--kcal",
    "110",
    "--protein",
    "18",
)
PLAIN += ("--carbs", "1", "--fat", "3", *_LABEL)
BREAKFAST: tuple[str, ...] = ("nutrition", "log", "--date", DAY, "--meal", "breakfast", "--item", "syn-oats", "80", "g")
BREAKFAST += ("--item", "syn-rice", "1", "pack")
LUNCH: tuple[str, ...] = ("nutrition", "log", "--date", DAY, "--meal", "lunch", "--item", "syn-butter", "40", "g")
DINNER: tuple[str, ...] = (
    "nutrition",
    "log",
    "--date",
    DAY,
    "--meal",
    "dinner",
    "--general",
    "--general-note",
    "SynBBQ",
)
DINNER += ("--general-estimate", "language_estimate:kcal=800-1100,fat=50-70,satfat=15-25")
GENERAL = "일반식"
FORBIDDEN = re.compile(r"LDL-C|mg/dL|risk|warning|danger|diagnos(?!is\))", re.IGNORECASE)


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
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 11, 5))
    return root


@pytest.fixture
def targets_file(home: Path) -> Path:
    return home / "config" / "nutrition_targets.json"


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return out


def _json(capsys: pytest.CaptureFixture[str], *argv: str) -> Any:
    out = _ok(capsys, *argv)
    document = json.loads(out)
    assert out == json.dumps(document, indent=2) + "\n"
    return document


def _food(capsys: pytest.CaptureFixture[str], *argv: str) -> None:
    _ok(capsys, "nutrition", "food", "add", *argv)


def _day_setup(capsys: pytest.CaptureFixture[str]) -> None:
    for food in (OATS, RICE, BUTTER):
        _food(capsys, *food)
    for meal in (BREAKFAST, LUNCH, DINNER):
        _ok(capsys, *meal)


def _rows(home: Path) -> dict[str, list[tuple[object, ...]]]:
    database = home / "db" / "muscle50.sqlite3"
    if not database.exists():
        return {}
    with sqlite3.connect(database) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall(), key=repr) for table in tables}


def _ascii_apart_from_names(text: str) -> None:
    assert text.replace(GENERAL, "").isascii()


# --- catalog (AC1) -------------------------------------------------------------------------------


def test_food_add_stores_and_shows_saturated_fat_and_fiber(capsys: pytest.CaptureFixture[str]) -> None:
    out = _ok(capsys, "nutrition", "food", "add", *OATS)
    assert "    per 40 g: kcal 150 | P 5 g | C 27 g | F 3 g  [nutrition_label/exact]\n" in out
    assert "    LDL per 40 g: sat fat 0.5 g | fiber 4 g\n    reference: " in out
    document = _json(capsys, "nutrition", "food", "show", "syn-oats", "--json")
    fact = document["facts"][0]
    assert list(fact)[-2:] == ["active", "ldl_nutrients"]
    assert fact["ldl_nutrients"] == {
        "saturated_fat_g": {"value": "0.5", "minimum": None, "maximum": None},
        "fiber_g": {"value": "4", "minimum": None, "maximum": None},
    }
    _food(capsys, *RICE)
    listed = _ok(capsys, "nutrition", "food", "list")
    assert "    LDL per 1 pack: sat fat unknown | fiber 1.2 g" in listed


def test_without_the_new_flags_nothing_new_is_stored_or_shown(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    out = _ok(capsys, "nutrition", "food", "add", *PLAIN)
    assert "LDL" not in out
    unknown = _ok(capsys, "nutrition", "food", "add", *RICE[:-6], "--fiber", "unknown", *_LABEL)
    assert "LDL" not in unknown
    for food in ("syn-plain", "syn-rice"):
        document = _json(capsys, "nutrition", "food", "show", food, "--json")
        assert "ldl_nutrients" not in document["facts"][0]
    assert _rows(home)["nutrition_fact_optional_nutrients"] == []


def test_fact_add_with_the_same_four_values_and_saturated_fat_is_a_new_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _food(capsys, *RICE)
    same = ("--per", "1", "pack", "--kcal", "300", "--protein", "5", "--carbs", "66", "--fat", "1")
    out = _ok(
        capsys, "nutrition", "food", "fact", "add", "syn-rice", *same, "--fiber", "1.2", "--satfat", "0.3", *_LABEL
    )
    assert "Added fact food:syn-rice:2 to syn-rice; it replaces food:syn-rice:1" in out
    assert "    LDL per 1 pack: sat fat 0.3 g | fiber 1.2 g" in out


# --- refusals (AC2) ------------------------------------------------------------------------------

_RICE_FACT = ("--per", "1", "pack", "--kcal", "300", "--protein", "5", "--carbs", "66", "--fat", "1", *_LABEL)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("nutrition", "food", "add", *PLAIN, "--satfat", "-1"), "--satfat must be a plain non-negative number"),
        (("nutrition", "food", "add", *PLAIN, "--fiber", "1e3"), "--fiber must be a plain non-negative number"),
        (("nutrition", "food", "add", *PLAIN, "--satfat", "3.5"), "--satfat 3.5 is more than --fat 3"),
        (
            ("nutrition", "food", "add", "--id", "syn-x", "--name", "SynX", "--per", "1", "g")
            + ("--kcal", "unknown", "--protein", "unknown", "--carbs", "unknown", "--fat", "unknown")
            + ("--satfat", "1", "--fiber", "2", *_LABEL),
            "at least one of kcal/protein/carbohydrate/fat must be a number",
        ),
        (
            ("nutrition", "food", "fact", "add", "syn-rice", *_RICE_FACT),
            "has a value for fiber; a new version must give a number for it too",
        ),
        (
            ("nutrition", "food", "fact", "add", "syn-rice", *_RICE_FACT, "--fiber", "unknown"),
            "has a value for fiber; a new version must give a number for it too",
        ),
        (
            ("nutrition", "log", "--meal", "dinner", "--general")
            + ("--general-estimate", "language_estimate:kcal=800-900,satfat=25-15"),
            "satfat minimum 25 is above its maximum 15",
        ),
        (
            ("nutrition", "log", "--meal", "dinner", "--general", "--general-estimate", "language_estimate:satfat=1-2"),
            "satfat and fiber cannot be the only ranges",
        ),
        (
            ("nutrition", "log", "--meal", "dinner", "--general")
            + ("--general-estimate", "language_estimate:fat=10-20,satfat=21-30"),
            "cannot be more than total fat",
        ),
        (
            ("nutrition", "log", "--meal", "dinner", "--general")
            + ("--general-estimate", "language_estimate:kcal=1-2,fiber=1-2,fiber=2-3"),
            "lists fiber twice",
        ),
    ],
)
def test_invalid_values_are_refused_and_nothing_is_written(
    capsys: pytest.CaptureFixture[str], home: Path, argv: tuple[str, ...], message: str
) -> None:
    _food(capsys, *RICE)
    before = _rows(home)
    code, out, err = _run(capsys, *argv)
    assert (code, out) == (1, "")
    assert err.startswith("오류: ") and message in err
    assert "Nothing was changed" in err or "nothing was changed" in err or "must be a" in err
    assert _rows(home) == before


# --- logging, day and meal show (AC3-AC5) -----------------------------------------------------------


def test_day_shows_item_meal_and_day_amounts_and_the_unknown_items(capsys: pytest.CaptureFixture[str]) -> None:
    _day_setup(capsys)
    out = _ok(capsys, "nutrition", "day", "--date", DAY)
    lines = out.splitlines()
    assert lines[lines.index("  1. SynOats (syn-oats) 80 g: kcal 300 | P 10 g | C 54 g | F 6 g") + 2] == (
        "     LDL: sat fat 1 g | fiber 8 g"
    )
    assert "     LDL: sat fat unknown | fiber 1.2 g" in lines
    assert "  LDL nutrients: sat fat incomplete (known items only: 1 g) | fiber 9.2 g" in lines
    assert "  LDL nutrients: sat fat 20 g | fiber 0 g" in lines
    assert "     LDL: sat fat estimated 15-25 g | fiber unknown" in lines
    assert lines[-6:] == [
        "",
        "LDL-related nutrients (consumed; compare: muscle50 nutrition status):",
        "  Saturated fat incomplete (known items only: 21 g (estimated))",
        "  Fiber         incomplete (known items only: 9.2 g)",
        (
            "  Unknown, not 0: saturated fat: 2026-11-05-breakfast-1 item 2 SynRice (syn-rice); "
            f"2026-11-05-dinner-1 item 1 {GENERAL} (general-meal)"
        ),
        f"  Unknown, not 0: fiber: 2026-11-05-dinner-1 item 1 {GENERAL} (general-meal)",
    ]
    # Unknown is never printed as 0: the only "0 g" amounts are the butter's own zero fiber.
    assert [line for line in lines if " 0 g" in line and "LDL" in line] == ["     LDL: sat fat 20 g | fiber 0 g"] + [
        "  LDL nutrients: sat fat 20 g | fiber 0 g"
    ]
    _ascii_apart_from_names(out)


def test_day_json_appends_the_new_keys_last(capsys: pytest.CaptureFixture[str]) -> None:
    _day_setup(capsys)
    document = _json(capsys, "nutrition", "day", "--date", DAY, "--json")
    assert list(document)[-2:] == ["total", "ldl_nutrients"]
    assert document["ldl_nutrients"]["saturated_fat_g"] == {
        "complete": False,
        "estimated": True,
        "consumed": None,
        "known_subtotal": "21.0",
        "missing_items": [
            {"meal_id": "2026-11-05-breakfast-1", "sequence": 2, "food_id": "syn-rice", "food_name": "SynRice"},
            {"meal_id": "2026-11-05-dinner-1", "sequence": 1, "food_id": "general-meal", "food_name": GENERAL},
        ],
    }
    breakfast, lunch, dinner = document["meals"]
    assert list(breakfast)[-2:] == ["total", "ldl_nutrients"]
    assert lunch["ldl_nutrients"]["fiber_g"] == {
        "complete": True,
        "estimated": False,
        "consumed": "0",
        "known_subtotal": "0",
        "missing_items": [],
    }
    oats = breakfast["items"][0]
    assert list(oats)[-1] == "ldl_nutrients"
    assert oats["ldl_nutrients"]["saturated_fat_g"] == {
        "value": "1.0",
        "minimum": None,
        "maximum": None,
        "fact_id": "2026-11-05-breakfast-1:1:food:syn-oats:1",
        "source_type": "nutrition_label",
        "accuracy": "exact",
    }
    assert list(oats["facts"][0])[-1] == "ldl_nutrients"
    general = dinner["items"][0]
    assert list(general)[-3:] == ["general_meal", "note", "ldl_nutrients"]
    assert general["ldl_nutrients"] == {
        "saturated_fat_g": {
            "value": None,
            "minimum": "15",
            "maximum": "25",
            "fact_id": "2026-11-05-dinner-1:1:estimate",
            "source_type": "language_estimate",
            "accuracy": "estimated",
        },
        "fiber_g": None,
    }
    # The four nutrients' documents are unchanged: the estimate-only item keeps them unknown.
    assert dinner["total"]["totals"] == {
        "calories_kcal": None,
        "protein_g": None,
        "carbohydrate_g": None,
        "fat_g": None,
    }
    assert "satfat=15-25" in dinner["original_text"]


def test_meal_show_text_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    _day_setup(capsys)
    out = _ok(capsys, "nutrition", "meal", "show", "2026-11-05-breakfast-1")
    assert out.splitlines()[-1] == "  LDL nutrients: sat fat incomplete (known items only: 1 g) | fiber 9.2 g"
    document = _json(capsys, "nutrition", "meal", "show", "2026-11-05-breakfast-1", "--json")
    assert list(document)[-1] == "ldl_nutrients"


def test_a_corrected_meal_keeps_the_new_key_last(capsys: pytest.CaptureFixture[str]) -> None:
    _day_setup(capsys)
    _ok(capsys, "nutrition", "meal", "edit", "2026-11-05-lunch-1", "--time", "12:30")
    document = _json(capsys, "nutrition", "meal", "show", "2026-11-05-lunch-1", "--json")
    assert list(document)[-2:] == ["revisions", "ldl_nutrients"]


def test_logged_meals_keep_their_snapshot_and_repeat_uses_the_current_catalog(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _food(capsys, *BUTTER)
    _ok(capsys, *LUNCH)
    newer = ("--per", "10", "g", "--kcal", "70", "--protein", "0", "--carbs", "0", "--fat", "8", "--satfat", "6")
    _ok(capsys, "nutrition", "food", "fact", "add", "syn-butter", *newer, "--fiber", "0", *_LABEL)
    assert "  LDL nutrients: sat fat 20 g | fiber 0 g" in _ok(capsys, "nutrition", "meal", "show", "2026-11-05-lunch-1")
    repeated = _ok(capsys, "nutrition", "repeat", "2026-11-05-lunch-1", "--additional")
    assert "  LDL nutrients: sat fat 24 g | fiber 0 g" in repeated


# --- targets (AC6) -----------------------------------------------------------------------------------


def test_target_set_and_show_with_ldl_targets(capsys: pytest.CaptureFixture[str], targets_file: Path) -> None:
    out = _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "7", "--meal-note-percent", "50")
    assert out.splitlines() == [
        "satfat target set.",
        "Daily nutrition targets (the same targets apply to every date):",
        "  kcal          not set",
        "  Protein       not set",
        "  Carbohydrate  not set",
        "  Fat           not set",
        (
            "  Saturated fat < 7 % of energy [user setting; LDL-05 reference < 7 %]; meal note at 50 % of the day "
            "limit [user setting]"
        ),
        "  Fiber         not set",
    ]
    _ok(capsys, "nutrition", "target", "set", "fiber", "--minimum", "25")
    assert json.loads(targets_file.read_text(encoding="utf-8")) == {
        "schema_version": 2,
        "targets": {
            "calories_kcal": {"kind": "unset"},
            "protein_g": {"kind": "unset"},
            "carbohydrate_g": {"kind": "unset"},
            "fat_g": {"kind": "unset"},
            "saturated_fat_g": {"kind": "max_energy_percent", "value": "7", "meal_note_percent": "50"},
            "fiber_g": {"kind": "minimum", "value": "25"},
        },
    }
    shown = _json(capsys, "nutrition", "target", "show", "--json")
    assert list(shown["targets"])[-2:] == ["saturated_fat_g", "fiber_g"]
    assert "  Fiber         >= 25 g/day [user setting; LDL-08 reference >= 25 g]" in _ok(
        capsys, "nutrition", "target", "show"
    )


def test_unsetting_both_ldl_targets_writes_schema_1_again(
    capsys: pytest.CaptureFixture[str], targets_file: Path
) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
    schema_1 = targets_file.read_bytes()
    show_before = _ok(capsys, "nutrition", "target", "show", "--json")
    _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "7")
    _ok(capsys, "nutrition", "target", "set", "fiber", "--minimum", "25")
    _ok(capsys, "nutrition", "target", "set", "satfat", "--unset")
    assert json.loads(targets_file.read_text(encoding="utf-8"))["schema_version"] == 2
    _ok(capsys, "nutrition", "target", "set", "fiber", "--unset")
    assert targets_file.read_bytes() == schema_1
    assert _ok(capsys, "nutrition", "target", "show", "--json") == show_before


def test_esc_general_population_line_only_for_ten_percent(capsys: pytest.CaptureFixture[str]) -> None:
    out = _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "10")
    assert "    LDL-05 also gives < 10 % for the general population (ESC) [LDL-05]" in out
    seven = _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "7")
    assert "ESC" not in seven


@pytest.mark.parametrize(
    ("argv", "code", "message"),
    [
        (["satfat", "--max-energy-percent", "0"], 1, "--max-energy-percent must be greater than 0"),
        (["satfat", "--max-energy-percent", "-1"], 1, "--max-energy-percent must be a plain non-negative number"),
        (["satfat", "--max-energy-percent", "100"], 1, "--max-energy-percent must be below 100"),
        (["satfat", "--max-energy-percent", "abc"], 1, "--max-energy-percent must be a plain non-negative number"),
        (["satfat", "--max-energy-percent", "7", "--meal-note-percent", "0"], 1, "--meal-note-percent must be"),
        (["satfat", "--unset", "--meal-note-percent", "50"], 1, "--meal-note-percent goes with satfat"),
        (["fiber", "--minimum", "25", "--meal-note-percent", "50"], 1, "--meal-note-percent goes with satfat"),
        (["kcal", "--exact", "2400", "--meal-note-percent", "50"], 1, "--meal-note-percent goes with satfat"),
        (["fiber", "--minimum", "0"], 1, "--minimum must be greater than 0"),
        (["fiber", "--minimum", "-25"], 1, "--minimum must be a plain non-negative number"),
        (["fiber", "--exact", "25"], 1, "fiber takes --minimum G or --unset. Nothing was changed."),
        (["fiber", "--max-energy-percent", "7"], 1, "fiber takes --minimum G or --unset"),
        (["satfat", "--range", "5", "7"], 1, "satfat takes --max-energy-percent P or --unset"),
        (["satfat", "--minimum", "7"], 1, "satfat takes --max-energy-percent P or --unset"),
        (["protein", "--minimum", "100"], 1, "protein takes --exact N, --range MIN MAX or --unset"),
        (["kcal", "--max-energy-percent", "7"], 1, "kcal takes --exact N, --range MIN MAX or --unset"),
        (["satfat"], 2, "one of the arguments --max-energy-percent --unset is required"),
        (["fiber"], 2, "one of the arguments --minimum --unset is required"),
        (["protein"], 2, "one of the arguments --exact --range --unset is required"),
        (["satfat", "--max-energy-percent", "7", "--unset"], 2, "not allowed with argument"),
    ],
)
def test_invalid_ldl_target_input_is_refused_and_nothing_is_written(
    capsys: pytest.CaptureFixture[str], targets_file: Path, argv: list[str], code: int, message: str
) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
    before = targets_file.read_bytes()
    if code == 2:
        with pytest.raises(SystemExit) as raised:
            main(["nutrition", "target", "set", *argv])
        assert raised.value.code == 2
        err = capsys.readouterr().err
    else:
        actual, _, err = _run(capsys, "nutrition", "target", "set", *argv)
        assert actual == 1
        assert err.startswith("오류: ")
    assert message in err
    assert targets_file.read_bytes() == before


def test_a_kind_refusal_creates_nothing_in_a_fresh_home(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    code, _, err = _run(capsys, "nutrition", "target", "set", "fiber", "--exact", "25")
    assert code == 1 and "fiber takes --minimum G or --unset" in err
    assert not home.exists()


# --- status (AC7-AC10) ---------------------------------------------------------------------------------


def _targets(capsys: pytest.CaptureFixture[str], kcal: tuple[str, ...] = ("--exact", "2400")) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", *kcal)
    _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "7", "--meal-note-percent", "50")
    _ok(capsys, "nutrition", "target", "set", "fiber", "--minimum", "25")


STATUS_BLOCK = [
    "",
    "LDL-related nutrients (your targets; advice only, not a diagnosis):",
    (
        "  Saturated fat incomplete (known items only: 21 g (estimated)); limit < 7 % of energy "
        "[user setting; LDL-05 reference < 7 %]"
    ),
    (
        "                = under 18.7 g at your kcal target 2400 [design: 9 kcal/g]: above limit (the known items "
        "alone reach it)"
    ),
    (
        "  Fiber         incomplete (known items only: 9.2 g); target >= 25 g/day [user setting; LDL-08 reference "
        ">= 25 g]: cannot tell yet (incomplete)"
    ),
    "    foods with fiber: oats, mixed grains, legumes [LDL-08; advice only]",
    "    LDL diet pattern also uses soy/tofu protein and nuts [LDL-11; advice only]",
    (
        "  Unknown, not 0: saturated fat: 2026-11-05-breakfast-1 item 2 SynRice (syn-rice); "
        f"2026-11-05-dinner-1 item 1 {GENERAL} (general-meal)"
    ),
    f"  Unknown, not 0: fiber: 2026-11-05-dinner-1 item 1 {GENERAL} (general-meal)",
    (
        "  Meal note: 2026-11-05-lunch-1 saturated fat 20 g = 107.1 % of the day limit 18.7 g, at or above your "
        "setting 50 % [user setting; advice only]"
    ),
]


def test_status_block_text(capsys: pytest.CaptureFixture[str]) -> None:
    _day_setup(capsys)
    _targets(capsys)
    out = _ok(capsys, "nutrition", "status", "--date", DAY)
    lines = out.splitlines()
    assert lines[-len(STATUS_BLOCK) :] == STATUS_BLOCK
    assert "No targets set" not in out
    _ascii_apart_from_names(out)
    assert FORBIDDEN.search(out) is None


def test_every_ldl_threshold_line_carries_its_evidence_tag(capsys: pytest.CaptureFixture[str]) -> None:
    _day_setup(capsys)
    _targets(capsys, ("--range", "2400", "2600"))
    _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "10", "--meal-note-percent", "50")
    texts = [
        _ok(capsys, "nutrition", "status", "--date", DAY),
        _ok(capsys, "nutrition", "target", "show"),
    ]
    block = [line for text in texts for line in text.splitlines() if "LDL" in text]
    threshold = re.compile(r"limit|target >=|under |Meal note|foods with|pattern|energy share|reference|% of")
    tagged = [line for line in block if threshold.search(line) and ("Saturated" in line or line.startswith(" "))]
    assert tagged
    for line in tagged:
        if line.startswith(("  kcal", "  Protein", "  Carbohydrate", "  Fat ")):
            continue
        assert re.search(r"\[(user setting|design|LDL-0[58]|LDL-11)[^\]]*\]", line), line
    for text in texts:
        assert FORBIDDEN.search(text) is None


def test_status_json_appends_ldl_nutrients_last(capsys: pytest.CaptureFixture[str]) -> None:
    _day_setup(capsys)
    _targets(capsys)
    first = _ok(capsys, "nutrition", "status", "--date", DAY, "--json")
    assert _ok(capsys, "nutrition", "status", "--date", DAY, "--json") == first
    document = json.loads(first)
    assert first == json.dumps(document, indent=2) + "\n"
    assert list(document)[-2:] == ["nutrients", "ldl_nutrients"]
    ldl = document["ldl_nutrients"]
    assert list(ldl) == ["advice_only", "saturated_fat_g", "fiber_g", "meal_notes"]
    assert ldl["advice_only"] is True
    saturated = ldl["saturated_fat_g"]
    assert saturated["target"] == {
        "kind": "max_energy_percent",
        "value": "7",
        "meal_note_percent": "50",
        "source": "user_setting",
        "reference": {"id": "LDL-05", "value": "7"},
        "reference_notes": [],
    }
    assert saturated["limit_g"] == {"low": "18.66666666666666666666666667", "high": "18.66666666666666666666666667"}
    assert saturated["limit_basis"] == {
        "calories_kcal_target": {"kind": "exact", "value": "2400"},
        "kcal_per_g": "9",
        "evidence": ["design"],
    }
    assert {key: saturated[key] for key in ("status", "complete", "consumed", "known_subtotal", "excess")} == {
        "status": "above_limit",
        "complete": False,
        "consumed": None,
        "known_subtotal": "21.0",
        "excess": None,
    }
    fiber = ldl["fiber_g"]
    assert fiber["target"] == {
        "kind": "minimum",
        "value": "25",
        "source": "user_setting",
        "reference": {"id": "LDL-08", "value": "25"},
    }
    assert (fiber["status"], fiber["remaining"]) == ("indeterminate", None)
    assert fiber["advice"] == [
        {"code": "fiber_foods", "evidence": ["LDL-08"]},
        {"code": "ldl_diet_pattern", "evidence": ["LDL-11"]},
    ]
    assert ldl["meal_notes"] == [
        {
            "meal_id": "2026-11-05-lunch-1",
            "code": "high_saturated_fat",
            "saturated_fat_g": "20",
            "share_of_day_limit": "1.071428571428571428571428571",
            "threshold": {"kind": "user_setting", "percent": "50"},
        }
    ]
    assert first.isascii()


def test_complete_day_within_limit_with_logged_energy_share_and_fiber_reached(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _food(capsys, *OATS)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "breakfast", "--item", "syn-oats", "80", "g")
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "1800")
    _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "7")
    _ok(capsys, "nutrition", "target", "set", "fiber", "--minimum", "8")
    lines = _ok(capsys, "nutrition", "status", "--date", DAY).splitlines()
    assert lines[-5:] == [
        "LDL-related nutrients (your targets; advice only, not a diagnosis):",
        "  Saturated fat 1 g; limit < 7 % of energy [user setting; LDL-05 reference < 7 %]",
        "                = under 14 g at your kcal target 1800 [design: 9 kcal/g]: within limit, 13 g below it",
        "    logged energy share: 3 % (info only, not used for the status) [LDL-05; design: 9 kcal/g]",
        "  Fiber         8 g; target >= 8 g/day [user setting; LDL-08 reference >= 25 g]: target reached",
    ]
    document = _json(capsys, "nutrition", "status", "--date", DAY, "--json")["ldl_nutrients"]
    assert document["saturated_fat_g"]["logged_energy_percent"] == "3.0"
    assert document["fiber_g"]["advice"] == []
    assert document["meal_notes"] == []


def test_kcal_range_between_limits_and_no_kcal_target(capsys: pytest.CaptureFixture[str]) -> None:
    _food(capsys, *BUTTER)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "lunch", "--item", "syn-butter", "30", "g")
    _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "7")
    no_kcal = _ok(capsys, "nutrition", "status", "--date", DAY).splitlines()
    assert no_kcal[-3:] == [
        "  Saturated fat 15 g; limit < 7 % of energy [user setting; LDL-05 reference < 7 %]",
        ("                = no gram limit without a kcal target (muscle50 nutrition target set kcal ...): not judged"),
        "  Fiber         0 g; no target",
    ]
    assert (
        _json(capsys, "nutrition", "status", "--date", DAY, "--json")["ldl_nutrients"]["saturated_fat_g"]["status"]
        == "no_kcal_target"
    )
    _ok(capsys, "nutrition", "target", "set", "kcal", "--range", "1800", "2700")
    lines = _ok(capsys, "nutrition", "status", "--date", DAY).splitlines()
    assert lines[-3] == (
        "                = under 14-21 g at your kcal target 1800-2700 (range) [design: 9 kcal/g]: between the "
        "limits of your kcal range (14-21 g): depends on where in your kcal range you end"
    )


def test_status_without_ldl_targets_shows_the_block_only_with_data(
    capsys: pytest.CaptureFixture[str], home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A food with saturated fat that was not eaten changes nothing (D5).
    _food(capsys, *PLAIN)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "lunch", "--item", "syn-plain", "100", "g")
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
    with_food = [
        _ok(capsys, "nutrition", *command)
        for command in (("day", "--date", DAY), ("day", "--date", DAY, "--json"), ("status", "--date", DAY))
    ]
    _food(capsys, *OATS)
    after = [
        _ok(capsys, "nutrition", *command)
        for command in (("day", "--date", DAY), ("day", "--date", DAY, "--json"), ("status", "--date", DAY))
    ]
    assert after == with_food
    assert "LDL" not in "".join(after)
    assert "ldl_nutrients" not in _ok(capsys, "nutrition", "status", "--date", DAY, "--json")
    _ok(capsys, "nutrition", "target", "set", "fiber", "--minimum", "25")
    status = _ok(capsys, "nutrition", "status", "--date", DAY)
    lines = status.splitlines()
    start = lines.index("LDL-related nutrients (your targets; advice only, not a diagnosis):")
    assert lines[start + 1 : start + 4] == [
        "  Saturated fat incomplete (no item has a value); no target",
        (
            "  Fiber         incomplete (no item has a value); target >= 25 g/day [user setting; LDL-08 reference "
            ">= 25 g]: cannot tell yet (incomplete)"
        ),
        "    foods with fiber: oats, mixed grains, legumes [LDL-08; advice only]",
    ]
    assert lines[-2:] == [
        "  Unknown, not 0: saturated fat: 2026-11-05-lunch-1 item 1 SynPlain (syn-plain)",
        "  Unknown, not 0: fiber: 2026-11-05-lunch-1 item 1 SynPlain (syn-plain)",
    ]


def test_no_command_but_target_set_changes_the_targets_file(
    capsys: pytest.CaptureFixture[str], targets_file: Path
) -> None:
    _targets(capsys)
    before = targets_file.read_bytes()
    _day_setup(capsys)
    for command in (
        ("nutrition", "status", "--date", DAY),
        ("nutrition", "status", "--date", DAY, "--json"),
        ("nutrition", "day", "--date", DAY),
        ("nutrition", "target", "show", "--json"),
        ("nutrition", "meal", "show", "2026-11-05-lunch-1"),
        ("recommend", "--date", DAY, "--json"),
    ):
        _ok(capsys, *command)
    assert targets_file.read_bytes() == before


def test_recommend_is_unchanged_by_ldl_data_and_targets(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def recommend_outputs(oats: tuple[str, ...], *, ldl_targets: bool) -> list[str]:
        _food(capsys, *oats)
        _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "breakfast", "--item", "syn-oats", "80", "g")
        _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
        if ldl_targets:
            _ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "7", "--meal-note-percent", "1")
            _ok(capsys, "nutrition", "target", "set", "fiber", "--minimum", "25")
        return [_ok(capsys, "recommend", "--date", DAY, "--json"), _ok(capsys, "recommend", "--date", DAY)]

    without_flags = tuple(arg for arg in OATS if arg not in ("--satfat", "0.5", "--fiber", "4"))
    plain = recommend_outputs(without_flags, ldl_targets=False)
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "with-ldl"))
    assert recommend_outputs(OATS, ldl_targets=True) == plain
