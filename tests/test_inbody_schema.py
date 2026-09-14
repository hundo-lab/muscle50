from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from muscle50.infrastructure.sqlite.body_composition import apply_inbody_schema


def _artifact(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO inbody_raw_artifacts (
            provider, artifact_kind, relative_path, content_type, source_format,
            metadata_relative_path, source_type, source_fetched_at, sha256,
            byte_size, fetched_at_utc
        ) VALUES ('inbody', 'measurement_detail', 'raw/a.json', 'application/json',
                  'synthetic', 'raw/a.meta', 'inbody_synthetic', '2026-09-13T00:00:00Z',
                  'aaa', 10, '2026-09-13T00:00:00Z')
        """
    )


def _measurement(connection: sqlite3.Connection) -> int:
    result = connection.execute(
        """
        INSERT INTO body_composition_measurements (
            provider, canonical_fingerprint_version, canonical_fingerprint,
            measured_at, primary_raw_artifact_id, normalizer_version, imported_at_utc
        ) VALUES ('inbody', 1, 'same-canonical', '2026-09-13T07:00:00+09:00',
                  1, 1, '2026-09-13T00:01:00Z')
        """
    ).lastrowid
    assert result is not None
    return result


def _source_id(
    connection: sqlite3.Connection,
    measurement_id: int,
    *,
    source_type: str,
    record_id: str,
    primary: int = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO body_composition_source_identities (
            measurement_id, source_type, source_profile_key, identity_kind,
            source_record_id, is_primary
        ) VALUES (?, ?, 'profile-one', 'source_id', ?, ?)
        """,
        (measurement_id, source_type, record_id, primary),
    )


def test_source_identity_is_namespaced_and_canonical_fingerprint_is_not_unique(
    tmp_path: Path,
) -> None:
    with sqlite3.connect(tmp_path / "schema.sqlite3") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        apply_inbody_schema(connection)
        _artifact(connection)
        samsung_id = _measurement(connection)
        export_id = _measurement(connection)

        _source_id(
            connection,
            samsung_id,
            source_type="inbody_samsung_health",
            record_id="same-source-record-id",
        )
        _source_id(
            connection,
            export_id,
            source_type="inbody_export",
            record_id="same-source-record-id",
        )

        duplicate_id = _measurement(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _source_id(
                connection,
                duplicate_id,
                source_type="inbody_samsung_health",
                record_id="same-source-record-id",
            )


def test_source_fingerprint_is_unique_only_inside_source_namespace(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "schema.sqlite3") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        apply_inbody_schema(connection)
        _artifact(connection)
        first_id = _measurement(connection)
        second_id = _measurement(connection)
        third_id = _measurement(connection)
        insert = """
            INSERT INTO body_composition_source_identities (
                measurement_id, source_type, source_profile_key, identity_kind,
                source_fingerprint_version, source_fingerprint, is_primary
            ) VALUES (?, ?, 'profile-one', 'fingerprint', 1, 'same-fingerprint', 1)
        """
        connection.execute(insert, (first_id, "inbody_samsung_health"))
        connection.execute(insert, (second_id, "inbody_export"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, (third_id, "inbody_samsung_health"))


def test_measurement_cannot_have_two_primary_source_identities(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "schema.sqlite3") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        apply_inbody_schema(connection)
        _artifact(connection)
        measurement_id = _measurement(connection)
        _source_id(
            connection,
            measurement_id,
            source_type="inbody_samsung_health",
            record_id="official-a",
        )
        with pytest.raises(sqlite3.IntegrityError):
            _source_id(
                connection,
                measurement_id,
                source_type="inbody_export",
                record_id="official-b",
            )
