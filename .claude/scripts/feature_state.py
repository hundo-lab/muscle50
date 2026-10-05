"""Shared runtime state for /feature runs: migration reservations, feature status, integration lock.

State lives in `<git common dir>/muscle50-orchestration/`, which every worktree of the repository
shares and git never commits. Reservations and the lock are directories created with `mkdir`, which
is atomic, so parallel /feature sessions cannot take the same migration number or integrate at the
same time.

Usage (run from any worktree of the repository):
  python .claude/scripts/feature_state.py reserve-migration <id>   # prints NNN (idempotent per id)
  python .claude/scripts/feature_state.py release-migration <id>
  python .claude/scripts/feature_state.py set <id> key=value [key=value ...]
  python .claude/scripts/feature_state.py get <id>                 # JSON
  python .claude/scripts/feature_state.py list                     # one line per feature
  python .claude/scripts/feature_state.py dir                      # state directory (plans/ lives here)
  python .claude/scripts/feature_state.py lock <id> [--wait SECONDS]
  python .claude/scripts/feature_state.py unlock <id>

Exit codes: 0 ok, 1 usage/state error, 3 lock held by another feature (holder printed on stderr).
Standard library only; runs on Python 3.9+.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = "src/muscle50/infrastructure/sqlite/migrations"
_MIGRATION_FILE = re.compile(r"^(\d{3})_[\w-]+\.sql$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class StateError(RuntimeError):
    pass


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise StateError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def state_dir() -> Path:
    common = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    directory = common / "muscle50-orchestration"
    (directory / "features").mkdir(parents=True, exist_ok=True)
    (directory / "migrations").mkdir(parents=True, exist_ok=True)
    (directory / "plans").mkdir(parents=True, exist_ok=True)
    return directory


def _now() -> str:
    # timezone.utc, not datetime.UTC: this script must also run on a Python older than 3.11.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: UP017


def _check_id(feature_id: str) -> str:
    if not _ID.match(feature_id):
        raise StateError(f"invalid feature id {feature_id!r} (use lower-case kebab-case)")
    return feature_id


def _used_migration_numbers() -> set[int]:
    """Numbers in use on any local branch, in any worktree's files, or reserved."""
    numbers: set[int] = set()
    for ref in _git("for-each-ref", "--format=%(refname)", "refs/heads").split():
        listing = subprocess.run(
            ["git", "ls-tree", "--name-only", f"{ref}:{MIGRATIONS}"], capture_output=True, text=True
        ).stdout
        numbers.update(int(m.group(1)) for name in listing.split() if (m := _MIGRATION_FILE.match(name)))
    for line in _git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            folder = Path(line[len("worktree ") :]) / MIGRATIONS
            if folder.is_dir():
                numbers.update(int(m.group(1)) for p in folder.iterdir() if (m := _MIGRATION_FILE.match(p.name)))
    for entry in (state_dir() / "migrations").iterdir():
        if entry.name.isdigit():
            numbers.add(int(entry.name))
    return numbers


def reserve_migration(feature_id: str) -> str:
    directory = state_dir() / "migrations"
    for entry in sorted(directory.iterdir()):
        owner = entry / "feature"
        if owner.exists() and owner.read_text(encoding="utf-8").strip() == feature_id:
            return entry.name
    candidate = max(_used_migration_numbers(), default=0) + 1
    while True:
        slot = directory / f"{candidate:03d}"
        try:
            slot.mkdir()  # atomic: only one session can create it
        except FileExistsError:
            candidate += 1
            continue
        (slot / "feature").write_text(feature_id + "\n", encoding="utf-8", newline="\n")
        (slot / "reserved_at").write_text(_now() + "\n", encoding="utf-8", newline="\n")
        set_fields(feature_id, {"migration": f"reserved:{candidate:03d}"})
        return f"{candidate:03d}"


