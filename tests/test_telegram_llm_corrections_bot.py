"""Telegram LLM v2.3 end to end: label values, follow-up corrections, overlap with `/fix_`, the logged day's totals,
portions and a recent menu item picked by name. `muscle50 telegram run` with a fake Bot API and a fake LLM provider
(never the real `claude`/`codex`, never the network), a temporary MUSCLE50_HOME and synthetic foods only. Covers
AC1-AC13 of docs/specs/telegram-llm-corrections.md."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
import test_telegram_llm_meals_bot as meals
from test_telegram_llm_domain import NULL_EDIT, NULL_ESTIMATE, interpretation
from test_telegram_llm_meals_bot import catalog_item, dishes, est, item

import muscle50.cli as cli
from muscle50.application.telegram_bot import IncomingMessage, IncomingUpdate
from muscle50.domain.telegram_commands import pending_migration_text
from muscle50.domain.telegram_llm_prompt import (
    EDIT_CATALOG_ESTIMATE_TEXT,
    EDIT_NO_MEAL_TEXT,
    EDIT_NO_OPEN_TEXT,
    EDIT_NO_RECENT_TEXT,
    OVERLAP_MANY_TEXT,
    OVERLAP_SAME_TEXT,
    PROPOSAL_CANCELLED_TEXT,
    PROPOSAL_EXPIRED_TEXT,
    PROPOSAL_UNKNOWN_TEXT,
    PROPOSAL_USED_TEXT,
    PROPOSAL_WRONG_KIND_TEXT,
)
from muscle50.infrastructure.sqlite.nutrition_reader import SqliteNutritionReader
from muscle50.infrastructure.sqlite.schema_status import code_migration_versions

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network


def prepare(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)


def say(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    document: dict[str, Any] | None,
    update_id: int,
    words: str,
) -> tuple[list[str], bot.FakeProvider]:
    provider = bot.FakeProvider(*([document] if document is not None else []))
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(update_id, words))
    return replies, provider


# --- AC11: the totals are those of the logged day ---


def test_a_past_day_is_confirmed_with_that_days_totals_and_today_keeps_its_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    yesterday = dishes(item("국밥", "dinner", estimate=est((600, 700), (20, 30))), date_expression="yesterday")
    say(monkeypatch, capsys, yesterday, 1, "어제 저녁 국밥")
    replies, _provider = say(monkeypatch, capsys, None, 2, "/ok_7f3a")
    assert replies[0].split("\n")[-4:] == [
        "  kcal 600~700",
        "  단백질 20~30 g",
        "  탄수화물 알 수 없음 (값 모르는 항목 1개 빠짐)",
        "  지방 알 수 없음 (값 모르는 항목 1개 빠짐)",
    ]
    assert "10-05 누적 (추정 포함):" in replies[0] and "오늘 누적" not in replies[0]
    # a record for today keeps the v2 label; the other day's meal is not in it
    say(monkeypatch, capsys, dishes(catalog_item("닭가슴살", "lunch", 1, "pack")), 3, "점심 닭가슴살")
    replies, _provider = say(monkeypatch, capsys, None, 4, "/ok_91c0")
    assert "\n오늘 누적:\n  kcal 165\n" in replies[0] and "10-05" not in replies[0].split("취소: /void")[1]
    assert meals.meal_tables(home)["nutrition_meals"]


# --- AC1: label values ---

PHOTO_DIGEST = hashlib.sha256(bot.PHOTO).hexdigest()[:12]
LABEL_ESTIMATE = est((185, 185), (5, 5), carbs_min=37, carbs_max=37)


def label_item(**fields: Any) -> dict[str, Any]:
    return bot._item(
        "삼각김밥",
        None,
        None,
        kind="general",
        memo="깻잎닭갈비 삼각김밥 1개",
        meal_type="breakfast",
        estimate=fields.pop("estimate", LABEL_ESTIMATE),
        from_label=fields.pop("from_label", True),
        **fields,
    )


def label_photo(**fields: Any) -> dict[str, Any]:
    return dishes(label_item(**fields), catalog_item("닭가슴살", "breakfast", 1, "pack"), photo_kind="meal_photo")


def send_photo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    update_id: int,
    *documents: dict[str, Any],
) -> tuple[list[str], bot.FakeProvider]:
    provider = bot.FakeProvider(*documents)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.photo(update_id, "아침으로 삼각김밥 먹음"))
    return replies, provider


def test_a_label_value_is_shown_as_a_label_without_a_recheck_or_a_marker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    replies, provider = send_photo(monkeypatch, capsys, 1, label_photo())
    assert len(provider.requests) == 1  # no corrective re-ask
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (아침, 10-06, 사진 추정)",
                "1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)",
                "   라벨: kcal 185, 단백질 5 g, 탄수화물 37 g",
                "2. 닭가슴살 (chicken-breast) 1 pack",
                "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a",
            ]
        )
    ]
    (proposal,) = meals.state_proposals(home)
    assert proposal["argv_ok"][6:10] == [
        *("--general", "--general-note=깻잎닭갈비 삼각김밥 1개"),
        "--general-estimate=visual_estimate:kcal=185-185,protein=5-5,carbs=37-37",
        f"--general-estimate-ref=telegram-llm photo sha256:{PHOTO_DIGEST} (claude sonnet); 라벨",
    ]
    assert bot._history(home)[-1]["recheck"] is None


def test_a_label_is_stored_as_a_normal_estimate_with_the_label_in_its_reference(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    send_photo(monkeypatch, capsys, 1, label_photo())
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    stored = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-breakfast-1", "--json"))
    nutrients = stored["items"][0]["nutrients"]
    assert nutrients["calories_kcal"]["source_type"] == "visual_estimate"
    assert (nutrients["calories_kcal"]["minimum"], nutrients["calories_kcal"]["maximum"]) == ("185", "185")
    assert nutrients["fat_g"] is None  # the label does not show it: unknown, never 0
    assert stored["items"][0]["facts"][0]["source_reference"].endswith("(claude sonnet); 라벨")


def test_a_single_value_without_the_label_flag_is_still_rechecked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    plain = label_photo(from_label=False)
    replies, provider = send_photo(monkeypatch, capsys, 1, plain, plain)
    assert len(provider.requests) == 2 and "range_is_a_point" in provider.requests[1][0].prompt
    assert "   추정: kcal 185, 단백질 5 g, 탄수화물 37 g (estimated) (값 확인 필요)" in replies[0]
    assert "라벨:" not in replies[0]


def test_a_label_with_a_real_range_is_an_ordinary_estimate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    mixed = label_photo(estimate=est((185, 185), (5, 8), carbs_min=37, carbs_max=37))
    replies, provider = send_photo(monkeypatch, capsys, 1, mixed, mixed)
    assert len(provider.requests) == 2  # the point values are checked as for any estimate
    assert "라벨:" not in replies[0] and "추정: kcal 185, 단백질 5~8 g" in replies[0]


# --- AC10: assumed portions and the dish name in the memo ---


def stew(**fields: Any) -> dict[str, Any]:
    return bot._item(
        "안동찜닭 닭 및 감자 위주",
        None,
        None,
        kind="general",
        memo="닭 및 감자 위주",
        meal_type="lunch",
        estimate=est((650, 950), (35, 50)),
        assumption="닭과 감자를 중간 크기로 가정",
        portions=[
            {"name": "닭", "g_min": 150, "g_max": 200},
            {"name": "감자", "g_min": 100, "g_max": 150},
        ],
        **fields,
    )


def test_assumed_portions_are_shown_per_component_and_kept_in_the_reference(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    replies, _provider = say(monkeypatch, capsys, dishes(stew()), 1, "점심 안동찜닭 닭 및 감자 위주")
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (점심, 10-06)",
                "1. 일반식 (메모: 안동찜닭 닭 및 감자 위주)",
                "   추정: kcal 650~950, 단백질 35~50 g (estimated)",
                "   양 가정: 닭 150~200 g, 감자 100~150 g",
                "   가정: 닭과 감자를 중간 크기로 가정",
                "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a",
            ]
        )
    ]
    say(monkeypatch, capsys, None, 2, "/ok_7f3a")
    stored = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert stored["items"][0]["note"] == "안동찜닭 닭 및 감자 위주"
    reference = stored["items"][0]["facts"][0]["source_reference"]
    assert (
        reference
        == "telegram-llm text (claude sonnet); 양: 닭 150-200g, 감자 100-150g; 가정: 닭과 감자를 중간 크기로 가정"
    )


def test_a_stated_amount_has_no_portion_line_and_a_memo_with_the_name_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    document = dishes(item("김밥 2.5줄", "lunch", estimate=est((800, 1150), (25, 40))))
    replies, _provider = say(monkeypatch, capsys, document, 1, "점심 김밥 두줄 반")
    assert "양 가정" not in replies[0] and "1. 일반식 (메모: 김밥 2.5줄)" in replies[0]
    assert "양:" not in meals.state_proposals(home)[0]["argv_ok"][-1]


# --- AC2, AC4, AC5: correcting what was just recorded ---


def edit_doc(action: str, *, refers: str | None = "last_recorded", meal_type: str | None = None, **fields: Any) -> Any:
    edit = {**NULL_EDIT, "action": action, **fields}
    return interpretation(intent="meal_edit", refers_to=refers, items=[], meal_type=meal_type, edit=edit)


def record_label_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, *, update_id: int = 1
) -> None:
    """The first two messages of the 2026-10-14 replay: a label photo, then `/ok`."""
    send_photo(monkeypatch, capsys, update_id, label_photo())
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(update_id + 1, "/ok_7f3a"))


FAT_FIX = edit_doc(
    "change_estimate",
    target_food_text="삼각김밥",
    estimate={**NULL_ESTIMATE, "fat_min": 2, "fat_max": 2},
    from_label=True,
)
FAT_FIX_PROPOSAL = "\n".join(
    [
        "이렇게 고칠까요?",
        "아침 2026-10-06-breakfast-1 item 1: 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)",
        "  지방 알 수 없음 → 2 g (라벨)",
        "고치기: /ok_91c0   취소: /no_91c0",
    ]
)


def test_a_follow_up_after_a_record_becomes_an_edit_and_never_a_new_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    before = meals.meal_tables(home)
    replies, provider = say(monkeypatch, capsys, FAT_FIX, 3, "삼각김밥 지방 2g 이네 사진에 나와있어")
    assert replies == [FAT_FIX_PROPOSAL]
    assert meals.meal_tables(home) == before  # nothing is written before /ok
    prompt = provider.requests[0][0].prompt
    assert "<직전 기록>\n2026-10-06-breakfast-1 | 아침\n1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개) | kcal 185," in prompt
    proposals = meals.state_proposals(home)
    assert [proposal["state"] for proposal in proposals] == ["used", "open"]
    edit_proposal = proposals[1]
    assert edit_proposal["kind"] == "edit" and edit_proposal["day"] == "2026-10-06"
    assert edit_proposal["argv_ok"] == [
        *("nutrition", "meal", "replace-item", "2026-10-06-breakfast-1", "--item-number", "1", "--general"),
        "--general-note=깻잎닭갈비 삼각김밥 1개",
        "--general-estimate=language_estimate:kcal=185-185,protein=5-5,carbs=37-37,fat=2-2",
        "--general-estimate-ref=telegram-llm edit (claude sonnet); 라벨",
    ]
    replies, _provider = say(monkeypatch, capsys, None, 4, "/ok_91c0")
    assert replies[0].startswith("Replaced item 1 of meal 2026-10-06-breakfast-1 with item 3.")
    assert "\n확인: /show 2026-10-06-breakfast-1\n오늘 누적" in replies[0]
    assert {row[0] for row in bot._tables(home)["nutrition_meals"]} == {"2026-10-06-breakfast-1"}  # no second meal
    tables = bot._tables(home)
    assert len(tables["nutrition_meal_item_removals"]) == 1
    estimate_facts = [row for row in tables["nutrition_facts"] if str(row[0]).endswith(":estimate")]
    assert len(estimate_facts) == 2  # the old label fact stays next to the new one
    assert "F 2-2 g" in bot._ok(capsys, "nutrition", "day")
    history = bot._history(home)
    assert history[-1]["kind"] == "edit"
    assert history[-1]["result"] == {"exit_code": 0, "meal_id": "2026-10-06-breakfast-1"}


def test_a_memo_only_edit_sends_the_stored_estimate_again_with_its_own_reference(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    memo_only = edit_doc("change_estimate", target_food_text="삼각김밥", new_memo="참치마요 삼각김밥 1개")
    replies, _provider = say(monkeypatch, capsys, memo_only, 3, "그거 참치마요야")
    assert replies[0].split("\n")[1:3] == [
        "아침 2026-10-06-breakfast-1 item 1: 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)",
        "  메모: 깻잎닭갈비 삼각김밥 1개 → 참치마요 삼각김밥 1개",
    ]
    argv = meals.state_proposals(home)[1]["argv_ok"]
    assert argv[7:] == [
        "--general-note=참치마요 삼각김밥 1개",
        "--general-estimate=visual_estimate:kcal=185-185,protein=5-5,carbs=37-37",
        f"--general-estimate-ref=telegram-llm photo sha256:{PHOTO_DIGEST} (claude sonnet); 라벨",
    ]


def test_a_changed_estimate_that_fails_a_check_is_marked_and_not_asked_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    wrong = edit_doc(
        "change_estimate",
        target_food_text="삼각김밥",
        estimate={**NULL_ESTIMATE, "fat_min": 30, "fat_max": 30},
        from_label=True,
    )
    replies, provider = say(monkeypatch, capsys, wrong, 3, "지방 30g")
    assert len(provider.requests) == 1  # no re-ask for an edit
    assert "  지방 알 수 없음 → 30 g (라벨) (값 확인 필요)" in replies[0]
    assert "값 확인 필요: 열량과 영양소 합이 맞지 않음" in replies[0]
    argv = meals.state_proposals(home)[1]["argv_ok"]
    assert argv[-1] == "--general-estimate-ref=telegram-llm edit (claude sonnet); 라벨; 값 확인 필요"


def test_a_catalog_item_is_never_given_an_estimate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    before = meals.meal_tables(home)
    document = edit_doc(
        "change_estimate", target_food_text="닭가슴살", estimate={**NULL_ESTIMATE, "fat_min": 3, "fat_max": 3}
    )
    replies, _provider = say(monkeypatch, capsys, document, 3, "닭가슴살 지방 3g")
    assert replies == [EDIT_CATALOG_ESTIMATE_TEXT]
    assert meals.meal_tables(home) == before and len(meals.state_proposals(home)) == 1


def test_the_last_recorded_is_the_last_two_meals_and_exactly_one_may_match(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)  # breakfast: a label item and chicken
    lunch = dishes(item("국밥", "lunch", estimate=est((600, 700), (20, 30))))
    say(monkeypatch, capsys, lunch, 3, "점심 국밥")
    say(monkeypatch, capsys, None, 4, "/ok_91c0")
    dinner = dishes(item("파스타", "dinner", estimate=est((700, 800), (20, 30))))
    say(monkeypatch, capsys, dinner, 5, "저녁 파스타")
    say(monkeypatch, capsys, None, 6, "/ok_c2e1")
    before = meals.meal_tables(home)
    # three meals exist; only the last two are "just recorded": the breakfast is not offered
    both = edit_doc("change_estimate", target_food_text="국밥", new_memo="국밥 큰 것")
    replies, provider = say(monkeypatch, capsys, both, 7, "국밥 큰 거야")
    block = provider.requests[0][0].prompt.split("<직전 기록>\n")[1].split("\n\n")[0]
    assert block.startswith("2026-10-06-dinner-1 | 저녁") and "2026-10-06-lunch-1 | 점심" in block
    assert "breakfast-1" not in block
    # exactly one of the two matches the words: that meal
    assert replies[0].split("\n")[1] == "점심 2026-10-06-lunch-1 item 1: 일반식 (메모: 국밥)"
    # nothing matches: candidates, nothing written
    none = edit_doc("change_estimate", target_food_text="김치찌개", new_memo="김치찌개 큰 것")
    replies, _provider = say(monkeypatch, capsys, none, 8, "김치찌개 큰 거야")
    assert replies[0].split("\n")[1:3] == ["/show 2026-10-06-dinner-1", "/show 2026-10-06-lunch-1"]
    # a whole-meal action with nothing to tell the two apart matches both: candidates, never "the newest"
    replies, _provider = say(monkeypatch, capsys, edit_doc("void_meal"), 9, "방금 거 취소")
    assert replies[0].split("\n")[1:3] == ["/show 2026-10-06-dinner-1", "/show 2026-10-06-lunch-1"]
    assert meals.meal_tables(home) == before


def test_no_recent_meal_gives_a_fixed_reply_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    before = meals.meal_tables(home)
    replies, _provider = say(monkeypatch, capsys, FAT_FIX, 1, "방금 거 지방 2g")
    assert replies == [EDIT_NO_RECENT_TEXT] and meals.meal_tables(home) == before
    record_label_meal(monkeypatch, capsys, home, update_id=2)
    bot._ok(capsys, "nutrition", "meal", "void", "2026-10-06-breakfast-1")  # the recorded meal was voided
    replies, _provider = say(monkeypatch, capsys, FAT_FIX, 4, "방금 거 지방 2g")
    assert replies == [EDIT_NO_RECENT_TEXT]


def test_a_recent_meal_is_found_after_a_restart_without_any_time_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    later = bot.NOW + timedelta(days=3)
    monkeypatch.setattr(cli, "_now", lambda: later)
    late = IncomingUpdate(3, IncomingMessage(bot.ALLOWED, "지방 2g이래", int(later.timestamp())))
    provider = bot.FakeProvider(FAT_FIX)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, late)
    assert replies[0].startswith("이렇게 고칠까요?\n아침 2026-10-06-breakfast-1 item 1:")
    assert "2026-10-06-breakfast-1 | 아침" in provider.requests[0][0].prompt


def with_ordinal(document: dict[str, Any], ordinal: int) -> dict[str, Any]:
    clone = copy.deepcopy(document)
    clone["edit"]["target_meal_ordinal"] = ordinal
    return clone


def test_the_nth_meal_of_a_type_counts_only_active_meals(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    for _ in range(2):
        bot._ok(capsys, "nutrition", "log", "--meal", "breakfast", "--additional", "--item", "햇반", "1", "pack")
    bot._ok(capsys, "nutrition", "meal", "void", "2026-10-06-breakfast-1")
    base = edit_doc("change_quantity", refers=None, meal_type="breakfast", target_food_text="햇반", new_quantity=2)
    replies, _provider = say(monkeypatch, capsys, with_ordinal(base, 1), 1, "아침 1식 햇반 2개로")
    assert "아침 2026-10-06-breakfast-2 item 1: 햇반 1 pack → 햇반 (hetbahn-210) 2 pack" in replies[0]
    replies, _provider = say(monkeypatch, capsys, with_ordinal(base, 2), 2, "아침 2식 햇반 2개로")
    assert replies == [EDIT_NO_MEAL_TEXT]
    without_type = with_ordinal(base, 1)
    without_type["meal_type"] = None
    replies, _provider = say(monkeypatch, capsys, without_type, 3, "1식 햇반 2개로")
    assert replies[0].split("\n")[1:2] == ["/show 2026-10-06-breakfast-2"]


def test_a_general_item_is_found_by_its_memo_and_an_ambiguous_one_lists_the_items(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    bot._ok(
        capsys,
        *("nutrition", "log", "--meal", "breakfast"),
        *("--general", "--general-note=깻잎닭갈비 삼각김밥 1개", "--general", "--general-note=참치마요 삼각김밥 1개"),
    )
    before = meals.meal_tables(home)
    document = edit_doc("remove_item", refers=None, meal_type="breakfast", target_food_text="삼각김밥")
    replies, _provider = say(monkeypatch, capsys, document, 1, "삼각김밥 빼줘")
    assert replies == [
        "\n".join(
            [
                "어느 음식인지 하나로 정하지 못해 아무것도 바꾸지 않았습니다. 후보:",
                "2026-10-06-breakfast-1 item 1: 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)",
                "2026-10-06-breakfast-1 item 2: 일반식 (메모: 참치마요 삼각김밥 1개)",
                "음식 이름을 더 구체적으로 적어 다시 보내 주세요.",
            ]
        )
    ]
    assert meals.meal_tables(home) == before
    document = edit_doc("remove_item", refers=None, meal_type="breakfast", target_food_text="참치마요")
    replies, _provider = say(monkeypatch, capsys, document, 2, "참치마요 빼줘")
    assert replies[0].split("\n")[1] == "아침 2026-10-06-breakfast-1 item 2: 일반식 (메모: 참치마요 삼각김밥 1개) 빼기"


# --- AC7: correcting a proposal that is still open ---


def test_correcting_an_open_proposal_replaces_it_in_one_save(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    first = dishes(catalog_item("닭가슴살", "lunch", 2, "pack"))
    say(monkeypatch, capsys, first, 1, "점심 닭가슴살 2팩")
    corrected = dishes(catalog_item("닭가슴살", "lunch", 1, "pack"), refers_to="open_proposal")
    replies, provider = say(monkeypatch, capsys, corrected, 2, "아니 2팩 아니고 1팩")
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (점심, 10-06)",
                "1. 닭가슴살 (chicken-breast) 1 pack",
                "이전 제안(/ok_7f3a)은 취소했습니다.",
                "기록: /ok_91c0   취소: /no_91c0",
            ]
        )
    ]
    prompt = provider.requests[0][0].prompt
    assert "<열린 제안>\n/ok_7f3a | 점심 10-06\n1. 닭가슴살 (chicken-breast) 2 pack" in prompt
    states = {proposal["token"]: proposal["state"] for proposal in meals.state_proposals(home)}
    assert states == {"7f3a": "cancelled", "91c0": "open"}  # one save: never both open
    replies, _provider = say(monkeypatch, capsys, None, 3, "/ok_7f3a")
    assert replies == [PROPOSAL_CANCELLED_TEXT]
    assert not meals.meal_tables(home)["nutrition_meals"]
    say(monkeypatch, capsys, None, 4, "/ok_91c0")
    stored = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert stored["items"][0]["quantity"] == "1"


def test_correcting_with_no_open_proposal_creates_no_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    corrected = dishes(catalog_item("닭가슴살", "lunch", 1, "pack"), refers_to="open_proposal")
    replies, _provider = say(monkeypatch, capsys, corrected, 1, "아니 1팩")
    assert replies == [EDIT_NO_OPEN_TEXT]
    assert not (home / "config" / meals.STATE).exists()
    # a used proposal is not "open" either
    say(monkeypatch, capsys, dishes(catalog_item("닭가슴살", "lunch", 2, "pack")), 2, "점심 닭가슴살 2팩")
    say(monkeypatch, capsys, None, 3, "/ok_7f3a")
    replies, provider = say(monkeypatch, capsys, corrected, 4, "아니 1팩")
    assert replies == [EDIT_NO_OPEN_TEXT] and "<열린 제안>\n" not in provider.requests[0][0].prompt


# --- the read-only lookup of one active meal ---


def test_get_active_is_read_only_and_none_for_a_voided_or_unknown_meal(
    capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    bot._ok(capsys, "nutrition", "log", "--meal", "breakfast", "--item", "햇반", "1", "pack")
    bot._ok(capsys, "nutrition", "log", "--meal", "lunch", "--item", "햇반", "1", "pack")
    database = home / "db" / "muscle50.sqlite3"
    reader = SqliteNutritionReader(database)
    before = database.read_bytes()
    meal = reader.get_active("2026-10-06-breakfast-1")
    assert meal is not None and meal.meal_type.value == "breakfast" and meal.items[0].food_profile_id == "hetbahn-210"
    assert reader.get_active("2026-10-06-dinner-9") is None
    bot._ok(capsys, "nutrition", "meal", "void", "2026-10-06-lunch-1")
    assert reader.get_active("2026-10-06-lunch-1") is None
    assert database.read_bytes() != before  # only the void command wrote; the reads below do not
    after_void = database.read_bytes()
    reader.get_active("2026-10-06-breakfast-1")
    assert database.read_bytes() == after_void


def test_get_active_reads_a_database_without_the_void_and_revision_tables(
    capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    bot._ok(capsys, "nutrition", "log", "--meal", "breakfast", "--item", "햇반", "1", "pack")
    database = home / "db" / "muscle50.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TABLE nutrition_meal_voids")
        connection.execute("DROP TABLE nutrition_meal_revisions")
        connection.commit()
    finally:
        connection.close()
    meal = SqliteNutritionReader(database).get_active("2026-10-06-breakfast-1")
    assert meal is not None and meal.meal_id == "2026-10-06-breakfast-1"


# --- AC3: the same food again in a slot that already has it ---


def tuna_rice_ball(estimate: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    return bot._item(
        "삼각김밥",
        None,
        None,
        kind="general",
        memo="깻잎닭갈비 삼각김밥 1개",
        meal_type="breakfast",
        estimate=estimate or est((180, 200), (5, 6)),
        **fields,
    )


OVERLAP_PROPOSAL = "\n".join(
    [
        "오늘 아침(2026-10-06-breakfast-1)에 이미 같은 음식이 있습니다: 깻잎닭갈비 삼각김밥 1개",
        "이렇게 기록할까요? (아침, 10-06)",
        "1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)",
        "   추정: kcal 180~200, 단백질 5~6 g (estimated)",
    ]
)

OVERLAP_COMMANDS = (
    "기존 아침 고치기: /fix_91c0   하나 더 기록: /ok_91c0   일반식만 기록(값 없이): /plain_91c0   취소: /no_91c0"
)


def overlap_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, *items: dict[str, Any]
) -> list[str]:
    """Breakfast recorded from a label photo (token 7f3a), then a text message that proposes ``items``."""
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    replies, _provider = say(monkeypatch, capsys, dishes(*items), 3, "아침에 삼각김밥 먹었어")
    return replies


def test_an_overlapping_food_asks_fix_one_more_or_cancel_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    before = meals.meal_tables(home)
    replies, _provider = say(monkeypatch, capsys, dishes(tuna_rice_ball()), 3, "아침에 삼각김밥 먹었어")
    assert replies == [OVERLAP_PROPOSAL + "\n" + OVERLAP_COMMANDS]
    assert meals.meal_tables(home) == before
    overlap = meals.state_proposals(home)[1]
    assert overlap["fix_argv"][:7] == ["nutrition", "meal", "replace-item", MEAL_1, "--item-number", "1", "--general"]
    assert overlap["argv_ok"][-1] == "--additional"  # /ok_ still records another meal


MEAL_1 = "2026-10-06-breakfast-1"


def test_fix_makes_an_edit_proposal_and_kills_the_overlap_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    overlap_reply(monkeypatch, capsys, home, tuna_rice_ball())
    before = meals.meal_tables(home)
    replies, _provider = say(monkeypatch, capsys, None, 4, "/fix_91c0")
    assert replies == [
        "\n".join(
            [
                "이렇게 고칠까요?",
                f"아침 {MEAL_1} item 1: 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)",
                "  kcal 185, 단백질 5 g, 탄수화물 37 g → kcal 180~200, 단백질 5~6 g",
                "고치기: /ok_c2e1   취소: /no_c2e1",
            ]
        )
    ]
    assert meals.meal_tables(home) == before  # nothing is written by /fix_ itself
    states = {proposal["token"]: proposal["state"] for proposal in meals.state_proposals(home)}
    assert states == {"7f3a": "used", "91c0": "cancelled", "c2e1": "open"}  # one save
    edit = meals.state_proposals(home)[2]
    assert edit["kind"] == "edit" and edit["meal_id"] == MEAL_1 and edit["day"] == "2026-10-06"
    assert edit["argv_ok"][:7] == ["nutrition", "meal", "replace-item", MEAL_1, "--item-number", "1", "--general"]
    assert edit["argv_ok"][7:9] == [
        "--general-note=깻잎닭갈비 삼각김밥 1개",
        "--general-estimate=language_estimate:kcal=180-200,protein=5-6",
    ]
    # the overlap proposal's commands are dead
    replies, _provider = say(monkeypatch, capsys, None, 5, "/ok_91c0")
    assert replies == [PROPOSAL_CANCELLED_TEXT]
    replies, _provider = say(monkeypatch, capsys, None, 6, "/fix_91c0")
    assert replies == [PROPOSAL_CANCELLED_TEXT]
    # confirming the fix replaces the item in the same meal: no second meal
    replies, _provider = say(monkeypatch, capsys, None, 7, "/ok_c2e1")
    assert replies[0].startswith(f"Replaced item 1 of meal {MEAL_1} with item 3.")
    assert {row[0] for row in bot._tables(home)["nutrition_meals"]} == {MEAL_1}
    shown = json.loads(bot._ok(capsys, "nutrition", "meal", "show", MEAL_1, "--json"))
    assert [item["sequence"] for item in shown["items"]] == [2, 3]
    assert shown["items"][1]["nutrients"]["calories_kcal"]["minimum"] == "180"


def test_the_fix_choice_is_in_the_history_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    overlap_reply(monkeypatch, capsys, home, tuna_rice_ball())
    say(monkeypatch, capsys, None, 4, "/fix_91c0")
    history = bot._history(home)  # a rejected kind would only be logged, never raised: assert the line itself
    assert [entry["kind"] for entry in history] == ["photo", "confirm", "text", "fix"]
    assert history[-1]["text"] == "/fix_91c0" and history[-1]["proposal"] == "c2e1"
    assert history[-1]["reply"].startswith("이렇게 고칠까요?")


def test_ok_after_an_overlap_records_another_meal_with_additional(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    overlap_reply(monkeypatch, capsys, home, tuna_rice_ball())
    replies, _provider = say(monkeypatch, capsys, None, 4, "/ok_91c0")
    assert replies[0].startswith("Recorded meal 2026-10-06-breakfast-2.")
    assert {row[0] for row in bot._tables(home)["nutrition_meals"]} == {MEAL_1, "2026-10-06-breakfast-2"}
    replies, _provider = say(monkeypatch, capsys, None, 5, "/fix_91c0")
    assert replies == [PROPOSAL_USED_TEXT]


def test_the_same_content_offers_no_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    same = tuna_rice_ball(estimate=LABEL_ESTIMATE, from_label=True)
    replies = overlap_reply(monkeypatch, capsys, home, same, catalog_item("닭가슴살", "breakfast", 1, "pack"))
    lines = replies[0].split("\n")
    assert lines[:2] == [
        "오늘 아침(2026-10-06-breakfast-1)에 이미 같은 음식이 있습니다: 깻잎닭갈비 삼각김밥 1개, 닭가슴살",
        OVERLAP_SAME_TEXT,
    ]
    assert lines[-1] == "하나 더 기록: /ok_91c0   일반식만 기록(값 없이): /plain_91c0   취소: /no_91c0"
    assert "/fix_" not in replies[0] and meals.state_proposals(home)[1]["fix_argv"] == []
    replies, _provider = say(monkeypatch, capsys, None, 4, "/fix_91c0")
    assert replies == [PROPOSAL_WRONG_KIND_TEXT]


def test_several_changes_offer_no_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    replies = overlap_reply(
        monkeypatch, capsys, home, tuna_rice_ball(), catalog_item("닭가슴살", "breakfast", 2, "pack")
    )
    assert replies[0].split("\n")[1] == OVERLAP_MANY_TEXT
    assert "/fix_" not in replies[0] and "하나 더 기록: /ok_91c0" in replies[0]
    replies, _provider = say(monkeypatch, capsys, None, 4, "/fix_91c0")
    assert replies == [PROPOSAL_WRONG_KIND_TEXT]


def test_new_items_next_to_an_identical_one_are_added_by_one_add_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    replies = overlap_reply(
        monkeypatch,
        capsys,
        home,
        catalog_item("닭가슴살", "breakfast", 1, "pack"),
        catalog_item("햇반", "breakfast", 1, "pack"),
    )
    assert "기존 아침 고치기: /fix_91c0" in replies[0]
    fix = meals.state_proposals(home)[1]["fix_argv"]
    assert fix == ["nutrition", "meal", "add-item", MEAL_1, "--item", "hetbahn-210", "1", "pack"]
    replies, _provider = say(monkeypatch, capsys, None, 4, "/fix_91c0")
    assert f"아침 {MEAL_1}: 추가 햇반 (hetbahn-210) 1 pack" in replies[0]
    say(monkeypatch, capsys, None, 5, "/ok_c2e1")
    shown = json.loads(bot._ok(capsys, "nutrition", "meal", "show", MEAL_1, "--json"))
    assert [item["sequence"] for item in shown["items"]] == [1, 2, 3]


def test_a_different_food_is_not_an_overlap_and_keeps_the_notice_on_top(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    replies = overlap_reply(monkeypatch, capsys, home, catalog_item("햇반", "breakfast", 1, "pack"))
    assert replies[0].split("\n")[:2] == [
        f"이미 기록된 아침({MEAL_1})이 있어 하나 더 기록합니다.",
        "이렇게 기록할까요? (아침, 10-06)",
    ]
    assert "/fix_" not in replies[0] and "기록: /ok_91c0" in replies[0]


def test_a_multi_meal_overlap_has_the_notice_and_no_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    document = dishes(
        tuna_rice_ball(), item("국밥", "lunch", estimate=est((600, 700), (20, 30))), item("파스타", "dinner")
    )
    replies, _provider = say(monkeypatch, capsys, document, 3, "아침에 삼각김밥, 점심 국밥, 저녁 파스타")
    lines = replies[0].split("\n")
    assert lines[0] == "오늘 아침(2026-10-06-breakfast-1)에 이미 같은 음식이 있습니다: 깻잎닭갈비 삼각김밥 1개"
    assert lines[1] == "이렇게 기록할까요? (10-06, 3끼)"
    assert "/fix_" not in replies[0] and "기록(겹치는 끼니는 하나 더): /ok_91c0" in replies[0]
    assert meals.state_proposals(home)[1]["fix_argv"] == []


def test_fix_on_proposals_that_cannot_be_fixed_gets_the_fixed_texts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    say(monkeypatch, capsys, dishes(catalog_item("닭가슴살", "lunch", 1, "pack")), 1, "점심 닭가슴살")
    replies, _provider = say(monkeypatch, capsys, None, 2, "/fix_7f3a")  # an open proposal with nothing to fix
    assert replies == [PROPOSAL_WRONG_KIND_TEXT]
    replies, _provider = say(monkeypatch, capsys, None, 3, "/fix_ffff")
    assert replies == [PROPOSAL_UNKNOWN_TEXT]
    # a menu proposal is not a meal proposal
    menu = interpretation(intent="menu_suggest", items=[])
    suggest = {
        "lead": "",
        "suggestions": [
            {"name": "샐러드", "category": "home", "description": "", "estimate": est((300, 400), (20, 30)), "note": ""}
        ],
        "memory_summary": "",
    }
    bot._session(monkeypatch, capsys, bot.FakeProvider(menu, suggest), bot.text(4, "뭐 먹지"))
    replies, _provider = say(monkeypatch, capsys, None, 5, "/fix_91c0")
    assert replies == [PROPOSAL_WRONG_KIND_TEXT]


def test_fix_on_an_expired_overlap_proposal_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    overlap_reply(monkeypatch, capsys, home, tuna_rice_ball())
    before = meals.meal_tables(home)
    later = bot.NOW + timedelta(minutes=61)
    monkeypatch.setattr(cli, "_now", lambda: later)
    late = IncomingUpdate(4, IncomingMessage(bot.ALLOWED, "/fix_91c0", int(later.timestamp())))
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), late)
    assert replies == [PROPOSAL_EXPIRED_TEXT] and meals.meal_tables(home) == before
    assert {proposal["token"] for proposal in meals.state_proposals(home)} == {"7f3a", "91c0"}


def test_a_pending_migration_refuses_the_fix_confirmation_without_consuming_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    overlap_reply(monkeypatch, capsys, home, tuna_rice_ball())
    say(monkeypatch, capsys, None, 4, "/fix_91c0")
    latest = code_migration_versions()[-1]
    v1._drop_migration_marker(v1._database(home), latest)
    replies, _provider = say(monkeypatch, capsys, None, 5, "/ok_c2e1")
    assert replies == [pending_migration_text((latest,))]
    assert meals.state_proposals(home)[2]["state"] == "open"


# --- AC12: a recently shown menu item picked by name ---

STEW_MENU = interpretation(
    intent="menu",
    photo_kind="menu_capture",
    items=[],
    meal_type=None,
    menu={
        "slots_visible": ["lunch"],
        "items": [
            bot._menu_item("한식", "얼큰순살감자탕", (900, 1100), (40, 55), printed_kcal=1022),
            bot._menu_item("분식", "김밥", (300, 400), (8, 12)),
        ],
    },
)


def picked(name: str, ref: int | None, **fields: Any) -> dict[str, Any]:
    """The user's meal message that names a menu item; the model's own estimate is deliberately different."""
    return dishes(
        bot._item(
            name,
            None,
            None,
            kind="general",
            memo=name,
            meal_type="lunch",
            estimate=est((600, 900), (30, 45)),
            menu_ref=ref,
            **fields,
        )
    )


def show_menu(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path) -> None:
    prepare(capsys, home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(STEW_MENU), bot.photo(1, "점심 메뉴"))


def test_a_menu_item_picked_by_name_takes_the_menus_values_and_provenance(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    before = meals.meal_tables(home)
    replies, provider = say(
        monkeypatch, capsys, picked("얼큰순살감자탕", 1), 2, "점심으로 위 사진에 있는 얼큰순살감자탕 먹었어"
    )
    block = provider.requests[0][0].prompt.split("<최근 메뉴>\n")[1].split("\n\n")[0]
    assert block == "\n".join(
        [
            "/eat_7f3a 점심 (메뉴 캡처 추정)",
            "1. 한식 얼큰순살감자탕 | kcal 1022, 단백질 40~55 g (메뉴판 표기 포함)",
            "2. 분식 김밥 | kcal 300~400, 단백질 8~12 g",
        ]
    )
    assert len(provider.requests) == 1  # a single printed value from a list the user saw: no re-ask
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (점심, 10-06)",
                "1. 일반식 (메모: 한식 얼큰순살감자탕)",
                "   추정: kcal 1022, 단백질 40~55 g (estimated) (메뉴판 표기)",
                "기록: /ok_91c0   일반식만 기록(값 없이): /plain_91c0   취소: /no_91c0",
            ]
        )
    ]
    assert meals.meal_tables(home) == before
    argv = meals.state_proposals(home)[1]["argv_ok"]
    assert argv[6:] == [
        *("--general", "--general-note=한식 얼큰순살감자탕"),
        "--general-estimate=visual_estimate:kcal=1022-1022,protein=40-55",
        f"--general-estimate-ref=telegram-llm photo sha256:{PHOTO_DIGEST} (claude sonnet); 메뉴판 표기",
    ]
    say(monkeypatch, capsys, None, 3, "/ok_91c0")
    stored = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert stored["items"][0]["nutrients"]["calories_kcal"]["minimum"] == "1022"


def test_a_menu_reference_that_does_not_check_out_is_ignored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    for update_id, name, ref in ((2, "얼큰순살감자탕", 3), (3, "얼큰순살감자탕", 0), (4, "된장찌개", 1)):
        replies, _provider = say(monkeypatch, capsys, picked(name, ref), update_id, f"{name} 먹었어")
        assert f"1. 일반식 (메모: {name})" in replies[0]
        assert "kcal 600~900, 단백질 30~45 g (estimated)" in replies[0] and "메뉴판 표기" not in replies[0]
    # the model's numbers are used as for any estimate, not the menu's
    assert "kcal=600-900" in meals.state_proposals(home)[-1]["argv_ok"][8]


def test_the_menu_is_offered_for_four_hours_after_it_was_made_and_not_when_cancelled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    # 118 minutes later: since v2.4 the menu proposal itself is valid for 4 hours, like the recent menu window
    later = bot.NOW + timedelta(minutes=118)
    monkeypatch.setattr(cli, "_now", lambda: later)
    update = IncomingUpdate(2, IncomingMessage(bot.ALLOWED, "얼큰순살감자탕 먹었어", int(later.timestamp())))
    provider = bot.FakeProvider(picked("얼큰순살감자탕", 1))
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, update)
    assert "<최근 메뉴>\n" in provider.requests[0][0].prompt and "추정: kcal 1022" in replies[0]
    # past four hours it is not offered, and a stale reference is ignored
    much_later = bot.NOW + timedelta(hours=4, minutes=1)
    monkeypatch.setattr(cli, "_now", lambda: much_later)
    update = IncomingUpdate(3, IncomingMessage(bot.ALLOWED, "얼큰순살감자탕 먹었어", int(much_later.timestamp())))
    provider = bot.FakeProvider(picked("얼큰순살감자탕", 1))
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, update)
    assert "<최근 메뉴>\n" not in provider.requests[0][0].prompt and "추정: kcal 600~900" in replies[0]
    # a cancelled menu is not offered either
    monkeypatch.setattr(cli, "_now", lambda: bot.NOW)
    say(monkeypatch, capsys, None, 4, "/no_7f3a")
    _replies, provider = say(monkeypatch, capsys, picked("얼큰순살감자탕", None), 5, "얼큰순살감자탕 먹었어")
    assert "<최근 메뉴>\n" not in provider.requests[0][0].prompt


def test_no_menu_block_without_a_menu_and_a_photo_message_gets_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    _replies, provider = send_photo(monkeypatch, capsys, 2, label_photo())
    assert "<최근 메뉴>\n" not in provider.requests[0][0].prompt  # text messages only


def test_an_edit_of_a_past_meal_shows_that_days_totals(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    bot._ok(capsys, "nutrition", "log", "--date", "2026-10-05", "--meal", "dinner", "--item", "햇반", "2", "pack")
    document = edit_doc(
        "change_quantity",
        refers=None,
        meal_type="dinner",
        target_food_text="햇반",
        new_quantity=1,
    )
    document["date_expression"] = "yesterday"
    replies, _provider = say(monkeypatch, capsys, document, 1, "어제 저녁 햇반 1팩이야")
    assert replies[0].startswith(
        "이렇게 고칠까요?\n저녁 2026-10-05-dinner-1 item 1: 햇반 2 pack → 햇반 (hetbahn-210) 1 pack"
    )
    assert meals.state_proposals(home)[0]["day"] == "2026-10-05"
    replies, _provider = say(monkeypatch, capsys, None, 2, "/ok_7f3a")
    assert "\n확인: /show 2026-10-05-dinner-1\n10-05 누적:\n  kcal 315\n" in replies[0]
    assert "오늘 누적" not in replies[0]


# --- review fixes: what /fix_ shows, the ordinal with last_recorded, the CLI's "<0.1", determinism ---


def test_fix_shows_the_values_it_replaces_with_their_label_and_check_markers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    record_label_meal(monkeypatch, capsys, home)
    label = tuna_rice_ball(estimate=est((190, 190), (5, 5), carbs_min=37, carbs_max=37), from_label=True)
    say(monkeypatch, capsys, dishes(label), 3, "아침에 삼각김밥 먹었어")
    replies, _provider = say(monkeypatch, capsys, None, 4, "/fix_91c0")
    assert replies[0].split("\n")[1:3] == [
        f"아침 {MEAL_1} item 1: 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)",
        "  kcal 185, 단백질 5 g, 탄수화물 37 g → kcal 190, 단백질 5 g, 탄수화물 37 g (라벨)",
    ]
    # a proposal that still fails a check after the re-ask is marked in the fix too, with the reason
    wide = tuna_rice_ball(estimate=est((100, 900), (5, 6)))
    bot._session(
        monkeypatch, capsys, bot.FakeProvider(dishes(wide), dishes(wide)), bot.text(5, "아침에 삼각김밥 또 먹었어")
    )
    replies, _provider = say(monkeypatch, capsys, None, 6, "/fix_44d2")
    lines = replies[0].split("\n")
    assert lines[2] == "  kcal 185, 단백질 5 g, 탄수화물 37 g → kcal 100~900, 단백질 5~6 g (값 확인 필요)"
    assert lines[3] == "  값 확인 필요: 범위가 너무 넓음"
    assert meals.state_proposals(home)[-1]["argv_ok"][-1].endswith("; 값 확인 필요")


def test_an_ordinal_means_that_days_meals_even_when_the_model_also_says_last_recorded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    bot._ok(capsys, "nutrition", "log", "--meal", "breakfast", "--item", "햇반", "1", "pack")  # not in the history
    lunch = dishes(item("국밥", "lunch", estimate=est((600, 700), (20, 30))))
    say(monkeypatch, capsys, lunch, 1, "점심 국밥")
    say(monkeypatch, capsys, None, 2, "/ok_7f3a")
    dinner = dishes(item("파스타", "dinner", estimate=est((700, 800), (20, 30))))
    say(monkeypatch, capsys, dinner, 3, "저녁 파스타")
    say(monkeypatch, capsys, None, 4, "/ok_91c0")
    document = edit_doc(
        "change_quantity", refers="last_recorded", meal_type="breakfast", target_food_text="햇반", new_quantity=2
    )
    replies, provider = say(monkeypatch, capsys, with_ordinal(document, 1), 5, "방금 아침 1식 햇반 2개로")
    assert "2026-10-06-breakfast-1" not in provider.requests[0][0].prompt.split("<직전 기록>\n")[1].split("\n\n")[0]
    assert "아침 2026-10-06-breakfast-1 item 1: 햇반 1 pack → 햇반 (hetbahn-210) 2 pack" in replies[0]
    # without the ordinal the same words look only at the two recent meals, where there is no breakfast
    replies, _provider = say(monkeypatch, capsys, document, 6, "방금 아침 햇반 2개로")
    assert replies == [EDIT_NO_RECENT_TEXT]


def test_a_tiny_remaining_amount_reads_less_than_0_1_like_the_cli_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    bot._ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "330.04")
    bot._ok(capsys, "nutrition", "target", "set", "protein", "--exact", "69.04")
    bot._ok(capsys, "nutrition", "log", "--meal", "breakfast", "--item", "chicken-breast", "300", "g")
    assert "below target, <0.1 g to go" in bot._ok(capsys, "nutrition", "status")  # what the CLI prints
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(bot.MENU), bot.photo(1))
    assert replies[0].split("\n")[0] == "오늘 점심 메뉴예요. 남은 양: 단백질 <0.1 g, kcal <0.1 (/status)"


def replay_label_correction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], root: Path
) -> tuple[list[list[str]], list[list[str]]]:
    """The 3-message replay on a fresh home; returns every reply and the argv of every stored proposal."""
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    v1._configure(root)
    tokens = iter(["7f3a", "91c0", "c2e1"])
    monkeypatch.setattr(cli, "_new_proposal_token", lambda: next(tokens))
    prepare(capsys, root)
    replies: list[list[str]] = []
    first, _provider = send_photo(monkeypatch, capsys, 1, label_photo())
    replies.append(first)
    for update_id, document, words in ((2, None, "/ok_7f3a"), (3, FAT_FIX, "지방 2g"), (4, None, "/ok_91c0")):
        sent, _provider = say(monkeypatch, capsys, document, update_id, words)
        replies.append(sent)
    return replies, [proposal["argv_ok"] for proposal in meals.state_proposals(root)]


def test_the_same_scripted_inputs_give_the_same_replies_and_argv_on_twin_homes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    first = replay_label_correction(monkeypatch, capsys, tmp_path / "first")
    second = replay_label_correction(monkeypatch, capsys, tmp_path / "second")
    assert first == second and len(first[1]) == 2
