"""PreToolUse guard for Bash/PowerShell commands in muscle50.

Claude Code passes the hook input as JSON on stdin. Exit code 2 blocks the tool call and the
stderr text is shown to Claude as the reason; exit code 0 lets the normal permission flow run.

Blocked (see CLAUDE.md "Human gates" and docs/specs/README.md):
1. `git push`: push is a human gate; the user runs it.
2. Direct write/delete commands aimed at the production data directory (%LOCALAPPDATA%\\muscle50):
   rm/mv/cp-into/redirects/sqlite3 without -readonly, and `python`/`uv run python` one-liners that
   name it without `mode=ro`. Production data changes only through the muscle50 CLI.
3. The `muscle50` CLI against production (MUSCLE50_HOME unset or pointing at production) unless
   - the code that runs is the `main` checkout (not a feature worktree), and
   - production already has every migration in that code. Applying a new migration to
     production is human gate 3 (CLAUDE.md), and any writing command would apply it.
   With a temporary MUSCLE50_HOME (inline `VAR=... muscle50`, an earlier `export`/`$env:`
   assignment, or the hook environment) the CLI is always allowed.

Only commands are checked, not text: quoted strings are inspected only where a shell would run
them (`bash -c "..."`, `powershell -Command "..."`, `cmd /c ...`, `$(...)`, backticks outside
single quotes), and heredoc bodies are skipped, so `grep "git push" docs` or a commit message
that mentions muscle50 is allowed.

This is a safety net, not a sandbox: it inspects command text only. Database access inside a
script file (`python script.py`) is not detected. Standard library only; runs on Python 3.9+.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# The production data root, in every spelling seen in shells on this machine.
_PROD_PATH = re.compile(
    r"(%LOCALAPPDATA%|\$\{?LOCALAPPDATA\}?|\$env:LOCALAPPDATA|AppData[\\/]+Local)[\\/]+muscle50(?![\w.-])",
    re.IGNORECASE,
)

# Commands that change or delete files when given a path.
_WRITE_VERBS = {
    "rm", "rmdir", "del", "erase", "rd", "remove-item", "ri",
    "mv", "move", "move-item", "mi", "ren", "rename", "rename-item", "rni",
    "mkdir", "md", "new-item", "ni", "touch", "truncate", "tee", "tee-object",
    "set-content", "sc", "add-content", "ac", "clear-content", "clc", "out-file",
    "chmod", "chown", "icacls", "attrib", "ln", "install",
}  # fmt: skip
# Copy commands write only to their destination (the last path argument).
_COPY_VERBS = {"cp", "copy", "copy-item", "cpi", "xcopy", "robocopy", "rsync"}
# git global options that take a separate value.
_GIT_VALUE_OPTIONS = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
# `uv run` options that take a separate value.
_UV_VALUE_OPTIONS = {
    "--extra", "--with", "--python", "-p", "--directory", "--project", "--package", "--group", "--env-file", "--index",
}  # fmt: skip

_HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.DOTALL)
_SHELL_WRAPPER = re.compile(
    r"(?:^|[\s;&|(])(?:bash|sh|zsh|pwsh|powershell)(?:\.exe)?(?:\s+-[\w-]+)*?\s+-(?:c|command)\s+"
    r"(\"(?:[^\"\\]|\\.)*\"|'[^']*')",
    re.IGNORECASE,
)
_CMD_WRAPPER = re.compile(r"(?:^|[\s;&|(])cmd(?:\.exe)?\s+/[ck]\s+(.+)$", re.IGNORECASE)
_REDIRECT = re.compile(r"\d?>>?\s*(\"[^\"]*\"|'[^']*'|[^\s\"']+)")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PERSISTENT_HOME = re.compile(
    r"^\s*(?:export\s+MUSCLE50_HOME=|set\s+MUSCLE50_HOME=|\$env:MUSCLE50_HOME\s*=\s*)(\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE,
)
_INLINE_HOME = re.compile(r"^MUSCLE50_HOME=(.*)$", re.IGNORECASE)


def _split_segments(command: str, *, bash: bool) -> tuple[list[str], list[str]]:
    """Split on ; && || | and newlines outside quotes; also collect $(...) and `...` bodies.

    Returns (segments, nested): `nested` are bodies a shell would execute, found outside
    single quotes. Backslash escapes inside double quotes and backticks count only for Bash
    (PowerShell keeps `\\` literally and uses ` as its escape character).
    """
    segments: list[str] = []
    nested: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            if char == "'":
                quote = ""
            current.append(char)
        elif bash and char == "\\" and quote == '"' and index + 1 < len(command):
            current.append(command[index : index + 2])
            index += 1
        elif char in "\"'" and (quote == "" or quote == char):
            quote = "" if quote else char
            current.append(char)
        elif command.startswith("$(", index):
            depth, end = 1, index + 2
            while end < len(command) and depth:
                depth += {"(": 1, ")": -1}.get(command[end], 0)
                end += 1
            nested.append(command[index + 2 : end - 1])
            current.append(command[index:end])
            index = end - 1
        elif bash and char == "`" and command.find("`", index + 1) > index:
            end = command.find("`", index + 1)
            nested.append(command[index + 1 : end])
            current.append(command[index : end + 1])
            index = end
        elif quote == "" and (command.startswith("&&", index) or command.startswith("||", index)):
            segments.append("".join(current))
            current = []
            index += 1
        elif quote == "" and char in ";|\n":
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()], nested


