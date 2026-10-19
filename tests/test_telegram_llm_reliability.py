"""Telegram LLM v2.4 pure logic (docs/specs/telegram-llm-reliability.md): the menu time-to-live text, the photo
caption rule, the photo memory text, the short summaries and the schema. No I/O."""

from __future__ import annotations

import json
from dataclasses import replace
from importlib.resources import files
from typing import Any

import pytest
import test_llm_today_totals as totals_tests
from test_telegram_llm_domain import interpretation

from muscle50.domain.telegram_llm import (
    MENU_PROPOSAL_TTL_S,
    PROPOSAL_TTL_S,
    Intent,
    Interpretation,
    MenuItem,
    PhotoKind,
    parse_interpretation,
)
from muscle50.domain.telegram_llm_corrections import MENU_WINDOW_S
from muscle50.domain.telegram_llm_photo import (
    album_partial_line,
    caption_is_clearly_eaten,
    photo_memory_text,
    photo_outcome_words,
)
from muscle50.domain.telegram_llm_prompt import PROPOSAL_EXPIRED_TEXT, menu_expired_text
from muscle50.domain.telegram_llm_summary import SummaryVerb, edit_verb, parse_meal_summary
from muscle50.presentation.telegram_llm_summary import render_meal_summary, render_voided

home = totals_tests.home  # the autouse fixture of the day-totals tests: a temporary MUSCLE50_HOME and fixed clock

# --- AC6: the menu time-to-live ---


def test_the_menu_window_and_the_menu_ttl_are_one_constant() -> None:
    assert MENU_WINDOW_S == MENU_PROPOSAL_TTL_S == 4 * 3600
    assert PROPOSAL_TTL_S == 3600


def test_menu_expired_text_names_the_stored_lifetime() -> None:
    assert menu_expired_text(4 * 3600) == (
        "이 메뉴 제안은 유효 시간(4시간)이 지났습니다. 메뉴 사진을 다시 보내거나 다시 물어봐 주세요."
    )
    assert "(60분)" in menu_expired_text(3600)
    assert "(90분)" in menu_expired_text(5400)
    assert "(3시간)" in menu_expired_text(3 * 3600)
    assert menu_expired_text(3600) != PROPOSAL_EXPIRED_TEXT


# --- AC8: the interpret schema and the Intent enum agree ---


def test_the_interpret_schema_intents_equal_the_intent_enum() -> None:
    text = files("muscle50").joinpath("schemas", "telegram_llm_interpret_v1.schema.json").read_text("utf-8")
    schema = json.loads(text)
    assert set(schema["properties"]["intent"]["enum"]) == {intent.value for intent in Intent}
    assert "sync_request" in schema["properties"]["intent"]["enum"]
    assert len(schema["required"]) == 12  # the root keys are unchanged: only the intent enum grew


# --- AC2: when a failed photo read may offer a plain general meal ---

CAPTION_CASES = [
    (None, False),
    ("", False),
    ("점심", False),
    ("점심 먹었어", True),
    ("먹음", True),
    ("이거 먹은 거야", True),
    ("드셨나요", True),
    ("I ate lunch", True),
    ("ATE", True),
    ("ate", True),
    ("plate", False),
    ("chocolate", False),
    ("a plate of rice", False),
    ("가나다ate", True),  # not an ASCII letter before it: a whole word as far as the rule can tell
    ("ate2", True),
    ("점심 메뉴 먹었어", False),
    ("menu ate", False),
    ("MENU 먹음", False),
    ("ＡＴＥ", True),  # full-width letters fold with NFKC
    ("메뉴", False),
]


@pytest.mark.parametrize(("caption", "expected"), CAPTION_CASES)
def test_caption_is_clearly_eaten(caption: str | None, expected: bool) -> None:
    assert caption_is_clearly_eaten(caption) is expected


# --- AC3: what the memory keeps about a photo ---


def _read(kind: PhotoKind, items: list[str | None] | None = None, menu: int = 0) -> Interpretation:
    document = interpretation(
        photo_kind=kind.value,
        items=[
            {
                **interpretation()["items"][0],
                "food_text": name or "x",
                "memo": name if name and name.startswith("메모") else None,
            }
            for name in (items or [])
        ],
    )
    parsed = parse_interpretation(document)
    return replace(parsed, menu_items=tuple(parsed.menu_items) + tuple(_menu_item(n) for n in range(menu)))


def _menu_item(number: int) -> MenuItem:
    return MenuItem(None, None, f"메뉴{number}", None, None, ())


