"""Telegram LLM v2.3 end to end: label values, follow-up corrections, overlap with `/fix_`, the logged day's totals,
portions and a recent menu item picked by name. `muscle50 telegram run` with a fake Bot API and a fake LLM provider
(never the real `claude`/`codex`, never the network), a temporary MUSCLE50_HOME and synthetic foods only. Covers
AC1-AC13 of docs/specs/telegram-llm-corrections.md."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import test_telegram_llm_bot as bot
import test_telegram_llm_meals_bot as meals
from test_telegram_llm_meals_bot import catalog_item, dishes, est, item

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


# --- AC11: the totals are those of the logged day ------------------------------------------------------------


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


# --- AC1: label values ---------------------------------------------------------------------------------------

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


# --- AC10: assumed portions and the dish name in the memo ----------------------------------------------------


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
