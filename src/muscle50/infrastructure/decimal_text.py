"""Canonical Decimal-to-text conversion shared across nutrition persistence layers.

Decimal nutrition values must never round-trip through a binary floating-point
representation (SQLite REAL, JSON number), so every persistence boundary reuses
this single canonical text form instead of duplicating the formatting rules.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

DECIMAL_TEXT_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


def decimal_to_text(value: Decimal) -> str:
    normalized = abs(value) if value == 0 else value
    return format(normalized, "f")


def decimal_from_text(text: str) -> Decimal:
    if DECIMAL_TEXT_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{text!r} is not a canonical decimal string")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{text!r} is not a canonical decimal string") from exc
