"""Synthetic InBody rows for the `inbody trend` tests and the neighbour goldens.

Rows are saved through the real ``SqliteBodyCompositionRepository.save`` so the stored text and
REAL columns are exactly what `inbody sync` would write. Synthetic values only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from muscle50.domain.body_composition import NormalizedBodyComposition, SourceMeasurementIdentity
from muscle50.infrastructure.inbody.raw_store import InBodyRawArtifact
from muscle50.infrastructure.sqlite.body_composition import SqliteBodyCompositionRepository

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "inbody_trend_golden"
SOURCE_TYPE = "inbody_samsung_health"


def golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_bytes().decode("utf-8")


def measurement(
    record_id: str,
    measured_at: str,
    *,
    weight: float | None = None,
    smm: float | None = None,
    bfm: float | None = None,
    pbf: float | None = None,
    source_type: str = SOURCE_TYPE,
) -> NormalizedBodyComposition:
    """A stored-shape measurement with only the four trend metrics set."""
    return NormalizedBodyComposition(
        source_identity=SourceMeasurementIdentity(source_type, "synthetic-profile", record_id, None, None),
        canonical_identity=None,
        measured_at=measured_at,
        weight_kg=weight,
        skeletal_muscle_mass_kg=smm,
        body_fat_mass_kg=bfm,
        body_fat_percent=pbf,
        bmi=None,
        waist_hip_ratio=None,
        visceral_fat_level=None,
        basal_metabolic_rate_kcal_per_day=None,
        total_body_water_l=None,
        protein_kg=None,
        minerals_kg=None,
        ecw_ratio=None,
        inbody_score=None,
        device_model=None,
        segmental_measurements=(),
        metrics=(),
        provenance=(),
    )


def save_measurements(database: Path, items: Sequence[NormalizedBodyComposition]) -> None:
    """Save each row in order (so stored ids follow the sequence) on an already-migrated database."""
    repository = SqliteBodyCompositionRepository(database)
    for item in items:
        record_id = item.source_identity.source_record_id or "no-id"
        relative_path = f"raw/inbody/samsung_health/synthetic/{record_id}.json"
        artifact = InBodyRawArtifact(
            relative_path=relative_path,
            metadata_relative_path=f"{relative_path}.meta",
            content_type="application/json",
            source_format="synthetic",
            sha256=hashlib.sha256(record_id.encode("utf-8")).hexdigest(),
            byte_size=2,
            source_type=item.source_identity.source_type,
            source_fetched_at="2026-10-01T00:00:00+00:00",
            source_record_id=record_id,
        )
        repository.save(item, artifact)


# Rows added to the recommend database for the neighbour goldens (AC9): InBody rows must not
# change recommend or analytics output.
NEIGHBOUR_ROWS = (
    measurement("neighbour-1", "2026-03-02T08:10:00+09:00", weight=80.0, smm=36.0, bfm=15.0, pbf=18.8),
    measurement("neighbour-2", "2026-03-16T07:30:00+09:00", weight=80.6, smm=36.5, bfm=None, pbf=18.7),
)


# The spec example (AC1): three dates, body fat mass and PBF missing on the last one.
AC1_ROWS = (
    measurement("synthetic-1", "2026-07-02T08:10:00+09:00", weight=80.0, smm=36.0, bfm=15.0, pbf=18.8),
    measurement("synthetic-2", "2026-08-05T08:05:00+09:00", weight=80.6, smm=36.5, bfm=15.1, pbf=18.7),
    measurement("synthetic-3", "2026-09-16T16:43:00+09:00", weight=81.0, smm=36.9),
)


def migrated_database(root: Path) -> Path:
    """`<root>/db/muscle50.sqlite3`, migrated by every migration file, with no rows."""
    path = root / "db" / "muscle50.sqlite3"
    SqliteBodyCompositionRepository(path).migrate()
    return path
