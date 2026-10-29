"""Read-only access to the stored Garmin ``details.json`` heart-rate series (strength set timing).

Never creates a directory, never writes, never contacts Garmin. RAW problems are returned as a
status (the snapshot still succeeds and the affected sets are "not estimated"); only a database
error from the reader propagates.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from muscle50.domain.strength_set_timing import HeartRateLoad, HeartRateStatus, parse_direct_heart_rate
from muscle50.infrastructure.raw_store import RawArtifact


class DetailsArtifactReader(Protocol):
    def details_artifact(self, source_activity_id: str) -> RawArtifact | None: ...


class RawHeartRateSource:
    """Loads the accepted ``details`` artifact of one activity, checked against its recorded size and sha256."""

    def __init__(self, reader: DetailsArtifactReader, data_root: Path, activities_dir: Path):
        self._reader = reader
        self._data_root = data_root
        self._activities_dir = activities_dir

    def load(self, source_activity_id: str) -> HeartRateLoad:
        artifact = self._reader.details_artifact(source_activity_id)
        if artifact is None:
            return HeartRateLoad(HeartRateStatus.RAW_MISSING, (), None)
        relative_path = artifact.relative_path

        def unreadable() -> HeartRateLoad:
            return HeartRateLoad(HeartRateStatus.RAW_UNREADABLE, (), relative_path)

        if not source_activity_id.isdigit() or int(source_activity_id) <= 0:
            return unreadable()
        activity_dir = (self._activities_dir / source_activity_id).resolve()
        path = (self._data_root / relative_path).resolve()
        # Initial RAW and refresh snapshots both live under raw/garmin/activities/<id>/.
        if path == activity_dir or not path.is_relative_to(activity_dir):
            return unreadable()
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return HeartRateLoad(HeartRateStatus.RAW_MISSING, (), relative_path)
        except OSError:
            return unreadable()
        if len(content) != artifact.byte_size or hashlib.sha256(content).hexdigest() != artifact.sha256:
            return unreadable()
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return unreadable()
        status, samples = parse_direct_heart_rate(payload)
        return HeartRateLoad(status, samples, relative_path)
