"""Telegram LLM v2.5 end to end: failure replies by reason, `/retry_<id>`, the 60-minute purge, the usage-limit note
and the history tail. A fake Bot API and fake providers or fake CLI runners only (never the real `claude`/`codex`,
never the network), a temporary MUSCLE50_HOME and synthetic values. Covers AC1, AC2 and part of AC3/AC7 of
docs/specs/telegram-llm-failures-and-meals.md.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
from test_llm_failure_reason import codex_error
from test_telegram_llm_argv import FakeRunner, claude_ok
from test_telegram_llm_domain import interpretation

import muscle50.cli as cli
from muscle50.application.llm_provider import LlmAttempt, LlmCallResult, LlmRequest
from muscle50.application.telegram_bot import IncomingMessage, IncomingUpdate, TelegramUnavailableError
from muscle50.cli import main
from muscle50.domain.llm_failure import (
    RETRY_EXPIRED_TEXT,
    RETRY_UNKNOWN_TEXT,
    RETRY_USED_TEXT,
    FailureReason,
    failure_text,
    retry_line,
)
from muscle50.domain.llm_settings import LlmSettings, ProviderName
from muscle50.domain.telegram_commands import UsageReply, parse_bot_message, usage_reply_text
from muscle50.domain.telegram_llm import ProposalKind, ProposalState
from muscle50.domain.telegram_llm_prompt import PHOTO_DOWNLOAD_FAILED_TEXT, PROVIDER_FAILED_TEXT
from muscle50.infrastructure.llm.provider import TEMP_PREFIX, CliLlmProvider
from muscle50.infrastructure.telegram.llm_state_store import JsonLlmStateStore

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
KST = bot.KST
CODEX = ProviderName.CODEX
CLAUDE = ProviderName.CLAUDE
ALLOWED = bot.ALLOWED
OTHER_CHAT = 222
SENTINEL = "SENTINEL-cli-text-91fe"
LUNCH_TEXT = "점심 닭가슴살 1팩 햇반 1개 먹었어"
STATE = Path("config") / "telegram_llm_state.json"


class ReasonProvider:
    """Answers each call with the next scripted item: a document, or `(outcome, reason)` for a failure."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[LlmRequest, ProviderName]] = []

    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        self.requests.append((request, provider))
        response = self.responses.pop(0)
        if isinstance(response, tuple):
            outcome, reason = response
            attempt = LlmAttempt(provider, "gpt-6.1-sol", outcome, 1.0, reason=reason)
            return LlmCallResult(provider, "gpt-6.1-sol", outcome, None, 1.0, False, (attempt,))
        document = request.validate(response)
        attempt = LlmAttempt(provider, "gpt-6.1-sol", "ok", 1.0)
        return LlmCallResult(provider, "gpt-6.1-sol", "ok", document, 1.0, False, (attempt,))


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def timestamp(self) -> int:
        return int(self.now.timestamp())


class TimedApi(bot.FakeApi):
    """A `timedelta` in the script moves the clock and polls empty (the bot then runs its idle step)."""

    def __init__(self, clock: Clock, *batches: Sequence[IncomingUpdate] | timedelta, fail_downloads: int = 0) -> None:
        super().__init__()
        self.batches = list(batches)  # type: ignore[arg-type]
        self.clock = clock
        self.fail_downloads = fail_downloads

    def get_updates(self, offset: int | None, timeout_s: int) -> tuple[IncomingUpdate, ...]:
        if self.batches and isinstance(self.batches[0], timedelta):
            self.clock.now += self.batches.pop(0)  # type: ignore[operator]
            return ()
        return super().get_updates(offset, timeout_s)

    def download_photo(self, file_id: str, max_bytes: int) -> bytes:
        self.downloads.append(file_id)
        if self.fail_downloads:
            self.fail_downloads -= 1
            raise TelegramUnavailableError("synthetic download failure")
        return bot.PHOTO


