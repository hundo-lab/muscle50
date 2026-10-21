"""Telegram LLM v2.4 end to end (AC2, AC3, AC6, AC7, AC8 of docs/specs/telegram-llm-reliability.md): the photo
failure wording, photos in the chat memory, the 4-hour menu proposal, short Korean `/ok` summaries and the sync
hint. `muscle50 telegram run` with a fake Bot API and a fake LLM provider (never the real `claude`/`codex`, never the
network), a temporary MUSCLE50_HOME and synthetic foods only.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
import test_telegram_llm_corrections_bot as corrections
import test_telegram_llm_meals_bot as meals
from test_telegram_llm_corrections_bot import STEW_MENU, show_menu
from test_telegram_llm_domain import interpretation

import muscle50.cli as cli
from muscle50.application.telegram_bot import CommandOutcome, IncomingMessage, IncomingUpdate
from muscle50.domain.llm_failure import retry_line
from muscle50.domain.telegram_llm import MENU_PROPOSAL_TTL_S
from muscle50.domain.telegram_llm_prompt import PROPOSAL_EXPIRED_TEXT, SYNC_HINT_TEXT, menu_expired_text
from muscle50.infrastructure.telegram.cli_runner import InProcessCliRunner

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network, no real sleep
_isolated = v1.sleeps

FOUR_HOURS = 4 * 3600


def at(delta: timedelta, update_id: int, words: str, monkeypatch: pytest.MonkeyPatch) -> IncomingUpdate:
    """A text message ``delta`` after the fixed clock; the bot's clock moves with it."""
    later = bot.NOW + delta
    monkeypatch.setattr(cli, "_now", lambda: later)
    return IncomingUpdate(update_id, IncomingMessage(bot.ALLOWED, words, int(later.timestamp())))


def state(home: Path) -> list[dict[str, Any]]:
    return meals.state_proposals(home)


# --- AC6: menu proposals are valid for 4 hours, meal proposals for 60 minutes -----------------------------


def test_a_menu_proposal_is_stored_for_four_hours_and_a_meal_proposal_for_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    (menu,) = state(home)
    assert menu["kind"] == "menu" and menu["expires_unix"] - menu["created_unix"] == FOUR_HOURS == MENU_PROPOSAL_TTL_S
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/eat_7f3a_1"))
    meal = state(home)[-1]
    assert meal["kind"] == "meal" and meal["expires_unix"] - meal["created_unix"] == 3600


