"""Filesystem configuration for local-only fitness data."""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(RuntimeError):
    """Raised when a safe local data directory cannot be selected."""


@dataclass(frozen=True)
class AppPaths:
    root: Path
    auth_dir: Path
    raw_dir: Path
    database_path: Path
    tmp_dir: Path

    @classmethod
    def from_environment(cls) -> AppPaths:
        override = os.environ.get("MUSCLE50_HOME")
        if override:
            root = Path(override).expanduser()
        else:
            local_app_data = os.environ.get("LOCALAPPDATA")
            if not local_app_data:
                raise ConfigurationError("LOCALAPPDATA is not set; refusing to store private data in the repository")
            root = Path(local_app_data) / "muscle50"

        root = root.resolve()
        _reject_git_worktree(root)
        return cls(
            root=root,
            auth_dir=root / "auth" / "garmin",
            raw_dir=root / "raw" / "garmin" / "activities",
            database_path=root / "db" / "muscle50.sqlite3",
            tmp_dir=root / "tmp",
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.root,
            self.auth_dir,
            self.raw_dir,
            self.database_path.parent,
            self.tmp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            # Windows permissions are primarily controlled through ACLs.
            with suppress(OSError):
                directory.chmod(0o700)


def _reject_git_worktree(path: Path) -> None:
    """Prevent an accidental MUSCLE50_HOME inside a Git worktree."""
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            raise ConfigurationError("MUSCLE50_HOME must be outside a Git worktree")
