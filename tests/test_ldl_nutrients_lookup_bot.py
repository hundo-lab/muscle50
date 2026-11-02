"""LDL Nutrients B (ldl-nutrients-lookup) end to end: saturated fat and fiber estimates in Telegram meal proposals.

`muscle50 telegram run` with a fake Bot API and fake LLM providers (never the real `claude`/`codex`, never the
network), a temporary MUSCLE50_HOME and synthetic values only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import test_telegram_llm_bot as bot
import test_telegram_llm_meals_bot as meals
from test_telegram_llm_corrections_bot import edit_doc, prepare, say, show_menu
from test_telegram_llm_domain import ITEM_ESTIMATE, NULL_ESTIMATE
from test_telegram_llm_lookup_bot import BIG_MAC, LookupProvider
from test_telegram_llm_lookup_bot import _config as codex_config

from muscle50.domain.llm_failure import FailureReason
from muscle50.domain.telegram_llm_check import RECHECK_INTRO
from muscle50.presentation.telegram_llm_replies import history_text, render_telegram_history

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
LUNCH = "2026-10-06-lunch-1"
JEYUK = "제육볶음 정식 1인분"
ALL_FOUR = {"carbs_min": 90, "carbs_max": 120, "fat_min": 25, "fat_max": 40}
LDL_BOTH = {"satfat_min": 8, "satfat_max": 14, "fiber_min": 4, "fiber_max": 8}
JEYUK_ESTIMATE = meals.est((750, 1000), (30, 45), **ALL_FOUR, **LDL_BOTH)
JEYUK_SPEC = "kcal=750-1000,protein=30-45,carbs=90-120,fat=25-40,satfat=8-14,fiber=4-8"
FOOTER = "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a"
OVER = {"fat_min": 10, "fat_max": 15, "satfat_min": 18, "satfat_max": 25}
"""Saturated fat above total fat (the lowest satfat is above the highest fat)."""
PASTA = "크림파스타 1접시"


def lunch(food: str, estimate: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return bot.meal(meals.item(food, None, estimate=estimate, **fields))


def pasta(**more: Any) -> dict[str, Any]:
    return lunch(PASTA, meals.est((800, 1000), (20, 30), **more))


def proposal_of(home: Path, index: int = -1) -> dict[str, Any]:
    proposal: dict[str, Any] = meals.state_proposals(home)[index]
    return proposal


def estimate_args(argv: list[str]) -> list[str]:
    return [arg for arg in argv if arg.startswith("--general-estimate")]


def ldl_rows(home: Path) -> list[tuple[Any, ...]]:
    return bot._tables(home).get("nutrition_fact_optional_nutrients", [])


def shown_ldl(capsys: pytest.CaptureFixture[str], meal_id: str, index: int = 0) -> dict[str, Any]:
    """The item's `ldl_nutrients` in `meal show --json` ({} when it has none: the key is then absent)."""
    document = json.loads(bot._ok(capsys, "nutrition", "meal", "show", meal_id, "--json"))
    ldl: dict[str, Any] = document["items"][index].get("ldl_nutrients", {})
    return ldl


def ok(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], update_id: int, token: str) -> str:
    replies, _provider = say(monkeypatch, capsys, None, update_id, f"/{token}")
    assert len(replies) == 1
    return replies[0]


# --- AC2, AC8: a text meal shows the line, `/ok` stores the ranges --------------------------------------------


