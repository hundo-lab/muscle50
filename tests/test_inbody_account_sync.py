from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest

from muscle50.application.inbody_repository import (
    BodyCompositionRepository,
    InMemoryBodyCompositionRepository,
)
from muscle50.application.sync_inbody import SyncInBody
from muscle50.domain.body_composition import RawInBodyDocument
from muscle50.infrastructure.inbody.auth import (
    AuthenticatedInBodySession,
    InBodyAuthServerError,
    InBodyInvalidCredentialsError,
    InBodyReauthenticationRequiredError,
    InBodySessionExpiredError,
)
from muscle50.infrastructure.inbody.authenticated_source import AuthenticatedInBodySource
from muscle50.infrastructure.inbody.connector import (
    InBodyMeasurementDetailError,
    InBodyMeasurementListError,
    InBodyResponseChangedError,
)
from muscle50.infrastructure.inbody.raw_store import InBodyRawStore
from muscle50.infrastructure.inbody.synthetic import (
    FakeAuthenticatedInBodySession,
    FakeInBodyAuthProvider,
    SyntheticInBodyConnector,
)
from muscle50.infrastructure.sqlite.body_composition import SqliteBodyCompositionRepository

FIXTURES = Path(__file__).parent / "fixtures" / "inbody"
LIST_FORMAT = "muscle50.synthetic.inbody.list.v1"
DETAIL_FORMAT = "muscle50.synthetic.inbody.v1"


class ExpiringListOnceConnector(SyntheticInBodyConnector):
    def __init__(
        self,
        document: RawInBodyDocument | None,
        *,
        list_document: RawInBodyDocument | None = None,
        detail_documents: Mapping[str, RawInBodyDocument] | None = None,
    ) -> None:
        super().__init__(
            document,
            list_document=list_document,
            detail_documents=detail_documents,
        )
        self._expired_once = False

    def list_measurements(self, session: AuthenticatedInBodySession) -> RawInBodyDocument:
        if not self._expired_once:
            self._expired_once = True
            raise InBodySessionExpiredError
        return super().list_measurements(session)


def _connector(list_name: str, *, include_first: bool = True) -> SyntheticInBodyConnector:
    details = {"measurement-2": FIXTURES / "synthetic_second.json"}
    if include_first:
        details["measurement-1"] = FIXTURES / "synthetic_full.json"
    return SyntheticInBodyConnector.from_account_fixtures(FIXTURES / list_name, details)


def _use_case(
    tmp_path: Path,
    auth_provider: FakeInBodyAuthProvider,
    connector: SyntheticInBodyConnector,
    repository: BodyCompositionRepository | None = None,
) -> SyncInBody:
    root = tmp_path / "private-muscle50"
    return SyncInBody(
        AuthenticatedInBodySource(auth_provider, connector),
        repository or InMemoryBodyCompositionRepository(),
        InBodyRawStore(root / "raw" / "inbody" / "measurements", root, root / "tmp"),
    )


def test_first_authentication_then_cached_session_reuse_and_duplicate_skip(tmp_path: Path) -> None:
    auth = FakeInBodyAuthProvider()
    connector = _connector("synthetic_account_list_one.json")
    repository = InMemoryBodyCompositionRepository()
    use_case = _use_case(tmp_path, auth, connector, repository)

    first = use_case.execute()
    second = use_case.execute()

    assert (first.listed_count, first.fetched_count, first.created_count) == (1, 1, 1)
    assert first.list_snapshot.kind == "measurement_list"
    assert "/inbody_synthetic/measurement_list/" in f"/{first.list_snapshot.relative_path}"
    assert (second.listed_count, second.fetched_count, second.created_count) == (1, 0, 0)
    assert second.existing_count == 1
    assert auth.authenticate_calls == 1
    assert auth.refresh_calls == 0
    assert connector.list_calls == 2
    assert connector.detail_calls == 1


def test_expired_cached_session_is_refreshed_without_full_authentication(tmp_path: Path) -> None:
    auth = FakeInBodyAuthProvider(
        cached_session=FakeAuthenticatedInBodySession(1, expired=True),
        refreshed_session=FakeAuthenticatedInBodySession(2),
    )
    connector = _connector("synthetic_account_list_one.json")

    result = _use_case(tmp_path, auth, connector).execute()

    assert result.created_count == 1
    assert auth.authenticate_calls == 0
    assert auth.refresh_calls == 1


def test_server_reported_session_expiry_refreshes_and_retries_once(tmp_path: Path) -> None:
    connector = ExpiringListOnceConnector.from_account_fixtures(
        FIXTURES / "synthetic_account_list_one.json",
        {"measurement-1": FIXTURES / "synthetic_full.json"},
    )
    auth = FakeInBodyAuthProvider(cached_session=FakeAuthenticatedInBodySession(1))

    result = _use_case(tmp_path, auth, connector).execute()

    assert result.created_count == 1
    assert auth.refresh_calls == 1
    assert connector.list_calls == 1


def test_refresh_failure_requires_explicit_reauthentication(tmp_path: Path) -> None:
    auth = FakeInBodyAuthProvider(
        cached_session=FakeAuthenticatedInBodySession(1, expired=True),
        refresh_error=InBodyReauthenticationRequiredError(),
    )
    connector = _connector("synthetic_account_list_one.json")

    with pytest.raises(InBodyReauthenticationRequiredError):
        _use_case(tmp_path, auth, connector).execute()

    assert auth.authenticate_calls == 0
    assert auth.refresh_calls == 1
    assert connector.list_calls == 0