def test_eat_works_at_3_hours_59_minutes_and_is_refused_at_4_hours(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    update = at(timedelta(hours=3, minutes=59), 2, "/eat_7f3a_1", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies[0].startswith("이렇게 기록할까요?")
    update = at(timedelta(hours=4), 3, "/eat_7f3a_2", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies == ["이 메뉴 제안은 유효 시간(4시간)이 지났습니다. 메뉴 사진을 다시 보내거나 다시 물어봐 주세요."]
    assert replies == [menu_expired_text(FOUR_HOURS)]


def test_the_one_second_edge_is_pinned_on_both_sides(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    # At exactly 4 h the menu is still offered to the LLM by name (`<=`), while `/eat_` is already expired
    # (`now >= expires_unix`). One second earlier both work.
    show_menu(monkeypatch, capsys, home)
    provider = bot.FakeProvider(bot.meal(bot._item("얼큰순살감자탕", None, None, kind="general", memo="x")))
    update = at(timedelta(hours=4), 2, "얼큰순살감자탕 먹었어", monkeypatch)
    bot._session(monkeypatch, capsys, provider, update)
    assert "<최근 메뉴>\n" in provider.requests[0][0].prompt
    update = at(timedelta(hours=4), 3, "/eat_7f3a_1", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies == [menu_expired_text(FOUR_HOURS)]
    update = at(timedelta(hours=4) - timedelta(seconds=1), 4, "/eat_7f3a_1", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies[0].startswith("이렇게 기록할까요?")


def test_a_meal_proposal_still_expires_at_sixty_minutes_with_its_own_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/eat_7f3a_1"))
    update = at(timedelta(minutes=61), 3, "/ok_91c0", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies == [PROPOSAL_EXPIRED_TEXT]


def test_a_menu_from_a_v2_3_state_file_keeps_its_sixty_minutes_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    path = home / "config" / "telegram_llm_state.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["proposals"][0]["expires_unix"] = document["proposals"][0]["created_unix"] + 3600
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    update = at(timedelta(minutes=90), 2, "/eat_7f3a_1", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies == [menu_expired_text(3600)]
    assert "(60분)" in replies[0]
    # the same old menu is still a recent menu: it is offered by name for 4 hours
    provider = bot.FakeProvider(bot.meal(bot._item("얼큰순살감자탕", None, None, kind="general", memo="x")))
    bot._session(monkeypatch, capsys, provider, at(timedelta(minutes=91), 3, "얼큰순살감자탕 먹었어", monkeypatch))
    assert "<최근 메뉴>\n" in provider.requests[0][0].prompt


def test_the_menu_fixture_is_the_one_the_corrections_tests_use() -> None:
    assert STEW_MENU["photo_kind"] == "menu_capture"


# --- AC8: "동기화 해줘" gets the /daily and /refresh hint and nothing runs ---------------------------------

SYNC_REQUEST = interpretation(
    intent="sync_request", items=[], tense="none", meal_type=None, memory_summary="동기화 요청"
)
SYNC_REPLY = "동기화는 /daily 로 합니다. 운동 하나만 다시 받으려면 /refresh 를 쓰세요.\n/daily\n/refresh"


def test_a_sync_request_gets_the_hint_and_runs_and_stores_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    before = bot._tables(home)

    def no_cli(self: object, argv: object) -> object:
        pytest.fail("a sync request must not run any CLI command")

    monkeypatch.setattr(InProcessCliRunner, "run", no_cli)
    provider = bot.FakeProvider(SYNC_REQUEST)
    replies, _err, fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "동기화 해줘"))
    assert replies == [SYNC_REPLY] and SYNC_HINT_TEXT in replies[0]
    assert fake.sent[0][1].endswith("</pre>\n/daily\n/refresh")  # tappable command lines after the body
    assert bot._tables(home) == before
    assert not (home / "config" / "telegram_llm_state.json").exists()  # no proposal
    (entry,) = bot._history(home)
    assert (entry["intent"], entry["reply"]) == ("sync_request", SYNC_REPLY) and entry["proposal"] is None
    assert "동기화 안내" in bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/history"))[0][0]


def test_the_prompts_carry_the_sync_rules(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    provider = bot.FakeProvider(SYNC_REQUEST)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "동기화 해줘"))
    assert "sync_request(" in provider.requests[0][0].prompt
    from muscle50.domain.telegram_llm_prompt import TASKS, PromptTask

    assert "/daily 로 동기화하라고 안내합니다" in TASKS[PromptTask.ANSWER]


# --- AC2: a failed photo read ---

PHOTO_FAILED = '사진을 해석하지 못했습니다. 사진에 "메뉴" 또는 "먹음"이라고 적어 다시 보내 주세요.'
PLAIN_PHOTO_PROPOSAL = (
    "사진을 해석하지 못했습니다. 일반식으로만 기록할까요? (점심, 10-06)",
    "(끼니: 지금 시각 기준)",
    "1. 일반식",
    "기록: /ok_7f3a   취소: /no_7f3a",
)


def test_a_failed_read_with_a_clear_caption_offers_the_plain_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home, {"keep_photos": False})
    replies, _err, _fake = bot._session(
        monkeypatch, capsys, bot.FakeProvider("bad_output"), bot.photo(1, "점심으로 이거 먹었어")
    )  # v2.5: a timeout has its own reply now; reason `other` keeps the v2.4 caption rule
    assert replies == ["\n".join(PLAIN_PHOTO_PROPOSAL)]
    assert len(state(home)) == 1


@pytest.mark.parametrize("caption", [None, "", "점심", "이거 뭐야", "점심 메뉴 먹었어", "plate", "menu ate"])
def test_a_failed_read_without_a_clear_caption_offers_nothing_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, caption: str | None
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home, {"keep_photos": False})
    before = bot._tables(home)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider("bad_output"), bot.photo(1, caption))
    # v2.5: reason `other` keeps the v2.4 text and adds the one-tap retry (a timeout has its own reply now).
    failed = f"{PHOTO_FAILED}\n{retry_line('7f3a')}"
    assert replies == [failed]
    assert bot._tables(home) == before
    assert [proposal["kind"] for proposal in state(home)] == ["retry"]  # no meal proposal
    assert not (home / "telegram" / "photos").exists()
    (entry,) = bot._history(home)
    assert entry["reply"] == failed and entry["proposal"] is None


# --- AC3: the chat memory keeps what a photo was ---


def memory(home: Path) -> list[dict[str, Any]]:
    document = json.loads((home / "config" / "telegram_llm_memory.json").read_text(encoding="utf-8"))
    return list(document["chats"][str(bot.ALLOWED)]["turns"])


def test_a_meal_photo_leaves_a_memory_line_the_next_call_and_memory_show(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    meal_photo = bot.meal(
        bot._item("닭가슴살", 1, "pack"),
        bot._item("햇반", 1, "pack"),
        photo_kind="meal_photo",
        memory_summary="점심 사진",
    )
    bot._session(monkeypatch, capsys, bot.FakeProvider(meal_photo), bot.photo(1, "점심"))
    (turn,) = memory(home)
    assert turn["user"] == "[사진 1장] 점심 → 식사 사진으로 읽음: 닭가슴살, 햇반"
    # the next call's prompt and /memory show the same line
    question = interpretation(intent="chat", items=[], tense="none", reply="네.", memory_summary="사진 이야기")
    provider = bot.FakeProvider(question)
    replies, _err, _fake = bot._session(
        monkeypatch, capsys, provider, bot.text(2, "두개는 해석 못해?"), bot.text(3, "/memory")
    )
    assert "- 나: [사진 1장] 점심 → 식사 사진으로 읽음: 닭가슴살, 햇반" in provider.requests[0][0].prompt
    assert "- 나: [사진 1장] 점심 → 식사 사진으로 읽음: 닭가슴살, 햇반" in replies[1]
    assert "'[사진 N장]'으로 시작하는 줄" in provider.requests[0][0].prompt  # the rule that goes with it


def test_a_menu_capture_a_failed_read_and_an_unclear_photo_are_remembered_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home, {"keep_photos": False})
    menu_capture = dict(STEW_MENU)
    unclear = bot.meal(photo_kind="unclear")
    bot._session(
        monkeypatch,
        capsys,
        bot.FakeProvider(menu_capture, "timeout", unclear),
        bot.photo(1, "점심 메뉴"),
        bot.photo(2, None),
        bot.photo(3, None),
    )
    assert [turn["user"] for turn in memory(home)] == [
        "[사진 1장] 점심 메뉴 → 메뉴 캡처로 읽음: 항목 2개",
        "[사진 1장] → 해석 못함",
        "[사진 1장] → 사진 종류 불명",
    ]


def test_a_text_turn_keeps_its_exact_memory_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)
    chat = interpretation(intent="chat", items=[], tense="none", reply="네.", memory_summary="인사")
    bot._session(monkeypatch, capsys, bot.FakeProvider(chat), bot.text(1, "안녕 [사진] 이야기"))
    assert memory(home)[0]["user"] == "안녕 [사진] 이야기"


# --- AC7: short Korean summaries after /ok, /plain, edits and voids -------------------------------------------

LABEL_SAMPLE = [
    "기록했습니다: 아침 2026-10-06-breakfast-1 (10-06)",
    "1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개) - 라벨 kcal 185, 단백질 5 g, 탄수화물 37 g",
    "2. 닭가슴살 (chicken-breast) 1 pack - kcal 165, 단백질 34 g, 탄수화물 0 g, 지방 2 g",
    "이 끼니 (추정 포함): kcal 350, 단백질 39 g, 탄수화물 37 g, 지방 2 g (값 모르는 항목 1개 빠짐)",
    "취소: /void 2026-10-06-breakfast-1   전체 보기: /show 2026-10-06-breakfast-1",
]
LABEL_TOTALS = [
    "오늘 누적 (추정 포함):",
    "  kcal 350",
    "  단백질 39 g",
    "  탄수화물 37 g",
    "  지방 2 g (값 모르는 항목 1개 빠짐)",
]


def test_ok_of_a_label_photo_is_the_short_summary_with_the_label_marked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    corrections.prepare(capsys, home)
    corrections.record_label_meal(monkeypatch, capsys, home)
    # the reply of /ok (the second message) is in the history; its text is what the user was sent
    entry = bot._history(home)[-1]
    assert entry["kind"] == "confirm" and entry["reply"] == "\n".join([*LABEL_SAMPLE, *LABEL_TOTALS])
    assert entry["result"] == {"exit_code": 0, "meal_id": "2026-10-06-breakfast-1"}
    assert "Recorded meal" not in entry["reply"]


def test_the_summary_is_the_same_on_a_twin_home(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    corrections.prepare(capsys, home)
    corrections.record_label_meal(monkeypatch, capsys, home)
    first = bot._history(home)[-1]["reply"]
    twin = tmp_path / "twin"
    monkeypatch.setenv("MUSCLE50_HOME", str(twin))
    tokens = iter(["7f3a", "91c0", "c2e1"])
    monkeypatch.setattr(cli, "_new_proposal_token", lambda: next(tokens))
    v1._configure(twin)
    corrections.prepare(capsys, twin)
    corrections.record_label_meal(monkeypatch, capsys, twin)
    assert bot._history(twin)[-1]["reply"] == first
    assert meals.meal_tables(twin) == meals.meal_tables(home)


def test_plain_records_without_values_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    corrections.prepare(capsys, home)
    corrections.send_photo(monkeypatch, capsys, 1, corrections.label_photo())
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/plain_7f3a"))
    assert replies[0].split("\n")[:5] == [
        "기록했습니다: 아침 2026-10-06-breakfast-1 (10-06)",
        "1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개) - 값 없음",
        "2. 닭가슴살 (chicken-breast) 1 pack - kcal 165, 단백질 34 g, 탄수화물 0 g, 지방 2 g",
        # one item has no value: every nutrient says so (the known part is a lower bound, never a total)
        "이 끼니: kcal 165 (값 모르는 항목 1개 빠짐), 단백질 34 g (값 모르는 항목 1개 빠짐), "
        "탄수화물 0 g (값 모르는 항목 1개 빠짐), 지방 2 g (값 모르는 항목 1개 빠짐)",
        "취소: /void 2026-10-06-breakfast-1   전체 보기: /show 2026-10-06-breakfast-1",
    ]


def test_a_general_meal_with_no_values_never_reads_as_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    corrections.prepare(capsys, home)
    only = meals.dishes(meals.item("국밥", "lunch", estimate=meals.est((600, 700), (20, 30))))
    bot._session(monkeypatch, capsys, bot.FakeProvider(only), bot.text(1, "점심 국밥"))
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/plain_7f3a"))
    lines = replies[0].split("\n")
    assert lines[1] == "1. 일반식 (메모: 국밥) - 값 없음"
    assert lines[2] == "이 끼니: 값 없음 (0이 아님)"
    assert "0 kcal" not in replies[0] and "kcal 0" not in replies[0]


def test_a_failed_write_keeps_the_cli_error_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(bot.LUNCH_MEAL), bot.text(1, "점심 닭가슴살이랑 햇반"))
    # a lunch typed meanwhile makes the proposal's `nutrition log` refuse (a second lunch needs --additional)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/log lunch 닭가슴살 100 g"))
    before = meals.meal_tables(home)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(3, "/ok_7f3a"))
    assert replies[0].startswith("오류:") and "기록했습니다" not in replies[0]
    assert meals.meal_tables(home) == before
    assert bot._history(home)[-1]["result"]["exit_code"] == 1


