"""Immutable RAW storage for InBody source documents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from muscle50.domain.body_composition import RawInBodyDocument


@dataclass(frozen=True)
class InBodyRawArtifact:
    relative_path: str
    metadata_relative_path: str
    content_type: str
    source_format: str
    sha256: str
    byte_size: int
    source_type: str
    source_fetched_at: str
    kind: Literal["measurement_list", "measurement_detail"] = "measurement_detail"
    source_record_id: str | None = None
    source_application: str | None = None
    source_schema_version: str | None = None


class InBodyRawStore:
    def __init__(self, root: Path, data_root: Path, tmp_dir: Path):
        self._root = root
        self._data_root = data_root
        self._tmp_dir = tmp_dir

    def preserve(
        self,
        raw: RawInBodyDocument,
        *,
        kind: Literal["measurement_list", "measurement_detail"] = "measurement_detail",
    ) -> InBodyRawArtifact:
        digest = hashlib.sha256(raw.document).hexdigest()
        # Content-addressed paths avoid putting profile/measurement identifiers on
        # disk and remain short enough for legacy Windows MAX_PATH environments.
        source_type = _source_type(raw.source_type)
        source_fetched_at = raw.source_fetched_at or datetime.now(UTC).isoformat()
        directory = self._root / source_type / kind / digest[:2]
        directory.mkdir(parents=True, exist_ok=True)
        extension = ".json" if raw.content_type.lower().startswith("application/json") else ".bin"
        destination = directory / f"{digest[:32]}{extension}"
        _write_once(destination, raw.document, self._tmp_dir)
        relative_path = destination.relative_to(self._data_root).as_posix()
        metadata = {
            "byte_size": len(raw.document),
            "content_type": raw.content_type,
            "kind": kind,
            "relative_path": relative_path,
            "schema": "muscle50.inbody.raw-metadata.v1",
            "sha256": digest,
            "source_application": raw.source_application,
            "source_fetched_at": source_fetched_at,
            "source_format": raw.source_format,
            "source_record_id": raw.source_record_id,
            "source_schema_version": raw.source_schema_version,
            "source_type": source_type,
        }
        metadata_bytes = (
            json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        metadata_digest = hashlib.sha256(metadata_bytes).hexdigest()
        metadata_destination = directory / f"{digest[:32]}.{metadata_digest[:16]}.meta"
        _write_once(metadata_destination, metadata_bytes, self._tmp_dir)
        return InBodyRawArtifact(
            relative_path=relative_path,
            metadata_relative_path=metadata_destination.relative_to(self._data_root).as_posix(),
            content_type=raw.content_type,
            source_format=raw.source_format,
            sha256=digest,
            byte_size=len(raw.document),
            kind=kind,
            source_type=source_type,
            source_fetched_at=source_fetched_at,
            source_record_id=raw.source_record_id,
            source_application=raw.source_application,
            source_schema_version=raw.source_schema_version,
        )


def _source_type(value: str) -> str:
    result = value.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", result):
        raise ValueError("InBody RAW source type must be a lowercase identifier")
    return result


def _write_once(destination: Path, content: bytes, tmp_dir: Path) -> None:
    if destination.exists():
        if destination.read_bytes() != content:
            raise RuntimeError("InBody RAW content hash collision")
        return
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temporary = tmp_dir / f"{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            if destination.read_bytes() != content:
                raise RuntimeError("InBody RAW content hash collision") from exc
    finally:
        temporary.unlink(missing_ok=True)