@pytest.mark.parametrize(
    ("error_type", "expected_text"),
    [
        (InBodyInvalidCredentialsError, "authentication was rejected"),
        (InBodyAuthServerError, "authentication service is unavailable"),
    ],
)
def test_initial_authentication_failures_are_distinct_and_redacted(
    tmp_path: Path,
    error_type: type[InBodyInvalidCredentialsError] | type[InBodyAuthServerError],
    expected_text: str,
) -> None:
    auth = FakeInBodyAuthProvider(authenticate_error=error_type())
    connector = _connector("synthetic_account_list_one.json")

    with pytest.raises(error_type) as captured:
        _use_case(tmp_path, auth, connector).execute()

    assert expected_text in str(captured.value)
    assert "synthetic-secret" not in str(captured.value)
    assert connector.list_calls == 0


def test_measurement_list_failure_is_distinct(tmp_path: Path) -> None:
    connector = SyntheticInBodyConnector(None)

    with pytest.raises(InBodyMeasurementListError):
        _use_case(tmp_path, FakeInBodyAuthProvider(), connector).execute()

    assert connector.detail_calls == 0


def test_measurement_detail_failure_is_distinct_and_list_raw_is_preserved(tmp_path: Path) -> None:
    connector = _connector("synthetic_account_list_one.json", include_first=False)
    root = tmp_path / "private-muscle50"

    with pytest.raises(InBodyMeasurementDetailError):
        _use_case(tmp_path, FakeInBodyAuthProvider(), connector).execute()

    raw_files = list((root / "raw" / "inbody" / "measurements").rglob("*.json"))
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == (FIXTURES / "synthetic_account_list_one.json").read_bytes()


def test_changed_response_shape_is_distinct_from_transport_failure(tmp_path: Path) -> None:
    changed_list = RawInBodyDocument(b'{"unexpected": true}', "application/json", LIST_FORMAT, "inbody_synthetic")
    connector = SyntheticInBodyConnector(None, list_document=changed_list)
    root = tmp_path / "private-muscle50"

    with pytest.raises(InBodyResponseChangedError, match="response format"):
        _use_case(tmp_path, FakeInBodyAuthProvider(), connector).execute()

    raw_files = list((root / "raw" / "inbody" / "measurements").rglob("*.json"))
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == changed_list.document


def test_changed_detail_shape_is_preserved_before_response_error(tmp_path: Path) -> None:
    changed_detail = RawInBodyDocument(b'{"unexpected": true}', "application/json", DETAIL_FORMAT, "inbody_synthetic")
    connector = SyntheticInBodyConnector(
        None,
        list_document=RawInBodyDocument(
            (FIXTURES / "synthetic_account_list_one.json").read_bytes(),
            "application/json",
            LIST_FORMAT,
            "inbody_synthetic",
        ),
        detail_documents={"measurement-1": changed_detail},
    )
    root = tmp_path / "private-muscle50"

    with pytest.raises(InBodyResponseChangedError, match="measurement_detail"):
        _use_case(tmp_path, FakeInBodyAuthProvider(), connector).execute()

    raw_contents = {path.read_bytes() for path in (root / "raw" / "inbody" / "measurements").rglob("*.json")}
    assert changed_detail.document in raw_contents


def test_incremental_sync_fetches_only_new_official_measurement(tmp_path: Path) -> None:
    auth = FakeInBodyAuthProvider()
    repository = InMemoryBodyCompositionRepository()
    first_connector = _connector("synthetic_account_list_one.json")
    second_connector = _connector("synthetic_account_list_two.json")

    first = _use_case(tmp_path, auth, first_connector, repository).execute()
    second = _use_case(tmp_path, auth, second_connector, repository).execute()

    assert first.created_count == 1
    assert (second.listed_count, second.fetched_count, second.created_count) == (2, 1, 1)
    assert second.existing_count == 1
    assert second_connector.detail_calls == 1
    assert second.items[0].measurement.source_identity.source_record_id == "synthetic-20260914-071500"


def test_refresh_existing_preserves_changed_raw_without_mutating_normalized_row(tmp_path: Path) -> None:
    database_path = tmp_path / "db" / "muscle50.sqlite3"
    repository = SqliteBodyCompositionRepository(database_path)
    repository.migrate()
    auth = FakeInBodyAuthProvider()
    first_connector = _connector("synthetic_account_list_one.json")
    first = _use_case(tmp_path, auth, first_connector, repository).execute()
    original_weight = first.items[0].measurement.weight_kg

    changed_bytes = (FIXTURES / "synthetic_full.json").read_bytes().replace(b"154.324", b"155.324")
    changed_connector = SyntheticInBodyConnector(
        None,
        list_document=RawInBodyDocument(
            (FIXTURES / "synthetic_account_list_one.json").read_bytes(),
            "application/json",
            LIST_FORMAT,
            "inbody_synthetic",
        ),
        detail_documents={
            "measurement-1": RawInBodyDocument(
                changed_bytes,
                "application/json",
                DETAIL_FORMAT,
                "inbody_synthetic",
            )
        },
    )

    refreshed = _use_case(tmp_path, auth, changed_connector, repository).execute(refresh_existing=True)

    assert (refreshed.fetched_count, refreshed.created_count, refreshed.existing_count) == (1, 0, 1)
    assert refreshed.items[0].measurement.weight_kg == original_weight
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM body_composition_measurements").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM inbody_raw_artifacts").fetchone()[0] == 2
        assert connection.execute("SELECT DISTINCT artifact_kind FROM inbody_raw_artifacts").fetchall() == [
            ("measurement_detail",)
        ]
        assert connection.execute("SELECT COUNT(*) FROM body_composition_raw_artifact_links").fetchone()[0] == 2


def test_fake_session_repr_never_contains_session_material() -> None:
    session = FakeAuthenticatedInBodySession(123)

    assert repr(session) == "FakeAuthenticatedInBodySession(<redacted>)"