def _all_segments(command: str, *, bash: bool, depth: int = 0) -> list[str]:
    """Top-level segments plus the segments of every command a shell would run from inside them."""
    command = _HEREDOC.sub("<<heredoc", command)
    segments, nested = _split_segments(command, bash=bash)
    if depth < 3:
        for segment in segments:
            for match in _SHELL_WRAPPER.finditer(segment):
                nested.append(match.group(1)[1:-1])
            cmd = _CMD_WRAPPER.search(segment)
            if cmd:
                nested.append(cmd.group(1).strip("\"'"))
        for body in nested:
            segments.extend(_all_segments(body, bash=bash, depth=depth + 1))
    return segments


def _shell_tokens(segment: str) -> list[str]:
    """Words split on whitespace outside quotes, with quote characters removed.

    Backslashes are kept (unlike shlex in POSIX mode) so unquoted Windows paths survive.
    """
    tokens: list[str] = []
    current: list[str] = []
    quote = ""
    started = False
    for char in segment:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
        elif char in "\"'":
            quote = char
            started = True
        elif char.isspace():
            if started or current:
                tokens.append("".join(current))
            current, started = [], False
        else:
            current.append(char)
            started = True
    if started or current:
        tokens.append("".join(current))
    return tokens


def _command_index(tokens: list[str]) -> int:
    """Index of the command word, skipping leading VAR=value assignments and PowerShell's `&`."""
    index = 0
    while index < len(tokens) and (_ASSIGNMENT.match(tokens[index]) or tokens[index] in {"&", "sudo"}):
        index += 1
    return index


def _verb(token: str) -> str:
    name = re.split(r"[\\/]", token)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _runs_git_push(segment: str) -> bool:
    tokens = _shell_tokens(segment)
    index = _command_index(tokens)
    if index >= len(tokens) or _verb(tokens[index]) != "git":
        return False
    rest = tokens[index + 1 :]
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in _GIT_VALUE_OPTIONS else rest[1:]
    return bool(rest) and rest[0].lower() == "push"


def _is_windows_switch(verb: str, arg: str) -> bool:
    # xcopy/robocopy switches look like /E or /MIR; Git Bash paths (/c/temp/x) are not switches.
    return verb in {"xcopy", "robocopy"} and re.fullmatch(r"/[A-Za-z]+(?::\S*)?", arg) is not None