def _empty_config(root: Path, document: dict[str, Any] | None = None) -> None:
    """`{}`: the v2.5 defaults (Codex, gpt-6.1-sol)."""
    (root / "config" / "telegram_llm.json").write_text(json.dumps(document or {}), encoding="utf-8", newline="\n")


def _text(update_id: int, body: str, clock: Clock, *, chat: int = ALLOWED) -> IncomingUpdate:
    return IncomingUpdate(update_id, IncomingMessage(chat, body, clock.timestamp()))


def _photo(update_id: int, clock: Clock, caption: str | None = None) -> IncomingUpdate:
    message = IncomingMessage(ALLOWED, None, clock.timestamp(), photo_file_id="file-1", photo_size=100, caption=caption)
    return IncomingUpdate(update_id, message)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: Any,
    clock: Clock,
    *batches: Sequence[IncomingUpdate] | timedelta,
    fail_downloads: int = 0,
) -> tuple[list[str], str, TimedApi]:
    monkeypatch.setattr(cli, "_now", lambda: clock.now)
    fake = TimedApi(clock, *batches, fail_downloads=fail_downloads)
    if isinstance(provider, FakeRunner):
        counter = iter(range(100))

        def make_temp_dir() -> str:
            path = Path(os.environ["MUSCLE50_HOME"]).parent / "llm-temp" / f"{TEMP_PREFIX}{next(counter)}"
            path.mkdir(parents=True)
            return str(path)

        def factory(settings: LlmSettings, executables: Any, log: Callable[[str], None]) -> CliLlmProvider:
            return CliLlmProvider(
                settings, executables, provider, log=log, environ={"PATH": "x"}, make_temp_dir=make_temp_dir
            )

        monkeypatch.setattr(cli, "_llm_provider", factory)
    else:
        bot._install(monkeypatch, provider)
    v1._install(monkeypatch, fake)
    code = main(["telegram", "run"])
    captured = capsys.readouterr()
    assert code == 130, captured.err
    assert captured.out == ""
    return [bot._plain(message) for _, message in fake.sent], captured.err, fake


def _in_state(root: Path, text: str) -> bool:
    """Whether ``text`` is anywhere in the state file (written with `ensure_ascii`)."""
    raw = (root / STATE).read_text(encoding="utf-8")
    return json.dumps(text, ensure_ascii=True)[1:-1] in raw or text in raw


def _proposals(root: Path) -> tuple[Any, ...]:
    return JsonLlmStateStore(root / STATE).load().proposals


def _start() -> Clock:
    return Clock(bot.NOW)


# --- failure replies by reason (AC1) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "outcome"),
    [
        (FailureReason.NETWORK, "failed"),
        (FailureReason.USAGE_LIMIT, "failed"),
        (FailureReason.LOGIN, "bad_output"),
        (FailureReason.TIMEOUT, "timeout"),
        (FailureReason.NOT_FOUND, "not_found"),
        (FailureReason.OTHER, "failed"),
    ],
)
def test_each_reason_gives_its_reply_and_history_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    reason: FailureReason,
    outcome: str,
) -> None:
    bot._catalog(capsys)
    _empty_config(home)
    before = bot._tables(home)
    clock = _start()
    provider = ReasonProvider((outcome, reason))
    replies, err, _fake = _run(monkeypatch, capsys, provider, clock, [_text(1, LUNCH_TEXT, clock)])
    body = failure_text(reason, CODEX, other_tried=False) or PROVIDER_FAILED_TEXT
    assert replies == [f"{body}\n{retry_line('7f3a')}"]
    assert provider.requests[0][1] is CODEX  # v2.5: the default provider is codex
    entry = bot._history(home)[0]
    assert (entry["provider_result"], entry["failure_reason"], entry["retry_of"]) == (outcome, reason.value, None)
    assert bot._tables(home) == before
    (retry,) = _proposals(home)
    assert (retry.kind, retry.state, retry.retry_text) == (ProposalKind.RETRY, ProposalState.OPEN, LUNCH_TEXT)
    assert f"chat {ALLOWED}: retry 7f3a offered ({reason.value})" in err


