"""Nutrition targets as one small JSON document under the muscle50 home.

Targets are a user setting, not nutrition fact history, so they need no SQLite table or
migration. The file is versioned, written atomically, and read strictly: values are canonical
decimal strings (never JSON numbers), every nutrient is listed with an explicit kind, and an
unreadable file is an error instead of silently meaning "no targets". A missing file means no
target has been set yet; reading never creates it.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import Any

from muscle50.domain.nutrition import NutrientField
from muscle50.domain.nutrition_targets import (
    ExactTarget,
    NutrientTarget,
    NutritionTargetError,
    NutritionTargets,
    RangeTarget,
    TargetKind,
)
from muscle50.infrastructure.decimal_text import decimal_from_text, decimal_to_text

SCHEMA_VERSION = 1

_KIND_KEYS: dict[TargetKind, frozenset[str]] = {
    TargetKind.EXACT: frozenset({"kind", "value"}),
    TargetKind.RANGE: frozenset({"kind", "minimum", "maximum"}),
    TargetKind.UNSET: frozenset({"kind"}),
}


class JsonNutritionTargetRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> NutritionTargets:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return NutritionTargets()
        try:
            document = json.loads(text)
            return _targets_from_document(document)
        except (ValueError, TypeError) as exc:
            raise NutritionTargetError(f"nutrition target file {self._path} is not valid: {exc}") from exc

    def save(self, targets: NutritionTargets) -> None:
        content = json.dumps(targets_document(targets), indent=2, ensure_ascii=True) + "\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()


def targets_document(targets: NutritionTargets) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "targets": {nutrient.value: target_payload(targets.get(nutrient)) for nutrient in NutrientField},
    }


def target_payload(target: NutrientTarget | None) -> dict[str, str]:
    if isinstance(target, ExactTarget):
        return {"kind": TargetKind.EXACT.value, "value": decimal_to_text(target.value)}
    if isinstance(target, RangeTarget):
        return {
            "kind": TargetKind.RANGE.value,
            "minimum": decimal_to_text(target.minimum),
            "maximum": decimal_to_text(target.maximum),
        }
    return {"kind": TargetKind.UNSET.value}


def _targets_from_document(document: Any) -> NutritionTargets:
    if not isinstance(document, dict) or set(document) != {"schema_version", "targets"}:
        raise ValueError("expected exactly the keys schema_version and targets")
    version = document["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {version!r}")
    entries = document["targets"]
    expected = {nutrient.value for nutrient in NutrientField}
    if not isinstance(entries, dict) or set(entries) != expected:
        raise ValueError(f"targets must list exactly {', '.join(sorted(expected))}")
    return NutritionTargets(
        **{nutrient.value: _target(nutrient, entries[nutrient.value]) for nutrient in NutrientField}
    )


def _target(nutrient: NutrientField, entry: Any) -> NutrientTarget | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str):
        raise ValueError(f"{nutrient.value}: expected an object with a kind")
    try:
        kind = TargetKind(entry["kind"])
    except ValueError as exc:
        raise ValueError(f"{nutrient.value}: unknown kind {entry['kind']!r}") from exc
    if set(entry) != _KIND_KEYS[kind]:
        raise ValueError(f"{nutrient.value}: a {kind.value} target has exactly {', '.join(sorted(_KIND_KEYS[kind]))}")
    if kind is TargetKind.EXACT:
        return ExactTarget(_decimal(nutrient, entry["value"]))
    if kind is TargetKind.RANGE:
        return RangeTarget(_decimal(nutrient, entry["minimum"]), _decimal(nutrient, entry["maximum"]))
    return None


def _decimal(nutrient: NutrientField, value: Any) -> Decimal:
    if not isinstance(value, str):
        # JSON numbers are refused so a value can never pass through a binary float.
        raise ValueError(f"{nutrient.value}: values must be decimal strings, got {value!r}")
    return decimal_from_text(value)
