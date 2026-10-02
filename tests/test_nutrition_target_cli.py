"""`muscle50 nutrition target` / `nutrition status` over a temporary MUSCLE50_HOME.

All nutrition values and targets here are synthetic test numbers, not real food data or the
user's real targets. The production data directory is never touched.
"""

from __future__ import annotations

import json
from datetime import date, timedelta, timezone, tzinfo
from pathlib import Path

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

KST = timezone(timedelta(hours=9))

CATALOG = (
    ["--id", "chicken", "--name", "닭가슴살", "--per", "100", "g"]
    + ["--kcal", "110", "--protein", "18", "--carbs", "1", "--fat", "3"]
    + ["--source", "nutrition_label", "--accuracy", "exact"],
    ["--id", "egg", "--name", "계란", "--per", "1", "count"]
    + ["--kcal", "70", "--protein", "6", "--carbs", "0.5", "--fat", "5"]
    + ["--source", "user_provided", "--accuracy", "estimated"],
    ["--id", "rice", "--name", "햇반", "--per", "1", "pack"]
    + ["--kcal", "300", "--protein", "5", "--carbs", "68", "--fat", "unknown"]
    + ["--source", "nutrition_label", "--accuracy", "exact"],
)
# kcal 660, protein 53, carbs 71, fat: 16 from known items + rice unknown.
BREAKFAST = ["nutrition", "log", "--date", "2026-10-02", "--meal", "breakfast"] + [
    "--item",
    "chicken",
    "200",
    "g",
    "--item",
    "egg",
    "2",
    "count",
    "--item",
    "rice",
    "1",
    "pack",
]
# protein +126 (day 179), fat +21 (known 37).
LUNCH = ["nutrition", "log", "--date", "2026-10-02", "--meal", "lunch", "--item", "chicken", "700", "g"]


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


def _log_breakfast(capsys: pytest.CaptureFixture[str]) -> None:
    for food in CATALOG:
        _ok(capsys, "nutrition", "food", "add", *food)
    _ok(capsys, *BREAKFAST)