def test_usage_limit_after_trying_the_other_provider_says_wait() -> None:
    assert failure_text(FailureReason.USAGE_LIMIT, CLAUDE, other_tried=True) == (
        "Claude 사용 한도에 걸려 해석하지 못했습니다. 한도가 풀린 뒤 다시 보내세요."
    )


def test_the_cli_text_never_appears_anywhere(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home, {"fallback_on_usage_limit": False})
    clock = _start()
    runner = FakeRunner(codex_error(f"ERROR: workspace routing discovery failed {SENTINEL}"))
    replies, err, _fake = _run(monkeypatch, capsys, runner, clock, [_text(1, "점심 김밥 한 줄", clock)])
    network = failure_text(FailureReason.NETWORK, CODEX, other_tried=False)
    assert replies == [f"{network}\n{retry_line('7f3a')}"]
    assert SENTINEL not in err and SENTINEL not in "".join(replies)
    for path in home.rglob("*"):
        if path.is_file() and path.suffix in (".jsonl", ".json", ".log"):
            assert SENTINEL not in path.read_text(encoding="utf-8"), path
    entry = bot._history(home)[0]
    assert entry["text"] == "점심 김밥 한 줄" and entry["failure_reason"] == "network"
    assert "reason network" in err


def test_a_usage_limit_goes_to_claude_and_the_reply_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    _empty_config(home)
    clock = _start()
    runner = FakeRunner(codex_error("ERROR: You've hit your usage limit."), claude_ok(bot.LUNCH_MEAL))
    replies, err, _fake = _run(monkeypatch, capsys, runner, clock, [_text(1, LUNCH_TEXT, clock)])
    body = replies[0].split("\n")
    assert body[0] == "이렇게 기록할까요? (점심, 10-06)"
    assert "(Codex 사용 한도라 이번에는 claude(Anthropic)로 처리했습니다.)" in body
    assert body[-1] == "기록: /ok_7f3a   취소: /no_7f3a"
    assert "trying fallback claude" in err
    entry = bot._history(home)[0]
    assert entry["failure_reason"] is None and [item["provider"] for item in entry["attempts"]] == ["codex", "claude"]


def test_a_failed_suggestion_offers_a_retry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home)
    clock = _start()
    suggest = interpretation(intent="menu_suggest", items=[], meal_type="dinner", tense="none")
    provider = ReasonProvider(suggest, ("timeout", FailureReason.TIMEOUT))
    replies, _err, _fake = _run(monkeypatch, capsys, provider, clock, [_text(1, "저녁 뭐 먹지?", clock)])
    assert replies == [f"{failure_text(FailureReason.TIMEOUT, CODEX, other_tried=False)}\n{retry_line('7f3a')}"]


# --- /retry_ (AC2) ---------------------------------------------------------------------------------------


