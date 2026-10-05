"""A logged meal's corrections: date/time/type revisions, a void, and meals merged into it.

Corrections never rewrite the logged meal. Each one is appended, so the meal as it was logged
stays recoverable: ``logged_*`` are the values `nutrition log` stored, and the latest revision
holds the current (effective) date, time and type. Pure values; no storage, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from muscle50.domain.nutrition import MealType


@dataclass(frozen=True)
class MealRevision:
    """The meal's full effective metadata after one `nutrition meal edit` (1, 2, ... per meal)."""

    revision: int
    revised_at: datetime
    meal_type: MealType
    eaten_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        _require_aware(self.revised_at, "revised_at")
        _require_aware(self.eaten_at, "eaten_at")


@dataclass(frozen=True)
class MealVoid:
    voided_at: datetime
    reason: str | None = None
    # The meal this one's items were copied into, when it was voided by `nutrition meal merge`.
    merged_into: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.voided_at, "voided_at")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("a void reason must not be blank")


@dataclass(frozen=True)
class MergedItem:
    """Item ``sequence`` of the target meal is a copy of item ``source_sequence`` of the source meal."""

    sequence: int
    source_sequence: int


@dataclass(frozen=True)
class MealMerge:
    source_meal_id: str
    merged_at: datetime
    items: tuple[MergedItem, ...]


@dataclass(frozen=True)
class MealHistory:
    logged_meal_type: MealType
    logged_eaten_at: datetime
    revisions: tuple[MealRevision, ...] = ()
    void: MealVoid | None = None
    merged_from: tuple[MealMerge, ...] = ()

    @property
    def recorded(self) -> bool:
        """True once the meal has any correction (edited, voided, or another meal merged into it)."""
        return bool(self.revisions) or self.void is not None or bool(self.merged_from)

    @property
    def voided(self) -> bool:
        return self.void is not None

    def revision_steps(self) -> tuple[tuple[MealType, datetime, MealRevision], ...]:
        """Each revision with the type and time it replaced (revision 1 replaced the logged values)."""
        steps: list[tuple[MealType, datetime, MealRevision]] = []
        meal_type, eaten_at = self.logged_meal_type, self.logged_eaten_at
        for revision in self.revisions:
            steps.append((meal_type, eaten_at, revision))
            meal_type, eaten_at = revision.meal_type, revision.eaten_at
        return tuple(steps)


def recorded_time(eaten_at: datetime) -> time | None:
    """The meal's local wall time, or None when no time was recorded (meals are stored at 00:00 then)."""
    wall = eaten_at.timetz().replace(tzinfo=None)
    return None if wall == time(0) else wall


def timestamp_text(value: datetime) -> str:
    """'2026-10-02 21:00 (UTC+09:00)': the time in the offset it was recorded with (ASCII)."""
    offset = value.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds()) // 60
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return f"{value.strftime('%Y-%m-%d %H:%M')} (UTC{sign}{hours:02d}:{rest:02d})"


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
