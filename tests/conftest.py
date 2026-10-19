from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

# The real value, read once before any test patches the environment (only the guard test compares against it).
REAL_LOCALAPPDATA = os.environ.get("LOCALAPPDATA")


@pytest.fixture(scope="session")
def real_local_app_data() -> str | None:
    return REAL_LOCALAPPDATA


@pytest.fixture(autouse=True)
def _isolated_muscle50_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test starts with MUSCLE50_HOME and LOCALAPPDATA inside its own temp dir.

    `AppPaths.from_environment` (src/muscle50/config.py) reads only these two variables, so with this fixture
    no test can resolve the real `%LOCALAPPDATA%\muscle50` by forgetting to set a home. A test that sets its own
    `MUSCLE50_HOME` (or deletes either variable) still works: its monkeypatch runs after this fixture.
    """
    isolated = tmp_path / "isolated-muscle50"
    monkeypatch.setenv("MUSCLE50_HOME", str(isolated / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(isolated / "localappdata"))
    yield