def _set_targets(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
    _ok(capsys, "nutrition", "target", "set", "protein", "--range", "170", "180")
    _ok(capsys, "nutrition", "target", "set", "fat", "--exact", "80")


# --- target set / show --------------------------------------------------------------------


def test_target_set_and_show(capsys: pytest.CaptureFixture[str]) -> None:
    out = _ok(capsys, "nutrition", "target", "set", "protein", "--range", "170", "180")
    assert out.startswith("protein target set.\n")

    _ok(capsys, "nutrition", "target", "set", "fat", "--exact", "80.5")
    out = _ok(capsys, "nutrition", "target", "show")

    assert out == (
        "Daily nutrition targets (the same targets apply to every date):\n"
        "  kcal          not set\n"
        "  Protein       170-180 g (range)\n"
        "  Carbohydrate  not set\n"
        "  Fat           80.5 g (exact)\n"
    )


def test_target_show_json_distinguishes_exact_range_and_unset(capsys: pytest.CaptureFixture[str]) -> None:
    _set_targets(capsys)

    payload = json.loads(_ok(capsys, "nutrition", "target", "show", "--json"))

    assert payload == {
        "targets": {
            "calories_kcal": {"kind": "exact", "value": "2400"},
            "protein_g": {"kind": "range", "minimum": "170", "maximum": "180"},
            "carbohydrate_g": {"kind": "unset"},
            "fat_g": {"kind": "exact", "value": "80"},
        }
    }


def test_unset_removes_only_that_target(capsys: pytest.CaptureFixture[str]) -> None:
    _set_targets(capsys)

    out = _ok(capsys, "nutrition", "target", "set", "fat", "--unset", "--json")

    targets = json.loads(out)["targets"]
    assert targets["fat_g"] == {"kind": "unset"}
    assert targets["protein_g"] == {"kind": "range", "minimum": "170", "maximum": "180"}


def test_no_targets_configured(capsys: pytest.CaptureFixture[str], targets_file: Path) -> None:
    out = _ok(capsys, "nutrition", "target", "show")

    assert "No targets set. See: muscle50 nutrition target set --help" in out
    assert {
        entry["kind"] for entry in json.loads(_ok(capsys, "nutrition", "target", "show", "--json"))["targets"].values()
    } == {"unset"}
    assert not targets_file.exists()


@pytest.mark.parametrize(
    ("argv", "code", "message"),
    [
        (["kcal", "--exact", "0"], 1, "--exact must be greater than 0 (to remove a target use --unset)"),
        (["kcal", "--exact", "-5"], 1, "--exact must be a plain non-negative number"),
        (["kcal", "--exact", "1e3"], 1, "--exact must be a plain non-negative number"),
        (["kcal", "--exact", "NaN"], 1, "--exact must be a plain non-negative number"),
        (["kcal", "--exact", "1,000"], 1, "--exact must be a plain non-negative number"),
        (["protein", "--range", "180", "170"], 1, "range minimum cannot exceed range maximum"),
        (["protein", "--range", "0", "180"], 1, "--range MIN must be greater than 0"),
        (["protein", "--range", "170", "abc"], 1, "--range MAX must be a plain non-negative number"),
        (["protein"], 2, "one of the arguments --exact --range --unset is required"),
        (["protein", "--exact", "175", "--unset"], 2, "not allowed with argument"),
        (["protein", "--exact", "175", "--range", "170", "180"], 2, "not allowed with argument"),
        (["protein", "--range", "170"], 2, "expected 2 arguments"),
        (["fiber", "--exact", "30"], 2, "invalid choice"),
    ],
)
def test_invalid_target_input_is_rejected_and_nothing_is_written(
    capsys: pytest.CaptureFixture[str], targets_file: Path, argv: list[str], code: int, message: str
) -> None:
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
    assert not targets_file.exists()


def test_rejected_input_keeps_existing_targets(capsys: pytest.CaptureFixture[str], targets_file: Path) -> None:
    _set_targets(capsys)
    before = targets_file.read_bytes()

    code, _, _ = _run(capsys, "nutrition", "target", "set", "protein", "--range", "180", "170")

    assert code == 1
    assert targets_file.read_bytes() == before


def test_malformed_target_file_is_reported_and_left_alone(
    capsys: pytest.CaptureFixture[str], targets_file: Path
) -> None:
    targets_file.parent.mkdir(parents=True)
    targets_file.write_text('{"schema_version": 1, "targets": {}}', encoding="utf-8")

    for argv in (
        ("nutrition", "target", "show"),
        ("nutrition", "status"),
        ("nutrition", "target", "set", "fat", "--exact", "80"),
    ):
        code, out, err = _run(capsys, *argv)
        assert code == 1
        assert out == ""
        assert err.startswith("오류: nutrition target file")
    assert targets_file.read_text(encoding="utf-8") == '{"schema_version": 1, "targets": {}}'


# --- status -------------------------------------------------------------------------------


def test_status_text_for_an_explicit_date(capsys: pytest.CaptureFixture[str]) -> None:
    _log_breakfast(capsys)
    _set_targets(capsys)

    out = _ok(capsys, "nutrition", "status", "--date", "2026-10-02")

    assert out == (
        "Nutrition status 2026-10-02 (UTC+09:00)\n"
        "Logged intake compared with the currently configured daily targets.\n"
        "\n"
        "Logged: 1 meal, 3 items\n"
        "  kcal          660 (estimated); target 2400 (exact): below target, 1740 to go\n"
        "  Protein       53 g (estimated); target 170-180 g (range): below range, 117 g to minimum, 127 g to maximum\n"
        "  Carbohydrate  71 g (estimated); no target\n"
        "  Fat           incomplete (known items only: 16 g (estimated)); target 80 g (exact): "
        "cannot tell yet (incomplete); remaining unknown\n"
        "Incomplete: no exact total or remaining amount, because an item has no value for:\n"
        "  fat: 2026-10-02-breakfast-1 item 3 햇반 (rice)\n"
        "Estimated: kcal, protein, carbohydrate, fat include values from facts marked estimated.\n"
    )


def test_status_defaults_to_today(capsys: pytest.CaptureFixture[str]) -> None:
    _log_breakfast(capsys)
    _set_targets(capsys)

    assert _ok(capsys, "nutrition", "status") == _ok(capsys, "nutrition", "status", "--date", "2026-10-02")
    assert _ok(capsys, "nutrition", "status", "--json") == _ok(
        capsys, "nutrition", "status", "--date", "2026-10-02", "--json"
    )


def test_status_within_range_and_proven_above_with_incomplete_data(capsys: pytest.CaptureFixture[str]) -> None:
    _log_breakfast(capsys)
    _ok(capsys, *LUNCH)
    _ok(capsys, "nutrition", "target", "set", "protein", "--range", "170", "180")
    _ok(capsys, "nutrition", "target", "set", "fat", "--exact", "30")

    out = _ok(capsys, "nutrition", "status")

    assert "Logged: 2 meals, 4 items" in out
    assert "  Protein       179 g (estimated); target 170-180 g (range): within range, 1 g left to maximum" in out
    assert (
        "  Fat           incomplete (known items only: 37 g (estimated)); target 30 g (exact): "
        "above target (the known items alone exceed it; exact excess unknown)"
    ) in out

    fat = json.loads(_ok(capsys, "nutrition", "status", "--json"))["nutrients"]["fat_g"]
    assert fat == {
        "target": {"kind": "exact", "value": "30"},
        "status": "above_target",
        "complete": False,
        "estimated": True,
        "consumed": None,
        "known_subtotal": "37",
        "remaining": None,
        "remaining_to_maximum": None,
        "excess": None,
        "missing_items": [{"meal_id": "2026-10-02-breakfast-1", "sequence": 3, "food_id": "rice", "food_name": "햇반"}],
    }


def test_status_json_is_exact_and_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    _log_breakfast(capsys)
    _ok(capsys, "nutrition", "log", "--meal", "snack", "--item", "chicken", "33.3", "g")
    _set_targets(capsys)

    first = _ok(capsys, "nutrition", "status", "--date", "2026-10-02", "--json")
    second = _ok(capsys, "nutrition", "status", "--date", "2026-10-02", "--json")

    assert first == second
    assert first.isascii()
    payload = json.loads(first)
    assert list(payload) == ["date", "timezone", "scope", "meal_count", "item_count", "nutrients"]
    assert (payload["date"], payload["timezone"], payload["meal_count"], payload["item_count"]) == (
        "2026-10-02",
        "+09:00",
        2,
        4,
    )
    assert list(payload["nutrients"]) == ["calories_kcal", "protein_g", "carbohydrate_g", "fat_g"]
    protein = payload["nutrients"]["protein_g"]
    # 53 + 33.3 g * 18 / 100 = 58.994, kept exactly.
    assert protein == {
        "target": {"kind": "range", "minimum": "170", "maximum": "180"},
        "status": "below_range",
        "complete": True,
        "estimated": True,
        "consumed": "58.994",
        "known_subtotal": "58.994",
        "remaining": "111.006",
        "remaining_to_maximum": "121.006",
        "excess": "0",
        "missing_items": [],
    }
    carbs = payload["nutrients"]["carbohydrate_g"]
    assert carbs["target"] == {"kind": "unset"}
    assert carbs["status"] == "no_target"
    assert (carbs["remaining"], carbs["excess"]) == (None, None)
    assert payload["nutrients"]["fat_g"]["status"] == "indeterminate"


def test_status_without_configured_targets(capsys: pytest.CaptureFixture[str], targets_file: Path) -> None:
    _log_breakfast(capsys)

    out = _ok(capsys, "nutrition", "status")

    assert "  Protein       53 g (estimated); no target" in out
    assert "No targets set. See: muscle50 nutrition target set --help" in out
    payload = json.loads(_ok(capsys, "nutrition", "status", "--json"))
    assert {entry["status"] for entry in payload["nutrients"].values()} == {"no_target"}
    assert not targets_file.exists()


def test_status_for_a_day_without_meals(capsys: pytest.CaptureFixture[str]) -> None:
    _set_targets(capsys)

    out = _ok(capsys, "nutrition", "status", "--date", "2026-10-03")

    assert "No meals recorded for this day." in out
    assert "  Protein       no items; target 170-180 g (range): no meals logged" in out
    assert "  Carbohydrate  no items; no target" in out
    protein = json.loads(_ok(capsys, "nutrition", "status", "--date", "2026-10-03", "--json"))["nutrients"]["protein_g"]
    assert protein["status"] == "no_intake_logged"
    assert (protein["consumed"], protein["known_subtotal"], protein["remaining"]) == (None, None, None)


def test_invalid_status_date_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(capsys, "nutrition", "status", "--date", "2026-13-01")

    assert code == 1
    assert err.startswith("오류: --date")


def test_status_text_is_ascii_apart_from_food_names(capsys: pytest.CaptureFixture[str]) -> None:
    _log_breakfast(capsys)
    _set_targets(capsys)

    out = _ok(capsys, "nutrition", "status")

    assert out.replace("햇반", "").isascii()


# --- existing commands --------------------------------------------------------------------


def test_targets_do_not_change_existing_nutrition_output(capsys: pytest.CaptureFixture[str]) -> None:
    _log_breakfast(capsys)
    before = [
        _ok(capsys, "nutrition", "day", "--json"),
        _ok(capsys, "nutrition", "day"),
        _ok(capsys, "nutrition", "food", "list", "--json"),
    ]

    _set_targets(capsys)

    after = [
        _ok(capsys, "nutrition", "day", "--json"),
        _ok(capsys, "nutrition", "day"),
        _ok(capsys, "nutrition", "food", "list", "--json"),
    ]
    assert after == before
    assert json.loads(after[0])["scope"] == "intake_only"


def test_targets_live_only_under_muscle50_home(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _set_targets(capsys)

    assert (home / "config" / "nutrition_targets.json").is_file()
    assert sorted(path.name for path in (home / "config").iterdir()) == ["nutrition_targets.json"]


@pytest.mark.parametrize(
    ("target", "shown", "exact"), [("53.04", "<0.1 g", "0.04"), ("53.05", "<0.1 g", "0.05"), ("53.06", "0.1 g", "0.06")]
)
def test_tiny_remaining_amount_is_not_displayed_as_zero(
    capsys: pytest.CaptureFixture[str], target: str, shown: str, exact: str
) -> None:
    # Breakfast protein is 53 g; 0.05 rounds half-even to 0.0, the boundary case.
    _log_breakfast(capsys)
    _ok(capsys, "nutrition", "target", "set", "protein", "--exact", target)

    out = _ok(capsys, "nutrition", "status")

    assert f"target {target} g (exact): below target, {shown} to go" in out
    assert json.loads(_ok(capsys, "nutrition", "status", "--json"))["nutrients"]["protein_g"]["remaining"] == exact
