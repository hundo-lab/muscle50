"""`muscle50 inbody trend` end to end, plus the neighbour outputs it must leave byte-identical (AC9)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import inbody_trend_builders as inbody
import pytest
import sync_coverage_builders as builders

import muscle50.cli as cli
from muscle50.application.inbody_trend import ShowBodyCompositionTrend
from muscle50.cli import build_parser, main
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.sqlite.body_composition_reader import BodyCompositionReadError, SqliteBodyCompositionReader

SAMSUNG_FIXTURE = Path(__file__).parent / "fixtures" / "inbody" / "synthetic_samsung_health_export_v1.json"
MIGRATIONS_DIR = Path(__file__).parents[1] / "src" / "muscle50" / "infrastructure" / "sqlite" / "migrations"
TODAY = date(2026, 10, 5)
NO_TABLE = (
    "오류: muscle50 database has no InBody measurement table (body_composition_measurements, added by migration 7); "
    'run any muscle50 command that writes, for example "muscle50 nutrition food list", once to migrate it\n'
)
FORMAT_ERROR = "오류: --from/--to는 YYYY-MM-DD 형식이어야 합니다.\n"
ORDER_ERROR = "오류: --from은 --to보다 이후일 수 없습니다.\n"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: builders.DAILY_TODAY)
    return root


@pytest.fixture
def trend_home(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    return home


def _out(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code = main(list(argv))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert captured.err == ""
    return captured.out


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _no_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_today", lambda: pytest.fail("--to is the reference date; today must not be read"))


def _database(root: Path, *rows: Any) -> Path:
    database = inbody.migrated_database(root)
    inbody.save_measurements(database, rows)
    return database


def _lines(capsys: pytest.CaptureFixture[str], *argv: str) -> list[str]:
    return _out(capsys, "inbody", "trend", *argv).splitlines()


# --- AC9: neighbours stay byte-identical (goldens captured before this feature) ---------------


@pytest.mark.parametrize(
    ("flags", "name"), [((), "inbody_sync.txt"), (("--show-values",), "inbody_sync_show_values.txt")]
)
def test_inbody_sync_output_equals_the_golden(
    home: Path, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...], name: str
) -> None:
    assert _out(capsys, "inbody", "sync", "--file", str(SAMSUNG_FIXTURE), *flags) == inbody.golden(name)


def test_recommend_and_analytics_ignore_inbody_rows(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = builders.build_recommend_database(home)
    inbody.save_measurements(database, inbody.NEIGHBOUR_ROWS)

    text = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE)
    document = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE, "--json")
    snapshot = _out(capsys, "analytics", "snapshot", "--date", builders.RECOMMEND_DATE, "--json")

    assert text == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.txt")
    assert document == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.json")
    assert snapshot == inbody.golden(f"analytics_snapshot_{builders.RECOMMEND_DATE}.json")


# --- parser ----------------------------------------------------------------------------------


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["inbody", "trend"])

    assert (args.command, args.inbody_command) == ("inbody", "trend")
    assert (args.from_date, args.to_date, args.json) == (None, None, False)
    ranged = build_parser().parse_args(["inbody", "trend", "--from", "2026-07-01", "--to", "2026-10-05", "--json"])
    assert (ranged.from_date, ranged.to_date, ranged.json) == ("2026-07-01", "2026-10-05", True)


# --- AC1 / AC2 / AC8: the spec example --------------------------------------------------------

AC1_TEXT = [
    "InBody body composition trend: 3 measurements on 3 dates (2026-07-02 to 2026-09-16)",
    "Values are stored InBody results rounded to 0.1. Missing values are shown as unknown.",
    "",
    "Measurements:",
    "  2026-07-02 08:10  weight 80.0 kg  SMM 36.0 kg  body fat 15.0 kg  PBF 18.8 %",
    "  2026-08-05 08:05  weight 80.6 kg  SMM 36.5 kg  body fat 15.1 kg  PBF 18.7 %",
    "  2026-09-16 16:43  weight 81.0 kg  SMM 36.9 kg  body fat unknown  PBF unknown",
    "",
    "Between measurements:",
    "  2026-07-02 -> 2026-08-05 (34 d): weight +0.6 kg, SMM +0.5 kg, body fat +0.1 kg, PBF -0.1 %",
    "  2026-08-05 -> 2026-09-16 (42 d): weight +0.4 kg, SMM +0.4 kg, body fat unknown, PBF unknown",
    "",
    "First to last:",
    "  weight    +1.0 kg over 76 d (2026-07-02 -> 2026-09-16), +0.4 kg per 28 d",
    "  SMM       +0.9 kg over 76 d (2026-07-02 -> 2026-09-16), +0.3 kg per 28 d",
    "  body fat  +0.1 kg over 34 d (2026-07-02 -> 2026-08-05), +0.1 kg per 28 d",
    "  PBF       -0.1 % over 34 d (2026-07-02 -> 2026-08-05), -0.1 % per 28 d",
    "",
    "Goal (skeletal muscle mass, from training goals):",
    "  milestone 43.0 kg: latest 36.9 kg (2026-09-16), 6.1 kg to go",
    "  long-term 50.0 kg: 13.1 kg to go",
    "",
    "Last measurement: 2026-09-16, 19 days before 2026-10-05",
]


def _overall(from_date: str, to_date: str, days: int, change: str | None, per_28_days: str | None) -> dict[str, Any]:
    return {"from_date": from_date, "to_date": to_date, "days": days, "change": change, "per_28_days": per_28_days}


AC1_JSON: dict[str, Any] = {
    "trend_version": 1,
    "from": None,
    "to": None,
    "reference_date": "2026-10-05",
    "measurement_count": 3,
    "measurements": [
        {
            "measured_at": "2026-07-02T08:10:00+09:00",
            "local_date": "2026-07-02",
            "weight_kg": "80.0",
            "skeletal_muscle_mass_kg": "36.0",
            "body_fat_mass_kg": "15.0",
            "body_fat_percent": "18.8",
        },
        {
            "measured_at": "2026-08-05T08:05:00+09:00",
            "local_date": "2026-08-05",
            "weight_kg": "80.6",
            "skeletal_muscle_mass_kg": "36.5",
            "body_fat_mass_kg": "15.1",
            "body_fat_percent": "18.7",
        },
        {
            "measured_at": "2026-09-16T16:43:00+09:00",
            "local_date": "2026-09-16",
            "weight_kg": "81.0",
            "skeletal_muscle_mass_kg": "36.9",
            "body_fat_mass_kg": None,
            "body_fat_percent": None,
        },
    ],
    "intervals": [
        {
            "from_date": "2026-07-02",
            "to_date": "2026-08-05",
            "days": 34,
            "changes": {
                "weight_kg": "0.6",
                "skeletal_muscle_mass_kg": "0.5",
                "body_fat_mass_kg": "0.1",
                "body_fat_percent": "-0.1",
            },
        },
        {
            "from_date": "2026-08-05",
            "to_date": "2026-09-16",
            "days": 42,
            "changes": {
                "weight_kg": "0.4",
                "skeletal_muscle_mass_kg": "0.4",
                "body_fat_mass_kg": None,
                "body_fat_percent": None,
            },
        },
    ],
    "overall": {
        "weight_kg": _overall("2026-07-02", "2026-09-16", 76, "1.0", "0.4"),
        "skeletal_muscle_mass_kg": _overall("2026-07-02", "2026-09-16", 76, "0.9", "0.3"),
        "body_fat_mass_kg": _overall("2026-07-02", "2026-08-05", 34, "0.1", "0.1"),
        "body_fat_percent": _overall("2026-07-02", "2026-08-05", 34, "-0.1", "-0.1"),
    },
    "goal": {
        "metric": "skeletal_muscle_mass_kg",
        "latest": "36.9",
        "latest_date": "2026-09-16",
        "milestone": {"target": "43.0", "remaining": "6.1", "reached": False},
        "long_term": {"target": "50.0", "remaining": "13.1", "reached": False},
    },
    "conflicts": [],
    "last_measurement_date": "2026-09-16",
    "days_since_last_measurement": 19,
}


def test_spec_example_text_and_json(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(trend_home, *inbody.AC1_ROWS)

    text = _out(capsys, "inbody", "trend")
    printed = _out(capsys, "inbody", "trend", "--json")

    assert text.splitlines() == AC1_TEXT
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert json.loads(printed) == AC1_JSON
    assert list(json.loads(printed)) == list(AC1_JSON)  # fixed key order
    assert printed == json.dumps(AC1_JSON, indent=2) + "\n"
    # AC2: a missing value is never shown as 0.
    assert "body fat 0.0" not in text and "PBF 0.0" not in text


def test_output_is_deterministic_ascii_and_free_of_float_noise(
    trend_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _database(
        trend_home,
        inbody.measurement("noise-1", "2026-07-01T08:00:00+09:00", weight=80.40000152587891, smm=41.400001525878906),
        inbody.measurement("noise-2", "2026-08-01T08:00:00+09:00", weight=80.09999847412109, smm=41.70000076293945),
    )

    first = _out(capsys, "inbody", "trend", "--json")
    second = _out(capsys, "inbody", "trend", "--json")
    text = _out(capsys, "inbody", "trend")

    assert first == second
    assert first.isascii() and text.isascii()
    assert "  2026-07-01 08:00  weight 80.4 kg  SMM 41.4 kg  body fat unknown  PBF unknown" in text.splitlines()
    assert "  2026-08-01 08:00  weight 80.1 kg  SMM 41.7 kg  body fat unknown  PBF unknown" in text.splitlines()
    for output in (first, text):
        assert "0000" not in output and "9999" not in output


# --- AC3: same-date rows ------------------------------------------------------------------------


def _dump(database: Path) -> tuple[Any, ...]:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        measurements = connection.execute("SELECT * FROM body_composition_measurements ORDER BY id").fetchall()
        identities = connection.execute("SELECT * FROM body_composition_source_identities ORDER BY id").fetchall()
        migrations = connection.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
    finally:
        connection.close()
    return measurements, identities, migrations


def _files(database: Path) -> tuple[str, int, bytes]:
    """DB bytes hash, mtime and WAL bytes (b"" when absent), read before any SQLite connection."""
    wal = database.with_name(database.name + "-wal")
    return (
        hashlib.sha256(database.read_bytes()).hexdigest(),
        database.stat().st_mtime_ns,
        wal.read_bytes() if wal.exists() else b"",
    )


def test_same_date_rows_are_listed_and_conflicts_reported_without_changing_the_database(
    trend_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = _database(
        trend_home,
        inbody.measurement("a", "2026-07-02T08:10:00+09:00", weight=80.0, smm=36.0),
        inbody.measurement("b", "2026-09-16T16:43:00+09:00", weight=81.0, smm=36.9, pbf=18.0),
        inbody.measurement("c", "2026-09-16T16:43:00+09:00", weight=81.4, pbf=18.04, source_type="inbody_export"),
    )
    files, rows = _files(database), _dump(database)

    text = _lines(capsys)
    document = json.loads(_out(capsys, "inbody", "trend", "--json"))

    assert text[:12] == [
        "InBody body composition trend: 3 measurements on 2 dates (2026-07-02 to 2026-09-16)",
        "Values are stored InBody results rounded to 0.1. Missing values are shown as unknown.",
        "",
        "Measurements:",
        "  2026-07-02 08:10  weight 80.0 kg  SMM 36.0 kg  body fat unknown  PBF unknown",
        "  2026-09-16 16:43  weight 81.0 kg  SMM 36.9 kg  body fat unknown  PBF 18.0 %",
        "  2026-09-16 16:43  weight 81.4 kg  SMM unknown  body fat unknown  PBF 18.0 %",
        "",
        "Same-date conflicts (left out of the trend):",
        "  2026-09-16 weight: 81.0 kg, 81.4 kg",
        "",
        "Between measurements:",
    ]
    assert text[12] == "  2026-07-02 -> 2026-09-16 (76 d): weight unknown, SMM +0.9 kg, body fat unknown, PBF unknown"
    assert document["conflicts"] == [{"local_date": "2026-09-16", "metric": "weight_kg", "values": ["81.0", "81.4"]}]
    assert document["measurement_count"] == 3
    assert document["overall"]["body_fat_percent"] == _overall("2026-09-16", "2026-09-16", 0, None, None)
    assert _files(database) == files
    assert _dump(database) == rows


# --- AC4: goal variants ---------------------------------------------------------------------


def test_goal_lines_when_the_milestone_is_reached(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(trend_home, inbody.measurement("a", "2026-09-16T08:00:00+09:00", smm=44.0))

    text = _lines(capsys)
    goal = json.loads(_out(capsys, "inbody", "trend", "--json"))["goal"]

    assert text[-5:-2] == [
        "Goal (skeletal muscle mass, from training goals):",
        "  milestone 43.0 kg: latest 44.0 kg (2026-09-16), reached",
        "  long-term 50.0 kg: 6.0 kg to go",
    ]
    assert goal == {
        "metric": "skeletal_muscle_mass_kg",
        "latest": "44.0",
        "latest_date": "2026-09-16",
        "milestone": {"target": "43.0", "remaining": None, "reached": True},
        "long_term": {"target": "50.0", "remaining": "6.0", "reached": False},
    }


def test_goal_lines_when_both_goals_are_reached(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(trend_home, inbody.measurement("a", "2026-09-16T08:00:00+09:00", smm=50.0))

    assert _lines(capsys)[-4:-2] == [
        "  milestone 43.0 kg: latest 50.0 kg (2026-09-16), reached",
        "  long-term 50.0 kg: reached",
    ]


def test_goal_is_unknown_without_smm(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(trend_home, inbody.measurement("a", "2026-10-04T08:00:00+09:00", weight=80.0))

    text = _lines(capsys)
    goal = json.loads(_out(capsys, "inbody", "trend", "--json"))["goal"]

    assert text[-5:] == [
        "Goal (skeletal muscle mass, from training goals):",
        "  milestone 43.0 kg: unknown (no skeletal muscle mass value)",
        "  long-term 50.0 kg: unknown",
        "",
        "Last measurement: 2026-10-04, 1 day before 2026-10-05",
    ]
    assert goal == {
        "metric": "skeletal_muscle_mass_kg",
        "latest": None,
        "latest_date": None,
        "milestone": {"target": "43.0", "remaining": None, "reached": None},
        "long_term": {"target": "50.0", "remaining": None, "reached": None},
    }


# --- first-to-last variants ------------------------------------------------------------------


def test_first_to_last_variants(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(
        trend_home,
        inbody.measurement("a", "2026-09-01T08:00:00+09:00", weight=80.0, smm=36.0),
        inbody.measurement("b", "2026-09-21T08:00:00+09:00", weight=80.3),
    )

    text = _lines(capsys)

    assert text[text.index("First to last:") + 1 : text.index("First to last:") + 5] == [
        "  weight    +0.3 kg over 20 d (2026-09-01 -> 2026-09-21), per 28 d not computed (under 28 d)",
        "  SMM       unknown (one date with a value: 2026-09-01)",
        "  body fat  unknown (no usable values)",
        "  PBF       unknown (no usable values)",
    ]


def test_future_dated_row_without_to_counts_days_after(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(trend_home, inbody.measurement("a", "2026-10-08T08:00:00+09:00", weight=80.0))

    assert _lines(capsys)[-1] == "Last measurement: 2026-10-08, 3 days after 2026-10-05"


# --- AC5: no measurements ------------------------------------------------------------------------


def test_no_measurements(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(trend_home)

    assert _out(capsys, "inbody", "trend") == "No InBody measurements stored.\n"
    assert json.loads(_out(capsys, "inbody", "trend", "--json")) == {
        "trend_version": 1,
        "from": None,
        "to": None,
        "reference_date": "2026-10-05",
        "measurement_count": 0,
        "measurements": [],
        "intervals": [],
        "overall": {
            metric: {"from_date": None, "to_date": None, "days": None, "change": None, "per_28_days": None}
            for metric in ("weight_kg", "skeletal_muscle_mass_kg", "body_fat_mass_kg", "body_fat_percent")
        },
        "goal": {
            "metric": "skeletal_muscle_mass_kg",
            "latest": None,
            "latest_date": None,
            "milestone": {"target": "43.0", "remaining": None, "reached": None},
            "long_term": {"target": "50.0", "remaining": None, "reached": None},
        },
        "conflicts": [],
        "last_measurement_date": None,
        "days_since_last_measurement": None,
    }


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ("--from", "2026-01-01", "--to", "2026-02-01"),
            "No InBody measurements stored in local dates between 2026-01-01 and 2026-02-01 (inclusive).\n",
        ),
        (("--from", "2026-10-01"), "No InBody measurements stored in local dates on or after 2026-10-01.\n"),
        (("--to", "2026-02-01"), "No InBody measurements stored in local dates on or before 2026-02-01.\n"),
    ],
)
def test_no_measurements_in_the_range(
    trend_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    expected: str,
) -> None:
    _database(trend_home, *inbody.AC1_ROWS)
    if "--to" in argv:
        _no_today(monkeypatch)

    assert _out(capsys, "inbody", "trend", *argv) == expected


# --- AC6: range ---------------------------------------------------------------------------------


def test_range_limits_the_trend_and_to_is_the_reference_date(
    trend_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _database(trend_home, *inbody.AC1_ROWS)
    _no_today(monkeypatch)

    text = _lines(capsys, "--from", "2026-08-05", "--to", "2026-09-16")
    document = json.loads(_out(capsys, "inbody", "trend", "--from", "2026-08-05", "--to", "2026-09-16", "--json"))

    assert text[:3] == [
        "InBody body composition trend: 2 measurements on 2 dates (2026-08-05 to 2026-09-16)",
        "Range: local dates between 2026-08-05 and 2026-09-16 (inclusive)",
        "Values are stored InBody results rounded to 0.1. Missing values are shown as unknown.",
    ]
    assert text[-1] == "Last measurement: 2026-09-16, 0 days before 2026-09-16"
    assert (document["from"], document["to"], document["reference_date"]) == ("2026-08-05", "2026-09-16", "2026-09-16")
    assert [item["local_date"] for item in document["measurements"]] == ["2026-08-05", "2026-09-16"]


def test_open_ended_range_lines(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(trend_home, *inbody.AC1_ROWS)

    after = _lines(capsys, "--from", "2026-08-05")

    assert after[:2] == [
        "InBody body composition trend: 2 measurements on 2 dates (2026-08-05 to 2026-09-16)",
        "Range: local dates on or after 2026-08-05",
    ]
    assert after[-1] == "Last measurement: 2026-09-16, 19 days before 2026-10-05"


def test_to_only_range_line(
    trend_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _database(trend_home, *inbody.AC1_ROWS)
    _no_today(monkeypatch)

    assert _lines(capsys, "--to", "2026-07-02")[:2] == [
        "InBody body composition trend: 1 measurement on 1 date (2026-07-02)",
        "Range: local dates on or before 2026-07-02",
    ]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("--from", "2026-7-01"), FORMAT_ERROR),
        (("--to", "2026-02-30"), FORMAT_ERROR),
        (("--from", "2026-10-06", "--to", "2026-10-05"), ORDER_ERROR),
    ],
)
def test_bad_dates_are_refused_before_the_database_is_opened(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    expected: str,
) -> None:
    _no_today(monkeypatch)
    monkeypatch.setattr(
        SqliteBodyCompositionReader, "load_measurements", lambda self: pytest.fail("must not open the database")
    )

    assert _run(capsys, "inbody", "trend", *argv) == (1, "", expected)
    assert not home.exists()


# --- AC7: read-only ------------------------------------------------------------------------------


def test_missing_database_is_refused_and_nothing_is_created(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = home / "db" / "muscle50.sqlite3"

    assert _run(capsys, "inbody", "trend") == (1, "", f"오류: muscle50 database not found: {database.resolve()}\n")
    assert not home.exists()


def test_existing_home_without_database_gets_no_directories(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home.mkdir()

    code, _, err = _run(capsys, "inbody", "trend", "--json")

    assert code == 1 and err.startswith("오류: muscle50 database not found: ")
    assert list(home.iterdir()) == []  # no db\, config\, raw\ or tmp\


def test_a_run_changes_neither_the_database_nor_its_wal(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = _database(trend_home, *inbody.AC1_ROWS)
    before = _files(database)

    _out(capsys, "inbody", "trend")
    after_first = _files(database)
    _out(capsys, "inbody", "trend", "--json")

    # SQLite may leave empty -wal/-shm sidecars on a read-only open of a WAL database (as the
    # analytics reader does); the database bytes, its mtime and the WAL content never change.
    assert after_first == before
    assert _files(database) == before
    rows = _dump(database)
    _out(capsys, "inbody", "trend")
    assert _dump(database) == rows


def test_reader_opens_read_only_and_rejects_writes(trend_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _database(trend_home, *inbody.AC1_ROWS)
    calls: list[tuple[str, bool]] = []
    real_connect = sqlite3.connect

    def spy(target: str, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        calls.append((target, bool(kwargs.get("uri"))))
        connection: sqlite3.Connection = real_connect(target, *args, **kwargs)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spy)  # the module object the reader calls
    reader = SqliteBodyCompositionReader(database)

    assert len(reader.load_measurements()) == 3
    with pytest.raises(BodyCompositionReadError, match="^cannot read InBody measurements: "):  # noqa: SIM117
        with reader._read_transaction() as connection:
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
            connection.execute("DELETE FROM body_composition_measurements")
    assert calls == [(f"{database.resolve().as_uri()}?mode=ro", True)] * 2
    assert len(reader.load_measurements()) == 3


def test_database_from_before_migration_7_is_refused_unchanged(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = home / "db" / "muscle50.sqlite3"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name < "007":
                connection.executescript(migration.read_text(encoding="utf-8"))
    finally:
        connection.close()
    before = _files(database)

    assert _run(capsys, "inbody", "trend") == (1, "", NO_TABLE)
    assert _files(database) == before
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (6,)
    finally:
        connection.close()


def test_empty_and_foreign_files_are_refused(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = home / "db" / "muscle50.sqlite3"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"")

    assert _run(capsys, "inbody", "trend") == (1, "", NO_TABLE)
    assert database.read_bytes() == b""

    database.write_bytes(b"not a sqlite database, synthetic" * 100)
    assert _run(capsys, "inbody", "trend") == (1, "", "오류: cannot read InBody measurements: file is not a database\n")


def test_unreadable_stored_timestamp_is_a_known_error(trend_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _database(trend_home, inbody.measurement("a", "not-a-timestamp", weight=80.0))

    code, out, err = _run(capsys, "inbody", "trend")

    assert (code, out) == (1, "")
    assert err == "오류: stored InBody measurement 1 has an unreadable measured_at: 'not-a-timestamp'\n"


def test_ctrl_c_exits_130(
    trend_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupt(self: ShowBodyCompositionTrend, *args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(ShowBodyCompositionTrend, "execute", interrupt)

    assert _run(capsys, "inbody", "trend") == (130, "", "\n취소되었습니다.\n")
