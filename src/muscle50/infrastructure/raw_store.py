"""Immutable local storage for personal Garmin source payloads."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from muscle50.infrastructure.garmin.client import GarminRawActivity, GarminRawRecovery

_ARTIFACT_FILES = (
    ("summary", "summary.json", "application/json"),
    ("activity", "activity.json", "application/json"),
    ("details", "details.json", "application/json"),
    ("splits", "splits.json", "application/json"),
    ("exercise_sets", "exercise_sets.json", "application/json"),
    ("original_archive", "original.zip", "application/zip"),
)

_RECOVERY_ARTIFACT_FILES = {
    "sleep": "sleep.json",
    "hrv": "hrv.json",
    "resting_heart_rate": "resting_heart_rate.json",
    "daily_stats": "daily_stats.json",
    "body_battery": "body_battery.json",
    "stress": "stress.json",
    "training_readiness": "training_readiness.json",
    "training_status": "training_status.json",
    "respiration": "respiration.json",
}


class RawStoreError(RuntimeError):
    """Raised when immutable raw content conflicts with existing content."""


@dataclass(frozen=True)
class RawArtifact:
    kind: str
    relative_path: str
    content_type: str
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class RecoveryCapture:
    capture_id: str
    requested_date: str
    manifest_relative_path: str
    artifacts: tuple[RawArtifact, ...]


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
        _validate_activity_id(activity_id)
        path = self._root / activity_id / "exercise_sets.json"
        if not path.exists():
            return None
        return _load_json_mapping(path, "exercise_sets")

    def load_swim_payloads(
        self,
        activity_id: str,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None] | None:
        """Read preserved pool-swimming inputs for a local normalization backfill."""
        _validate_activity_id(activity_id)
        directory = self._root / activity_id
        summary_path = directory / "summary.json"
        activity_path = directory / "activity.json"
        if not summary_path.exists() or not activity_path.exists():
            return None
        splits_path = directory / "splits.json"
        splits = _load_json_mapping(splits_path, "splits") if splits_path.exists() else None
        return (
            _load_json_mapping(summary_path, "summary"),
            _load_json_mapping(activity_path, "activity"),
            splits,
        )


class RecoveryRawStore:
    """Content-addressed immutable snapshots of daily Garmin responses."""

    def __init__(self, root: Path, data_root: Path, tmp_dir: Path):
        self._root = root
        self._data_root = data_root
        self._tmp_dir = tmp_dir

    def preserve(self, raw: GarminRawRecovery) -> RecoveryCapture:
        _validate_recovery_date(raw.requested_date)
        payload_bytes = {
            kind: _json_bytes(raw.payloads[kind])
            for kind in _RECOVERY_ARTIFACT_FILES
            if kind in raw.payloads
        }
        if not payload_bytes:
            raise RawStoreError("보존할 Garmin recovery 응답이 없습니다.")

        digest = hashlib.sha256()
        digest.update(raw.requested_date.encode("utf-8"))
        for kind, content in payload_bytes.items():
            digest.update(b"\0" + kind.encode("utf-8") + b"\0" + content)
        digest.update(b"\0warnings\0" + _json_bytes(list(raw.warnings)))
        capture_id = digest.hexdigest()
        directory = self._root / raw.requested_date / capture_id
        directory.mkdir(parents=True, exist_ok=True)

        artifacts: list[RawArtifact] = []
        for kind, content in payload_bytes.items():
            destination = directory / _RECOVERY_ARTIFACT_FILES[kind]
            _write_immutable(destination, content, self._tmp_dir)
            artifacts.append(
                RawArtifact(
                    kind=kind,
                    relative_path=destination.relative_to(self._data_root).as_posix(),
                    content_type="application/json",
                    sha256=hashlib.sha256(content).hexdigest(),
                    byte_size=len(content),
                )
            )

        manifest_path = directory / "manifest.json"
        manifest = {
            "provider": "garmin",
            "capture_id": capture_id,
            "requested_date": raw.requested_date,
            "artifacts": [asdict(item) for item in artifacts],
            "warnings": list(raw.warnings),
        }
        _write_immutable(manifest_path, _json_bytes(manifest), self._tmp_dir)
        return RecoveryCapture(
            capture_id=capture_id,
            requested_date=raw.requested_date,
            manifest_relative_path=manifest_path.relative_to(self._data_root).as_posix(),
            artifacts=tuple(artifacts),
        )


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _validate_activity_id(activity_id: str) -> None:
    if not activity_id.isdigit() or int(activity_id) <= 0:
        raise RawStoreError("올바르지 않은 Garmin activity ID입니다.")


def _validate_recovery_date(value: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RawStoreError("올바르지 않은 Garmin recovery 날짜입니다.") from exc
    if parsed.isoformat() != value:
        raise RawStoreError("올바르지 않은 Garmin recovery 날짜입니다.")


def _load_json_mapping(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RawStoreError(f"기존 {label} RAW 파일을 읽을 수 없습니다.") from exc
    if not isinstance(payload, Mapping):
        raise RawStoreError(f"기존 {label} RAW 파일 형식이 올바르지 않습니다.")
    return payload


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
