"""Run one provider CLI process: no shell, a scrubbed environment, a time limit and a process-tree kill.

The CLIs start helper processes of their own, so on a timeout or Ctrl+C the whole tree is killed
(Windows: `taskkill /PID <pid> /T /F` without a shell; POSIX: the process group). stdin is the
prompt bytes, or DEVNULL when there is none, so a CLI never waits for a keyboard.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Removed from the child environment so each CLI uses its own subscription login, never an API key,
# and never sees muscle50's own settings (MUSCLE50_HOME and friends).
SCRUBBED_VARIABLES = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY"})
SCRUBBED_PREFIXES = ("MUSCLE50_",)


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    """None when the process was killed after the time limit."""
    stdout: bytes
    stderr: bytes
    timed_out: bool


class ProcessRunner(Protocol):
    def run(
        self, argv: Sequence[str], *, cwd: Path, stdin: bytes | None, timeout_s: float, env: Mapping[str, str]
    ) -> ProcessResult: ...


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in environ.items()
        if name.upper() not in SCRUBBED_VARIABLES and not name.upper().startswith(SCRUBBED_PREFIXES)
    }


class SubprocessRunner:
    def run(
        self, argv: Sequence[str], *, cwd: Path, stdin: bytes | None, timeout_s: float, env: Mapping[str, str]
    ) -> ProcessResult:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=sys.platform != "win32",
        )
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill_tree(process)
            stdout, stderr = _drain(process)
            return ProcessResult(None, stdout, stderr, True)
        except BaseException:  # KeyboardInterrupt included: never leave the CLI running
            kill_tree(process)
            _drain(process)
            raise
        return ProcessResult(process.returncode, stdout, stderr, False)


def kill_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
    else:
        with suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
    with suppress(OSError):
        process.kill()


def _drain(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    try:
        stdout, stderr = process.communicate(timeout=10)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return b"", b""
    return stdout or b"", stderr or b""
