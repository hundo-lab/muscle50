"""The training goal and the sleep thresholds as small JSON documents under the muscle50 home.

Both are user settings like ``nutrition_targets.json``: no SQLite table, no migration. Each file is
versioned, written atomically, read strictly (exact keys, decimal strings for decimals, integers
for the sleep thresholds) and validated with the same rules as the command that writes it. An
invalid file is an error that names the key but never the value; a missing file means "not set"
(no goal; default sleep thresholds). Reading never creates a file or a directory.

The goal file is schema 1 unless the goal has a plateau setting (Aerobic Guide v1): then it is
schema 2, the same keys plus a trailing ``plateau_weeks``. A goal without that setting is written
as schema 1, byte for byte as before. The sleep thresholds file is schema 1 only.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from muscle50.domain.recovery_assessment import SleepThresholds
from muscle50.domain.recovery_normalization import RecoveryNormalizationError, validate_calendar_date
from muscle50.domain.training_goal import (
    DEFAULT_SLEEP_SETTING,
    GoalMode,
    GoalSettingsError,
    SleepThresholdSetting,
    TrainingGoal,
    TrainingGoalError,
    WeeklyRateRange,
    validate_goal,
    validate_sleep_thresholds,
)
from muscle50.infrastructure.decimal_text import decimal_from_text, decimal_to_text

SCHEMA_VERSION = 1
PLATEAU_SCHEMA_VERSION = 2
GOAL_KEYS = (
    "mode",
    "target_body_fat_percent",
    "target_weight_kg",
    "target_date",
    "min_skeletal_muscle_mass_kg",
    "weekly_loss_percent",
)
PLATEAU_GOAL_KEYS = (*GOAL_KEYS, "plateau_weeks")
SLEEP_KEYS = ("hold_below_seconds", "reduce_below_seconds", "hold_below_score")


class _InvalidKey(ValueError):
    """An invalid document; the message is the key only (never the value)."""


class JsonTrainingGoalRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> TrainingGoal | None:
        document = _read(self._path, "training goal")
        if document is None:
            return None
        try:
            return _goal_from_document(document)
        except _InvalidKey as exc:
            raise GoalSettingsError(f"training goal file {self._path} is not valid ({exc})") from None

    def save(self, goal: TrainingGoal) -> None:
        version = SCHEMA_VERSION if goal.plateau_weeks is None else PLATEAU_SCHEMA_VERSION
        _write(self._path, {"schema_version": version, "goal": goal_payload(goal)})

    def delete(self) -> bool:
        return _delete(self._path)


class JsonSleepThresholdRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> SleepThresholdSetting:
        document = _read(self._path, "sleep thresholds")
        if document is None:
            return DEFAULT_SLEEP_SETTING
        try:
            return SleepThresholdSetting(_sleep_from_document(document), "user_setting")
        except _InvalidKey as exc:
            raise GoalSettingsError(f"sleep thresholds file {self._path} is not valid ({exc})") from None

    def save(self, thresholds: SleepThresholds) -> None:
        _write(self._path, {"schema_version": SCHEMA_VERSION, "sleep_thresholds": sleep_payload(thresholds)})

    def delete(self) -> bool:
        return _delete(self._path)


def goal_payload(goal: TrainingGoal) -> dict[str, Any]:
    """The goal in the file's (and every JSON output's) exact key order, decimals as strings.

    ``plateau_weeks`` is a trailing key present only when it is set, so a goal without it keeps
    exactly the schema 1 payload.
    """
    rate = goal.weekly_loss_percent
    payload: dict[str, Any] = {
        "mode": goal.mode.value,
        "target_body_fat_percent": _text(goal.target_body_fat_percent),
        "target_weight_kg": _text(goal.target_weight_kg),
        "target_date": goal.target_date.isoformat() if goal.target_date is not None else None,
        "min_skeletal_muscle_mass_kg": _text(goal.min_skeletal_muscle_mass_kg),
        "weekly_loss_percent": None
        if rate is None
        else {"minimum": decimal_to_text(rate.minimum), "maximum": decimal_to_text(rate.maximum)},
    }
    if goal.plateau_weeks is not None:
        payload["plateau_weeks"] = goal.plateau_weeks
    return payload


def sleep_payload(thresholds: SleepThresholds) -> dict[str, int]:
    return {
        "hold_below_seconds": thresholds.short_sleep_seconds,
        "reduce_below_seconds": thresholds.very_short_sleep_seconds,
        "hold_below_score": thresholds.low_sleep_score,
    }


def _read(path: Path, what: str) -> Any | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        raise GoalSettingsError(f"{what} file {path} cannot be read") from None
    try:
        return json.loads(text)
    except ValueError:
        raise GoalSettingsError(f"{what} file {path} is not valid (not JSON)") from None


def _write(path: Path, document: dict[str, Any]) -> None:
    content = json.dumps(document, indent=2, ensure_ascii=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _delete(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def _envelope(document: Any, body_key: str, versions: frozenset[int] = frozenset({SCHEMA_VERSION})) -> tuple[int, Any]:
    if not isinstance(document, dict) or set(document) != {"schema_version", body_key}:
        raise _InvalidKey(f"expected exactly the keys schema_version and {body_key}")
    version = document["schema_version"]
    if type(version) is not int or version not in versions:
        raise _InvalidKey("schema_version")
    return version, document[body_key]


def _goal_from_document(document: Any) -> TrainingGoal:
    version, body = _envelope(document, "goal", frozenset({SCHEMA_VERSION, PLATEAU_SCHEMA_VERSION}))
    keys = GOAL_KEYS if version == SCHEMA_VERSION else PLATEAU_GOAL_KEYS
    if not isinstance(body, dict) or set(body) != set(keys):
        raise _InvalidKey(f"goal must list exactly {', '.join(keys)}")
    mode_text = body["mode"]
    if not isinstance(mode_text, str) or mode_text not in {mode.value for mode in GoalMode}:
        raise _InvalidKey("mode")
    rate = body["weekly_loss_percent"]
    if rate is not None and (not isinstance(rate, dict) or set(rate) != {"minimum", "maximum"}):
        raise _InvalidKey("weekly_loss_percent")
    plateau_weeks = body.get("plateau_weeks")
    # Schema 2 always sets it: a whole number (a bool, a string or null is not).
    if version == PLATEAU_SCHEMA_VERSION and type(plateau_weeks) is not int:
        raise _InvalidKey("plateau_weeks")
    goal = TrainingGoal(
        mode=GoalMode(mode_text),
        target_body_fat_percent=_optional_decimal(body, "target_body_fat_percent"),
        target_weight_kg=_optional_decimal(body, "target_weight_kg"),
        target_date=_optional_date(body, "target_date"),
        min_skeletal_muscle_mass_kg=_optional_decimal(body, "min_skeletal_muscle_mass_kg"),
        weekly_loss_percent=None
        if rate is None
        else WeeklyRateRange(
            _decimal(rate["minimum"], "weekly_loss_percent"), _decimal(rate["maximum"], "weekly_loss_percent")
        ),
        plateau_weeks=plateau_weeks,
    )
    try:
        # No ``today``: a deadline that has passed still loads (it is reported as passed).
        return validate_goal(goal)
    except TrainingGoalError as exc:
        raise _InvalidKey(exc.key) from None


def _sleep_from_document(document: Any) -> SleepThresholds:
    _version, body = _envelope(document, "sleep_thresholds")
    if not isinstance(body, dict) or set(body) != set(SLEEP_KEYS):
        raise _InvalidKey(f"sleep_thresholds must list exactly {', '.join(SLEEP_KEYS)}")
    for key in SLEEP_KEYS:
        # Whole numbers only; a bool is not an integer here.
        if type(body[key]) is not int:
            raise _InvalidKey(key)
    thresholds = SleepThresholds(
        short_sleep_seconds=body["hold_below_seconds"],
        very_short_sleep_seconds=body["reduce_below_seconds"],
        low_sleep_score=body["hold_below_score"],
    )
    try:
        return validate_sleep_thresholds(thresholds)
    except TrainingGoalError as exc:
        raise _InvalidKey(exc.key) from None


def _optional_decimal(body: dict[str, Any], key: str) -> Decimal | None:
    value = body[key]
    return None if value is None else _decimal(value, key)


def _decimal(value: Any, key: str) -> Decimal:
    # JSON numbers are refused so a value never passes through a binary float.
    if not isinstance(value, str):
        raise _InvalidKey(key)
    try:
        return decimal_from_text(value)
    except ValueError:
        raise _InvalidKey(key) from None


def _optional_date(body: dict[str, Any], key: str) -> date | None:
    value = body[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise _InvalidKey(key)
    try:
        return date.fromisoformat(validate_calendar_date(value))
    except (RecoveryNormalizationError, ValueError):
        raise _InvalidKey(key) from None


def _text(value: Decimal | None) -> str | None:
    return decimal_to_text(value) if value is not None else None
