"""Run one muscle50 CLI command in this process and capture what it prints.

The bot's replies are therefore the CLI's own output, byte for byte. stdout and stderr are
swapped for in-memory buffers and stdin for an empty one (a prompt such as a Garmin login then
raises EOFError instead of waiting for a keyboard nobody is at). All three are restored in
``finally``. The swap is process-global, which is safe only because the bot handles one command
at a time; no thread may run a command concurrently.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Callable, Sequence

from muscle50.application.telegram_bot import CommandOutcome


class InProcessCliRunner:
    def __init__(self, main: Callable[[Sequence[str]], int]) -> None:
        self._main = main

    def run(self, argv: Sequence[str]) -> CommandOutcome:
        stdout, stderr = io.StringIO(), io.StringIO()
        saved = sys.stdout, sys.stderr, sys.stdin
        sys.stdout, sys.stderr, sys.stdin = stdout, stderr, io.StringIO()
        try:
            try:
                code = self._main(list(argv))
                usage_error = False
            except SystemExit as exc:  # argparse refused the argv
                code = exc.code if isinstance(exc.code, int) else 2
                usage_error = True
        finally:
            sys.stdout, sys.stderr, sys.stdin = saved
        return CommandOutcome(code, stdout.getvalue(), stderr.getvalue(), usage_error)
