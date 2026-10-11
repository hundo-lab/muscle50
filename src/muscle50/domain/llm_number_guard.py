"""Telegram LLM v2 number guard: an LLM answer may only use numbers found in the data the bot passed.

Numbers in the reply: NFKC-normalized text (fullwidth digits become ASCII), then
`1,150` / `61.50` / `3` style tokens, commas removed, canonical Decimal (`61.50` -> 61.5, `07` -> 7).
Signs and units are ignored. The allowed set comes only from the JSON documents in `[데이터]`: every
number value and every number token inside a string value (`2026-10-12` gives 2026, 10 and 12), each
with its HALF_UP and HALF_EVEN integer rounding and its 1-decimal rounding. Keys, memory, persona,
the coach guide and the user's message are never sources. Known limits: small integers almost always
occur in the data; a unit mix-up passes; Korean number words (`오십`) are not detected.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def canonical(text: str) -> Decimal | None:
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return value.to_integral_value() if value == value.to_integral_value() else value.normalize()


def reply_numbers(text: str) -> tuple[Decimal, ...]:
    """Every number written in ``text``, in order, canonical."""
    normalized = unicodedata.normalize("NFKC", text)
    numbers = []
    for match in _NUMBER.finditer(normalized):
        value = canonical(match.group(0))
        if value is not None:
            numbers.append(value)
    return tuple(numbers)


def allowed_numbers(documents: Iterable[Any]) -> frozenset[Decimal]:
    allowed: set[Decimal] = set()
    for document in documents:
        for value in _scalars(document):
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int | float):
                found = [canonical(repr(value))] if isinstance(value, float) else [Decimal(value)]
            elif isinstance(value, str):
                found = list(reply_numbers(value))
            else:
                continue
            for number in found:
                if number is not None:
                    allowed.update(_variants(number.copy_abs()))
    return frozenset(allowed)


def unknown_numbers(text: str, allowed: frozenset[Decimal]) -> tuple[Decimal, ...]:
    """The numbers in ``text`` that are not in ``allowed`` (empty: the answer may be sent)."""
    return tuple(number for number in reply_numbers(text) if number not in allowed)


def _variants(value: Decimal) -> set[Decimal]:
    variants = {value}
    for rounding in (ROUND_HALF_UP, ROUND_HALF_EVEN):
        try:
            variants.add(value.quantize(Decimal(1), rounding=rounding))
            tenth = value.quantize(Decimal("0.1"), rounding=rounding)
        except InvalidOperation:  # too many digits to round (a long ID): only the value itself
            continue
        variants.add(tenth.to_integral_value() if tenth == tenth.to_integral_value() else tenth.normalize())
    return {canonical(str(variant)) or variant for variant in variants}


def _scalars(document: Any) -> Iterable[Any]:
    if isinstance(document, dict):
        for value in document.values():
            yield from _scalars(value)
    elif isinstance(document, list):
        for value in document:
            yield from _scalars(value)
    else:
        yield document