def test_retry_runs_the_message_once_more_and_nothing_is_written_before_ok(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    _empty_config(home)
    before = bot._tables(home)
    clock = _start()
    provider = ReasonProvider(("failed", FailureReason.NETWORK), bot.LUNCH_MEAL)
    replies, err, _fake = _run(
        monkeypatch,
        capsys,
        provider,
        clock,
        [_text(1, LUNCH_TEXT, clock)],
        [_text(2, "/retry_7f3a", clock)],
        [_text(3, "/retry_7f3a", clock)],
    )
    assert replies[1].split("\n")[0] == "이렇게 기록할까요? (점심, 10-06)"
    assert replies[1].split("\n")[-1] == "기록: /ok_91c0   취소: /no_91c0"
    assert replies[2] == RETRY_USED_TEXT
    assert len(provider.requests) == 2 and LUNCH_TEXT in provider.requests[1][0].prompt
    assert bot._tables(home) == before  # a proposal only
    retry, meal = _proposals(home)
    assert (retry.state, retry.retry_text, retry.has_retry_payload) == (ProposalState.USED, None, False)
    assert (meal.kind, meal.state) == (ProposalKind.MEAL, ProposalState.OPEN)
    history = bot._history(home)
    assert [(entry["kind"], entry["text"], entry["retry_of"]) for entry in history] == [
        ("text", LUNCH_TEXT, None),
        ("text", LUNCH_TEXT, "7f3a"),
        ("retry", "/retry_7f3a", None),
    ]
    assert f"chat {ALLOWED}: retry 7f3a used" in err
    # `telegram history` shows the reason and the retry token.
    heads = [line for line in v1._ok(capsys, "telegram", "history").split("\n") if not line.startswith(" ")]
    assert heads[0].endswith(f"chat {ALLOWED} text codex/gpt-6.1-sol failed reason=network")
    assert heads[1].endswith("proposal=91c0 retry_of=7f3a")


def test_history_reply_names_the_failure_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home)
    clock = _start()
    provider = ReasonProvider(("failed", FailureReason.LOGIN))
    replies, _err, _fake = _run(
        monkeypatch, capsys, provider, clock, [_text(1, "점심 김밥", clock)], [_text(2, "/history 1", clock)]
    )
    assert replies[1].split("\n")[0] == "10-06 12:00 문장 · codex gpt-6.1-sol · 실패 이유: 로그인 필요"


def test_a_photo_retry_downloads_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home, {"keep_photos": False})
    clock = _start()
    photo_meal = interpretation(photo_kind="meal_photo", items=[bot._item("김밥", 1, "serving", kind="general")])
    provider = ReasonProvider(("failed", FailureReason.NETWORK), photo_meal)
    replies, _err, fake = _run(
        monkeypatch, capsys, provider, clock, [_photo(1, clock, "점심")], [_text(2, "/retry_7f3a", clock)]
    )
    assert replies[0] == f"{failure_text(FailureReason.NETWORK, CODEX, other_tried=False)}\n{retry_line('7f3a')}"
    assert fake.downloads == ["file-1", "file-1"]
    assert replies[1].split("\n")[0] == "이렇게 기록할까요? (점심, 10-06, 사진 추정)"
    assert [request.photo for request, _provider in provider.requests] == [bot.PHOTO, bot.PHOTO]
    assert bot._history(home)[1]["retry_of"] == "7f3a"


def test_a_photo_that_did_not_arrive_offers_a_retry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home, {"keep_photos": False})
    clock = _start()
    photo_meal = interpretation(photo_kind="meal_photo", items=[bot._item("김밥", 1, "serving", kind="general")])
    provider = ReasonProvider(photo_meal)
    replies, _err, fake = _run(
        monkeypatch,
        capsys,
        provider,
        clock,
        [_photo(1, clock)],
        [_text(2, "/retry_7f3a", clock)],
        fail_downloads=1,
    )
    assert replies[0] == f"{PHOTO_DOWNLOAD_FAILED_TEXT}\n{retry_line('7f3a')}"
    assert fake.downloads == ["file-1", "file-1"]
    assert replies[1].startswith("이렇게 기록할까요?")
    assert len(provider.requests) == 1


def test_retry_refusals_write_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    v1._configure(home, {"bot_token": bot.TOKEN, "allowed_chat_ids": [ALLOWED, OTHER_CHAT]})
    bot._catalog(capsys)
    _empty_config(home)
    before = bot._tables(home)
    clock = _start()
    provider = ReasonProvider(("failed", FailureReason.NETWORK))
    replies, _err, _fake = _run(
        monkeypatch,
        capsys,
        provider,
        clock,
        [_text(1, LUNCH_TEXT, clock)],
        [_text(2, "/retry_7f3a", clock, chat=OTHER_CHAT)],
        [_text(3, "/retry_0000", clock)],
    )
    assert replies[1:] == [RETRY_UNKNOWN_TEXT, RETRY_UNKNOWN_TEXT]
    assert len(provider.requests) == 1
    assert bot._tables(home) == before
    (retry,) = _proposals(home)
    assert (retry.state, retry.retry_text) == (ProposalState.OPEN, LUNCH_TEXT)


