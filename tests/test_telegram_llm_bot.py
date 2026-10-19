"""Telegram LLM v2 end to end: `muscle50 telegram run` with `config\\telegram_llm.json`, a fake Bot API and a
fake LLM provider (never the real `claude`/`codex`, never the network), a temporary MUSCLE50_HOME and
synthetic foods only. Covers AC1-AC9j of docs/specs/telegram-llm.md.
"""

from __future__ import annotations

import html
import json
import re
import socket
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
from test_telegram_llm_domain import ITEM_ESTIMATE, NEW_ITEM_KEYS, NULL_EDIT, NULL_ESTIMATE, interpretation

import muscle50.cli as cli
from muscle50.application.llm_provider import LlmAttempt, LlmCallResult, LlmRequest, SchemaName
from muscle50.application.telegram_bot import IncomingMessage, IncomingUpdate
from muscle50.cli import main
from muscle50.domain.llm_settings import LlmSettings, ProviderName
from muscle50.domain.telegram_commands import HELP_TEXT, help_text, pending_migration_text
from muscle50.domain.telegram_llm_prompt import (
    CANCELLED_TEXT,
    FORGET_TEXT,
    MEMORY_EMPTY_TEXT,
    PHOTO_KIND_UNCLEAR_TEXT,
    PLANNED_TEXT,
    PROPOSAL_CANCELLED_TEXT,
    PROPOSAL_EXPIRED_TEXT,
    PROPOSAL_USED_TEXT,
    PROVIDER_FAILED_TEXT,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.llm.executables import ResolvedExecutable
from muscle50.infrastructure.sqlite.schema_status import code_migration_versions

KST = timezone(timedelta(hours=9))
TODAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=KST)
NOW_TS = int(NOW.timestamp())
TOKEN = v1.TOKEN
ALLOWED = v1.ALLOWED
PHOTO = b"\xff\xd8\xff\xe0synthetic-photo"
COMMON = ["--source", "nutrition_label", "--accuracy", "exact"]
CHICKEN = ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g", "--kcal", "110", "--protein", "23"]
CHICKEN += ["--carbs", "0", "--fat", "1", *COMMON]
CHICKEN_PACK = ["--per", "1", "pack", "--kcal", "165", "--protein", "34", "--carbs", "0", "--fat", "2", *COMMON]
RICE = ["--id", "hetbahn-210", "--name", "햇반", "--per", "1", "pack", "--kcal", "315", "--protein", "5"]
RICE += ["--carbs", "70", "--fat", "1", *COMMON]
BANANA = ["--id", "banana", "--name", "바나나", "--per", "1", "count", "--kcal", "90", "--protein", "1"]
BANANA += ["--carbs", "23", "--fat", "0", *COMMON, "--alias", "apple"]
APPLE = ["--id", "apple", "--name", "사과", "--per", "1", "count", "--kcal", "80", "--protein", "0"]
APPLE += ["--carbs", "21", "--fat", "0", *COMMON]


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FixedDateTime:
        value = NOW if tz is None else NOW.astimezone(tz)
        return cls.fromisoformat(value.isoformat())


class FakeApi(v1.FakeTelegramApi):
    def __init__(self, *batches: Sequence[IncomingUpdate]) -> None:
        super().__init__(*batches)
        self.downloads: list[str] = []

    def download_photo(self, file_id: str, max_bytes: int) -> bytes:
        self.downloads.append(file_id)
        return PHOTO


