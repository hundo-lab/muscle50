"""`config\\telegram_llm_state.json`: the `/llm` provider override and the open meal/menu/edit proposals.

Owned by `telegram run` (created on its first proposal or `/llm` change), versioned, written atomically
(temp file, fsync, `os.replace`) and read strictly: a damaged file is a `TelegramStateError` (the bot
stops, as for the v1 state file), never "no proposals". A proposal holds the exact argv `/ok_` runs.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from muscle50.application.telegram_bot import TelegramStateError
from muscle50.domain.llm_settings import ProviderName
from muscle50.domain.nutrition import MealType, NutrientField, NutritionSourceType
from muscle50.domain.telegram_llm import (
    EMPTY_STATE,
    PROPOSAL_TOKEN,
    LlmState,
    MealCommand,
    MenuChoice,
    Proposal,
    ProposalKind,
    ProposalState,
)

SCHEMA_VERSION = 1


class JsonLlmStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> LlmState:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return EMPTY_STATE
        except OSError as exc:
            raise TelegramStateError(
                f"telegram LLM 상태 파일을 읽을 수 없습니다: {self._path} ({exc.strerror})"
            ) from None
        try:
            return _state(json.loads(raw.decode("utf-8")))
        except UnicodeDecodeError:
            reason = "not UTF-8"
        except json.JSONDecodeError as exc:
            reason = f"not valid JSON: line {exc.lineno}, column {exc.colno}"
        except (KeyError, TypeError, ValueError) as exc:
            reason = f"unexpected content ({type(exc).__name__})"
        raise TelegramStateError(
            f"telegram LLM 상태 파일이 올바르지 않습니다: {self._path} ({reason}). telegram run이 만드는 파일입니다. "
            "지우고 다시 시작해도 됩니다(열린 제안과 /llm 선택만 사라집니다)."
        )

    def save(self, state: LlmState) -> None:
        content = json.dumps(state_document(state), indent=2, ensure_ascii=True) + "\n"
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as exc:
            raise TelegramStateError(
                f"telegram LLM 상태 파일을 쓸 수 없습니다: {self._path} ({exc.strerror}). 아무것도 기록하지 않았습니다."
            ) from None
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()


def state_document(state: LlmState) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider_override": state.provider_override,
        "proposals": [_proposal_document(proposal) for proposal in state.proposals],
    }


def _proposal_document(proposal: Proposal) -> dict[str, Any]:
    return {
        "token": proposal.token,
        "chat_id": proposal.chat_id,
        "kind": proposal.kind.value,
        "created_unix": proposal.created_unix,
        "expires_unix": proposal.expires_unix,
        "state": proposal.state.value,
        "argv_ok": list(proposal.argv_ok),
        "argv_plain": list(proposal.argv_plain),
        "choices": [
            {
                "memo": choice.memo,
                "ranges": [[nutrient.value, str(low), str(high)] for nutrient, low, high in choice.ranges],
                "printed": choice.printed,
            }
            for choice in proposal.choices
        ],
        "meal_type": proposal.meal_type.value if proposal.meal_type is not None else None,
        "day": proposal.day.isoformat() if proposal.day is not None else None,
        "source": proposal.source.value if proposal.source is not None else None,
        "reference": proposal.reference,
        "meal_id": proposal.meal_id,
        "label": proposal.label,
        "meals": [
            {
                "meal_type": meal.meal_type.value,
                "argv_ok": list(meal.argv_ok),
                "argv_plain": list(meal.argv_plain),
            }
            for meal in proposal.meals
        ],
    }


def _state(document: Any) -> LlmState:
    if not isinstance(document, dict) or set(document) != {"schema_version", "provider_override", "proposals"}:
        raise ValueError("unexpected keys")
    if document["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    override = document["provider_override"]
    if override is not None:
        override = ProviderName(override).value
    return LlmState(override, tuple(_proposal(item) for item in document["proposals"]))


def _proposal(item: dict[str, Any]) -> Proposal:
    token = item["token"]
    if not isinstance(token, str) or PROPOSAL_TOKEN.fullmatch(token) is None:
        raise ValueError("bad token")
    integers = (item["chat_id"], item["created_unix"], item["expires_unix"])
    if any(type(value) is not int for value in integers):
        raise ValueError("bad integer")
    return Proposal(
        token=token,
        chat_id=item["chat_id"],
        kind=ProposalKind(item["kind"]),
        created_unix=item["created_unix"],
        expires_unix=item["expires_unix"],
        state=ProposalState(item["state"]),
        argv_ok=_strings(item["argv_ok"]),
        argv_plain=_strings(item["argv_plain"]),
        choices=tuple(
            MenuChoice(
                memo=str(choice["memo"]),
                ranges=tuple(
                    (NutrientField(nutrient), Decimal(low), Decimal(high)) for nutrient, low, high in choice["ranges"]
                ),
                printed=bool(choice["printed"]),
            )
            for choice in item["choices"]
        ),
        meal_type=MealType(item["meal_type"]) if item["meal_type"] is not None else None,
        day=date.fromisoformat(item["day"]) if item["day"] is not None else None,
        source=NutritionSourceType(item["source"]) if item["source"] is not None else None,
        reference=item["reference"],
        meal_id=item["meal_id"],
        label=str(item["label"]),
        # A state file written before multi-meal proposals (v2.1) has no `meals` key: its proposals still load.
        meals=tuple(
            MealCommand(
                meal_type=MealType(meal["meal_type"]),
                argv_ok=_strings(meal["argv_ok"]),
                argv_plain=_strings(meal["argv_plain"]),
            )
            for meal in item.get("meals", [])
        ),
    )


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("argv must be a list of strings")
    return tuple(value)
