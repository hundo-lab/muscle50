"""Adapter that contains authentication for an approved network connector."""

from __future__ import annotations

from collections.abc import Callable

from muscle50.application.inbody_source import InBodyMeasurementReference
from muscle50.domain.body_composition import RawInBodyDocument, RawInBodyMeasurement
from muscle50.infrastructure.inbody.auth import (
    AuthenticatedInBodySession,
    InBodyAuthProvider,
    InBodyReauthenticationRequiredError,
    InBodySessionExpiredError,
)
from muscle50.infrastructure.inbody.connector import InBodyConnector


class AuthenticatedInBodySource:
    """Keep session/token policy out of the application and domain layers.

    This adapter is intentionally transport-only. It is not a production path
    until an official authentication and data contract is available.
    """

    def __init__(self, auth_provider: InBodyAuthProvider, connector: InBodyConnector) -> None:
        self._auth_provider = auth_provider
        self._connector = connector
        self._session: AuthenticatedInBodySession | None = None

    def list_measurements(self) -> RawInBodyDocument:
        return self._call_with_refresh(self._connector.list_measurements)

    def extract_measurement_references(self, document: RawInBodyDocument) -> tuple[InBodyMeasurementReference, ...]:
        return self._connector.extract_measurement_references(document)

    def get_measurement(self, reference: InBodyMeasurementReference) -> RawInBodyDocument:
        return self._call_with_refresh(lambda session: self._connector.get_measurement(session, reference))

    def extract_measurement(self, document: RawInBodyDocument) -> RawInBodyMeasurement:
        return self._connector.extract_measurement(document)

    def _session_or_authenticate(self) -> AuthenticatedInBodySession:
        if self._session is not None:
            return self._session
        session = self._auth_provider.load_cached_session()
        if session is None:
            session = self._auth_provider.authenticate()
            if session.expired:
                raise InBodyReauthenticationRequiredError
        elif session.expired:
            session = self._refresh_session(session)
        self._session = session
        return session

    def _refresh_session(self, session: AuthenticatedInBodySession) -> AuthenticatedInBodySession:
        refreshed = self._auth_provider.refresh_session(session)
        if refreshed.expired:
            raise InBodyReauthenticationRequiredError
        self._session = refreshed
        return refreshed

    def _call_with_refresh[T](self, operation: Callable[[AuthenticatedInBodySession], T]) -> T:
        session = self._session_or_authenticate()
        try:
            return operation(session)
        except InBodySessionExpiredError:
            refreshed = self._refresh_session(session)
            try:
                return operation(refreshed)
            except InBodySessionExpiredError:
                raise InBodyReauthenticationRequiredError from None