def _break_show(monkeypatch: pytest.MonkeyPatch, outcome: CommandOutcome) -> list[tuple[str, ...]]:
    """Every `nutrition meal show` of the bot returns ``outcome``; the other commands run for real."""
    original = InProcessCliRunner.run
    seen: list[tuple[str, ...]] = []

    def run(self: InProcessCliRunner, argv: Sequence[str]) -> CommandOutcome:
        seen.append(tuple(argv[:3]))
        if tuple(argv[:3]) == ("nutrition", "meal", "show"):
            return outcome
        return original(self, argv)

    monkeypatch.setattr(InProcessCliRunner, "run", run)
    return seen


def test_the_cli_text_is_sent_when_the_stored_meal_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(bot.LUNCH_MEAL), bot.text(1, "점심 닭가슴살이랑 햇반"))
    _break_show(monkeypatch, CommandOutcome(1, "", "오류: synthetic\n"))
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert replies[0].startswith("Recorded meal 2026-10-06-lunch-1.\n")
    assert "\n취소: /void 2026-10-06-lunch-1\n오늘 누적:" in replies[0]
    assert "기록했습니다" not in replies[0]
    assert bot._history(home)[-1]["result"] == {"exit_code": 0, "meal_id": "2026-10-06-lunch-1"}


