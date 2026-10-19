"""The autouse fixture of tests/conftest.py keeps every test away from the real muscle50 home."""

from __future__ import annotations

from pathlib import Path

import pytest

from muscle50.config import AppPaths


def _under(path: Path, parent: Path) -> bool:
    return parent.resolve() in path.resolve().parents or path.resolve() == parent.resolve()


def test_the_default_home_is_under_the_pytest_temp_dir_not_the_real_local_app_data(
    tmp_path_factory: pytest.TempPathFactory, real_local_app_data: str | None
) -> None:
    root = AppPaths.from_environment().root
    assert _under(root, tmp_path_factory.getbasetemp())
    if real_local_app_data:
        # The pytest temp dir itself is usually under the real %LOCALAPPDATA%\Temp: only the real muscle50 home matters.
        assert not _under(root, Path(real_local_app_data) / "muscle50")


def test_without_muscle50_home_the_local_app_data_fallback_is_isolated_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory, real_local_app_data: str | None
) -> None:
    monkeypatch.delenv("MUSCLE50_HOME")
    root = AppPaths.from_environment().root
    assert root.name == "muscle50" and _under(root, tmp_path_factory.getbasetemp())
    if real_local_app_data:
        assert not _under(root, Path(real_local_app_data) / "muscle50")


def test_a_test_can_still_set_its_own_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "mine"))
    assert AppPaths.from_environment().root == tmp_path / "mine"
