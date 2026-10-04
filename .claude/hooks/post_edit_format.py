"""PostToolUse hook for Edit/Write/MultiEdit in muscle50: keep LF and ruff-format touched files.

Claude Code passes the hook input as JSON on stdin (`tool_input.file_path`). The tool already
ran, so this hook never blocks; it exits 0 and, when it changed the file or skipped formatting,
prints `hookSpecificOutput.additionalContext` JSON so Claude knows the file on disk changed.

Rules (memory note "muscle50 formatting and line endings", docs/HANDOFF.md checks sections):
- The repo is LF (`.gitattributes`: `* text=auto eol=lf`). Windows tools can write CRLF, so a
  file that gained CRLF is converted back to LF. A file that already had CRLF at HEAD is left
  alone (not this task's change).
- `ruff format` runs on the edited .py file only, and only when that file is new or was already
  ruff-formatted at HEAD. Several files on main are not ruff-formatted (for example
  `presentation/terminal.py`); formatting them whole would rewrite unrelated lines, so the
  hook skips them and says so.

Ruff runs as `.venv/Scripts/ruff.exe` when the worktree has one, else `uv run --frozen --extra dev ruff`.
Standard library only; runs on Python 3.9+.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_TIMEOUT_SECONDS = 110


def _git(top: Path | None, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    command = ["git", *(["-C", str(top)] if top else []), *args]
    return subprocess.run(command, capture_output=True, cwd=cwd, timeout=30)


def _repo_root(path: Path) -> Path | None:
    result = _git(None, "rev-parse", "--show-toplevel", cwd=path.parent)
    if result.returncode != 0:
        return None
    return Path(result.stdout.decode("utf-8").strip())


def _head_bytes(top: Path, relative: str) -> bytes | None:
    """The file at HEAD, or None when it is new (untracked or added since HEAD)."""
    result = _git(top, "show", f"HEAD:{relative}")
    return result.stdout if result.returncode == 0 else None


def _ruff(top: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    local = top / ".venv" / "Scripts" / "ruff.exe"
    if not local.exists():
        local = top / ".venv" / "bin" / "ruff"
    command = [str(local), *args] if local.exists() else ["uv", "run", "--frozen", "--extra", "dev", "ruff", *args]
    return subprocess.run(command, cwd=top, input=stdin, capture_output=True, timeout=_TIMEOUT_SECONDS)


def _last_line(result: subprocess.CompletedProcess[bytes]) -> str:
    lines = (result.stderr or result.stdout).decode("utf-8", "replace").strip().splitlines()
    return lines[-1] if lines else f"exit code {result.returncode}"


def _report(messages: list[str]) -> None:
    if messages:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "post_edit_format: " + " ".join(messages),
            }
        }
        print(json.dumps(output, ensure_ascii=True))


def process(file_path: str) -> list[str]:
    path = Path(file_path)
    if not path.is_file():
        return []
    top = _repo_root(path)
    if top is None:
        return []
    try:
        relative = path.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return []
    if relative.startswith((".venv/", ".git/")):
        return []

    messages: list[str] = []
    head = _head_bytes(top, relative)
    content = path.read_bytes()
    if b"\0" not in content and b"\r\n" in content and (head is None or b"\r\n" not in head):
        path.write_bytes(content.replace(b"\r\n", b"\n"))
        messages.append(f"converted CRLF to LF in {relative}.")

    if path.suffix == ".py":
        if head is not None:
            check = _ruff(top, "format", "--check", "--stdin-filename", relative, "-", stdin=head)
            if check.returncode not in (0, 1):  # 1 = would reformat; anything else = ruff/uv failed
                messages.append(f"could not check {relative} with ruff: {_last_line(check)}.")
                return messages
            if check.returncode == 1:
                messages.append(
                    f"skipped ruff format for {relative}: it is not ruff-formatted at HEAD, so formatting the "
                    "whole file would rewrite unrelated lines. Keep your edit in the surrounding style."
                )
                return messages
        result = _ruff(top, "format", relative)
        if result.returncode != 0:
            messages.append(f"ruff format failed for {relative}: {_last_line(result)}.")
        elif b"1 file reformatted" in result.stdout:
            messages.append(f"ruff-formatted {relative}.")
    return messages


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"post_edit_format: could not parse hook input ({exc})", file=sys.stderr)
        return 0
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file_path, str) or not file_path:
        return 0
    try:
        _report(process(os.path.expanduser(file_path)))
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"post_edit_format: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