def test_a_text_meal_shows_the_line_and_ok_stores_language_estimate_ranges(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    before = meals.meal_tables(home)
    replies, provider = say(monkeypatch, capsys, lunch(JEYUK, JEYUK_ESTIMATE), 1, "점심에 제육볶음 정식 먹었어")
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (점심, 10-06)",
                f"1. 일반식 (메모: {JEYUK})",
                "   추정: kcal 750~1000, 단백질 30~45 g, 탄수화물 90~120 g, 지방 25~40 g (estimated)",
                "   포화지방 8~14 g · 섬유 4~8 g (추정, 정확도 미확인)",
                FOOTER,
            ]
        )
    ]
    assert len(provider.requests) == 1
    assert meals.meal_tables(home) == before  # nothing before /ok
    proposal = proposal_of(home)
    assert proposal["argv_ok"] == [
        *("nutrition", "log", "--date", "2026-10-06", "--meal", "lunch", "--general", f"--general-note={JEYUK}"),
        f"--general-estimate=language_estimate:{JEYUK_SPEC}",
        "--general-estimate-ref=telegram-llm text (claude sonnet)",
    ]
    assert proposal["argv_plain"] == [*proposal["argv_ok"][:8]]
    assert not any("포화지방" in line for line in proposal["outline"])  # D7: the open-proposal block is unchanged
    reply = ok(monkeypatch, capsys, 2, "ok_7f3a")
    assert reply.startswith(f"기록했습니다: 점심 {LUNCH} (10-06)\n")
    assert "포화지방" not in reply  # ldl D6: the short /ok reply is unchanged
    day = json.loads(bot._ok(capsys, "nutrition", "day", "--date", "2026-10-06", "--json"))
    ldl = day["meals"][0]["items"][0]["ldl_nutrients"]
    assert ldl["saturated_fat_g"] == {
        "value": None,
        "minimum": "8",
        "maximum": "14",
        "fact_id": ldl["saturated_fat_g"]["fact_id"],
        "source_type": "language_estimate",
        "accuracy": "estimated",
    }
    assert ldl["saturated_fat_g"]["fact_id"].endswith(":estimate")
    assert (ldl["fiber_g"]["minimum"], ldl["fiber_g"]["maximum"], ldl["fiber_g"]["value"]) == ("4", "8", None)


def test_an_unknown_fiber_has_no_row_and_is_not_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    estimate = meals.est((750, 1000), (30, 45), **ALL_FOUR, satfat_min=8, satfat_max=14)
    replies, _provider = say(monkeypatch, capsys, lunch(JEYUK, estimate), 1, "점심 제육")
    assert "   포화지방 8~14 g · 섬유 모름 (추정, 정확도 미확인)" in replies[0].split("\n")
    assert estimate_args(proposal_of(home)["argv_ok"])[0].endswith(",fat=25-40,satfat=8-14")
    ok(monkeypatch, capsys, 2, "ok_7f3a")
    assert shown_ldl(capsys, LUNCH)["fiber_g"] is None
    assert [row for row in ldl_rows(home) if "fiber_g" in row] == []
    assert len(ldl_rows(home)) == 1


def test_a_photo_meal_stores_visual_estimate_ranges(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    document = bot.meal(
        meals.item("SynPhoto 덮밥", None, estimate=meals.est((600, 800), (20, 30), fiber_min=3, fiber_max=5)),
        photo_kind="meal_photo",
    )
    provider = bot.FakeProvider(document)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.photo(1, "점심 먹음"))
    assert "   포화지방 모름 · 섬유 3~5 g (추정, 정확도 미확인)" in replies[0].split("\n")
    assert estimate_args(proposal_of(home)["argv_ok"])[0] == (
        "--general-estimate=visual_estimate:kcal=600-800,protein=20-30,fiber=3-5"
    )
    ok(monkeypatch, capsys, 2, "ok_7f3a")
    fiber = shown_ldl(capsys, LUNCH)["fiber_g"]
    assert (fiber["source_type"], fiber["accuracy"], fiber["minimum"]) == ("visual_estimate", "estimated", "3")


# --- AC4: label values -------------------------------------------------------------------------------------------

LABEL = meals.est((185, 185), (5, 5), carbs_min=37, carbs_max=37, fat_min=2, fat_max=2, satfat_min=0.5, satfat_max=0.5)


def label_doc(estimate: dict[str, Any]) -> dict[str, Any]:
    item = bot._item(
        "삼각김밥", None, None, kind="general", memo="깻잎닭갈비 삼각김밥 1개", estimate=estimate, from_label=True
    )
    return bot.meal(item, meal_type="snack", photo_kind="meal_photo")


def test_a_label_photo_stores_single_values_and_shows_the_label_tag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(label_doc(LABEL))
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.photo(1, "간식"))
    assert len(provider.requests) == 1  # no re-ask for a label's single values
    lines = replies[0].split("\n")
    assert lines[1:4] == [
        "1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)",
        "   라벨: kcal 185, 단백질 5 g, 탄수화물 37 g, 지방 2 g",
        "   포화지방 0.5 g · 섬유 모름 (라벨)",
    ]
    args = estimate_args(proposal_of(home)["argv_ok"])
    assert args[0] == "--general-estimate=visual_estimate:kcal=185-185,protein=5-5,carbs=37-37,fat=2-2,satfat=0.5-0.5"
    assert args[1].endswith("(claude sonnet); 라벨")
    ok(monkeypatch, capsys, 2, "ok_7f3a")
    satfat = shown_ldl(capsys, "2026-10-06-snack-1")["saturated_fat_g"]
    assert (satfat["value"], satfat["minimum"], satfat["maximum"], satfat["accuracy"]) == (
        None,
        "0.5",
        "0.5",
        "estimated",
    )