class FakeProvider:
    """Answers each call with the next scripted document; a str is a failure outcome."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[LlmRequest, ProviderName]] = []

    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        self.requests.append((request, provider))
        response = self.responses.pop(0)
        if isinstance(response, str):
            return _result(provider, response, None)
        try:
            document = request.validate(response)
        except ValueError:
            return _result(provider, "bad_output", None)
        return _result(provider, "ok", document)


def _result(provider: ProviderName, outcome: Any, document: Any) -> LlmCallResult:
    attempts = (LlmAttempt(provider, "sonnet", outcome, 1.0),)
    return LlmCallResult(provider, "sonnet", outcome, document, 1.0, False, attempts)


def _fail_connect(*args: object, **kwargs: object) -> object:
    pytest.fail("no network in tests")


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(urllib.request, "urlopen", _fail_connect)
    monkeypatch.setattr(socket.socket, "connect", _fail_connect)
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "datetime", _FixedDateTime)
    monkeypatch.setattr(cli, "_telegram_sleep", lambda seconds: None)
    monkeypatch.setattr(
        cli,
        "_resolve_llm_executable",
        lambda provider, configured: ResolvedExecutable(provider, rf"C:\Tools\{provider.value}.exe", None),
    )
    tokens = iter(["7f3a", "91c0", "c2e1", "44d2", "a1b2", "b3c4", "d5e6", "e7f8", "0a0b", "1c1d"])
    monkeypatch.setattr(cli, "_new_proposal_token", lambda: next(tokens))
    v1._configure(root)
    return root


def _llm_config(root: Path, document: dict[str, Any] | None = None) -> None:
    path = root / "config" / "telegram_llm.json"
    path.write_text(json.dumps(document or {}), encoding="utf-8", newline="\n")


def _install(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> list[LlmSettings]:
    seen: list[LlmSettings] = []

    def factory(settings: LlmSettings, executables: Any, log: Callable[[str], None]) -> FakeProvider:
        seen.append(settings)
        return provider

    monkeypatch.setattr(cli, "_llm_provider", factory)
    return seen


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    return v1._ok(capsys, *argv)


def _catalog(capsys: pytest.CaptureFixture[str]) -> None:
    for food in (CHICKEN, RICE, APPLE, BANANA):
        _ok(capsys, "nutrition", "food", "add", *food)
    _ok(capsys, "nutrition", "food", "fact", "add", "chicken-breast", *CHICKEN_PACK, "--new-unit")


def text(update_id: int, body: str, *, chat: int = ALLOWED) -> IncomingUpdate:
    return IncomingUpdate(update_id, IncomingMessage(chat, body, NOW_TS))


def photo(update_id: int, caption: str | None = None, *, chat: int = ALLOWED) -> IncomingUpdate:
    message = IncomingMessage(chat, None, NOW_TS, photo_file_id="file-1", photo_size=100, caption=caption)
    return IncomingUpdate(update_id, message)


def _plain(message: str) -> str:
    """A sent HTML message as the user reads it."""
    return html.unescape(re.sub(r"</?(pre|code)>", "", message))


def _session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: FakeProvider,
    *updates: IncomingUpdate,
) -> tuple[list[str], str, FakeApi]:
    fake = FakeApi(list(updates))
    _install(monkeypatch, provider)
    v1._install(monkeypatch, fake)
    code = main(["telegram", "run"])
    captured = capsys.readouterr()
    assert code == 130, captured.err
    assert captured.out == ""
    return [_plain(message) for _, message in fake.sent], captured.err, fake


def _item(food: str, quantity: float | None, unit: str | None, **fields: Any) -> dict[str, Any]:
    item = {
        "kind": "catalog",
        "food_text": food,
        "quantity": quantity,
        "unit": unit,
        "quantity_estimated": False,
        "memo": None,
        "estimate": dict(ITEM_ESTIMATE),
        **NEW_ITEM_KEYS,
    }
    item.update(fields)
    return item


def _estimate(**values: float) -> dict[str, Any]:
    return {**NULL_ESTIMATE, **values}


def meal(*items: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return interpretation(items=list(items), **fields)


def _tables(root: Path) -> dict[str, list[tuple[Any, ...]]]:
    database = v1._database(root)
    return v1._tables(database) if database.exists() else {}


def _history(root: Path) -> list[dict[str, Any]]:
    path = root / "telegram" / "history" / "2026-10.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


LUNCH_MEAL = meal(_item("닭가슴살", 1, "pack"), _item("햇반", 1, "pack", quantity_estimated=True))
LUNCH_PROPOSAL = "\n".join(
    [
        "이렇게 기록할까요? (점심, 10-06)",
        "1. 닭가슴살 (chicken-breast) 1 pack",
        "2. 햇반 (hetbahn-210) 1 pack (수량 추정)",
        "기록: /ok_7f3a   취소: /no_7f3a",
    ]
)
LUNCH_ARGV: tuple[str, ...] = ("nutrition", "log", "--date", "2026-10-06", "--meal", "lunch")
LUNCH_ARGV += ("--item", "chicken-breast", "1", "pack", "--item", "hetbahn-210", "1", "pack")


# --- AC1, AC9j: proposal, confirm, same rows as the CLI ------------------------------------------------


def test_meal_proposal_writes_nothing_until_ok_then_rows_equal_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    before = _tables(home)
    provider = FakeProvider(LUNCH_MEAL)
    replies, _err, _fake = _session(monkeypatch, capsys, provider, text(1, "점심에 닭가슴살 한 팩이랑 햇반 먹었어"))
    assert replies == [LUNCH_PROPOSAL]
    assert _tables(home) == before
    request, chosen = provider.requests[0]
    assert (request.schema, chosen, request.photo) == (SchemaName.INTERPRET, ProviderName.CLAUDE, None)
    assert request.prompt.endswith("[메시지]\n점심에 닭가슴살 한 팩이랑 햇반 먹었어\n")

    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(2, "/ok_7f3a"))
    after = _tables(home)
    meal_rows = {name: rows for name, rows in after.items() if name.startswith("nutrition_meal")}
    log_reply = v1._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1")
    assert "2026-10-06-lunch-1" in log_reply
    # The same argv typed in the CLI on a twin home gives the same rows.
    twin = tmp_path / "twin"
    monkeypatch.setenv("MUSCLE50_HOME", str(twin))
    _catalog(capsys)
    cli_reply = _ok(capsys, *LUNCH_ARGV)
    twin_rows = {name: rows for name, rows in _tables(twin).items() if name.startswith("nutrition_meal")}
    assert meal_rows == twin_rows
    assert _tables(twin)["nutrition_facts"] == after["nutrition_facts"]
    expected = "\n".join(
        [
            cli_reply.removesuffix("\n"),
            "취소: /void 2026-10-06-lunch-1",
            "오늘 누적:",
            "  kcal 480",
            "  단백질 39 g",
            "  탄수화물 70 g",
            "  지방 3 g",
        ]
    )
    assert replies == [expected]


def test_typed_log_reply_is_unchanged_with_the_llm_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    provider = FakeProvider()
    replies, _err, _fake = _session(monkeypatch, capsys, provider, text(1, "/log lunch 닭가슴살 150 g"))
    assert replies[0].endswith("\n취소: /void 2026-10-06-lunch-1")
    assert "오늘 누적" not in replies[0] and provider.requests == []


# --- AC2: never guessed ---------------------------------------------------------------------------------


def test_unmatched_ambiguous_and_missing_unit_items_are_never_linked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    # v2.2 (spec rule 4): nothing is dropped any more. Every item that cannot be linked stays a general item
    # that keeps the LLM's estimate range, with the reason (and, for an unregistered unit, the registration hint).
    _catalog(capsys)
    _llm_config(home)
    document = meal(
        _item("오징어볶음", 1, "serving"),
        _item("apple", 1, "count"),
        _item("햇반", None, None),
        _item("바나나", 2, "g"),
    )
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(document), text(1, "점심 먹었어"))
    estimate = "   추정: kcal 300~400, 단백질 10~20 g (estimated)"
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (점심, 10-06)",
                "1. 일반식 (메모: 오징어볶음 1 serving) - 카탈로그에 없음",
                estimate,
                "2. 일반식 (메모: apple 1 count) - 이름이 여러 음식에 맞음",
                estimate,
                "3. 일반식 (메모: 햇반) - 수량·단위를 말하지 않음",
                estimate,
                "4. 일반식 (메모: 바나나 2 g) - 이 음식은 count 기준 값만 있습니다(단위 변환 없음)",
                estimate,
                "   등록: muscle50 nutrition food fact add banana --per 1 g ... --new-unit",
                "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a",
            ]
        )
    ]
    state = json.loads((home / "config" / "telegram_llm_state.json").read_text(encoding="utf-8"))
    ref = "--general-estimate-ref=telegram-llm text (claude sonnet)"
    spec = "--general-estimate=language_estimate:kcal=300-400,protein=10-20"
    assert state["proposals"][0]["argv_ok"] == [
        *LUNCH_ARGV[:6],
        *("--general", "--general-note=오징어볶음 1 serving", spec, ref),
        *("--general", "--general-note=apple 1 count", spec, ref),
        *("--general", "--general-note=햇반", spec, ref),
        *("--general", "--general-note=바나나 2 g", spec, ref),
    ]


def test_a_message_of_only_meal_words_gives_the_usage_text_and_no_proposal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    document = meal(_item("점심", None, None, kind="general"), _item("저녁식사", None, None, kind="general"))
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(document), text(1, "점심 저녁"))
    assert len(replies) == 1 and replies[0].startswith("사용법: /log")
    assert not (home / "config" / "telegram_llm_state.json").exists()


def test_planned_meal_is_not_logged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home)
    document = meal(_item("햇반", 1, "pack"), tense="planned")
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(document), text(1, "점심에 햇반 먹을 예정"))
    assert replies == [PLANNED_TEXT]


def test_meal_slot_from_the_time_and_duplicate_guard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    _ok(capsys, "nutrition", "log", "--meal", "lunch", "--item", "햇반", "1", "pack")
    # A different food in a slot that already has a meal: recorded as another meal, said at the very top.
    document = meal(_item("닭가슴살", 1, "pack"), meal_type=None)
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(document), text(1, "닭가슴살 하나 먹었어"))
    assert replies[0].split("\n")[:3] == [
        "이미 기록된 점심(2026-10-06-lunch-1)이 있어 하나 더 기록합니다.",
        "이렇게 기록할까요? (점심, 10-06)",
        "(끼니: 지금 시각 기준)",
    ]
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(2, "/ok_7f3a"))
    assert replies[0].startswith("Recorded meal 2026-10-06-lunch-2.")


# --- AC3: at most once ----------------------------------------------------------------------------------


def test_ok_twice_expired_cancelled_and_restart_store_at_most_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    provider = FakeProvider(LUNCH_MEAL, LUNCH_MEAL)
    _session(monkeypatch, capsys, provider, text(1, "점심"), text(2, "점심"))
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(3, "/ok_7f3a"), text(4, "/ok_7f3a"))
    assert replies[1] == PROPOSAL_USED_TEXT
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(5, "/ok_7f3a"))  # after a restart
    assert replies == [PROPOSAL_USED_TEXT]
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(6, "/no_91c0"), text(7, "/ok_91c0"))
    assert replies == [CANCELLED_TEXT, PROPOSAL_CANCELLED_TEXT]
    meals = _tables(home)["nutrition_meals"]
    assert [row[0] for row in meals] == ["2026-10-06-lunch-1"]


def test_expired_proposal_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    _session(monkeypatch, capsys, FakeProvider(LUNCH_MEAL), text(1, "점심"))
    later = NOW + timedelta(minutes=60)
    monkeypatch.setattr(cli, "_now", lambda: later)
    late = IncomingUpdate(2, IncomingMessage(ALLOWED, "/ok_7f3a", int(later.timestamp())))
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), late)
    assert replies == [PROPOSAL_EXPIRED_TEXT]
    assert "nutrition_meals" not in _tables(home) or _tables(home)["nutrition_meals"] == []


def test_another_chats_token_is_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    v1._configure(home, {"bot_token": TOKEN, "allowed_chat_ids": [ALLOWED, 222]})
    _catalog(capsys)
    _llm_config(home)
    _session(monkeypatch, capsys, FakeProvider(LUNCH_MEAL), text(1, "점심"))
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(2, "/ok_7f3a", chat=222))
    assert replies == ["이 확인 명령을 찾지 못했습니다."]


# --- AC9a: migrations and dates --------------------------------------------------------------------------


def test_pending_migration_refuses_ok_without_consuming(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    _session(monkeypatch, capsys, FakeProvider(LUNCH_MEAL), text(1, "점심"))
    latest = code_migration_versions()[-1]
    v1._drop_migration_marker(v1._database(home), latest)
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(2, "/ok_7f3a"))
    assert replies == [pending_migration_text((latest,))]
    assert _tables(home)["nutrition_meals"] == []
    state = json.loads((home / "config" / "telegram_llm_state.json").read_text(encoding="utf-8"))
    assert state["proposals"][0]["state"] == "open"


def test_yesterday_uses_the_bots_date(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    document = meal(_item("햇반", 1, "pack"), meal_type="dinner", date_expression="yesterday")
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(document), text(1, "어제 저녁 햇반"))
    assert replies[0].startswith("이렇게 기록할까요? (저녁, 10-05)")
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(2, "/ok_7f3a"))
    assert replies[0].startswith("Recorded meal 2026-10-05-dinner-1.")
    other = meal(_item("햇반", 1, "pack"), date_expression="other")
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(other), text(3, "지난 주 금요일"))
    assert replies[0].startswith("날짜를 정하지 못했습니다.")


# --- AC4: photo estimates --------------------------------------------------------------------------------


def _photo_meal() -> dict[str, Any]:
    item = _item(
        "제육볶음 정식",
        None,
        None,
        kind="general",
        memo="제육볶음 정식",
        estimate=_estimate(kcal_min=700, kcal_max=950, protein_min=30, protein_max=45),
    )
    return meal(item, photo_kind="meal_photo", meal_type="dinner")


def test_photo_estimate_shows_range_estimated_and_plain_stores_no_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home)
    provider = FakeProvider(_photo_meal())
    replies, _err, fake = _session(monkeypatch, capsys, provider, photo(1, "저녁"))
    assert fake.downloads == ["file-1"]
    assert provider.requests[0][0].photo == PHOTO
    assert replies[0] == "\n".join(
        [
            "이렇게 기록할까요? (저녁, 10-06, 사진 추정)",
            "1. 일반식 (메모: 제육볶음 정식)",
            "   추정: kcal 700~950, 단백질 30~45 g (estimated)",
            "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a",
        ]
    )
    _session(monkeypatch, capsys, FakeProvider(), text(2, "/ok_7f3a"))
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(_photo_meal()), photo(3, "저녁"))
    # the same dish again: the overlap notice replaces the "another meal" notice; /plain_ still records another meal
    assert replies[0].startswith("오늘 저녁(2026-10-06-dinner-1)에 이미 같은 음식이 있습니다: 제육볶음 정식\n")
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(4, "/plain_91c0"))
    estimated = json.loads(_ok(capsys, "nutrition", "meal", "show", "2026-10-06-dinner-1", "--json"))
    item = estimated["items"][0]
    assert item["nutrients"]["calories_kcal"]["minimum"] == "700"
    assert item["nutrients"]["calories_kcal"]["source_type"] == "visual_estimate"
    reference = item["facts"][0]["source_reference"]
    assert re.fullmatch(r"telegram-llm photo sha256:[0-9a-f]{12} \(claude sonnet\)", reference)
    plain = json.loads(_ok(capsys, "nutrition", "meal", "show", "2026-10-06-dinner-2", "--json"))
    assert plain["items"][0]["facts"] == [] and plain["items"][0]["note"] == "제육볶음 정식"
    assert "  kcal 700~950 (값 모르는 항목 1개 빠짐)" in replies[0]
    kept = list((home / "telegram" / "photos" / "2026-10").iterdir())
    assert len(kept) == 1 and kept[0].read_bytes() == PHOTO


def test_unclear_photo_asks_and_photo_failure_offers_a_plain_general_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home, {"keep_photos": False})
    provider = FakeProvider(meal(photo_kind="unclear"), "timeout")
    # v2.4: the plain general meal is offered after a failed read only when the caption says it was eaten.
    replies, _err, _fake = _session(monkeypatch, capsys, provider, photo(1), photo(2, "점심 먹었어"))
    assert replies[0] == PHOTO_KIND_UNCLEAR_TEXT
    assert replies[1] == "\n".join(
        [
            "사진을 해석하지 못했습니다. 일반식으로만 기록할까요? (점심, 10-06)",
            "(끼니: 지금 시각 기준)",
            "1. 일반식",
            "기록: /ok_7f3a   취소: /no_7f3a",
        ]
    )
    assert not (home / "telegram" / "photos").exists()
    assert [entry["photo"] for entry in _history(home)] == [None, None]


# --- AC5, AC9i: questions and the number guard ------------------------------------------------------------


def _question(*topics: str) -> dict[str, Any]:
    return interpretation(intent="question", items=[], question_topics=list(topics), tense="none")


def test_answer_with_only_data_numbers_is_sent_else_existing_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    v1._seed_reads(capsys, home)
    _llm_config(home)
    (home / "config" / "telegram_llm_coach.md").write_text("저녁은 단백질 150 g 이상", encoding="utf-8")
    good = {"answer": "단백질은 120 g 목표예요.", "memory_summary": "단백질 질문"}
    bad = {"answer": "단백질은 77 g 남았어요.", "memory_summary": ""}
    coach_number = {"answer": "목표보다 많이, 150 g 드세요.", "memory_summary": ""}
    provider = FakeProvider(
        _question("nutrition"), good, _question("nutrition"), bad, _question("nutrition"), coach_number
    )
    replies, err, _fake = _session(monkeypatch, capsys, provider, text(1, "단백질?"), text(2, "단백질?"), text(3, "?"))
    assert replies[0] == "단백질은 120 g 목표예요.\n(근거: /status)"
    status_doc = json.loads(_ok(capsys, "nutrition", "status", "--json"))
    from muscle50.presentation.telegram_summary import status_summary

    assert replies[1] == status_summary(status_doc).plain_text()
    assert replies[2] == status_summary(status_doc).plain_text()
    assert "llm answer had 1 numbers outside the data; sent the existing replies" in err
    answer_request = provider.requests[1][0]
    assert answer_request.schema is SchemaName.ANSWER
    prompt = answer_request.prompt
    assert (
        prompt.index("[코치 가이드]\n저녁은 단백질 150 g")
        < prompt.index("[고정 규칙]")
        < prompt.index("<nutrition status --json>")
    )


def test_question_needing_nutrition_is_refused_while_a_migration_is_pending(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    v1._seed_reads(capsys, home)
    _llm_config(home)
    latest = code_migration_versions()[-1]
    v1._drop_migration_marker(v1._database(home), latest)
    provider = FakeProvider(_question("nutrition"))
    replies, _err, _fake = _session(monkeypatch, capsys, provider, text(1, "단백질 얼마 남았어?"))
    assert replies == [pending_migration_text((latest,))]
    assert len(provider.requests) == 1


def test_training_question_passes_the_recommend_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    v1._seed_reads(capsys, home)
    _llm_config(home)
    provider = FakeProvider(_question("training"), {"answer": "오늘 계획은 /today에 있어요.", "memory_summary": ""})
    replies, _err, _fake = _session(monkeypatch, capsys, provider, text(1, "오늘 뭐 운동해?"))
    assert replies == ["오늘 계획은 /today에 있어요.\n(근거: /today)"]
    assert "<recommend --date 2026-10-06 --json>" in provider.requests[1][0].prompt


def test_coach_guide_missing_or_too_long_is_skipped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home)
    (home / "config" / "telegram_llm_coach.md").write_text("x" * 4001, encoding="utf-8")
    chat = interpretation(intent="chat", items=[], reply="안녕하세요, 머슬이에요.")
    provider = FakeProvider(chat)
    replies, err, _fake = _session(monkeypatch, capsys, provider, text(1, "안녕"))
    assert replies == ["안녕하세요, 머슬이에요."]
    assert "[코치 가이드]\n" not in provider.requests[0][0].prompt
    assert "coach guide ignored (longer than 4000 characters)" in err


def test_chat_with_a_number_gets_the_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home)
    chat = interpretation(intent="chat", items=[], reply="오늘 3세트 하세요.")
    unclear = interpretation(intent="unclear", items=[])
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(chat, unclear), text(1, "a"), text(2, "b"))
    assert replies[0] == help_text(True)
    assert replies[1] == "무슨 뜻인지 알지 못했습니다. 명령으로 보내 주세요.\n\n" + help_text(True)


# --- AC6: provider failure ------------------------------------------------------------------------------


def test_provider_failure_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    before = _tables(home)
    provider = FakeProvider("failed", {"intent": "not a schema"})
    replies, _err, _fake = _session(monkeypatch, capsys, provider, text(1, "점심"), text(2, "점심"))
    assert replies == [PROVIDER_FAILED_TEXT, PROVIDER_FAILED_TEXT]
    assert _tables(home) == before
    assert not (home / "config" / "telegram_llm_state.json").exists()
    assert [entry["provider_result"] for entry in _history(home)] == ["failed", "bad_output"]


# --- AC9, AC9d: allowlist, console, no other network -------------------------------------------------------


def test_unlisted_chat_photo_and_text_never_reach_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home)
    provider = FakeProvider()
    replies, err, fake = _session(
        monkeypatch, capsys, provider, text(1, "점심 먹었어", chat=v1.OTHER), photo(2, "저녁", chat=v1.OTHER)
    )
    assert (replies, provider.requests, fake.downloads) == ([], [], [])
    assert not (home / "telegram" / "history").exists()


def test_console_has_no_text_url_or_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    provider = FakeProvider(LUNCH_MEAL, _photo_meal())
    _replies, err, _fake = _session(
        monkeypatch, capsys, provider, text(1, "점심에 닭가슴살 비밀메모"), photo(2, "저녁 비밀")
    )
    assert err.removesuffix(v1.STOPPED).isascii()
    for secret in ("비밀", "닭가슴살", "api.telegram.org", TOKEN, "제육"):
        assert secret not in err
    assert "telegram llm: on, provider claude, fallback none, timeout 90 s" in err


def test_source_has_no_company_site() -> None:
    source = Path(__file__).resolve().parents[1] / "src"
    assert not any("grc.hd.com" in path.read_text(encoding="utf-8") for path in source.rglob("*.py"))


# --- AC9b, AC9c: menu capture --------------------------------------------------------------------------------


def _menu_item(
    corner: str, name: str, kcal: tuple[int, int], protein: tuple[int, int], **fields: Any
) -> dict[str, Any]:
    estimate = _estimate(kcal_min=kcal[0], kcal_max=kcal[1], protein_min=protein[0], protein_max=protein[1])
    item: dict[str, Any] = {"slot": "lunch", "corner": corner, "name": name, "printed_kcal": None}
    item["printed_protein_g"] = None
    item["estimate"] = estimate
    item.update(fields)
    return item


MENU = interpretation(
    intent="menu",
    photo_kind="menu_capture",
    items=[],
    meal_type=None,
    menu={
        "slots_visible": ["lunch"],
        "items": [
            _menu_item("일품", "돈까스 카레", (900, 1150), (20, 30)),
            _menu_item("한식", "제육볶음, 잡곡밥", (750, 950), (35, 50)),
            _menu_item("간편식", "닭가슴살 샐러드", (350, 450), (25, 35), printed_kcal=400),
        ],
    },
)


def test_menu_ranked_by_remaining_then_eat_then_ok_or_plain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2000")
    _ok(capsys, "nutrition", "target", "set", "protein", "--exact", "120")
    _ok(capsys, "nutrition", "log", "--meal", "breakfast", "--item", "chicken-breast", "300", "g")  # 330 kcal, 69 g
    before = _tables(home)
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(MENU, MENU), photo(1), photo(2))
    assert replies[0] == "\n".join(
        [
            "오늘 점심 메뉴예요. 남은 양: 단백질 51 g, kcal 1670 (/status)",
            "오늘 누적:",
            "  kcal 330",
            "  단백질 69 g",
            "  탄수화물 0 g",
            "  지방 3 g",
            "추천 순서 (메뉴 값은 사진 추정, estimated)",
            "1. 한식: 제육볶음, 잡곡밥   단백질 35~50 g, kcal 750~950",
            "2. 간편식: 닭가슴살 샐러드   단백질 25~35 g, kcal 400 (메뉴판 표기)",
            "3. 일품: 돈까스 카레   단백질 20~30 g, kcal 900~1150",
            "먹을 메뉴: /eat_7f3a_1 /eat_7f3a_2 /eat_7f3a_3",
        ]
    )
    assert replies[1] == replies[0].replace("7f3a", "91c0")  # same status, same order
    assert _tables(home) == before
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(3, "/eat_7f3a_2"))
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (점심, 10-06, 메뉴 캡처 추정)",
                "1. 일반식 (메모: 간편식 닭가슴살 샐러드)",
                "   추정: kcal 400, 단백질 25~35 g (estimated)",
                "기록: /ok_c2e1   일반식만 기록(값 없이): /plain_c2e1   취소: /no_c2e1",
            ]
        )
    ]
    assert _tables(home) == before
    _session(monkeypatch, capsys, FakeProvider(), text(4, "/ok_c2e1"))
    stored = json.loads(_ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert stored["items"][0]["nutrients"]["calories_kcal"]["minimum"] == "400"
    assert stored["items"][0]["note"] == "간편식 닭가슴살 샐러드"
    # The menu stays open: another pick, recorded without values this time.
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(5, "/eat_7f3a_1"), text(6, "/plain_44d2"))
    assert "이미 기록된 점심(2026-10-06-lunch-1)이 있어 하나 더 기록합니다." in replies[0]
    assert replies[1].startswith("Recorded meal 2026-10-06-lunch-2.")
    plain = json.loads(_ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-2", "--json"))
    assert plain["items"][0]["facts"] == [] and plain["items"][0]["note"] == "한식 제육볶음, 잡곡밥"


def test_menu_unknown_remaining_ranks_by_ratio_with_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home)
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(MENU), photo(1, "점심"))
    lines = replies[0].split("\n")
    assert lines[0] == (
        "오늘 점심 메뉴예요. 남은 양을 몰라 단백질/kcal 비율 순 "
        "(kcal 목표 없음, 오늘 식사 기록이 없어 남은 양을 알 수 없음 (0 kcal이 아님))"
    )
    assert lines[1] == "오늘 누적: 오늘 기록 없음 (0이 아님)"
    assert [line.split(".")[0] for line in lines[3:6]] == ["1", "2", "3"]
    assert "간편식" in lines[3] and "한식" in lines[4] and "일품" in lines[5]


# --- AC9g: menu suggestion without a capture ----------------------------------------------------------------


def _suggestions() -> dict[str, Any]:
    def entry(name: str, category: str, kcal: tuple[int, int], protein: tuple[int, int], note: str) -> dict[str, Any]:
        estimate = _estimate(kcal_min=kcal[0], kcal_max=kcal[1], protein_min=protein[0], protein_max=protein[1])
        return {"name": name, "category": category, "description": "", "estimate": estimate, "note": note}

    return {
        "lead": "가볍게 고르세요.",
        "suggestions": [
            entry("포케", "delivery", (500, 650), (25, 35), "탄수 적당"),
            entry("연어 덮밥", "eating_out", (600, 800), (30, 40), "단백질 999 g"),
        ],
        "memory_summary": "점심 추천",
    }


def test_menu_suggest_renders_template_ranked_and_eat_makes_language_estimate_proposal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home)
    ask = interpretation(intent="menu_suggest", items=[], tense="planned")
    replies, err, _fake = _session(monkeypatch, capsys, FakeProvider(ask, _suggestions()), text(1, "점심 뭐 먹지?"))
    lines = replies[0].split("\n")
    assert lines[0].startswith("점심 메뉴 제안이에요. 남은 양을 몰라 단백질/kcal 비율 순")
    assert "가볍게 고르세요." in lines and "추천 (값은 추정, estimated)" in lines
    assert "1. 포케 (배달)   단백질 25~35 g, kcal 500~650 - 탄수 적당" in lines  # 30/575 > 35/700
    assert "2. 연어 덮밥 (외식)   단백질 30~40 g, kcal 600~800" in lines  # its note had a foreign number
    assert lines[-1] == "먹을 메뉴: /eat_7f3a_1 /eat_7f3a_2"
    assert "suggestion text with numbers outside the data was left out" in err
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(2, "/eat_7f3a_1"), text(3, "/ok_91c0"))
    assert replies[0].startswith("이렇게 기록할까요? (점심, 10-06, 메뉴 제안 추정)\n1. 일반식 (메모: 포케)")
    stored = json.loads(_ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert stored["items"][0]["nutrients"]["protein_g"]["source_type"] == "language_estimate"


def test_suggest_reads_status_with_d3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    latest = code_migration_versions()[-1]
    v1._drop_migration_marker(v1._database(home), latest)
    ask = interpretation(intent="menu_suggest", items=[])
    provider = FakeProvider(ask)
    replies, _err, _fake = _session(monkeypatch, capsys, provider, text(1, "뭐 먹지"))
    assert replies == [pending_migration_text((latest,))] and len(provider.requests) == 1


# --- AC9h: meal edits -------------------------------------------------------------------------------------------


def _edit(action: str, **fields: Any) -> dict[str, Any]:
    edit = {**NULL_EDIT, "action": action, **fields}
    return interpretation(intent="meal_edit", items=[], meal_type=None, edit=edit)


def test_edit_change_quantity_runs_replace_item_after_ok_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    _ok(
        capsys,
        "nutrition",
        "log",
        "--meal",
        "lunch",
        "--item",
        "chicken-breast",
        "2",
        "pack",
        "--item",
        "햇반",
        "1",
        "pack",
    )
    edit = _edit("change_quantity", target_food_text="닭가슴살", new_quantity=1)
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(edit), text(1, "점심 닭가슴살 2팩 아니고 1팩"))
    assert replies == [
        "이렇게 고칠까요?\n점심 2026-10-06-lunch-1 item 1: 닭가슴살 2 pack → 닭가슴살 (chicken-breast) 1 pack\n"
        "고치기: /ok_7f3a   취소: /no_7f3a"
    ]
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(2, "/ok_7f3a"), text(3, "/ok_7f3a"))
    assert replies[0].startswith("Replaced item 1 of meal 2026-10-06-lunch-1 with item 3.")
    assert "\n확인: /show 2026-10-06-lunch-1\n오늘 누적:" in replies[0]
    assert replies[1] == PROPOSAL_USED_TEXT
    assert _history(home)[-2]["kind"] == "edit"
    assert _history(home)[-2]["result"] == {"exit_code": 0, "meal_id": "2026-10-06-lunch-1"}


def test_edit_ambiguous_meal_or_item_lists_candidates_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    _ok(capsys, "nutrition", "log", "--meal", "lunch", "--item", "햇반", "1", "pack")
    _ok(capsys, "nutrition", "log", "--meal", "lunch", "--additional", "--item", "햇반", "1", "pack")
    before = _tables(home)
    edit = _edit("remove_item", target_food_text="햇반")
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(edit), text(1, "점심 햇반 빼줘"))
    assert replies[0].split("\n")[1:3] == ["/show 2026-10-06-lunch-1", "/show 2026-10-06-lunch-2"]
    assert _tables(home) == before
    assert not (home / "config" / "telegram_llm_state.json").exists()


def test_edit_void_and_meal_type(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    _ok(capsys, "nutrition", "log", "--meal", "snack", "--item", "햇반", "1", "pack")
    provider = FakeProvider(
        _edit("change_meal_type", new_meal_type="dinner", **{"target_food_text": None}),
        _edit("void_meal"),
    )
    replies, _err, _fake = _session(monkeypatch, capsys, provider, text(1, "간식 아니고 저녁"), text(2, "그거 취소"))
    assert "간식 2026-10-06-snack-1: 끼니 간식 → 저녁" in replies[0]
    assert "간식 2026-10-06-snack-1 기록 취소(void)" in replies[1]
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(3, "/ok_7f3a"), text(4, "/ok_91c0"))
    assert replies[0].startswith("Edited meal 2026-10-06-snack-1: type snack -> dinner.")
    assert replies[1].startswith("Voided meal 2026-10-06-snack-1.")


def test_edit_refused_while_migration_pending(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    _ok(capsys, "nutrition", "log", "--meal", "snack", "--item", "햇반", "1", "pack")
    _session(monkeypatch, capsys, FakeProvider(_edit("void_meal")), text(1, "취소"))
    latest = code_migration_versions()[-1]
    v1._drop_migration_marker(v1._database(home), latest)
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(2, "/ok_7f3a"))
    assert replies == [pending_migration_text((latest,))]


# --- AC9e: history, memory, /llm ---------------------------------------------------------------------------------


def test_each_exchange_appends_one_history_line_forget_keeps_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    _llm_config(home)
    chat = interpretation(intent="chat", items=[], reply="반가워요.", memory_summary="인사함")
    provider = FakeProvider(LUNCH_MEAL, chat)
    replies, _err, _fake = _session(
        monkeypatch,
        capsys,
        provider,
        text(1, "점심 먹었어"),
        text(2, "/ok_7f3a"),
        text(3, "안녕"),
        text(4, "/memory"),
        text(5, "/forget"),
        text(6, "/memory"),
        text(7, "/history"),
    )
    history = _history(home)
    assert [entry["kind"] for entry in history] == ["text", "confirm", "text"]
    assert [entry["update_id"] for entry in history] == [1, 2, 3]
    assert history[0]["proposal"] == "7f3a" and history[0]["llm_output"]["interpret"]["intent"] == "meal_log"
    assert history[1]["result"] == {"exit_code": 0, "meal_id": "2026-10-06-lunch-1"}
    assert history[0]["at"] == "2026-10-06T12:00:00+09:00"
    memory = replies[3]
    assert memory.startswith("다음 호출에 LLM에게 넘어가는 기억:\n[기억]\n요약: 인사함\n최근 대화:\n- 나: 점심 먹었어")
    second_prompt = provider.requests[1][0].prompt
    first_turn = memory.split("\n- 나: 안녕")[0].split("최근 대화:\n")[1]
    assert f"[기억]\n요약: 점심 기록\n최근 대화:\n{first_turn}\n\n" in second_prompt
    assert replies[4] == FORGET_TEXT and replies[5] == MEMORY_EMPTY_TEXT
    assert replies[6].startswith(
        "10-06 12:00 문장 · 식사 기록 · claude sonnet\n나: 점심 먹었어\nbot: 이렇게 기록할까요?"
    )
    assert "결과: 기록 2026-10-06-lunch-1" in replies[6]
    code, out, err = v1._cli(capsys, "telegram", "history", "--json")
    assert code == 0 and json.loads(out) == {"entries": history}
    assert len(_history(home)) == 3


def test_llm_override_switches_the_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home, {"fallback_provider": "codex"})
    chat = interpretation(intent="chat", items=[], reply="네.")
    provider = FakeProvider(chat, chat)
    replies, _err, _fake = _session(
        monkeypatch,
        capsys,
        provider,
        text(1, "/llm"),
        text(2, "/llm codex"),
        text(3, "안녕"),
        text(4, "/llm"),
        text(5, "/llm default"),
        text(6, "안녕"),
        text(7, "/llm gemini"),
    )
    assert replies[0] == (
        "LLM: claude · 글 haiku · 사진 sonnet · 형식 실패 시 재시도: sonnet (글만) · "
        "대체 제공자: codex · 시간 상한 90초\n"
        "바꾸기: /llm codex · 설정 파일로 되돌리기: /llm default"
    )
    assert replies[1] == "다음 메시지부터 codex(OpenAI)로 보냅니다. 메시지와 사진이 OpenAI로 전송됩니다."
    assert replies[3].endswith("(채팅에서 바꿈, 설정 파일: claude)")
    assert replies[4] == "설정 파일의 제공자로 되돌렸습니다: claude(Anthropic)."
    assert [chosen for _request, chosen in provider.requests] == [ProviderName.CODEX, ProviderName.CLAUDE]
    assert replies[6].startswith("사용법: /llm")
    assert json.loads((home / "config" / "telegram_llm.json").read_text(encoding="utf-8")) == {
        "fallback_provider": "codex"
    }


# --- startup and AC8 ------------------------------------------------------------------------------------------


def test_bad_llm_config_stops_run_with_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    (home / "config" / "telegram_llm.json").write_text('{"provider": "gemini"}', encoding="utf-8")
    fake = FakeApi()
    v1._install(monkeypatch, fake)
    code = main(["telegram", "run"])
    err = capsys.readouterr().err
    assert code == 1 and "provider must be claude or codex" in err and fake.calls == []


def test_help_gets_the_llm_lines_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(1, "/help"), text(2, "/memory"))
    assert replies == [HELP_TEXT, "모르는 명령입니다: /memory\n\n" + HELP_TEXT]
    _llm_config(home)
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(3, "/help"), text(4, "/foo"))
    assert replies == [help_text(True), "모르는 명령입니다: /foo\n\n" + help_text(True)]
    assert help_text(True).startswith(HELP_TEXT + "\n/llm [claude|codex|default]")


EXISTING_COMMANDS = [
    "/today",
    "/today full",
    "/status",
    "/status full",
    "/day",
    "/day 2026-10-05",
    "/show 2026-10-06-lunch-1",
    "/inbody",
    "/unknown",
    "/void 2026-10-05-dinner-1 중복",
    "/log snack 햇반 1 pack",
    "/log snack+ 일반식 편의점",
    "/refresh abc",
    "/refresh 24610155225",
    "/refresh",
    "/daily",
    "/nope",
    "/start",
]


def _garmin_login_needed(auth_dir: Path, *, input_fn: Callable[[str], str], **kwargs: object) -> object:
    """The v1 path without a keyboard: the login prompt raises EOFError (no network, nothing written)."""
    input_fn("Garmin email: ")
    raise AssertionError("input must raise EOFError")


@pytest.mark.parametrize("command", EXISTING_COMMANDS)
def test_existing_commands_reply_byte_identical_with_and_without_the_llm(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    tmp_path: Path,
    command: str,
) -> None:
    monkeypatch.setattr(PythonGarminConnector, "authenticate", _garmin_login_needed)

    def run(root: Path, *, llm: bool) -> tuple[list[str], dict[str, Any]]:
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        v1._configure(root)
        v1._seed_reads(capsys, root)
        if llm:
            _llm_config(root)
        fake = FakeApi([v1.update(1, command)])
        _install(monkeypatch, FakeProvider())
        v1._install(monkeypatch, fake)
        assert main(["telegram", "run"]) == 130
        capsys.readouterr()
        # Nutrition rows only: the seeded Garmin/InBody rows carry the wall-clock time they were seeded at.
        tables = {name: rows for name, rows in v1._tables(v1._database(root)).items() if name.startswith("nutrition")}
        return [message for _, message in fake.sent], tables

    without, rows_without = run(tmp_path / "plain", llm=False)
    with_llm, rows_with = run(tmp_path / "llm", llm=True)
    if command in ("/nope", "/start"):
        assert [_plain(message) for message in with_llm] == [
            _plain(message).replace(HELP_TEXT, help_text(True)) for message in without
        ]
    else:
        assert with_llm == without
    assert rows_with == rows_without


def test_non_command_text_without_llm_config_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    provider = FakeProvider()
    replies, err, fake = _session(monkeypatch, capsys, provider, text(1, "점심 먹었어"), photo(2, "저녁"))
    assert replies == ["명령이 아닙니다.\n\n" + HELP_TEXT] * 2
    assert provider.requests == [] and fake.downloads == []
    assert "telegram llm" not in err and not (home / "telegram" / "history").exists()


def test_console_stays_ascii_with_a_non_ascii_executable_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    monkeypatch.setattr(
        cli,
        "_resolve_llm_executable",
        lambda provider, configured: ResolvedExecutable(provider, f"D:/홍길동/{provider.value}.exe", None),
    )
    _llm_config(home)
    _replies, err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(1, "/help"))
    start = next(line for line in err.split("\n") if line.startswith("telegram llm: on"))
    assert start.isascii() and "\\ud64d" in start
    assert err.removesuffix(v1.STOPPED).isascii()


class _InterruptingProvider(FakeProvider):
    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        self.requests.append((request, provider))
        raise KeyboardInterrupt


def test_ctrl_c_during_an_llm_call_stops_the_bot_and_the_message_is_never_rerun(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _llm_config(home)
    provider = _InterruptingProvider()
    replies, err, _fake = _session(monkeypatch, capsys, provider, text(1, "점심 먹었어"), text(2, "/help"))
    assert replies == [] and len(provider.requests) == 1
    assert "chat 111: /llm_message interrupted by Ctrl+C; it will not be run again" in err.split("\n")
    assert v1._state(home)["handled_update_ids"] == [1]
    replies, _err, _fake = _session(monkeypatch, capsys, FakeProvider(), text(1, "점심 먹었어"))
    assert replies == []  # already handled: not interpreted again
