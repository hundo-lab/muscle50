"""Nutrition targets as one small JSON document under the muscle50 home.

Targets are a user setting, not nutrition fact history, so they need no SQLite table or
migration. The file is versioned, written atomically, and read strictly: values are canonical
decimal strings (never JSON numbers), every nutrient is listed with an explicit kind, and an
unreadable file is an error instead of silently meaning "no targets". A missing file means no
target has been set yet; reading never creates it.

LDL Nutrients v1: schema 2 adds ``saturated_fat_g`` and ``fiber_g`` after the four nutrients. It is
written only while one of them is set; otherwise the file stays schema 1, byte for byte as before
(the aerobic-guide goal file does the same). Each schema has its exact key set, so schema 1 with an
LDL key, or schema 2 without both, is refused. An older muscle50 refuses a schema 2 file.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import Any

from muscle50.domain.nutrition import NutrientField, OptionalNutrient
from muscle50.domain.nutrition_targets import (
    ExactTarget,
    FiberTarget,
    LdlTargetKind,
    LdlTargets,
    NutrientTarget,
    NutritionTargetError,
    NutritionTargets,
    RangeTarget,
    SaturatedFatTarget,
    TargetKind,
)
from muscle50.infrastructure.decimal_text import decimal_from_text, decimal_to_text

SCHEMA_VERSION = 1
LDL_SCHEMA_VERSION = 2

_KIND_KEYS: dict[TargetKind, frozenset[str]] = {
    TargetKind.EXACT: frozenset({"kind", "value"}),
    TargetKind.RANGE: frozenset({"kind", "minimum", "maximum"}),
    TargetKind.UNSET: frozenset({"kind"}),
}
_UNSET = TargetKind.UNSET.value
_SATURATED_FAT_KEYS = frozenset({"kind", "value", "meal_note_percent"})
_FIBER_KEYS = frozenset({"kind", "value"})


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
    if not targets.ldl.is_set:
        return {
            "schema_version": SCHEMA_VERSION,
            "targets": {nutrient.value: target_payload(targets.get(nutrient)) for nutrient in NutrientField},
        }
    return {"schema_version": LDL_SCHEMA_VERSION, "targets": targets_payload_with_ldl(targets)}


def targets_payload_with_ldl(targets: NutritionTargets) -> dict[str, Any]:
    """The four nutrients, then saturated fat and fiber (schema 2 and `target show --json` with an LDL target)."""
    payload: dict[str, Any] = {nutrient.value: target_payload(targets.get(nutrient)) for nutrient in NutrientField}
    payload[OptionalNutrient.SATURATED_FAT_G.value] = saturated_fat_target_payload(targets.ldl.saturated_fat_g)
    payload[OptionalNutrient.FIBER_G.value] = fiber_target_payload(targets.ldl.fiber_g)
    return payload


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


def saturated_fat_target_payload(target: SaturatedFatTarget | None) -> dict[str, str | None]:
    if target is None:
        return {"kind": _UNSET}
    return {
        "kind": LdlTargetKind.MAX_ENERGY_PERCENT.value,
        "value": decimal_to_text(target.max_energy_percent),
        "meal_note_percent": decimal_to_text(target.meal_note_percent)
        if target.meal_note_percent is not None
        else None,
    }


def fiber_target_payload(target: FiberTarget | None) -> dict[str, str]:
    if target is None:
        return {"kind": _UNSET}
    return {"kind": LdlTargetKind.MINIMUM.value, "value": decimal_to_text(target.minimum)}


def _targets_from_document(document: Any) -> NutritionTargets:
    if not isinstance(document, dict) or set(document) != {"schema_version", "targets"}:
        raise ValueError("expected exactly the keys schema_version and targets")
    version = document["schema_version"]
    if type(version) is not int or version not in (SCHEMA_VERSION, LDL_SCHEMA_VERSION):
        raise ValueError(f"unsupported schema_version {version!r}")
    entries = document["targets"]
    expected = {nutrient.value for nutrient in NutrientField}
    if version == LDL_SCHEMA_VERSION:
        expected |= {nutrient.value for nutrient in OptionalNutrient}
    if not isinstance(entries, dict) or set(entries) != expected:
        raise ValueError(f"targets must list exactly {', '.join(sorted(expected))}")
    values: dict[str, NutrientTarget | None] = {
        nutrient.value: _target(nutrient, entries[nutrient.value]) for nutrient in NutrientField
    }
    if version == SCHEMA_VERSION:
        return NutritionTargets(**values)
    ldl = LdlTargets(
        _saturated_fat_target(entries[OptionalNutrient.SATURATED_FAT_G.value]),
        _fiber_target(entries[OptionalNutrient.FIBER_G.value]),
    )
    if not ldl.is_set:
        raise ValueError("schema_version 2 is only written with a saturated_fat_g or fiber_g target")
    return NutritionTargets(**values).with_ldl(ldl)


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
        return ExactTarget(_decimal(nutrient.value, entry["value"]))
    if kind is TargetKind.RANGE:
        return RangeTarget(_decimal(nutrient.value, entry["minimum"]), _decimal(nutrient.value, entry["maximum"]))
    return None


def _ldl_entry(name: str, entry: Any, kind: LdlTargetKind, keys: frozenset[str]) -> dict[str, Any] | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str):
        raise ValueError(f"{name}: expected an object with a kind")
    if entry["kind"] == _UNSET:
        if set(entry) != {"kind"}:
            raise ValueError(f"{name}: an unset target has exactly kind")
        return None
    if entry["kind"] != kind.value:
        raise ValueError(f"{name}: unknown kind {entry['kind']!r}")
    if set(entry) != keys:
        raise ValueError(f"{name}: a {kind.value} target has exactly {', '.join(sorted(keys))}")
    return entry


def _saturated_fat_target(entry: Any) -> SaturatedFatTarget | None:
    name = OptionalNutrient.SATURATED_FAT_G.value
    checked = _ldl_entry(name, entry, LdlTargetKind.MAX_ENERGY_PERCENT, _SATURATED_FAT_KEYS)
    if checked is None:
        return None
    note = checked["meal_note_percent"]
    return SaturatedFatTarget(_decimal(name, checked["value"]), _decimal(name, note) if note is not None else None)


def _fiber_target(entry: Any) -> FiberTarget | None:
    name = OptionalNutrient.FIBER_G.value
    checked = _ldl_entry(name, entry, LdlTargetKind.MINIMUM, _FIBER_KEYS)
    return None if checked is None else FiberTarget(_decimal(name, checked["value"]))


def _decimal(name: str, value: Any) -> Decimal:
    if not isinstance(value, str):
        # JSON numbers are refused so a value can never pass through a binary float.
        raise ValueError(f"{name}: values must be decimal strings, got {value!r}")
    return decimal_from_text(value)