def test_a_label_with_a_ranged_saturated_fat_is_an_ordinary_estimate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    mixed = {**LABEL, "satfat_min": 0.5, "satfat_max": 1}
    provider = bot.FakeProvider(label_doc(mixed), label_doc(mixed))
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.photo(1, "간식"))
    assert len(provider.requests) == 2  # D8: no longer a label, so its single kcal is re-asked as a point
    assert "   추정: kcal 185, 단백질 5 g, 탄수화물 37 g, 지방 2 g (estimated) (값 확인 필요)" in replies[0].split("\n")
    assert "   포화지방 0.5~1 g · 섬유 모름 (추정, 정확도 미확인)" in replies[0].split("\n")


def test_a_non_label_single_saturated_fat_or_fiber_value_is_not_re_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    estimate = meals.est((750, 1000), (30, 45), **ALL_FOUR, satfat_min=10, satfat_max=10, fiber_min=5, fiber_max=5)
    replies, provider = say(monkeypatch, capsys, lunch(JEYUK, estimate), 1, "점심 제육")
    assert len(provider.requests) == 1
    assert "   포화지방 10 g · 섬유 5 g (추정, 정확도 미확인)" in replies[0].split("\n")
    assert bot._history(home)[-1]["recheck"] is None


# --- AC5: saturated fat above fat (rule 6) -----------------------------------------------------------------------


def test_satfat_above_fat_is_re_asked_once_and_a_fixed_answer_is_used(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    fixed = pasta(fat_min=10, fat_max=15, satfat_min=4, satfat_max=6)
    provider = bot.FakeProvider(pasta(**OVER), fixed)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 크림파스타"))
    assert len(provider.requests) == 2
    note = provider.requests[1][0].prompt.split("[재확인]\n")[1].split("\n\n")[0]
    assert note == f"{RECHECK_INTRO}\n- items[1]: satfat_exceeds_fat (fat 10-15, satfat 18-25)"
    assert "   포화지방 4~6 g · 섬유 모름 (추정, 정확도 미확인)" in replies[0].split("\n")
    assert estimate_args(proposal_of(home)["argv_ok"])[0].endswith(",fat=10-15,satfat=4-6")
    assert bot._history(home)[-1]["recheck"] == {"reasons": ["satfat_exceeds_fat"], "outcome": "fixed"}


@pytest.mark.parametrize(("second", "outcome"), [("same", "still_inconsistent"), ("bad_output", "reask_failed")])
def test_satfat_still_above_fat_is_left_out_and_the_rest_is_recorded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, second: str, outcome: str
) -> None:
    prepare(capsys, home)
    first = pasta(**OVER, fiber_min=3, fiber_max=5)
    provider = bot.FakeProvider(first, first if second == "same" else second)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 크림파스타"))
    assert len(provider.requests) == 2  # exactly one re-ask
    assert replies[0].split("\n")[1:4] == [
        f"1. 일반식 (메모: {PASTA})",
        "   추정: kcal 800~1000, 단백질 20~30 g, 지방 10~15 g (estimated)",
        "   포화지방 모름(지방보다 커서 뺌) · 섬유 3~5 g (추정, 정확도 미확인)",
    ]
    assert "(값 확인 필요)" not in replies[0] and "값 확인 필요:" not in replies[0]
    args = estimate_args(proposal_of(home)["argv_ok"])
    assert args == [
        "--general-estimate=language_estimate:kcal=800-1000,protein=20-30,fat=10-15,fiber=3-5",
        "--general-estimate-ref=telegram-llm text (claude sonnet)",
    ]
    assert bot._history(home)[-1]["recheck"] == {"reasons": ["satfat_exceeds_fat"], "outcome": outcome}
    reply = ok(monkeypatch, capsys, 2, "ok_7f3a")
    assert reply.startswith(f"기록했습니다: 점심 {LUNCH} (10-06)\n")  # the CLI accepted it (exit 0)
    ldl = shown_ldl(capsys, LUNCH)
    assert ldl["saturated_fat_g"] is None
    assert (ldl["fiber_g"]["minimum"], ldl["fiber_g"]["maximum"]) == ("3", "5")


