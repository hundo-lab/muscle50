"""`telegram\\run-YYYY-MM.log`: what `telegram run` printed to the console, plus why it stopped.

Telegram LLM Reliability v2.4. A bot that stopped overnight left nothing to read once its console window
was gone. This file keeps the console lines (already redacted by the caller) and four file-only lines:
`run started pid=<n> llm=<on|off>`, `alive` every 30 minutes, `run stopped: <reason>`.

Rules held here:

- Append only; muscle50 never deletes or rotates it (one small file per month).
- One line per write; the file is opened, appended and closed each time, so a line survives a kill and the
  Windows console-event thread can write while the main thread does.
- ASCII only (`backslashreplace`), like the console. No message text and no token: the caller passes the
  console lines, which carry neither.
- A mkdir or write failure is ignored: the run log must never stop the bot.
- The month comes from the injected clock on every write, so a run that crosses midnight of the 1st switches
  files.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

ALIVE_INTERVAL_S = 1800
"""Seconds between two `alive` lines (checked between loop iterations, so a long LLM call leaves a gap)."""

# Console control events that end the process: CTRL_BREAK, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN.
# CTRL_C (0) is left alone: Python's KeyboardInterrupt still stops the bot the way it always did.
LOGGED_CONSOLE_EVENTS = frozenset({1, 2, 5, 6})


class RunLog:
    def __init__(
        self, directory: Path, now: Callable[[], datetime], *, alive_interval_s: float = ALIVE_INTERVAL_S
    ) -> None:
        self._directory = directory
        self._now = now
        self._alive_interval_s = alive_interval_s
        self._last_alive = now()
        self._lock = threading.Lock()

    def started(self, pid: int, *, llm_on: bool) -> None:
        self._last_alive = self._now()
        self.event(f"run started pid={pid} llm={'on' if llm_on else 'off'}")

    def line(self, text: str) -> None:
        """A console line (already redacted). A multi-line text is written one timestamped line per line."""
        for part in text.split("\n"):
            self._write(part)

    def event(self, text: str) -> None:
        """A file-only line (never printed to the console)."""
        self._write(text)

    def stopped(self, reason: str) -> None:
        self.event(f"run stopped: {reason}")

    def tick(self) -> None:
        """Called between loop iterations: writes `alive` when `alive_interval_s` has passed since the last one."""
        try:
            now = self._now()
            if (now - self._last_alive).total_seconds() < self._alive_interval_s:
                return
            self._last_alive = now
            self.event("alive")
        except Exception:  # a clock or write problem must not reach the bot
            return

    def _write(self, text: str) -> None:
        try:
            now = self._now()
            safe = text.encode("ascii", "backslashreplace").decode("ascii")
            stamp = now.strftime("%Y-%m-%d %H:%M:%S")
            with self._lock:
                self._directory.mkdir(parents=True, exist_ok=True)
                path = self._directory / f"run-{now:%Y-%m}.log"
                with path.open("a", encoding="ascii", newline="\n") as handle:
                    handle.write(f"{stamp} {safe}\n")
        except Exception:  # an OS error, a closed file or a failing clock: the run log never raises
            return


def console_event_handler(on_event: Callable[[int], None]) -> Callable[[int], int]:
    """The function Windows calls on a console control event.

    It reports events 1, 2, 5 and 6 to `on_event`, swallows anything `on_event` raises, and returns 0 (False)
    for every event, so the next handler (Python's own, then the default one) still runs: the process ends
    exactly as it did without this hook, and CTRL_C still raises KeyboardInterrupt.
    """

    def handler(event: int) -> int:
        if event in LOGGED_CONSOLE_EVENTS:
            with suppress(Exception):
                on_event(event)
        return 0

    return handler


# The ctypes callback must stay referenced for as long as it is registered.
_CALLBACKS: list[Any] = []


def install_console_event_hook(on_event: Callable[[int], None], *, platform: str = sys.platform) -> Callable[[], None]:
    """Registers `console_event_handler(on_event)` with `SetConsoleCtrlHandler` (Windows only; best effort).

    Returns a function that removes it. It never raises: on another OS, without `ctypes.windll`, or when
    Windows refuses, nothing is registered and the returned function does nothing.
    """

    def nothing() -> None:
        return None

    try:
        windll = getattr(ctypes, "windll", None)
        winfunctype = getattr(ctypes, "WINFUNCTYPE", None)
        if platform != "win32" or windll is None or winfunctype is None:
            return nothing
        routine = winfunctype(ctypes.c_int, ctypes.c_uint)(console_event_handler(on_event))
        kernel32 = windll.kernel32
        if not kernel32.SetConsoleCtrlHandler(routine, 1):
            return nothing
        _CALLBACKS.append(routine)

        def remove() -> None:
            try:
                kernel32.SetConsoleCtrlHandler(routine, 0)
            except Exception:
                return None
            finally:
                if routine in _CALLBACKS:
                    _CALLBACKS.remove(routine)

        return remove
    except Exception:
        return nothing