def release_migration(feature_id: str) -> str | None:
    directory = state_dir() / "migrations"
    for entry in sorted(directory.iterdir()):
        owner = entry / "feature"
        if owner.exists() and owner.read_text(encoding="utf-8").strip() == feature_id:
            for child in entry.iterdir():
                child.unlink()
            entry.rmdir()
            set_fields(feature_id, {"migration": "none"})
            return entry.name
    return None


def _feature_path(feature_id: str) -> Path:
    return state_dir() / "features" / f"{_check_id(feature_id)}.json"


def get_fields(feature_id: str) -> dict[str, str]:
    path = _feature_path(feature_id)
    if not path.exists():
        return {}
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def set_fields(feature_id: str, fields: dict[str, str]) -> dict[str, str]:
    data = get_fields(feature_id)
    data.update(fields)
    data["id"] = feature_id
    data["updated_at"] = _now()
    path = _feature_path(feature_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)
    return data


def lock(feature_id: str, wait_seconds: float) -> None:
    directory = state_dir() / "integration.lock"
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            directory.mkdir()
        except FileExistsError:
            holder_file = directory / "holder"
            holder = holder_file.read_text(encoding="utf-8").strip() if holder_file.exists() else "?"
            if holder.split(" ", 1)[0] == feature_id:
                return  # re-entrant for the same feature
            if time.monotonic() >= deadline:
                raise LockHeld(f"integration lock held by {holder} ({directory})") from None
            time.sleep(5)
            continue
        (directory / "holder").write_text(f"{feature_id} {_now()}\n", encoding="utf-8", newline="\n")
        return


def unlock(feature_id: str) -> None:
    directory = state_dir() / "integration.lock"
    holder_file = directory / "holder"
    if not directory.exists():
        return
    holder = holder_file.read_text(encoding="utf-8").strip() if holder_file.exists() else ""
    if holder.split(" ", 1)[0] != feature_id:
        raise StateError(f"integration lock is held by {holder or '?'}, not {feature_id}")
    holder_file.unlink(missing_ok=True)
    directory.rmdir()


class LockHeld(StateError):
    pass


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 1
    command, args = argv[0], argv[1:]
    try:
        if command == "reserve-migration" and len(args) == 1:
            print(reserve_migration(_check_id(args[0])))
        elif command == "release-migration" and len(args) == 1:
            released = release_migration(_check_id(args[0]))
            print(released or "none")
        elif command == "set" and len(args) >= 2:
            fields = {}
            for pair in args[1:]:
                key, sep, value = pair.partition("=")
                if not sep or not key:
                    raise StateError(f"expected key=value, got {pair!r}")
                fields[key] = value
            print(json.dumps(set_fields(_check_id(args[0]), fields), indent=2, sort_keys=True))
        elif command == "dir" and not args:
            print(state_dir().as_posix())
        elif command == "get" and len(args) == 1:
            print(json.dumps(get_fields(_check_id(args[0])), indent=2, sort_keys=True))
        elif command == "list" and not args:
            for path in sorted((state_dir() / "features").glob("*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                print(
                    f"{data.get('id')}\tstatus={data.get('status', '?')}\tmigration={data.get('migration', 'none')}"
                    f"\tbranch={data.get('branch', '-')}\tupdated={data.get('updated_at', '-')}"
                )
            holder = state_dir() / "integration.lock" / "holder"
            if holder.exists():
                print(f"integration.lock\t{holder.read_text(encoding='utf-8').strip()}")
        elif command == "lock" and args:
            wait = 0.0
            if len(args) == 3 and args[1] == "--wait":
                wait = float(args[2])
            elif len(args) != 1:
                raise StateError("usage: lock <id> [--wait SECONDS]")
            lock(_check_id(args[0]), wait)
            print(f"locked by {args[0]}")
        elif command == "unlock" and len(args) == 1:
            unlock(_check_id(args[0]))
            print(f"unlocked by {args[0]}")
        else:
            print(__doc__, file=sys.stderr)
            return 1
    except LockHeld as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except StateError as exc:
        print(f"feature_state: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
