"""Immutable local storage for personal Garmin source payloads."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from muscle50.infrastructure.garmin.client import GarminRawActivity

_ARTIFACT_FILES = (
    ("summary", "summary.json", "application/json"),
    ("activity", "activity.json", "application/json"),
    ("details", "details.json", "application/json"),
    ("splits", "splits.json", "application/json"),
    ("exercise_sets", "exercise_sets.json", "application/json"),
    ("original_archive", "original.zip", "application/zip"),
)


class RawStoreError(RuntimeError):
    """Raised when immutable raw content conflicts with existing content."""


@dataclass(frozen=True)
class RawArtifact:
    kind: str
    relative_path: str
    content_type: str
    sha256: str
    byte_size: int


class RawStore:
    def __init__(self, root: Path, data_root: Path, tmp_dir: Path):
        self._root = root
        self._data_root = data_root
        self._tmp_dir = tmp_dir

    def preserve(self, activity_id: str, raw: GarminRawActivity) -> tuple[RawArtifact, ...]:
        directory = self._root / activity_id
        directory.mkdir(parents=True, exist_ok=True)
        payloads: list[tuple[str, str, bytes, str]] = [
            ("summary", "summary.json", _json_bytes(raw.summary), "application/json"),
            ("activity", "activity.json", _json_bytes(raw.activity), "application/json"),
            ("details", "details.json", _json_bytes(raw.details), "application/json"),
        ]
        if raw.splits is not None:
            payloads.append(("splits", "splits.json", _json_bytes(raw.splits), "application/json"))
        if raw.exercise_sets is not None:
            payloads.append(
                (
                    "exercise_sets",
                    "exercise_sets.json",
                    _json_bytes(raw.exercise_sets),
                    "application/json",
                )
            )
        if raw.original_archive is not None:
            payloads.append(("original_archive", "original.zip", raw.original_archive, "application/zip"))

        for _kind, name, content, _content_type in payloads:
            destination = directory / name
            _write_immutable(destination, content, self._tmp_dir)

        # Include first-capture optional files left by an interrupted earlier run even
        # when the retry cannot fetch that optional endpoint.
        artifacts: list[RawArtifact] = []
        for kind, name, content_type in _ARTIFACT_FILES:
            destination = directory / name
            if not destination.exists():
                continue
            content = destination.read_bytes()
            artifacts.append(
                RawArtifact(
                    kind=kind,
                    relative_path=destination.relative_to(self._data_root).as_posix(),
                    content_type=content_type,
                    sha256=hashlib.sha256(content).hexdigest(),
                    byte_size=len(content),
                )
            )

        manifest = {
            "provider": "garmin",
            "source_activity_id": activity_id,
            "artifacts": [asdict(item) for item in artifacts],
            "warnings": list(raw.warnings),
        }
        # The manifest is metadata and can be recreated; raw source files remain immutable.
        _write_atomic_replace(directory / "manifest.json", _json_bytes(manifest), self._tmp_dir)
        return tuple(artifacts)

    def load_exercise_sets(self, activity_id: str) -> Mapping[str, Any] | None:
        """Read an already-preserved strength payload without contacting Garmin."""
        if not activity_id.isdigit() or int(activity_id) <= 0:
            raise RawStoreError("올바르지 않은 Garmin activity ID입니다.")
        path = self._root / activity_id / "exercise_sets.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RawStoreError("기존 exercise_sets RAW 파일을 읽을 수 없습니다.") from exc
        if not isinstance(payload, Mapping):
            raise RawStoreError("기존 exercise_sets RAW 파일 형식이 올바르지 않습니다.")
        return payload


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_immutable(destination: Path, content: bytes, tmp_dir: Path) -> None:
    expected = hashlib.sha256(content).hexdigest()
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            raise RawStoreError(f"기존 RAW 파일과 새 데이터가 다릅니다: {destination.name}")
        return

    tmp_dir.mkdir(parents=True, exist_ok=True)
    temporary = tmp_dir / f"{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                raise RawStoreError(f"기존 RAW 파일과 새 데이터가 다릅니다: {destination.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _write_atomic_replace(destination: Path, content: bytes, tmp_dir: Path) -> None:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temporary = tmp_dir / f"{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
