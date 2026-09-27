from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from muscle50.application.inbody_repository import BodyCompositionRepository, InMemoryBodyCompositionRepository
from muscle50.application.inbody_source import InBodySourceError
from muscle50.application.sync_latest_inbody import NoInBodyMeasurementsError, SyncLatestInBodyMeasurement
from muscle50.domain.body_composition import RawInBodyDocument
from muscle50.domain.inbody_normalization import normalize_inbody_measurement
from muscle50.infrastructure.inbody.raw_store import InBodyRawArtifact, InBodyRawStore
from muscle50.infrastructure.inbody.synthetic import SyntheticInBodyConnector
from muscle50.infrastructure.sqlite.body_composition import SqliteBodyCompositionRepository

FIXTURES = Path(__file__).parent / "fixtures" / "inbody"


def _artifact() -> InBodyRawArtifact:
    return InBodyRawArtifact(
        relative_path="raw/a.json",
        metadata_relative_path="raw/a.meta",
        content_type="application/json",
        source_format="synthetic",
        sha256="a" * 64,
        byte_size=1,
        source_type="inbody_synthetic",
        source_fetched_at="2026-09-13T00:00:00+00:00",
    )


@pytest.fixture(params=["memory", "sqlite"])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> BodyCompositionRepository:
    if request.param == "memory":
        return InMemoryBodyCompositionRepository()
    sqlite_repository = SqliteBodyCompositionRepository(tmp_path / "db" / "muscle50.sqlite3")
    sqlite_repository.migrate()
    return sqlite_repository


def _use_case(tmp_path: Path, repository: BodyCompositionRepository) -> SyncLatestInBodyMeasurement:
    root = tmp_path / "private-muscle50"
    connector = SyntheticInBodyConnector.from_fixture(FIXTURES / "synthetic_full.json")
    return SyncLatestInBodyMeasurement(
        connector,
        repository,
        InBodyRawStore(root / "raw" / "inbody" / "measurements", root, root / "tmp"),
    )


def test_duplicate_sync_preserves_one_raw_document_and_one_measurement(
    tmp_path: Path, repository: BodyCompositionRepository
) -> None:
    first = _use_case(tmp_path, repository).execute()
    second = _use_case(tmp_path, repository).execute()

    assert first.created is True
    assert second.created is False
    assert second.measurement == first.measurement
    files = list((tmp_path / "private-muscle50" / "raw" / "inbody" / "measurements").rglob("*.json"))
    assert len(files) == 1
    assert files[0].read_bytes() == (FIXTURES / "synthetic_full.json").read_bytes()


def test_repository_identity_check_is_atomic_for_concurrent_saves(
    tmp_path: Path, repository: BodyCompositionRepository
) -> None:
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: _use_case(tmp_path, repository).execute(), range(4)))

    assert sum(result.created for result in results) == 1


def test_distinct_official_ids_are_not_merged_by_equal_fingerprint(
    repository: BodyCompositionRepository,
) -> None:
    connector = SyntheticInBodyConnector.from_fixture(FIXTURES / "synthetic_full.json")
    document = connector.latest_document()
    assert document is not None
    base = normalize_inbody_measurement(connector.extract_measurement(document))
    artifact = _artifact()
    first = replace(
        base,
        source_identity=replace(base.source_identity, source_record_id="official-a"),
    )
    second = replace(
        base,
        source_identity=replace(base.source_identity, source_record_id="official-b"),
    )

    assert repository.save(first, artifact).created is True
    assert repository.save(second, artifact).created is True


def test_idless_measurement_is_not_heuristically_merged_with_official_id(
    repository: BodyCompositionRepository,
) -> None:
    connector = SyntheticInBodyConnector.from_fixture(FIXTURES / "synthetic_without_id.json")
    document = connector.latest_document()
    assert document is not None
    base = normalize_inbody_measurement(connector.extract_measurement(document))
    artifact = _artifact()
    with_id = replace(
        base,
        source_identity=replace(
            base.source_identity,
            source_record_id="official-a",
            source_fingerprint_version=None,
            source_fingerprint=None,
        ),
    )
    assert with_id.canonical_identity is not None
    changed_payload_same_id = replace(
        with_id,
        canonical_identity=replace(with_id.canonical_identity, fingerprint="b" * 64),
    )

    assert repository.save(base, artifact).created is True
    assert repository.save(with_id, artifact).created is True
    assert repository.save(changed_payload_same_id, artifact).created is False


def test_raw_document_is_preserved_before_extraction_failure(tmp_path: Path) -> None:
    root = tmp_path / "private-muscle50"
    connector = SyntheticInBodyConnector(
        RawInBodyDocument(
            b"not-json",
            "application/json",
            "muscle50.synthetic.inbody.v1",
            "inbody_synthetic",
        )
    )
    use_case = SyncLatestInBodyMeasurement(
        connector,
        InMemoryBodyCompositionRepository(),
        InBodyRawStore(root / "raw" / "inbody" / "measurements", root, root / "tmp"),
    )

    try:
        use_case.execute()
    except InBodySourceError:
        pass
    else:  # pragma: no cover - documents the required failure
        raise AssertionError("invalid document must fail extraction")

    raw_files = list((root / "raw" / "inbody" / "measurements").rglob("*.json"))
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == b"not-json"


def test_no_measurement_is_reported_without_writing_raw(tmp_path: Path) -> None:
    root = tmp_path / "private-muscle50"
    use_case = SyncLatestInBodyMeasurement(
        SyntheticInBodyConnector(None),
        InMemoryBodyCompositionRepository(),
        InBodyRawStore(root / "raw" / "inbody" / "measurements", root, root / "tmp"),
    )

    try:
        use_case.execute()
    except NoInBodyMeasurementsError:
        pass
    else:  # pragma: no cover - documents the required failure
        raise AssertionError("empty connector must fail")

    assert not (root / "raw").exists()
