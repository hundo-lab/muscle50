"""Telegram LLM v2 number guard: only numbers from the passed JSON documents may appear in an answer."""

from __future__ import annotations

from decimal import Decimal

import pytest

from muscle50.domain.llm_number_guard import allowed_numbers, reply_numbers, unknown_numbers

DATA = {
    "as_of": "2026-10-12",
    "time": "07:12:00",
    "strength": {"exercises": [{"name": "Squat", "weight_kg": "40", "sets": 3, "reps": 12}]},
    "nutrients": {"protein_g": {"remaining": "61.50", "consumed": "1150.25"}},
    "sleep_seconds": 25200.0,
    "flag": True,
    "missing": None,
}


def test_reply_numbers_are_canonical() -> None:
    text = "오늘은 1,150 kcal, 단백질 61.50 g, 07시, 스쿼트 40 kg 3×12, -5"
    assert reply_numbers(text) == tuple(Decimal(value) for value in ("1150", "61.5", "7", "40", "3", "12", "5"))


def test_fullwidth_digits_are_numbers() -> None:
    assert reply_numbers("４０ kg") == (Decimal(40),)


@pytest.mark.parametrize(
    "answer",
    [
        "오늘은 하체예요. 스쿼트 40 kg 3×12부터 시작하세요.",
        "10-12 기준 단백질 61.5 g 남았어요.",
        "2026-10-12, 07:12 기록이에요.",
        "단백질 62 g 남았어요.",  # 61.50 rounded half up
        "kcal 1,150.3 정도예요.",  # 1150.25 to one decimal
        "1150 kcal",
        "수면 25200초",
    ],
)
def test_numbers_from_the_data_pass(answer: str) -> None:
    assert unknown_numbers(answer, allowed_numbers([DATA])) == ()


@pytest.mark.parametrize(
    ("answer", "unknown"),
    [
        ("스쿼트 45 kg으로 올리세요.", ("45",)),
        ("단백질 61.6 g", ("61.6",)),
        ("1,200 kcal", ("1200",)),
    ],
)
def test_numbers_outside_the_data_fail(answer: str, unknown: tuple[str, ...]) -> None:
    assert unknown_numbers(answer, allowed_numbers([DATA])) == tuple(Decimal(value) for value in unknown)


def test_memory_persona_guide_and_message_are_not_sources() -> None:
    allowed = allowed_numbers([DATA])
    memory = "[기억] 요약: 어제 단백질 88 g"
    guide = "저녁은 700 kcal 이상"
    assert unknown_numbers("어제 88 g 드셨죠. 700 kcal 이상 드세요.", allowed) == (Decimal(88), Decimal(700))
    assert Decimal(88) not in allowed_numbers([]) and memory and guide


def test_chat_allows_no_number_at_all() -> None:
    assert unknown_numbers("좋은 아침이에요!", allowed_numbers([])) == ()
    assert unknown_numbers("3세트 하세요", allowed_numbers([])) == (Decimal(3),)


def test_booleans_and_nulls_are_not_numbers_and_long_ids_do_not_crash() -> None:
    allowed = allowed_numbers([{"a": True, "b": None, "id": 123456789012345678901234567890123}])
    assert Decimal(1) not in allowed and Decimal(0) not in allowed
    assert Decimal(123456789012345678901234567890123) in allowed