def test_ok_and_no_on_a_retry_token_are_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home)
    clock = _start()
    provider = ReasonProvider(("failed", FailureReason.NETWORK))
    replies, _err, _fake = _run(
        monkeypatch,
        capsys,
        provider,
        clock,
        [_text(1, "점심 김밥", clock)],
        [_text(2, "/ok_7f3a", clock)],
        [_text(3, "/no_7f3a", clock)],
    )
    assert replies[1:] == ["이 명령은 이 제안에 쓸 수 없습니다."] * 2
    assert _proposals(home)[0].state is ProposalState.OPEN


def test_after_60_minutes_the_message_is_gone_from_the_state_file_and_retry_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home)
    clock = _start()
    provider = ReasonProvider(("failed", FailureReason.NETWORK))
    replies, err, _fake = _run(
        monkeypatch,
        capsys,
        provider,
        clock,
        [_photo(1, clock, "점심 김밥 먹음")],
        timedelta(minutes=60),
        [_text(2, "/retry_7f3a", clock)],
    )
    assert replies[1] == RETRY_EXPIRED_TEXT
    assert not _in_state(home, "점심 김밥 먹음") and not _in_state(home, "file-1")
    (retry,) = _proposals(home)
    assert (retry.retry_text, retry.retry_caption, retry.retry_file_ids, retry.retry_album) == (None, None, (), 0)
    assert "llm retry: expired messages removed" in err


def test_an_expired_retry_message_is_removed_at_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home)
    clock = _start()
    provider = ReasonProvider(("failed", FailureReason.NETWORK))
    _run(monkeypatch, capsys, provider, clock, [_text(1, "점심 김밥", clock)])
    assert _in_state(home, "점심 김밥")
    clock.now += timedelta(hours=2)
    _run(monkeypatch, capsys, ReasonProvider(), clock)
    assert not _in_state(home, "점심 김밥")


def test_a_retry_after_midnight_records_the_day_it_was_first_sent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    _empty_config(home)
    clock = Clock(datetime(2026, 10, 6, 23, 27, tzinfo=KST))
    provider = ReasonProvider(("failed", FailureReason.NETWORK), {**bot.LUNCH_MEAL, "meal_type": None})
    replies, _err, _fake = _run(
        monkeypatch,
        capsys,
        provider,
        clock,
        [_text(1, LUNCH_TEXT, clock)],
        timedelta(minutes=43),
        [_text(2, "/retry_7f3a", clock)],
    )
    head = replies[1].split("\n")
    assert head[0] == "이렇게 기록할까요? (저녁, 10-06)" and head[1] == "(끼니: 지금 시각 기준)"
    meal = _proposals(home)[1]
    assert meal.day.isoformat() == "2026-10-06" and "2026-10-06" in meal.argv_ok


def test_the_llm_off_bot_answers_retry_like_any_unknown_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fake = bot.FakeApi([bot.text(1, "/retry_7f3a")])
    v1._install(monkeypatch, fake)
    assert main(["telegram", "run"]) == 130
    capsys.readouterr()
    parsed = parse_bot_message("/retry_7f3a", bot_username=v1.IDENTITY.username, today=bot.TODAY)
    assert isinstance(parsed, UsageReply)
    assert fake.replies() == [usage_reply_text(parsed)]
    assert not (home / STATE).exists()


def test_startup_line_names_the_codex_default_and_the_usage_limit_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _empty_config(home)
    _replies, err, _fake = _run(monkeypatch, capsys, ReasonProvider(), _start())
    assert "telegram llm: on, provider codex, fallback none, usage-limit fallback on, timeout 90 s" in err
    _empty_config(home, {"provider": "claude", "fallback_on_usage_limit": False})
    _replies, err, _fake = _run(monkeypatch, capsys, ReasonProvider(), _start())
    assert "telegram llm: on, provider claude, fallback none, usage-limit fallback off, timeout 90 s" in err