def _writes_to_production(segment: str) -> bool:
    if not _PROD_PATH.search(segment):
        return False
    if any(_PROD_PATH.search(target) for target in _REDIRECT.findall(segment)):
        return True
    tokens = _shell_tokens(segment)
    index = _command_index(tokens)
    if index >= len(tokens):
        return False
    verb = _verb(tokens[index])
    args = tokens[index + 1 :]
    if verb in _WRITE_VERBS:
        return True
    if verb == "sed" and any(arg.startswith("-i") or arg == "--in-place" for arg in args):
        return True
    if verb in _COPY_VERBS:
        paths = [arg for arg in args if not arg.startswith("-") and not _is_windows_switch(verb, arg)]
        return bool(paths) and bool(_PROD_PATH.search(paths[-1]))
    if verb == "sqlite3":
        return not any(arg in {"-readonly", "--readonly"} or "mode=ro" in arg for arg in args)
    runs_python = verb in {"python", "python3", "py"} or (verb == "uv" and "python" in [a.lower() for a in args[:6]])
    if runs_python:
        # A one-liner that names the production directory may only open it read-only.
        return "mode=ro" not in segment
    return False


def _is_muscle50_executable(token: str) -> bool:
    # `muscle50`, `muscle50.exe`, or a venv entry point such as .venv/Scripts/muscle50.exe. A bare
    # directory path that ends in muscle50 (the repo folder, the data folder) is not the CLI.
    return re.fullmatch(r"(?:.*[\\/](?:Scripts|bin)[\\/])?muscle50(?:\.exe)?", token, re.IGNORECASE) is not None


def _muscle50_invocation(tokens: list[str]) -> tuple[bool, str | None]:
    """(runs the muscle50 CLI?, project directory given by `uv run --directory/--project`)."""
    index = _command_index(tokens)
    words = tokens[index:]
    if not words:
        return False, None
    if _is_muscle50_executable(words[0]):
        return True, None
    project = None
    if _verb(words[0]) == "uv" and len(words) > 1 and words[1].lower() == "run":
        words = words[2:]
        while words and words[0].startswith("-"):
            option = words[0].lower()
            if option in _UV_VALUE_OPTIONS:
                if option in {"--directory", "--project"} and len(words) > 1:
                    project = words[1]
                words = words[2:]
            elif option.startswith(("--directory=", "--project=")):
                project = words[0].split("=", 1)[1]
                words = words[1:]
            else:
                words = words[1:]
        if words and _is_muscle50_executable(words[0]):
            return True, project
    if words and _verb(words[0]) in {"python", "python3", "py"}:
        for position, word in enumerate(words[1:], start=1):
            if word == "-m" and position + 1 < len(words):
                return words[position + 1].lower() in {"muscle50", "muscle50.cli"}, project
    return False, None


def _runs_muscle50_cli(tokens: list[str]) -> bool:
    return _muscle50_invocation(tokens)[0]


def _native_path(path: str, base: str | None) -> str:
    """Resolve a shell path (Git Bash /c/..., ~, $VARS, relative) to a native absolute path."""
    path = os.path.expandvars(os.path.expanduser(path))
    drive = re.match(r"^/([A-Za-z])(/.*)?$", path)
    if drive:
        path = f"{drive.group(1).upper()}:{drive.group(2) or '/'}"
    if base and not os.path.isabs(path):
        path = os.path.join(base, path)
    return os.path.normpath(path)


def _git_output(directory: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", directory, *args], capture_output=True, text=True, encoding="utf-8", timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _production_database() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return Path(local_app_data) / "muscle50" / "db" / "muscle50.sqlite3" if local_app_data else None


def _unapplied_migrations(top: str) -> list[int] | None:
    """Migration numbers in the code at `top` that production has not applied (None = cannot tell)."""
    folder = Path(top) / "src" / "muscle50" / "infrastructure" / "sqlite" / "migrations"
    code = {int(p.name[:3]) for p in folder.glob("[0-9][0-9][0-9]_*.sql")} if folder.is_dir() else set()
    database = _production_database()
    if database is None or not database.exists():
        return []  # no production database yet: nothing to migrate
    try:
        # immutable=1: no locks, no -wal/-shm files are created next to the production database.
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True, timeout=5)
        try:
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    return sorted(code - applied)


