"""Developer-only Windows smoke entry point for a Galaxy companion export.

This deliberately is not wired into the shared ``muscle50`` CLI. It imports one user-provided
Samsung Health JSON export into an isolated feature-local SQLite database under MUSCLE50_HOME,
preserving RAW first and printing presence/status only unless ``--show-values`` is explicit.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from muscle50.application.inbody_source import InBodySourceError
from muscle50.application.sync_inbody import InBodySyncItem, SyncInBody
from muscle50.config import AppPaths, ConfigurationError
from muscle50.domain.inbody_normalization import InBodyNormalizationError
from muscle50.infrastructure.inbody.raw_store import InBodyRawStore
from muscle50.infrastructure.inbody.samsung_health import SamsungHealthInBodySource
from muscle50.infrastructure.sqlite.body_composition import SqliteBodyCompositionRepository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import one Samsung Health InBody diagnostic export")
    parser.add_argument("payload", type=Path, help="JSON exported by the Galaxy diagnostic companion")
    parser.add_argument(
        "--show-values",
        action="store_true",
        help="explicitly print normalized health values; disabled by default",
    )
    args = parser.parse_args(argv)

    try:
        payload_path = args.payload.expanduser().resolve(strict=True)
        _reject_repository_payload(payload_path)
        paths = AppPaths.from_environment()
        database_path = paths.root / "db" / "inbody-samsung-health-smoke.sqlite3"
        raw_root = paths.root / "raw" / "inbody" / "samsung_health"
        repository = SqliteBodyCompositionRepository(database_path)
        repository.migrate()
        result = SyncInBody(
            SamsungHealthInBodySource(payload_path),
            repository,
            InBodyRawStore(raw_root, paths.root, paths.tmp_dir),
        ).execute(refresh_existing=True)
    except (OSError, ConfigurationError, InBodySourceError, InBodyNormalizationError):
        print("Samsung Health import failed; no health values were logged.", file=sys.stderr)
        return 1

    print("Source: inbody_samsung_health")
    print(f"Records discovered: {result.listed_count}")
    print(f"Source UID present: {_presence_count(result.items, 'source_uid')}/{result.fetched_count}")
    print(f"measured_at parsed: {_presence_count(result.items, 'measured_at')}/{result.fetched_count}")
    print(f"SMM present: {_presence_count(result.items, 'smm')}/{result.fetched_count}")
    print(f"Weight present: {_presence_count(result.items, 'weight')}/{result.fetched_count}")
    print(f"PBF present: {_presence_count(result.items, 'pbf')}/{result.fetched_count}")
    print(f"BFM present: {_presence_count(result.items, 'bfm')}/{result.fetched_count}")
    print(f"Inserted: {result.created_count}")
    print(f"Already existing: {result.existing_count}")
    print(f"Changed RAW conflicts: {result.changed_count}")
    print(f"RAW list snapshot stored: {result.list_snapshot.relative_path}")
    print(f"RAW detail artifacts stored: {len(result.items)}")
    print(f"Normalized measurements available: {len(result.items)}")
    print(f"Smoke database: {database_path}")

    if args.show_values:
        for index, item in enumerate(result.items, start=1):
            measurement = item.measurement
            print(
                f"Record {index} values: weight_kg={measurement.weight_kg!r} "
                f"smm_kg={measurement.skeletal_muscle_mass_kg!r} "
                f"bfm_kg={measurement.body_fat_mass_kg!r} "
                f"pbf={measurement.body_fat_percent!r} bmi={measurement.bmi!r} "
                f"tbw_l={measurement.total_body_water_l!r} "
                f"bmr_kcal_per_day={measurement.basal_metabolic_rate_kcal_per_day!r}"
            )

    if result.changed_count:
        print(
            "A known Samsung UID had different RAW content. The new RAW was preserved and the "
            "normalized row was not overwritten.",
            file=sys.stderr,
        )
        return 2
    return 0


def _presence_count(items: tuple[InBodySyncItem, ...], field: str) -> int:
    def present(item: InBodySyncItem) -> bool:
        measurement = item.measurement
        if field == "source_uid":
            return measurement.source_identity.source_record_id is not None
        if field == "measured_at":
            return bool(measurement.measured_at)
        if field == "smm":
            return measurement.skeletal_muscle_mass_kg is not None
        if field == "weight":
            return measurement.weight_kg is not None
        if field == "pbf":
            return measurement.body_fat_percent is not None
        if field == "bfm":
            return measurement.body_fat_mass_kg is not None
        raise ValueError("unknown presence field")

    return sum(present(item) for item in items)


def _reject_repository_payload(path: Path) -> None:
    for candidate in (path.parent, *path.parents):
        if (candidate / ".git").exists():
            raise ConfigurationError("Samsung Health export must be stored outside a Git worktree")


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
