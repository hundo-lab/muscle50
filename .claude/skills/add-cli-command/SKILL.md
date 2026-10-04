---
name: add-cli-command
description: How to add or extend a muscle50 CLI subcommand the way the codebase already does it - argparse registration, a handler with paths/ensure_directories/migrate/wiring/try-except and exit codes 0/1/2/130, a VerbNoun use case with execute(), render_x/render_x_json renderers, and capsys CLI tests over a temporary MUSCLE50_HOME. Use whenever a spec adds a command, flag or output.
user-invocable: false
---

# Adding a muscle50 CLI command

Follow the existing chain. Do not invent a new structure. The worked example below is
`muscle50 nutrition repeat <meal_id>` (Nutrition Meal Repeat v1, commit `2d2ea84`), the most recent
command that went through every layer.

Sources: `src/muscle50/cli.py` (`build_parser`, `main`, `_nutrition`, `_analytics_snapshot`);
`src/muscle50/application/nutrition_logging.py` (`RepeatMeal`);
`src/muscle50/presentation/nutrition_terminal.py` (`render_repeated_meal`, `render_logged_meal_json`);
`tests/test_nutrition_meal_repeat.py`, `tests/test_nutrition_target_cli.py`; docs/HANDOFF.md "Nutrition Meal
Repeat v1" (files changed). Data/output rules come from the `domain-principles` skill.

## Layer map

| Layer | Where | Rule |
|---|---|---|
| Domain | `src/muscle50/domain/<area>.py` | Pure and deterministic. `@dataclass(frozen=True)`, `StrEnum`, domain errors. No I/O, no clock, no `date.today()`. |
| Application | `src/muscle50/application/<area>.py` | `class VerbNoun` with `__init__(ports)` and `execute(...)`. Ports are `typing.Protocol`. Results are frozen dataclasses. |
| Infrastructure | `src/muscle50/infrastructure/...` | SQLite repositories/readers, RAW stores, JSON stores, Garmin adapter. |
| Presentation | `src/muscle50/presentation/terminal.py` (training) or `nutrition_terminal.py` (nutrition) | `render_<thing>(result) -> str` (ASCII text) and `render_<thing>_json(result) -> str`. |
| CLI | `src/muscle50/cli.py` | Parser registration + handler that wires the concrete adapters (the composition root). |

`cli.py`, `nutrition_terminal.py` and `nutrition_logging.py` are shared hotspots. Keep each edit small
and next to its sibling commands, so the next ff-only integration stays conflict-free.

## 1. Register the parser (`build_parser`)

Nest the command under its group. Use the dest and metavar names the existing commands already use:
`--date` -> `dest="as_of"` with `metavar="YYYY-MM-DD"`, `--time` -> `dest="eaten_time"`, and always a
`--json` flag. Each help text says what the default is.

```python
repeat = nutrition_commands.add_parser("repeat", help=("Record a new meal with the same foods ... "))
repeat.add_argument("meal_id", help="meal to repeat, as printed by `nutrition log`/`nutrition day`")
repeat.add_argument(
    "--date", dest="as_of", metavar="YYYY-MM-DD", help="new meal date (default: today on this computer)"
)
repeat.add_argument("--time", dest="eaten_time", metavar="HH:MM", help="local time eaten (optional)")
repeat.add_argument(
    "--meal", choices=[meal.value for meal in MealType], help="meal type (default: the source meal's type)"
)
repeat.add_argument("--additional", action="store_true", help="record another meal of the same type ...")
repeat.add_argument("--json", action="store_true", help="print the recorded meal as JSON")
```

- Validate argument format before any login, network call or mkdir (for example
  `validate_calendar_date`). Garmin range commands reject bad dates "before authentication"
  (docs/CURRENT_STATE.md).
- Flags shared by several commands go through one helper, such as `_add_fact_arguments` and
  `_add_item_number_argument`.

## 2. Dispatch and handler (`main` -> `_handler`)

`main()` dispatches with `if args.command == ... and args.<group>_command == ...: return _handler(...)`.
The nutrition group sends everything to `_nutrition(args)`, which builds the repositories once.

The handler for a **writing** command:

