from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from muscle50.domain.body_composition import (
    RawInBodyMeasurement,
    RawSegmentalMeasurement,
    SourceField,
)
from muscle50.domain.inbody_normalization import (
    InBodyNormalizationError,
    normalize_inbody_measurement,
)
from muscle50.infrastructure.inbody.synthetic import SyntheticInBodyConnector

FIXTURES = Path(__file__).parent / "fixtures" / "inbody"


def _full_measurement() -> RawInBodyMeasurement:
    connector = SyntheticInBodyConnector.from_fixture(FIXTURES / "synthetic_full.json")
    document = connector.latest_document()
    assert document is not None
    return connector.extract_measurement(document)


def _without_id_measurement() -> RawInBodyMeasurement:
    connector = SyntheticInBodyConnector.from_fixture(FIXTURES / "synthetic_without_id.json")
    document = connector.latest_document()
    assert document is not None
    return connector.extract_measurement(document)


def test_normalizes_units_and_preserves_source_provenance() -> None:
    normalized = normalize_inbody_measurement(_full_measurement())

    assert normalized.measured_at == "2026-09-13T07:00:00+09:00"
    assert normalized.weight_kg == pytest.approx(70.000189)
    assert normalized.skeletal_muscle_mass_kg == 31.2
    assert normalized.body_fat_mass_kg == 14.1
    assert normalized.body_fat_percent == 20.1
    assert normalized.bmi == 22.9
    assert normalized.waist_hip_ratio == 0.84
    assert normalized.visceral_fat_level == 6
    assert normalized.basal_metabolic_rate_kcal_per_day == pytest.approx(1589.866)
    assert normalized.total_body_water_l == 39.8
    assert normalized.protein_kg == 10.8
    assert normalized.minerals_kg == 3.71
    assert normalized.ecw_ratio == 0.371
    assert normalized.inbody_score == 78
    assert normalized.device_model == "Synthetic InBody 570"
    assert normalized.segmental_measurements[0].value == 2.81
    weight_source = next(item for item in normalized.provenance if item.normalized_field == "weight_kg")
    assert weight_source.source_value == 154.324
    assert weight_source.source_unit == "lb"
    assert weight_source.source_path == "$.result.weight"
    assert weight_source.transformation == "lb to kg"


def test_official_id_is_preferred_but_fingerprint_is_always_present() -> None:
    normalized = normalize_inbody_measurement(_full_measurement())

    assert normalized.source_identity.key == (
        "inbody_synthetic",
        "synthetic-primary",
        "source_id",
        None,
        "synthetic-20260913-070000",
    )
    assert normalized.canonical_identity is not None
    assert len(normalized.canonical_identity.fingerprint) == 64


def test_fingerprint_is_deterministic_when_source_has_no_id() -> None:
    raw = _without_id_measurement()

    first = normalize_inbody_measurement(raw)
    second = normalize_inbody_measurement(raw)

    assert first.source_identity.source_record_id is None
    assert first.source_identity.key[:4] == (
        "inbody_synthetic",
        "synthetic-primary",
        "fingerprint",
        1,
    )
    assert first.source_identity.source_fingerprint == second.source_identity.source_fingerprint


def test_structured_identity_key_does_not_collide_when_components_contain_colons() -> None:
    base = normalize_inbody_measurement(_full_measurement()).source_identity
    first = replace(base, source_profile_key="profile:id:value", source_record_id="measurement")
    second = replace(base, source_profile_key="profile", source_record_id="value:id:measurement")

    assert first.key != second.key


def test_fingerprint_treats_equivalent_offset_timestamps_as_the_same_instant() -> None:
    raw = replace(_full_measurement(), source_record_id=None)
    same_instant = replace(raw, measured_at=SourceField("2026-09-12T22:00:00Z", None, "$.other.time"))

    assert (
        normalize_inbody_measurement(raw).canonical_identity
        == normalize_inbody_measurement(same_instant).canonical_identity
    )


def test_unknown_unit_is_rejected_instead_of_guessed() -> None:
    raw = replace(_full_measurement(), weight=SourceField(154.324, "stone", "$.result.weight"))

    with pytest.raises(InBodyNormalizationError, match="unsupported unit"):
        normalize_inbody_measurement(raw)


def test_bmi_accepts_unicode_squared_unit_spelling() -> None:
    raw = replace(_full_measurement(), bmi=SourceField(22.9, "kg/m²", "$.result.bmi"))

    assert normalize_inbody_measurement(raw).bmi == 22.9


def test_timestamp_only_fingerprint_is_rejected() -> None:
    raw = replace(
        _full_measurement(),
        source_record_id=None,
        weight=None,
        skeletal_muscle_mass=None,
        body_fat_mass=None,
        body_fat_percent=None,
    )

    with pytest.raises(InBodyNormalizationError, match="weight, and body fat percent"):
        normalize_inbody_measurement(raw)


def test_naive_source_timestamp_remains_naive() -> None:
    raw = _without_id_measurement()

    normalized = normalize_inbody_measurement(raw)

    assert normalized.measured_at == "2026-09-12T06:45:12"
    source = normalized.provenance[0]
    assert "timezone not inferred" in source.transformation


def test_date_only_timestamp_is_rejected_instead_of_assuming_midnight() -> None:
    raw = replace(_full_measurement(), measured_at=SourceField("2026-09-13", None, "$.result.date"))

    with pytest.raises(InBodyNormalizationError, match="date-only"):
        normalize_inbody_measurement(raw)


@pytest.mark.parametrize(
    ("metric", "field", "expected_unit"),
    [
        ("body_water", SourceField(6.2, "L", "$.segments.water"), "L"),
        ("ecw_ratio", SourceField(0.372, "ratio", "$.segments.ecw"), "ratio"),
        ("phase_angle", SourceField(5.8, "degree", "$.segments.phase"), "deg"),
        ("impedance", SourceField(512, "ohm", "$.segments.impedance"), "ohm"),
    ],
)
def test_extended_segmental_measurements_are_supported(metric: str, field: SourceField, expected_unit: str) -> None:
    raw = replace(
        _full_measurement(),
        segmental_measurements=(RawSegmentalMeasurement("trunk", metric, field),),
    )

    segment = normalize_inbody_measurement(raw).segmental_measurements[0]

    assert segment.metric == metric
    assert segment.unit == expected_unit


def test_official_id_does_not_require_fallback_fields() -> None:
    raw = replace(_full_measurement(), weight=None, body_fat_percent=None)

    normalized = normalize_inbody_measurement(raw)

    assert normalized.source_identity.source_record_id == "synthetic-20260913-070000"
    assert normalized.source_identity.source_fingerprint is None
    assert normalized.canonical_identity is None