def test_an_unexpected_shape_falls_back_to_the_cli_text_and_logs_the_type(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(bot.LUNCH_MEAL), bot.text(1, "점심 닭가슴살이랑 햇반"))
    _break_show(monkeypatch, CommandOutcome(0, json.dumps({"meal_id": "x"}), ""))
    replies, err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert replies[0].startswith("Recorded meal 2026-10-06-lunch-1.\n")
    assert "chat 111: meal summary not built (KeyError)" in err


def test_remove_item_and_a_meal_type_change_are_edits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    bot._ok(
        capsys,
        *(
            "nutrition",
            "log",
            "--meal",
            "lunch",
            "--item",
            "chicken-breast",
            "1",
            "pack",
            "--item",
            "햇반",
            "1",
            "pack",
        ),
    )
    provider = bot.FakeProvider(
        bot._edit("remove_item", target_food_text="햇반"),
        bot._edit("change_meal_type", new_meal_type="dinner", target_food_text=None),
    )
    bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 햇반 빼줘"), bot.text(2, "점심 아니고 저녁"))
    replies, _err, _fake = bot._session(
        monkeypatch, capsys, bot.FakeProvider(), bot.text(3, "/ok_7f3a"), bot.text(4, "/ok_91c0")
    )
    assert replies[0].split("\n")[:5] == [
        "수정했습니다: 점심 2026-10-06-lunch-1 (10-06)",
        "1. 닭가슴살 (chicken-breast) 1 pack - kcal 165, 단백질 34 g, 탄수화물 0 g, 지방 2 g",
        "이 끼니: kcal 165, 단백질 34 g, 탄수화물 0 g, 지방 2 g",
        "확인: /show 2026-10-06-lunch-1",
        "오늘 누적:",
    ]
    assert replies[1].startswith("수정했습니다: 저녁 2026-10-06-lunch-1 (10-06)\n1. 닭가슴살")


