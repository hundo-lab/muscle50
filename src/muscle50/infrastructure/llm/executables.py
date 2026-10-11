"""Find each provider CLI once, at `telegram run` start.

The configured absolute path wins; otherwise the name is looked up on PATH. On Windows only a real
`.exe` is accepted (any letter case, `shutil.which` returns `claude.EXE`): Python does not quote
arguments for `cmd.exe`, so a `.cmd`/`.bat`/`.ps1` shim would mangle `--tools ""` and the schema JSON.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from muscle50.domain.llm_settings import ProviderName

ResolveFailure = Literal["not_found", "executable_not_supported"]


@dataclass(frozen=True)
class ResolvedExecutable:
    provider: ProviderName
    path: str | None
    failure: ResolveFailure | None

    def log_text(self) -> str:
        if self.path is not None:
            return f"{self.provider.value} ({self.path})"
        if self.failure == "executable_not_supported":
            return f"{self.provider.value} (not an .exe; set {self.provider.value}.executable)"
        return f"{self.provider.value} (not found)"


def resolve_executable(
    provider: ProviderName,
    configured: str | None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    is_file: Callable[[Path], bool] = Path.is_file,
    windows: bool = sys.platform == "win32",
) -> ResolvedExecutable:
    candidate = configured if configured is not None else which(provider.value)
    if candidate is None or not is_file(Path(candidate)):
        return ResolvedExecutable(provider, None, "not_found")
    if windows and Path(candidate).suffix.lower() != ".exe":
        return ResolvedExecutable(provider, None, "executable_not_supported")
    return ResolvedExecutable(provider, candidate, None)
