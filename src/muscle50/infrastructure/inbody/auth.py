"""Authentication boundary for an approved InBody network integration.

Only the infrastructure source wrapper sees an opaque session and its expiry
state. A future network adapter owns credentials, tokens, cookies, secure
persistence, refresh, and redaction; none belong in application/domain models.
"""

from __future__ import annotations

from typing import Protocol


class InBodyAuthenticationError(RuntimeError):
    """Base class for safe-to-display authentication failures."""

    _safe_message = "InBody authentication failed"

    def __init__(self) -> None:
        super().__init__(self._safe_message)


class InBodyInvalidCredentialsError(InBodyAuthenticationError):
    _safe_message = "InBody authentication was rejected"


class InBodyAuthServerError(InBodyAuthenticationError):
    _safe_message = "InBody authentication service is unavailable"


class InBodySessionExpiredError(InBodyAuthenticationError):
    _safe_message = "InBody session expired"


class InBodyReauthenticationRequiredError(InBodyAuthenticationError):
    _safe_message = "InBody requires user reauthentication"


class AuthenticatedInBodySession(Protocol):
    """Opaque authenticated state; token/cookie contents are adapter-private."""

    @property
    def expired(self) -> bool: ...


class InBodyAuthProvider(Protocol):
    """Own secure session persistence and official authentication mechanics."""

    def load_cached_session(self) -> AuthenticatedInBodySession | None:
        """Load reusable protected state without exposing its secret material."""
        ...

    def authenticate(self) -> AuthenticatedInBodySession:
        """Perform the official initial user authorization flow and cache it."""
        ...

    def refresh_session(self, session: AuthenticatedInBodySession) -> AuthenticatedInBodySession:
        """Refresh official session state or require explicit reauthentication."""
        ...