def test_void_is_confirmed_without_reading_the_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    bot._ok(capsys, "nutrition", "log", "--meal", "snack", "--item", "햇반", "1", "pack")
    bot._session(monkeypatch, capsys, bot.FakeProvider(bot._edit("void_meal")), bot.text(1, "간식 취소"))
    seen = _break_show(monkeypatch, CommandOutcome(1, "", "must not be asked\n"))
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert replies[0].split("\n")[:3] == [
        "취소(void)했습니다: 2026-10-06-snack-1",
        "확인: /show 2026-10-06-snack-1",
        "오늘 누적: 오늘 기록 없음 (0이 아님)",
    ]
    assert ("nutrition", "meal", "show") not in seen
    assert bot._history(home)[-1]["result"] == {"exit_code": 0, "meal_id": "2026-10-06-snack-1"}


def test_fix_confirms_as_an_edit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    corrections.overlap_reply(monkeypatch, capsys, home, corrections.tuna_rice_ball())
    corrections.say(monkeypatch, capsys, None, 4, "/fix_91c0")
    replies, _provider = corrections.say(monkeypatch, capsys, None, 5, "/ok_c2e1")
    assert replies[0].startswith("수정했습니다: 아침 2026-10-06-breakfast-1 (10-06)\n")
    assert "\n확인: /show 2026-10-06-breakfast-1\n오늘 누적" in replies[0]
    assert bot._history(home)[-1]["kind"] == "edit"


def test_typed_log_keeps_the_cli_text_with_the_llm_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    replies, _err, _fake = bot._session(
        monkeypatch, capsys, bot.FakeProvider(), bot.text(1, "/log lunch 닭가슴살 150 g")
    )
    assert replies[0].startswith("Recorded meal 2026-10-06-lunch-1.\n")
    assert replies[0].endswith("\n취소: /void 2026-10-06-lunch-1") and "오늘 누적" not in replies[0]