def test_photo_outcome_words() -> None:
    assert photo_outcome_words(None) == "해석 못함"
    assert photo_outcome_words(_read(PhotoKind.UNCLEAR)) == "사진 종류 불명"
    assert photo_outcome_words(_read(PhotoKind.NONE)) == "사진 종류 불명"
    assert photo_outcome_words(_read(PhotoKind.MENU_CAPTURE, menu=5)) == "메뉴 캡처로 읽음: 항목 5개"
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO, ["제육볶음 정식", "햇반"])) == (
        "식사 사진으로 읽음: 제육볶음 정식, 햇반"
    )
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO, ["가", "나", "다", "라", "마"])) == (
        "식사 사진으로 읽음: 가, 나, 다 외 2개"
    )
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO, ["가", "나", "다"])) == "식사 사진으로 읽음: 가, 나, 다"
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO)) == "식사 사진으로 읽음"


def test_a_long_item_name_is_clipped_to_twenty_characters() -> None:
    long_name = "가" * 30
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO, [long_name])) == "식사 사진으로 읽음: " + "가" * 20


def test_photo_memory_text() -> None:
    assert photo_memory_text(2, "점심", "메뉴 캡처로 읽음: 항목 5개") == "[사진 2장] 점심 → 메뉴 캡처로 읽음: 항목 5개"
    assert photo_memory_text(1, None, "해석 못함") == "[사진 1장] → 해석 못함"
    assert photo_memory_text(1, "  ", "사진 종류 불명") == "[사진 1장] → 사진 종류 불명"
    assert photo_memory_text(1, "a  b\nc", "x") == "[사진 1장] a b c → x"


def test_photo_memory_text_survives_the_memory_clip() -> None:
    text = photo_memory_text(4, "캡" * 200, "결" * 300)
    assert len(text) <= 300 and text.startswith("[사진 4장] " + "캡" * 60 + " → ") and text.endswith("결" * 160)


def test_album_partial_line() -> None:
    assert album_partial_line(5, 4) == "사진 5장 중 4장만 읽었습니다"
    assert album_partial_line(2, 2) is None
    assert album_partial_line(1, 1) is None


# --- AC7: the summary of a stored meal (documents made by the real CLI on a temporary home) ---

DAY = totals_tests.DAY
MEAL = f"{DAY}-lunch-1"


def _shown(capsys: pytest.CaptureFixture[str], meal_id: str = MEAL) -> Any:
    return totals_tests._cli(capsys, "nutrition", "meal", "show", meal_id, "--json")


def _log_lunch(capsys: pytest.CaptureFixture[str], *entries: str) -> None:
    totals_tests._log(capsys, "lunch", *entries)


def _rendered(capsys: pytest.CaptureFixture[str], verb: SummaryVerb = SummaryVerb.RECORDED) -> list[str]:
    summary = parse_meal_summary(_shown(capsys))
    assert summary is not None
    return render_meal_summary(summary, verb).split("\n")


def test_a_catalog_item_and_a_label_general_item(capsys: pytest.CaptureFixture[str]) -> None:
    totals_tests._cli(capsys, "nutrition", "food", "add", *totals_tests.CHICKEN)
    _log_lunch(
        capsys,
        *("--general", "--general-note=깻잎닭갈비 삼각김밥 1개"),
        "--general-estimate=visual_estimate:kcal=185-185,protein=5-5,carbs=37-37",
        "--general-estimate-ref=telegram-llm photo sha256:abc (claude sonnet); 라벨",
        *("--item", "chicken-breast", "100", "g"),
    )
    assert _rendered(capsys) == [
        f"기록했습니다: 점심 {MEAL} (10-12)",
        "1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개) - 라벨 kcal 185, 단백질 5 g, 탄수화물 37 g",
        "2. 닭가슴살 (chicken-breast) 100 g - kcal 110, 단백질 23.3 g, 탄수화물 0 g",
        "이 끼니 (추정 포함): kcal 295, 단백질 28.3 g, 탄수화물 37 g, 지방 알 수 없음 (값 모르는 항목 2개 빠짐)",
        f"취소: /void {MEAL}   전체 보기: /show {MEAL}",
    ]


