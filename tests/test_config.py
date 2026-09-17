from __future__ import annotations

from pathlib import Path

import pytest

from muscle50.config import AppPaths, ConfigurationError


def test_default_data_root_uses_local_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MUSCLE50_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    paths = AppPaths.from_environment()

    assert paths.root == (tmp_path / "muscle50").resolve()
    assert paths.database_path.parent == paths.root / "db"
    assert paths.recovery_raw_dir == paths.root / "raw" / "garmin" / "recovery"


def test_missing_local_app_data_is_not_replaced_with_repo_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MUSCLE50_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with pytest.raises(ConfigurationError, match="LOCALAPPDATA"):
        AppPaths.from_environment()


def test_data_root_inside_git_worktree_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "private"))

    with pytest.raises(ConfigurationError, match="outside a Git worktree"):
        AppPaths.from_environment()
