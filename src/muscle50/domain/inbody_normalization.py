"""Pure normalization and identity logic for InBody connector output."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from muscle50.domain.body_composition import (
    CanonicalMeasurementIdentity,
    FieldProvenance,
    NormalizedBodyComposition,
    RawInBodyMeasurement,
    RawSegmentalMeasurement,
    SegmentalMeasurement,
    SourceField,
    SourceMeasurementIdentity,
)

_MASS_TO_KG = {
    "kg": Decimal("1"),
    "g": Decimal("0.001"),
    "lb": Decimal("0.45359237"),
    "lbs": Decimal("0.45359237"),
}
_ENERGY_TO_KCAL = {
    "kcal/day": Decimal("1"),
    "kcal/d": Decimal("1"),
    "kj/day": Decimal("0.239005736"),
    "kj/d": Decimal("0.239005736"),
}
_PERCENT_UNITS = {"%", "percent"}
_BMI_UNITS = {None, "", "kg/m2", "kg/m^2", "kg/m²"}
_RATIO_UNITS = {None, "", "ratio"}
_LEVEL_UNITS = {None, "", "level"}
_SCORE_UNITS = {None, "", "score"}


class InBodyNormalizationError(ValueError):
    """Raised when source data cannot be normalized without guessing."""


def normalize_inbody_measurement(raw: RawInBodyMeasurement) -> NormalizedBodyComposition:
    measured_at, measured_at_provenance = _timestamp(raw.measured_at)
    provenance = [measured_at_provenance]

    weight = _optional_mass("weight_kg", raw.weight, provenance)
    skeletal_muscle_mass = _optional_mass("skeletal_muscle_mass_kg", raw.skeletal_muscle_mass, provenance)
    body_fat_mass = _optional_mass("body_fat_mass_kg", raw.body_fat_mass, provenance)
    body_fat_percent = _optional_percent("body_fat_percent", raw.body_fat_percent, provenance)
    bmi = _optional_ratio("bmi", raw.bmi, provenance, _BMI_UNITS)
    waist_hip_ratio = _optional_ratio("waist_hip_ratio", raw.waist_hip_ratio, provenance, _RATIO_UNITS)
    visceral_fat_level = _optional_ratio("visceral_fat_level", raw.visceral_fat_level, provenance, _LEVEL_UNITS)
    basal_metabolic_rate = _optional_energy("basal_metabolic_rate_kcal_per_day", raw.basal_metabolic_rate, provenance)
    total_body_water = _optional_water("total_body_water_l", raw.total_body_water, provenance)
    protein = _optional_mass("protein_kg", raw.protein, provenance)
    minerals = _optional_mass("minerals_kg", raw.minerals, provenance)
    ecw_ratio = _optional_bounded_ratio("ecw_ratio", raw.ecw_ratio, provenance, _RATIO_UNITS, maximum=1)
    inbody_score = _optional_ratio("inbody_score", raw.inbody_score, provenance, _SCORE_UNITS)
    device_model = _optional_text("device_model", raw.device_model, provenance)
    segmental = tuple(_normalize_segment(item) for item in raw.segmental_measurements)

    source_id = _source_id(raw.source_record_id)
    profile_key = _profile_key(raw.source_profile_key)
    fingerprint = None
    if weight is not None and body_fat_percent is not None:
        fingerprint = measurement_fingerprint(
            measured_at=measured_at,
            weight_kg=weight,
            body_fat_percent=body_fat_percent,
        )
    elif source_id is None:
        raise InBodyNormalizationError(
            "fingerprint identity requires measured_at, weight, and body fat percent when source ID is absent"
        )
    source_type = _source_type(raw.source_type)
    source_identity = SourceMeasurementIdentity(
        source_type=source_type,
        source_profile_key=profile_key,
        source_record_id=source_id,
        source_fingerprint_version=1 if fingerprint is not None and source_id is None else None,
        source_fingerprint=fingerprint if source_id is None else None,
    )
    canonical_identity = (
        CanonicalMeasurementIdentity(fingerprint_version=1, fingerprint=fingerprint)
        if fingerprint is not None
        else None
    )
    return NormalizedBodyComposition(
        source_identity=source_identity,
        canonical_identity=canonical_identity,
        measured_at=measured_at,
        weight_kg=weight,
        skeletal_muscle_mass_kg=skeletal_muscle_mass,
        body_fat_mass_kg=body_fat_mass,
        body_fat_percent=body_fat_percent,
        bmi=bmi,
        waist_hip_ratio=waist_hip_ratio,
        visceral_fat_level=visceral_fat_level,
        basal_metabolic_rate_kcal_per_day=basal_metabolic_rate,
        total_body_water_l=total_body_water,
        protein_kg=protein,
        minerals_kg=minerals,
        ecw_ratio=ecw_ratio,
        inbody_score=inbody_score,
        device_model=device_model,
        segmental_measurements=segmental,
        metrics=(),
        provenance=tuple(provenance),
    )


def measurement_fingerprint(
    *,
    measured_at: str,
    weight_kg: float,
    body_fat_percent: float,
) -> str:
    canonical = {
        "fingerprint_version": 1,
        "measured_at": _fingerprint_timestamp(measured_at),
        # Fixed fields keep unrelated enrichment from changing identity. Values
        # are rounded to the device-facing precision to tolerate unit conversion.
        "stable_values": {
            "body_fat_percent": _canonical_number(body_fat_percent),
            "weight_kg": _canonical_number(weight_kg),
        },
    }
    encoded = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _timestamp(field: SourceField) -> tuple[str, FieldProvenance]:
    if not isinstance(field.value, str) or not field.value.strip():
        raise InBodyNormalizationError("measured_at must be a non-empty ISO 8601 string")
    text = field.value.strip()
    if re.search(r"[T ]\d{2}:\d{2}", text) is None:
        raise InBodyNormalizationError("measured_at must include a time; date-only values are not accepted")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InBodyNormalizationError("measured_at must be ISO 8601") from exc
    normalized = parsed.isoformat()
    return normalized, _provenance("measured_at", field, "ISO 8601 canonicalization; timezone not inferred")


def _optional_mass(name: str, field: SourceField | None, target: list[FieldProvenance]) -> float | None:
    if field is None:
        return None
    unit = _unit(field)
    if unit not in _MASS_TO_KG:
        raise InBodyNormalizationError(f"{name} has unsupported unit: {field.unit!r}")
    result = _number(field, name) * _MASS_TO_KG[unit]
    target.append(_provenance(name, field, f"{unit} to kg" if unit != "kg" else "identity"))
    return _finite_non_negative(result, name)


def _optional_water(name: str, field: SourceField | None, target: list[FieldProvenance]) -> float | None:
    if field is None:
        return None
    unit = _unit(field)
    if unit == "l":
        factor = Decimal("1")
    elif unit == "ml":
        factor = Decimal("0.001")
    else:
        raise InBodyNormalizationError(f"{name} has unsupported unit: {field.unit!r}")
    target.append(_provenance(name, field, f"{unit} to L" if unit != "l" else "identity"))
    return _finite_non_negative(_number(field, name) * factor, name)


def _optional_percent(name: str, field: SourceField | None, target: list[FieldProvenance]) -> float | None:
    if field is None:
        return None
    if _unit(field) not in _PERCENT_UNITS:
        raise InBodyNormalizationError(f"{name} has unsupported unit: {field.unit!r}")
    result = _finite_non_negative(_number(field, name), name)
    if result > 100:
        raise InBodyNormalizationError(f"{name} must be at most 100 percent")
    target.append(_provenance(name, field, "identity"))
    return result


def _optional_ratio(
    name: str,
    field: SourceField | None,
    target: list[FieldProvenance],
    allowed_units: set[str | None],
) -> float | None:
    if field is None:
        return None
    if _unit(field) not in allowed_units:
        raise InBodyNormalizationError(f"{name} has unsupported unit: {field.unit!r}")
    result = _finite_non_negative(_number(field, name), name)
    target.append(_provenance(name, field, "identity"))
    return result


def _optional_bounded_ratio(
    name: str,
    field: SourceField | None,
    target: list[FieldProvenance],
    allowed_units: set[str | None],
    *,
    maximum: float,
) -> float | None:
    result = _optional_ratio(name, field, target, allowed_units)
    if result is not None and result > maximum:
        raise InBodyNormalizationError(f"{name} must be at most {maximum}")
    return result


def _optional_energy(name: str, field: SourceField | None, target: list[FieldProvenance]) -> float | None:
    if field is None:
        return None
    unit = _unit(field)
    if unit not in _ENERGY_TO_KCAL:
        raise InBodyNormalizationError(f"{name} has unsupported unit: {field.unit!r}")
    result = _number(field, name) * _ENERGY_TO_KCAL[unit]
    target.append(_provenance(name, field, f"{unit} to kcal/day" if unit != "kcal/day" else "identity"))
    return _finite_non_negative(result, name)


def _optional_text(name: str, field: SourceField | None, target: list[FieldProvenance]) -> str | None:
    if field is None:
        return None
    if not isinstance(field.value, str) or not field.value.strip():
        raise InBodyNormalizationError(f"{name} must be non-empty text")
    target.append(_provenance(name, field, "trim whitespace"))
    return field.value.strip()


def _normalize_segment(item: RawSegmentalMeasurement) -> SegmentalMeasurement:
    provenance: list[FieldProvenance] = []
    name = f"segmental.{item.region}.{item.metric}"
    if item.metric.endswith("_mass"):
        value = _optional_mass(name, item.field, provenance)
        unit = "kg"
    elif item.metric.endswith("_percent"):
        value = _optional_percent(name, item.field, provenance)
        unit = "%"
    elif item.metric.endswith("body_water"):
        value = _optional_water(name, item.field, provenance)
        unit = "L"
    elif item.metric.endswith("ecw_ratio"):
        value = _optional_bounded_ratio(name, item.field, provenance, _RATIO_UNITS, maximum=1)
        unit = "ratio"
    elif item.metric.endswith("phase_angle"):
        value = _optional_scalar(name, item.field, provenance, {"deg", "degree", "degrees"})
        unit = "deg"
    elif item.metric.endswith("impedance"):
        value = _optional_scalar(name, item.field, provenance, {"ohm", "ω"})
        unit = "ohm"
    else:
        raise InBodyNormalizationError(f"unsupported segmental metric: {item.metric}")
    if value is None:  # pragma: no cover - the field is structurally required
        raise InBodyNormalizationError("segmental measurement value is required")
    return SegmentalMeasurement(
        region=item.region,
        metric=item.metric,
        value=value,
        unit=unit,
        provenance=provenance[0],
    )


def _optional_scalar(
    name: str,
    field: SourceField | None,
    target: list[FieldProvenance],
    allowed_units: set[str],
) -> float | None:
    if field is None:
        return None
    if _unit(field) not in allowed_units:
        raise InBodyNormalizationError(f"{name} has unsupported unit: {field.unit!r}")
    result = _finite_non_negative(_number(field, name), name)
    target.append(_provenance(name, field, "unit label canonicalization"))
    return result


def _number(field: SourceField, name: str) -> Decimal:
    if isinstance(field.value, bool) or field.value is None:
        raise InBodyNormalizationError(f"{name} must be numeric")
    try:
        return Decimal(str(field.value))
    except (InvalidOperation, ValueError) as exc:
        raise InBodyNormalizationError(f"{name} must be numeric") from exc


def _finite_non_negative(value: Decimal, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise InBodyNormalizationError(f"{name} must be finite and non-negative")
    return result


def _unit(field: SourceField) -> str | None:
    return field.unit.strip().lower() if isinstance(field.unit, str) else None


def _provenance(name: str, field: SourceField, transformation: str) -> FieldProvenance:
    if not field.path:
        raise InBodyNormalizationError(f"{name} source path is required")
    return FieldProvenance(name, field.path, field.value, field.unit, transformation)


def _source_id(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip()
    if not result:
        raise InBodyNormalizationError("source measurement ID cannot be blank")
    return result


def _profile_key(value: str) -> str:
    result = value.strip()
    if not result:
        raise InBodyNormalizationError("source profile key cannot be blank")
    return result


def _source_type(value: str) -> str:
    result = value.strip()
    if not result or not re.fullmatch(r"[a-z][a-z0-9_]*", result):
        raise InBodyNormalizationError("source type must be a non-empty lowercase identifier")
    return result


def _canonical_number(value: float) -> str:
    return format(Decimal(str(value)).quantize(Decimal("0.1")), "f")


def _fingerprint_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(UTC).isoformat()