def test_a_range_without_the_label_marker_is_an_estimate_and_a_real_range_is_one_too(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _log_lunch(
        capsys,
        *("--general", "--general-note=국밥", "--general-estimate=visual_estimate:kcal=700-950,protein=30-45"),
        *("--general", "--general-note=김밥", "--general-estimate=visual_estimate:kcal=300-300"),
    )
    lines = _rendered(capsys)
    assert lines[1:3] == [
        "1. 일반식 (메모: 국밥) - 추정 kcal 700~950, 단백질 30~45 g",
        "2. 일반식 (메모: 김밥) - 추정 kcal 300",  # a point range without the label marker is still an estimate
    ]
    assert lines[3] == (
        "이 끼니 (추정 포함): kcal 1000~1250, 단백질 30~45 g (값 모르는 항목 1개 빠짐), "
        "탄수화물 알 수 없음 (값 모르는 항목 2개 빠짐), 지방 알 수 없음 (값 모르는 항목 2개 빠짐)"
    )


def test_a_general_item_without_values_is_no_value_and_a_meal_of_only_those_is_not_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _log_lunch(capsys, "--general", "--general-note=모름")
    lines = _rendered(capsys)
    assert lines[1] == "1. 일반식 (메모: 모름) - 값 없음"
    assert lines[2] == "이 끼니: 값 없음 (0이 아님)"
    _log_lunch_additional = totals_tests._cli(
        capsys, "nutrition", "log", "--date", DAY, "--meal", "dinner", "--general"
    )
    assert "dinner-1" in _log_lunch_additional
    nameless = _shown(capsys, f"{DAY}-dinner-1")
    summary = parse_meal_summary(nameless)
    assert summary is not None and summary.items[0].text == "일반식" and summary.items[0].values == ()


def test_a_value_zero_is_shown_as_zero_and_a_missing_one_is_not(capsys: pytest.CaptureFixture[str]) -> None:
    totals_tests._cli(capsys, "nutrition", "food", "add", *totals_tests.CHICKEN)
    _log_lunch(capsys, "--item", "chicken-breast", "100", "g")
    lines = _rendered(capsys)
    assert lines[1] == "1. 닭가슴살 (chicken-breast) 100 g - kcal 110, 단백질 23.3 g, 탄수화물 0 g"  # fat is unknown
    assert "지방" not in lines[1]
    assert lines[2] == "이 끼니: kcal 110, 단백질 23.3 g, 탄수화물 0 g, 지방 알 수 없음 (값 모르는 항목 1개 빠짐)"


def test_the_cli_rounding_is_used_34_95_reads_35(capsys: pytest.CaptureFixture[str]) -> None:
    totals_tests._cli(capsys, "nutrition", "food", "add", *totals_tests.CHICKEN)
    _log_lunch(capsys, "--item", "chicken-breast", "150", "g")
    lines = _rendered(capsys)
    assert lines[1] == "1. 닭가슴살 (chicken-breast) 150 g - kcal 165, 단백질 35 g, 탄수화물 0 g"


def test_an_edit_and_a_voided_meal(capsys: pytest.CaptureFixture[str]) -> None:
    totals_tests._cli(capsys, "nutrition", "food", "add", *totals_tests.CHICKEN)
    _log_lunch(capsys, "--item", "chicken-breast", "100", "g")
    assert _rendered(capsys, SummaryVerb.EDITED)[-1] == f"확인: /show {MEAL}"
    totals_tests._cli(capsys, "nutrition", "meal", "void", MEAL)
    assert parse_meal_summary(_shown(capsys)) is None
    assert render_voided(MEAL) == f"취소(void)했습니다: {MEAL}\n확인: /show {MEAL}"


def test_the_meal_totals_equal_the_days_totals_of_a_day_with_that_one_meal(capsys: pytest.CaptureFixture[str]) -> None:
    totals_tests._cli(capsys, "nutrition", "food", "add", *totals_tests.CHICKEN)
    _log_lunch(
        capsys,
        *("--item", "chicken-breast", "150", "g"),
        *("--general", "--general-note=국밥", "--general-estimate=visual_estimate:kcal=700-950,protein=30-45"),
        *("--general", "--general-note=모름"),
    )
    summary = parse_meal_summary(_shown(capsys))
    assert summary is not None
    assert summary.totals == totals_tests._totals(capsys)
    assert summary.totals.meal_count == 1


def test_an_unexpected_shape_raises_and_never_guesses() -> None:
    cases: list[Any] = [
        {},
        {"meal_id": "x"},
        [],
        {"meal_id": "x", "meal_type": "lunch", "eaten_at": "2026-10-12T12:00:00+09:00", "items": "no", "total": {}},
    ]
    for broken in cases:
        with pytest.raises((KeyError, TypeError, ValueError)):
            parse_meal_summary(broken)


def test_edit_verb_by_the_command() -> None:
    assert edit_verb(("nutrition", "meal", "void", "m")) is SummaryVerb.VOIDED
    for name in ("replace-item", "add-item", "remove-item", "edit"):
        assert edit_verb(("nutrition", "meal", name, "m")) is SummaryVerb.EDITED
    assert edit_verb(()) is SummaryVerb.EDITED