def _production_run_problem(code_dir: str | None) -> str | None:
    """None when the muscle50 CLI may run against production from `code_dir`."""
    if not code_dir:
        return "cannot tell which checkout's code would run (no working directory)"
    top = _git_output(code_dir, "rev-parse", "--show-toplevel")
    branch = _git_output(code_dir, "symbolic-ref", "--quiet", "--short", "HEAD") if top else None
    if not top:
        return f"cannot tell which checkout's code would run ({code_dir} is not a git checkout)"
    if branch != "main":
        return (
            f"the code in {top} is on '{branch or 'detached HEAD'}', not main; unintegrated code never runs against "
            "production. Use a temporary MUSCLE50_HOME, or run it from the main checkout"
        )
    unapplied = _unapplied_migrations(top)
    if unapplied is None:
        return "cannot read schema_migrations from the production database to check for unapplied migrations"
    if unapplied:
        numbers = ", ".join(f"{number:03d}" for number in unapplied)
        return (
            f"production has not applied migration {numbers} yet, and this command would apply it. Applying a "
            "migration to production is human gate 3 (back up, apply, verify; add-migration skill section 6). "
            "Ask the user"
        )
    return None


def _is_production_home(value: str) -> bool:
    if _PROD_PATH.search(value):
        return True
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return False
    production = os.path.normcase(os.path.join(local_app_data, "muscle50"))
    return os.path.normcase(os.path.abspath(os.path.expandvars(value))) == production


def _muscle50_problem(segments: list[str], cwd: str | None) -> str | None:
    """None when every muscle50 CLI call is allowed (temporary home, or production from main)."""
    persistent = os.environ.get("MUSCLE50_HOME") or None
    directory = cwd
    for segment in segments:
        assignment = _PERSISTENT_HOME.match(segment)
        if assignment:
            persistent = assignment.group(1).strip("\"'")
            continue
        tokens = _shell_tokens(segment)
        index = _command_index(tokens)
        if index < len(tokens) and _verb(tokens[index]) in {"cd", "pushd", "set-location", "sl", "chdir"}:
            targets = [token for token in tokens[index + 1 :] if not token.startswith("-")]
            if targets:
                directory = _native_path(targets[0], directory)
            continue
        is_cli, project = _muscle50_invocation(tokens)
        if not is_cli:
            continue
        home = persistent
        for token in tokens[:index]:
            inline = _INLINE_HOME.match(token)
            if inline:
                home = inline.group(1)
        if home and not _is_production_home(home):
            continue  # temporary home: always allowed
        code_dir = _native_path(project, directory) if project else directory
        problem = _production_run_problem(code_dir)
        if problem:
            return f"running the muscle50 CLI against production is blocked: {problem}"
    return None


def check(command: str, tool_name: str = "Bash", cwd: str | None = None) -> str | None:
    """Return the reason to block `command`, or None to allow it."""
    segments = _all_segments(command, bash=tool_name != "PowerShell")
    if any(_runs_git_push(segment) for segment in segments):
        return (
            "git push is blocked: pushing is a human gate in muscle50 (CLAUDE.md). "
            "Report the branch and commits and let the user run the push."
        )
    if any(_writes_to_production(segment) for segment in segments):
        return (
            "Write/delete aimed at the production data directory (%LOCALAPPDATA%\\muscle50) is blocked. "
            "Work in a temporary MUSCLE50_HOME; production changes (for example migrations) are a human gate."
        )
    problem = _muscle50_problem(segments, cwd)
    if problem:
        return (
            f"{problem}. For development and tests use a temporary home outside the repo, e.g. "
            '`MUSCLE50_HOME="$TEMP/muscle50-smoke" uv run muscle50 ...` (Bash) or '
            '`$env:MUSCLE50_HOME = "$env:TEMP\\muscle50-smoke"; uv run muscle50 ...` (PowerShell).'
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # Fail open: a broken hook input must not disable every shell command.
        print(f"pre_bash_guard: could not parse hook input ({exc}); not checked", file=sys.stderr)
        return 0
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    reason = check(command, str(payload.get("tool_name") or "Bash"), cwd)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