```python
def _garmin_latest() -> int:
    try:
        paths = AppPaths.from_environment()          # MUSCLE50_HOME or %LOCALAPPDATA%\muscle50
        paths.ensure_directories()
        repository = ActivityRepository(paths.database_path)
        repository.migrate()                         # every writing command migrates first
        connector = PythonGarminConnector.authenticate(paths.auth_dir)
        use_case = SyncLatestGarminActivity(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir))
        print(render_sync_result(use_case.execute()))
        return 0
    except (ActivitySyncError, ConfigurationError, GarminConnectorError, ...) as exc:   # known errors only
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130
```

The handler for a **read-only** command (analytics, recommend, and anything a reader serves) never calls
`ensure_directories()` or `migrate()`:

```python
def _analytics_snapshot(as_of_text: str, lookback_days: int, *, as_json: bool) -> int:
    # Deliberately read-only: no ensure_directories(), no migrate(), no Garmin connector.
    ...
        paths = AppPaths.from_environment()
        snapshot = BuildTrainingSnapshot(SqliteAnalyticsReader(paths.database_path)).execute(as_of, lookback_days)
        print(render_training_snapshot_json(snapshot) if as_json else render_training_snapshot(snapshot))
        return 0
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | a known, safe-to-display error on stderr |
| 2 | argparse usage error, `return 2` fallthrough, or InBody "changed RAW" conflict |
| 130 | KeyboardInterrupt |

Notes:
- Catch only the known error families. Anything else propagates as a traceback on purpose (for example
  a local integrity error).
- Error message language matches the group. Garmin/analytics/recommend/nutrition handlers print
  `오류: ...`; inbody prints English. Do not "fix" this in passing.
- Defaults that depend on the machine (`_today()`, `_local_timezone(day)`) stay module-level functions so
  tests can monkeypatch them. Pass the date and timezone into the use case; never read the clock inside it.

## 3. Use case (`VerbNoun.execute`)

```python
class RepeatMeal:
    def __init__(self, meals: MealRepository, foods: FoodNutritionRepository) -> None:
        self._meals = meals
        self._foods = foods

    def execute(self, source_meal_id: str, day: date, *, timezone: tzinfo,
                meal_type: MealType | None = None, eaten_time: time | None = None,
                additional: bool = False) -> RepeatedMeal:
        ...
        intake = LogMeal(self._meals, self._foods).execute(..., repeated_from=source.meal_id)
```

- Reuse existing use cases rather than copying their logic. `RepeatMeal` calls `LogMeal.execute`, and
  `daily` composes the existing sync use cases.
- When you add a parameter to a shared use case, give it a default that leaves existing callers
  byte-identical (`repeated_from=None`).
- Validation failures raise the area's error (`NutritionLoggingError`) with a message that says that
  nothing was changed. Writes are all-or-nothing, in one transaction.

## 4. Renderers

- Text: ASCII only, except user-entered names. Fixed line order. Unknown values are spelled out
  ("incomplete (known items only: ...)"), never 0.
- JSON: reuse the existing payload builders whenever the document already exists (`nutrition repeat
  --json` is exactly `render_logged_meal_json`). Otherwise `json.dumps(payload, indent=2, ensure_ascii=True)`
  with fixed key order and Decimal values as strings.
- Adding to an existing JSON document means appending new keys at the end and keeping the old ones
  unchanged. Record that as `output_change: additive` in the spec.

## 5. CLI tests (`tests/test_<feature>.py`)

Every CLI test runs against a temporary home, never production:

```python
@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("nutrition must not use Garmin")
    )
    monkeypatch.setattr(cli, "_local_timezone", lambda day: KST)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 3))
    return root


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err
```

Cover at least these:
- The happy path, text and `--json`, checked against an exact expected text (a list of lines).
- Determinism: run twice and get byte-identical output. `printed == json.dumps(document, indent=2) + "\n"`.
  The text is ASCII once the user-entered names are removed.
- Every refusal path: exit 1, the `오류:` message on stderr, and **nothing written** (compare the DB/rows
  before and after).
- **Unchanged neighbours**: the existing commands this feature touches (for example `nutrition log`,
  `day`, `status`, `recommend`) produce the same bytes as before.
- Synthetic values only. Never use real foods or measurements from the user's data.
- For Garmin commands, use fake connectors (`FakeApi`, `Stub*` in `tests/test_garmin_connector.py`,
  `tests/test_daily_sync.py`). Tests never log in.

Then document the command in `docs/<feature>.md`: purpose and non-goals, command examples (text and
`--json`), rules, limitations. Leave README.md to the integrator.