def test_a_history_line_with_the_new_code_is_rendered_by_history_and_telegram_history(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    first = pasta(**OVER)
    bot._session(monkeypatch, capsys, bot.FakeProvider(first, first), bot.text(1, "점심 크림파스타"))
    entries = bot._history(home)
    assert entries[-1]["recheck"] == {"reasons": ["satfat_exceeds_fat"], "outcome": "still_inconsistent"}
    assert "recheck=still_inconsistent" in render_telegram_history(entries)
    assert "재확인(남음)" in history_text(entries)
    replies, _provider = say(monkeypatch, capsys, None, 2, "/history")
    assert "재확인(남음)" in replies[0]
    assert "recheck=still_inconsistent" in bot._ok(capsys, "telegram", "history")


def test_satfat_with_another_failure_marks_only_that_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    wide = lunch(PASTA, meals.est((100, 900), (20, 30), **OVER))
    provider = bot.FakeProvider(wide, wide)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 크림파스타"))
    assert replies[0].split("\n")[2:5] == [
        "   추정: kcal 100~900, 단백질 20~30 g, 지방 10~15 g (estimated) (값 확인 필요)",
        "   포화지방 모름(지방보다 커서 뺌) · 섬유 모름",
        "   값 확인 필요: 범위가 너무 넓음",
    ]
    args = estimate_args(proposal_of(home)["argv_ok"])
    assert args == [
        "--general-estimate=language_estimate:kcal=100-900,protein=20-30,fat=10-15",
        "--general-estimate-ref=telegram-llm text (claude sonnet); 값 확인 필요",
    ]
    assert bot._history(home)[-1]["recheck"] == {
        "reasons": ["range_too_wide", "satfat_exceeds_fat"],
        "outcome": "still_inconsistent",
    }
    assert ok(monkeypatch, capsys, 2, "ok_7f3a").startswith("기록했습니다:")


def test_satfat_without_a_fat_range_is_kept_and_not_re_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    replies, provider = say(monkeypatch, capsys, pasta(satfat_min=50, satfat_max=60), 1, "점심 크림파스타")
    assert len(provider.requests) == 1  # D5: nothing to compare with
    assert "   포화지방 50~60 g · 섬유 모름 (추정, 정확도 미확인)" in replies[0].split("\n")
    assert estimate_args(proposal_of(home)["argv_ok"])[0].endswith("protein=20-30,satfat=50-60")
    assert ok(monkeypatch, capsys, 2, "ok_7f3a").startswith("기록했습니다:")
    assert shown_ldl(capsys, LUNCH)["saturated_fat_g"]["minimum"] == "50"


# --- AC3: items that never carry the model's values --------------------------------------------------------------


def test_a_catalog_linked_item_drops_the_models_satfat_and_fiber(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    ldl = {"satfat_min": 1, "satfat_max": 2, "fiber_min": 1, "fiber_max": 2}
    estimate = {**ITEM_ESTIMATE, "fat_min": 1, "fat_max": 3, **ldl}
    document = bot.meal(meals.catalog_item("닭가슴살", None, 1, "pack", estimate=estimate))
    replies, _provider = say(monkeypatch, capsys, document, 1, "점심 닭가슴살 1팩")
    assert "포화지방" not in replies[0]
    argv = proposal_of(home)["argv_ok"]
    assert argv[6:10] == ["--item", "chicken-breast", "1", "pack"] and estimate_args(argv) == []
    ok(monkeypatch, capsys, 2, "ok_7f3a")
    assert shown_ldl(capsys, LUNCH) == {}  # no LDL values: the key is absent, as before
    assert ldl_rows(home) == []


def test_a_menu_pick_keeps_the_menus_values_without_satfat_or_fiber(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    estimate = meals.est((600, 900), (30, 45), fat_min=20, fat_max=30, satfat_min=8, satfat_max=12)
    stew = bot._item(
        "얼큰순살감자탕",
        None,
        None,
        kind="general",
        memo="얼큰순살감자탕",
        meal_type="lunch",
        estimate=estimate,
        menu_ref=1,
    )
    replies, _provider = say(monkeypatch, capsys, meals.dishes(stew), 2, "점심으로 얼큰순살감자탕 먹었어")
    assert "포화지방" not in replies[0] and "(메뉴판 표기)" in replies[0]
    assert "satfat" not in estimate_args(proposal_of(home)["argv_ok"])[0]


def test_plain_stores_no_satfat_or_fiber(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    say(monkeypatch, capsys, lunch(JEYUK, JEYUK_ESTIMATE), 1, "점심 제육")
    assert "satfat" not in json.dumps(proposal_of(home)["argv_plain"])
    assert ok(monkeypatch, capsys, 2, "plain_7f3a").startswith("기록했습니다:")
    assert shown_ldl(capsys, LUNCH) == {}  # no LDL values: the key is absent, as before
    assert ldl_rows(home) == []


# --- AC6 / D4: an edit that lowers fat below the stored saturated fat -----------------------------------------------

ONIGIRI = "SynOnigiri 1개"


def _log_onigiri(capsys: pytest.CaptureFixture[str]) -> None:
    bot._ok(
        capsys,
        *("nutrition", "log", "--meal", "dinner", "--general", f"--general-note={ONIGIRI}"),
        "--general-estimate=language_estimate:kcal=180-220,fat=4-8,satfat=3-5,fiber=1-2",
    )


def _fat_edit(fat: int) -> dict[str, Any]:
    estimate = {**NULL_ESTIMATE, "fat_min": fat, "fat_max": fat}
    return edit_doc(  # type: ignore[no-any-return]
        "change_estimate",
        refers=None,
        meal_type="dinner",
        target_food_text="SynOnigiri",
        estimate=estimate,
        from_label=True,
    )


def test_lowering_fat_below_the_stored_satfat_drops_it_with_a_line_and_ok_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    _log_onigiri(capsys)
    replies, _provider = say(monkeypatch, capsys, _fat_edit(2), 1, "아까 SynOnigiri 지방 2g 이네 라벨에 나와있어")
    lines = replies[0].split("\n")
    assert lines[0] == "이렇게 고칠까요?"
    assert lines[1] == f"저녁 2026-10-06-dinner-1 item 1: 일반식 (메모: {ONIGIRI})"
    assert lines[2:4] == ["  지방 4~8 g → 2 g (라벨)", "  포화지방 3~5 g → 모름(지방보다 커서 뺌)"]
    assert lines[-1] == "고치기: /ok_7f3a   취소: /no_7f3a"
    assert "(값 확인 필요)" not in replies[0]
    argv = proposal_of(home)["argv_ok"]
    assert estimate_args(argv) == [
        "--general-estimate=language_estimate:kcal=180-220,fat=2-2,fiber=1-2",
        "--general-estimate-ref=telegram-llm edit (claude sonnet); 라벨",
    ]
    before_items = len(bot._tables(home)["nutrition_meal_items"])
    reply = ok(monkeypatch, capsys, 2, "ok_7f3a")
    assert reply.startswith("수정했습니다:")  # the CLI accepted it (exit 0)
    ldl = shown_ldl(capsys, "2026-10-06-dinner-1")
    assert ldl["saturated_fat_g"] is None
    assert (ldl["fiber_g"]["minimum"], ldl["fiber_g"]["maximum"]) == ("1", "2")
    assert len(bot._tables(home)["nutrition_meal_items"]) == before_items + 1  # the old item stays


def test_an_edit_that_keeps_fat_at_or_above_the_stored_satfat_keeps_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    _log_onigiri(capsys)
    replies, _provider = say(monkeypatch, capsys, _fat_edit(3), 1, "SynOnigiri 지방 3g")
    assert "포화지방" not in replies[0]  # satfat_min 3 is not above fat 3
    assert estimate_args(proposal_of(home)["argv_ok"])[0].endswith("fat=3-3,satfat=3-5,fiber=1-2")


# --- AC7 / D2 (L3): the Claude lookup replaces the whole answer, a failed one keeps Codex's ----------------------

BURGER = {**ITEM_ESTIMATE, "fat_min": 20, "fat_max": 30}


def _burger(satfat: tuple[int, int], **fields: Any) -> dict[str, Any]:
    estimate = {**BURGER, "satfat_min": satfat[0], "satfat_max": satfat[1]}
    return bot.meal(meals.item(BIG_MAC, None, lookup_wanted=True, estimate=estimate, **fields))


def _codex_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, *responses: Any, words: str
) -> tuple[list[str], LookupProvider]:
    bot._catalog(capsys)
    codex_config(home)
    provider = LookupProvider(*responses)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, words))
    return replies, provider


def test_the_lookup_answers_satfat_replace_codexs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    claude = _burger((14, 20), source="맥도날드")
    replies, provider = _codex_session(monkeypatch, capsys, home, _burger((5, 8)), claude, words=f"점심 {BIG_MAC}")
    assert [chosen.value for _request, chosen in provider.requests] == ["codex", "claude"]
    lines = replies[0].split("\n")
    assert lines[2:5] == [
        "   추정: kcal 300~400, 단백질 10~20 g, 지방 20~30 g (estimated)",
        "   포화지방 14~20 g · 섬유 모름 (추정, 정확도 미확인)",
        "   출처: 맥도날드",
    ]
    assert "웹 검색 2회 (Claude)" in lines
    args = estimate_args(proposal_of(home)["argv_ok"])
    assert args == [
        "--general-estimate=language_estimate:kcal=300-400,protein=10-20,fat=20-30,satfat=14-20",
        "--general-estimate-ref=telegram-llm text (claude haiku); 출처: 맥도날드",
    ]
    codex_prompt, claude_prompt = (request.prompt for request, _chosen in provider.requests)
    assert "흔한 음식이어도 true." in codex_prompt  # L3: the lookup_wanted bullet
    assert "사용자가 검색해 달라고 한 음식은 흔한 음식이어도 검색할 수 있습니다." in claude_prompt  # web rule 12


def test_a_failed_lookup_keeps_codexs_satfat_and_says_why(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    failed = ("failed", FailureReason.USAGE_LIMIT)
    replies, provider = _codex_session(monkeypatch, capsys, home, _burger((5, 8)), failed, words=BIG_MAC)
    assert len(provider.requests) == 2
    lines = replies[0].split("\n")
    assert "   포화지방 5~8 g · 섬유 모름 (추정, 정확도 미확인)" in lines
    assert lines[-2] == "(웹 검색은 하지 못했습니다: 사용 한도)"
    assert estimate_args(proposal_of(home)["argv_ok"])[0].endswith("fat=20-30,satfat=5-8")


def test_a_home_meal_the_user_asks_to_search_is_looked_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    words = "저녁에 집에서 끓인 된장찌개 먹었어 포화지방은 검색해서 넣어줘"
    stew = {**BURGER, "satfat_min": 1, "satfat_max": 3, "fiber_min": 2, "fiber_max": 4}
    codex = bot.meal(meals.item("된장찌개", None, lookup_wanted=True), meal_type="dinner")
    claude = bot.meal(meals.item("된장찌개", None, lookup_wanted=True, estimate=stew), meal_type="dinner")
    replies, provider = _codex_session(monkeypatch, capsys, home, codex, claude, words=words)
    assert [request.web_search for request, _chosen in provider.requests] == [False, True]
    lines = replies[0].split("\n")
    assert "   포화지방 1~3 g · 섬유 2~4 g (추정, 정확도 미확인)" in lines and "웹 검색 2회 (Claude)" in lines


# --- AC8: multi-meal, joins, /add_, /fix_ and an open-proposal correction ---------------------------------------


def _with_ldl(kcal: tuple[int, int], protein: tuple[int, int], **ldl: Any) -> dict[str, Any]:
    return meals.est(kcal, protein, fat_min=5, fat_max=10, **ldl)


def test_a_multi_meal_proposal_has_the_line_per_item_and_the_ranges_per_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    document = meals.dishes(
        meals.item("SynToast", "breakfast", estimate=_with_ldl((300, 400), (10, 20), satfat_min=2, satfat_max=3)),
        meals.item("SynSalad", "dinner", estimate=_with_ldl((200, 300), (10, 20), fiber_min=4, fiber_max=6)),
    )
    replies, _provider = say(monkeypatch, capsys, document, 1, "아침 SynToast 저녁 SynSalad")
    lines = replies[0].split("\n")
    assert lines[1:4] == [
        "아침",
        "  1. 일반식 (메모: SynToast)",
        "     추정: kcal 300~400, 단백질 10~20 g, 지방 5~10 g (estimated)",
    ]
    assert lines[4] == "     포화지방 2~3 g · 섬유 모름 (추정, 정확도 미확인)"
    assert lines[8] == "     포화지방 모름 · 섬유 4~6 g (추정, 정확도 미확인)"
    proposal = proposal_of(home)
    breakfast, dinner = (estimate_args(meal["argv_ok"])[0] for meal in proposal["meals"])
    assert breakfast.endswith("fat=5-10,satfat=2-3") and dinner.endswith("fat=5-10,fiber=4-6")
    assert not any("포화지방" in line for line in proposal["outline"])


BREAKFAST = "2026-10-06-breakfast-1"
POTATO = bot.meal(
    meals.item("고구마 1개", None, estimate=_with_ldl((100, 150), (1, 3), fiber_min=3, fiber_max=4)),
    meal_type="breakfast",
)


def _record_banana(capsys: pytest.CaptureFixture[str]) -> None:
    bot._ok(capsys, "nutrition", "log", "--date", "2026-10-06", "--meal", "breakfast", "--item", "banana", "1", "count")


def test_joining_a_recorded_meal_adds_the_item_with_its_ranges(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    _record_banana(capsys)
    joined = copy_with_join(POTATO)
    replies, _provider = say(monkeypatch, capsys, joined, 1, "아침에 고구마도 먹었어 하나에 같이")
    assert "   포화지방 모름 · 섬유 3~4 g (추정, 정확도 미확인)" in replies[0].split("\n")
    argv = proposal_of(home)["argv_ok"]
    assert argv[:4] == ["nutrition", "meal", "add-item", BREAKFAST]
    assert estimate_args(argv)[0].endswith("fat=5-10,fiber=3-4")
    assert ok(monkeypatch, capsys, 2, "ok_7f3a").startswith(f"수정했습니다: 아침 {BREAKFAST}")  # an add-item
    assert shown_ldl(capsys, BREAKFAST, 1)["fiber_g"]["maximum"] == "4"


def copy_with_join(document: dict[str, Any]) -> dict[str, Any]:
    return {**document, "items": [{**item, "join_existing": True} for item in document["items"]]}


def test_add_offers_the_recorded_meal_with_the_same_ranges(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    _record_banana(capsys)
    say(monkeypatch, capsys, POTATO, 1, "아침에 고구마 먹었어")
    proposal = proposal_of(home)
    assert proposal["alt_action"] == "add" and proposal["argv_alt"][:4] == ["nutrition", "meal", "add-item", BREAKFAST]
    assert estimate_args(proposal["argv_alt"]) == estimate_args(proposal["argv_ok"])
    assert estimate_args(proposal["argv_alt"])[0].endswith("fat=5-10,fiber=3-4")


def _record_onigiri_breakfast(capsys: pytest.CaptureFixture[str]) -> None:
    bot._ok(
        capsys,
        *("nutrition", "log", "--meal", "breakfast", "--general", f"--general-note={ONIGIRI}"),
        "--general-estimate=language_estimate:kcal=180-200,protein=5-6",
    )


def test_fix_replaces_the_recorded_item_with_the_ranges_and_shows_the_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    _record_onigiri_breakfast(capsys)
    estimate = _with_ldl((190, 210), (5, 7), satfat_min=2, satfat_max=3)
    say(monkeypatch, capsys, meals.dishes(meals.item(ONIGIRI, "breakfast", estimate=estimate)), 1, "아침 SynOnigiri")
    fix = proposal_of(home)["fix_argv"]
    assert fix[:6] == ["nutrition", "meal", "replace-item", BREAKFAST, "--item-number", "1"]
    assert estimate_args(fix)[0].endswith("fat=5-10,satfat=2-3")
    replies, _provider = say(monkeypatch, capsys, None, 2, "/fix_7f3a")
    assert replies[0].split("\n")[1:4] == [
        f"아침 {BREAKFAST} item 1: 일반식 (메모: {ONIGIRI})",
        "  kcal 180~200, 단백질 5~6 g → kcal 190~210, 단백질 5~7 g, 지방 5~10 g",
        "  포화지방 2~3 g · 섬유 모름 (추정, 정확도 미확인)",
    ]
    assert ok(monkeypatch, capsys, 3, "ok_91c0").startswith("수정했습니다:")
    assert shown_ldl(capsys, BREAKFAST)["saturated_fat_g"]["minimum"] == "2"


def test_fix_adds_new_items_with_the_line_in_the_change_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    _record_onigiri_breakfast(capsys)
    same = meals.item(ONIGIRI, "breakfast", estimate=meals.est((180, 200), (5, 6)))
    soup = meals.item("SynSoup", "breakfast", estimate=_with_ldl((100, 150), (5, 8), fiber_min=2, fiber_max=3))
    say(monkeypatch, capsys, meals.dishes(same, soup), 1, "아침 SynOnigiri SynSoup")
    fix = proposal_of(home)["fix_argv"]
    assert fix[:4] == ["nutrition", "meal", "add-item", BREAKFAST]
    assert estimate_args(fix)[0].endswith("fat=5-10,fiber=2-3")
    replies, _provider = say(monkeypatch, capsys, None, 2, "/fix_7f3a")
    assert replies[0].split("\n")[1] == (
        f"아침 {BREAKFAST}: 추가 일반식 (메모: SynSoup): kcal 100~150, 단백질 5~8 g, 지방 5~10 g"
        " / 포화지방 모름 · 섬유 2~3 g (추정, 정확도 미확인)"
    )


def test_correcting_an_open_proposal_carries_the_new_ranges(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    plain = meals.est((750, 1000), (30, 45), **ALL_FOUR)
    say(monkeypatch, capsys, lunch(JEYUK, plain), 1, "점심 제육")
    corrected = {**lunch(JEYUK, JEYUK_ESTIMATE), "refers_to": "open_proposal"}
    replies, provider = say(monkeypatch, capsys, corrected, 2, "포화지방도 넣어줘")
    block = provider.requests[0][0].prompt.split("<열린 제안>\n")[1].split("\n\n")[0]
    assert "포화지방" not in block  # D7: the context block is unchanged
    assert "   포화지방 8~14 g · 섬유 4~8 g (추정, 정확도 미확인)" in replies[0].split("\n")
    states = {proposal["token"]: proposal["state"] for proposal in meals.state_proposals(home)}
    assert states == {"7f3a": "cancelled", "91c0": "open"}
    assert estimate_args(proposal_of(home)["argv_ok"])[0] == f"--general-estimate=language_estimate:{JEYUK_SPEC}"


# --- determinism, refusals and the unchanged status ---------------------------------------------------------------


def test_the_same_answer_gives_the_same_reply_and_argv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    first, _provider = say(monkeypatch, capsys, lunch(JEYUK, JEYUK_ESTIMATE), 1, "점심 제육")
    second, _provider = say(monkeypatch, capsys, lunch(JEYUK, JEYUK_ESTIMATE), 2, "점심 제육")
    assert first[0].replace("7f3a", "TOKEN") == second[0].replace("91c0", "TOKEN")
    one, two = meals.state_proposals(home)
    assert one["argv_ok"] == two["argv_ok"] and one["argv_plain"] == two["argv_plain"]


def test_a_malformed_satfat_is_a_failure_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    before = meals.meal_tables(home)
    broken = lunch(JEYUK, {**JEYUK_ESTIMATE, "satfat_max": None})
    provider = bot.FakeProvider(broken, broken)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 제육"))
    assert not replies[0].startswith("이렇게 기록할까요?")
    assert meals.meal_tables(home) == before
    assert {proposal["kind"] for proposal in meals.state_proposals(home)} <= {"retry"}
    assert bot._history(home)[-1]["provider_result"] == "bad_output"


def test_no_writes_nothing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path) -> None:
    prepare(capsys, home)
    before = meals.meal_tables(home)
    say(monkeypatch, capsys, lunch(JEYUK, JEYUK_ESTIMATE), 1, "점심 제육")
    ok(monkeypatch, capsys, 2, "no_7f3a")
    assert meals.meal_tables(home) == before and ldl_rows(home) == []


def test_stored_ranges_do_not_change_the_status_verdict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    def status() -> tuple[str, str]:
        bot._ok(capsys, "nutrition", "target", "set", "fiber", "--minimum", "25")
        bot._ok(capsys, "nutrition", "target", "set", "satfat", "--max-energy-percent", "7")
        bot._ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
        text = bot._ok(capsys, "nutrition", "status", "--date", "2026-10-06")
        document = bot._ok(capsys, "nutrition", "status", "--date", "2026-10-06", "--json")
        assert bot._ok(capsys, "nutrition", "status", "--date", "2026-10-06", "--json") == document
        return text, document

    prepare(capsys, home)
    say(monkeypatch, capsys, lunch(JEYUK, JEYUK_ESTIMATE), 1, "점심 제육")
    ok(monkeypatch, capsys, 2, "ok_7f3a")
    with_ranges = status()
    ldl = json.loads(with_ranges[1])["ldl_nutrients"]
    for name in ("saturated_fat_g", "fiber_g"):
        assert ldl[name]["complete"] is False and ldl[name]["consumed"] is None
        assert [item["meal_id"] for item in ldl[name]["missing_items"]] == [LUNCH]
        assert ldl[name]["estimated"] is True  # ldl v1: a range-only value marks the aggregate as estimated
    # the same meal typed in the CLI without satfat/fiber gives the same verdicts, totals and text
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "twin"))
    argv = proposal_of(home)["argv_ok"]
    bot._ok(capsys, *[arg.replace(",satfat=8-14,fiber=4-8", "") for arg in argv])
    text, document = status()
    assert text == with_ranges[0]
    twin = json.loads(document)
    for name in ("saturated_fat_g", "fiber_g"):
        assert twin["ldl_nutrients"][name].pop("estimated") is False
        ldl[name].pop("estimated")
    assert twin == {**json.loads(with_ranges[1]), "ldl_nutrients": ldl}
