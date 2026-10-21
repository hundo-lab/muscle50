"""AC1 of docs/specs/telegram-llm-reliability.md: photos of one album become one LLM call and one proposal.

`muscle50 telegram run` with a fake Bot API that accepts the album's short poll and a fake LLM provider (never the
real `claude`/`codex`, never the network), a temporary MUSCLE50_HOME and synthetic foods only.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
import test_telegram_llm_corrections_bot as corrections
from test_telegram_llm_domain import interpretation

from muscle50.application.telegram_bot import (
    ALBUM_MAX_PHOTOS,
    ALBUM_MAX_WAIT_S,
    ALBUM_POLL_TIMEOUT_S,
    BotIdentity,
    IncomingMessage,
    IncomingUpdate,
    LlmReply,
    RunTelegramBot,
    TelegramUnavailableError,
)
from muscle50.cli import main
from muscle50.domain.llm_failure import retry_line
from muscle50.domain.telegram_commands import stale_text
from muscle50.domain.telegram_llm_prompt import PHOTO_DOWNLOAD_FAILED_TEXT, PHOTO_TOO_LARGE_TEXT

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network, no real sleep
_isolated = v1.sleeps

PARTIAL = "사진 5장 중 4장만 읽었습니다"


def data_of(file_id: str) -> bytes:
    return bot.PHOTO + file_id.encode("ascii")


class AlbumApi(bot.FakeApi):
    """The bot tests' fake Bot API, but it answers the album's 2 s poll. Each `get_updates` takes the next scripted
    batch (an Exception is raised); when the script is empty it raises Ctrl+C like the base fake."""

    def __init__(self, *batches: Sequence[IncomingUpdate] | Exception, broken: frozenset[str] = frozenset()) -> None:
        super().__init__()
        self.batches = list(batches)
        self.timeouts: list[int] = []
        self.broken = broken

    def get_updates(self, offset: int | None, timeout_s: int) -> tuple[IncomingUpdate, ...]:
        self.timeouts.append(timeout_s)
        self.calls.append("getUpdates")
        self.offsets.append(offset)
        if not self.batches:
            raise KeyboardInterrupt
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return tuple(batch)

    def download_photo(self, file_id: str, max_bytes: int) -> bytes:
        self.downloads.append(file_id)
        if file_id in self.broken:
            raise TelegramUnavailableError("network error (synthetic)")
        return data_of(file_id)


def member(
    update_id: int,
    *,
    group: str | None = "g1",
    caption: str | None = None,
    chat: int = bot.ALLOWED,
    sent: int = bot.NOW_TS,
    **fields: Any,
) -> IncomingUpdate:
    message = IncomingMessage(
        chat,
        None,
        sent,
        photo_file_id=fields.pop("photo_file_id", f"file-{update_id}"),
        photo_size=100,
        caption=caption,
        media_group_id=group,
        **fields,
    )
    return IncomingUpdate(update_id, message)


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: bot.FakeProvider,
    *batches: Sequence[IncomingUpdate] | Exception,
    broken: frozenset[str] = frozenset(),
) -> tuple[list[str], str, AlbumApi]:
    fake = AlbumApi(*batches, broken=broken)
    bot._install(monkeypatch, provider)
    v1._install(monkeypatch, fake)
    code = main(["telegram", "run"])
    captured = capsys.readouterr()
    assert code == 130, captured.err
    return [bot._plain(message) for _, message in fake.sent], captured.err, fake


LUNCH_PHOTO = bot.meal(
    bot._item("닭가슴살", 1, "pack"), bot._item("햇반", 1, "pack"), photo_kind="meal_photo", memory_summary="점심 사진"
)


def prepare(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)


def handled_ids(home: Path) -> list[int]:
    state = json.loads((home / "config" / "telegram_state.json").read_text(encoding="utf-8"))
    return list(state["handled_update_ids"])


# --- one call for the album ---------------------------------------------------------------------------------


def test_two_photos_of_one_group_are_one_call_with_both_photos_and_the_album_caption(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    # Telegram puts the caption on one photo of the album: here the second one.
    replies, _err, fake = run(monkeypatch, capsys, provider, [member(1), member(2, caption="점심 먹었어")], [])
    assert len(provider.requests) == 1
    request, _chosen = provider.requests[0]
    assert (request.photo, request.extra_photos) == (data_of("file-1"), (data_of("file-2"),))
    assert request.prompt.endswith("[메시지]\n점심 먹었어\n(사진 2장 첨부)\n")
    assert len(replies) == 1 and replies[0].startswith("이렇게 기록할까요? (점심, 10-06, 사진 추정)")
    assert PARTIAL not in replies[0] and "사진 2장 중" not in replies[0]
    assert fake.downloads == ["file-1", "file-2"]
    # The album's poll is the short one; the normal polls keep their timeout.
    assert fake.timeouts == [10, ALBUM_POLL_TIMEOUT_S, 10]
    assert fake.offsets == [None, 3, 3]
    assert handled_ids(home) == [2, 1]  # every member id, remembered before the album runs
    assert len(bot._history(home)) == 1


def test_a_single_photo_keeps_its_prompt_and_has_no_extra_photos(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    bot._session(monkeypatch, capsys, provider, bot.photo(1, "점심 먹었어"))
    request, _chosen = provider.requests[0]
    assert request.extra_photos == () and request.prompt.endswith("[메시지]\n점심 먹었어\n(사진 첨부)\n")


def test_an_album_whose_other_members_never_arrive_is_a_single_photo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    replies, _err, fake = run(monkeypatch, capsys, provider, [member(1, caption="점심 먹었어")], [])
    request, _chosen = provider.requests[0]
    assert request.extra_photos == () and request.prompt.endswith("(사진 첨부)\n")
    assert replies[0].startswith("이렇게 기록할까요?") and fake.downloads == ["file-1"]
    assert handled_ids(home) == [1]


def test_the_cap_reads_four_photos_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    members = [member(index, caption="점심 먹었어" if index == 1 else None) for index in range(1, 6)]
    replies, _err, fake = run(monkeypatch, capsys, provider, members)
    request, _chosen = provider.requests[0]
    assert 1 + len(request.extra_photos) == ALBUM_MAX_PHOTOS == 4
    assert fake.downloads == ["file-1", "file-2", "file-3", "file-4"]
    assert "(사진 4장 첨부)" in request.prompt
    assert PARTIAL in replies[0]
    # inside the <pre> body, before the tappable commands, and in the history reply too
    assert fake.sent[0][1].index(PARTIAL) < fake.sent[0][1].index("</pre>")
    assert PARTIAL in bot._history(home)[0]["reply"]
    assert fake.timeouts == [10, 10]  # four photos in hand: no extra poll
    assert handled_ids(home) == [2, 3, 4, 5, 1]  # all five members are remembered


def test_two_groups_stay_separate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO, LUNCH_PHOTO)
    batch = [
        member(1, group="a", caption="점심 먹었어"),
        member(2, group="b", caption="점심 먹었어"),
        member(3, group="a"),
    ]
    batch.append(member(4, group="b"))
    replies, _err, _fake = run(monkeypatch, capsys, provider, batch, [], [])
    assert len(provider.requests) == 2
    first, second = (request for request, _chosen in provider.requests)
    assert (first.photo, first.extra_photos) == (data_of("file-1"), (data_of("file-3"),))
    assert (second.photo, second.extra_photos) == (data_of("file-2"), (data_of("file-4"),))
    assert len(replies) == 2


def test_a_redelivered_album_is_not_run_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    album = [member(1, caption="점심 먹었어"), member(2)]
    provider = bot.FakeProvider(LUNCH_PHOTO)
    run(monkeypatch, capsys, provider, album, [])
    assert len(provider.requests) == 1
    again = bot.FakeProvider()
    replies, _err, fake = run(monkeypatch, capsys, again, album, [])
    assert again.requests == [] and replies == [] and fake.downloads == []
    # one member redelivered on its own is a known id too
    replies, _err, fake = run(monkeypatch, capsys, bot.FakeProvider(), [member(2)])
    assert replies == [] and fake.downloads == []


# --- the rules of one photo hold for every member ----------------------------------------------------------


def test_a_stale_member_is_not_part_of_the_album(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    old = bot.NOW_TS - 3600
    provider = bot.FakeProvider(LUNCH_PHOTO)
    replies, _err, fake = run(
        monkeypatch, capsys, provider, [member(1, caption="점심 먹었어"), member(2, sent=old)], []
    )
    request, _chosen = provider.requests[0]
    assert request.extra_photos == () and fake.downloads == ["file-1"]
    assert replies[0].startswith("이렇게 기록할까요?")
    from datetime import UTC, datetime

    assert replies[1] == stale_text(datetime.fromtimestamp(old, UTC).astimezone())


def test_a_too_large_member_is_dropped_and_counted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    large = member(2, photo_file_id=None, photo_too_large=True)
    replies, _err, fake = run(monkeypatch, capsys, provider, [member(1, caption="점심 먹었어"), large], [])
    request, _chosen = provider.requests[0]
    assert request.extra_photos == () and fake.downloads == ["file-1"]
    assert "사진 2장 중 1장만 읽었습니다" in replies[0]


def test_an_album_of_only_large_photos_gets_the_fixed_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider()
    batch = [member(index, photo_file_id=None, photo_too_large=True) for index in (1, 2)]
    replies, _err, fake = run(monkeypatch, capsys, provider, batch, [])
    assert replies == [PHOTO_TOO_LARGE_TEXT] and provider.requests == [] and fake.downloads == []
    assert handled_ids(home) == [2, 1]


def test_a_member_from_another_chat_is_not_taken(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    batch = [member(1, caption="점심 먹었어"), member(2, chat=v1.OTHER), member(3)]
    replies, err, fake = run(monkeypatch, capsys, provider, batch, [])
    request, _chosen = provider.requests[0]
    assert request.extra_photos == (data_of("file-3"),) and fake.downloads == ["file-1", "file-3"]
    assert "ignored message from chat 987654321 (not in allowed_chat_ids)" in err and len(replies) == 1


def test_a_chat_that_is_not_allowed_never_starts_an_album(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    fake_batches = [[member(1, chat=v1.OTHER), member(2, chat=v1.OTHER)]]
    replies, err, fake = run(monkeypatch, capsys, bot.FakeProvider(), *fake_batches)
    assert replies == [] and fake.timeouts == [10, 10]  # no short poll
    assert err.count("ignored message from chat 987654321") == 2


def test_a_member_that_cannot_be_downloaded_is_dropped_and_counted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    replies, err, _fake = run(
        monkeypatch,
        capsys,
        provider,
        [member(1, caption="점심 먹었어"), member(2)],
        [],
        broken=frozenset({"file-2"}),
    )
    request, _chosen = provider.requests[0]
    assert request.extra_photos == () and "사진 2장 중 1장만 읽었습니다" in replies[0]
    assert "chat 111: photo download failed (network error (synthetic))" in err


def test_an_album_whose_photos_all_fail_to_download_gets_the_download_failed_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider()
    replies, _err, _fake = run(
        monkeypatch, capsys, provider, [member(1), member(2)], [], broken=frozenset({"file-1", "file-2"})
    )
    # v2.5: no photo arrived at all, so `/retry_` is offered (it downloads the same photos again).
    assert replies == [f"{PHOTO_DOWNLOAD_FAILED_TEXT}\n{retry_line('7f3a')}"] and provider.requests == []


def test_a_failing_album_poll_still_uses_the_members_in_hand(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    replies, err, _fake = run(
        monkeypatch,
        capsys,
        provider,
        [member(1, caption="점심 먹었어"), member(2)],
        TelegramUnavailableError("network error (synthetic)"),
    )
    request, _chosen = provider.requests[0]
    assert request.extra_photos == (data_of("file-2"),) and len(replies) == 1
    assert "chat 111: album poll failed (TelegramUnavailableError)" in err


def test_a_later_member_arrives_in_the_poll(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    provider = bot.FakeProvider(LUNCH_PHOTO)
    replies, _err, fake = run(
        monkeypatch, capsys, provider, [member(1, caption="점심 먹었어")], [member(2), member(3)], []
    )
    request, _chosen = provider.requests[0]
    assert request.extra_photos == (data_of("file-2"), data_of("file-3")) and len(replies) == 1
    assert fake.timeouts == [10, 2, 2, 10] and fake.offsets == [None, 2, 4, 4]


# --- order within a batch -------------------------------------------------------------------------------------


def test_the_album_is_handled_where_its_first_member_is_and_the_rest_follow_in_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)

    def chat(reply: str) -> dict[str, Any]:
        return interpretation(intent="chat", items=[], tense="none", reply=reply, memory_summary="잡담")

    provider = bot.FakeProvider(chat("먼저"), LUNCH_PHOTO, chat("그다음"), chat("마지막"))
    before = bot.text(1, "안녕")
    batch = [before, member(2, caption="점심 먹었어"), bot.text(3, "둘째"), member(4)]
    replies, _err, _fake = run(monkeypatch, capsys, provider, batch, [bot.text(5, "마지막")], [])
    assert replies[0] == "먼저"
    assert replies[1].startswith("이렇게 기록할까요?")
    assert replies[2:] == ["그다음", "마지막"]
    request = provider.requests[1][0]
    assert request.extra_photos == (data_of("file-4"),)


# --- the re-ask and the memory ---------------------------------------------------------------------------------


def test_the_numeric_re_ask_sends_the_same_photos(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    plain = corrections.label_photo(from_label=False)  # a single value that is not a label: checked and asked again
    provider = bot.FakeProvider(plain, plain)
    run(monkeypatch, capsys, provider, [member(1, caption="아침으로 삼각김밥 먹음"), member(2)], [])
    assert len(provider.requests) == 2
    first, second = (request for request, _chosen in provider.requests)
    assert (
        (second.photo, second.extra_photos)
        == (first.photo, first.extra_photos)
        == (
            data_of("file-1"),
            (data_of("file-2"),),
        )
    )
    assert "(사진 2장 첨부)" in second.prompt and "range_is_a_point" in second.prompt


def test_the_memory_keeps_the_album_as_one_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)
    menu = dict(corrections.STEW_MENU)
    run(monkeypatch, capsys, bot.FakeProvider(menu), [member(1, caption="점심 메뉴"), member(2)], [])
    document = json.loads((home / "config" / "telegram_llm_memory.json").read_text(encoding="utf-8"))
    (turn,) = document["chats"][str(bot.ALLOWED)]["turns"]
    assert turn["user"] == "[사진 2장] 점심 메뉴 → 메뉴 캡처로 읽음: 항목 2개"


def test_a_failed_read_of_an_album_uses_the_album_caption(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home, {"keep_photos": False})
    replies, _err, _fake = run(
        monkeypatch, capsys, bot.FakeProvider("bad_output"), [member(1), member(2, caption="점심 먹었어")], []
    )  # v2.5: a timeout has its own reply now; reason `other` keeps the v2.4 caption rule
    assert replies[0].startswith("사진을 해석하지 못했습니다. 일반식으로만 기록할까요?")
    replies, _err, _fake = run(monkeypatch, capsys, bot.FakeProvider("bad_output"), [member(3), member(4)], [])
    assert replies == [
        '사진을 해석하지 못했습니다. 사진에 "메뉴" 또는 "먹음"이라고 적어 다시 보내 주세요.\n' + retry_line("91c0")
    ]


# --- LLM off: the old loop --------------------------------------------------------------------------------------


def test_with_the_llm_off_an_album_is_separate_photos_and_the_polls_are_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fake = v1.FakeTelegramApi([member(1, caption="점심 먹었어"), member(2), member(3)])
    code, err = v1._run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert fake.offsets == [None, 4]  # one batch, then the next normal poll: no album polls
    assert len(fake.sent) == 3 and "album" not in err
    assert handled_ids(home) == [1, 2, 3]


# --- the collector in isolation (injected clock) -----------------------------------------------------------------


class StubLlm:
    def __init__(self) -> None:
        self.messages: list[tuple[int, IncomingMessage]] = []

    def handle(self, chat_id: int, update_id: int, message: IncomingMessage, bot_username: str) -> LlmReply:
        self.messages.append((update_id, message))
        return LlmReply(("<pre>ok</pre>",))


class Memory:
    def load(self) -> None:
        return None

    def save(self, handled: object) -> None:
        return None


class ScriptedPolls:
    def __init__(self, *batches: Sequence[IncomingUpdate]) -> None:
        self.batches = list(batches)
        self.calls: list[tuple[int | None, int]] = []
        self.sent: list[str] = []

    def get_me(self) -> BotIdentity:
        return v1.IDENTITY

    def webhook_is_set(self) -> bool:
        return False

    def get_updates(self, offset: int | None, timeout_s: int) -> tuple[IncomingUpdate, ...]:
        self.calls.append((offset, timeout_s))
        if not self.batches:
            raise KeyboardInterrupt
        return tuple(self.batches.pop(0))

    def send_message(self, chat_id: int, html: str) -> None:
        self.sent.append(html)


def _direct(api: ScriptedPolls, times: list[float]) -> StubLlm:
    llm = StubLlm()
    clock = iter(times)
    RunTelegramBot(
        api,
        Memory(),
        object(),  # type: ignore[arg-type]
        allowed_chat_ids=frozenset({bot.ALLOWED}),
        today=lambda: None,  # type: ignore[arg-type,return-value]
        pending_migrations=lambda: (),
        format_reply=lambda text: [text],
        summaries=None,  # type: ignore[arg-type]
        unknown_sets=lambda activity_id: None,
        log=lambda line: None,
        sleep=lambda seconds: None,
        clock=lambda: next(clock),
        llm=llm,
    ).execute()
    return llm


def test_collection_stops_after_the_maximum_wait_on_the_injected_clock() -> None:
    # clock calls: started_at (0), the deadline (100 -> 106), then one per loop check
    # three more members are scripted; the third must be left for the normal poll, which ignores it (other chat)
    polls = [[member(2)], [member(3)], [member(4, chat=v1.OTHER)]]
    api = ScriptedPolls([member(1, sent=100)], *polls)
    llm = _direct(api, [100.0, 100.0, 101.0, 104.0, 107.0])
    assert ALBUM_MAX_WAIT_S == 6
    assert [timeout for _offset, timeout in api.calls[1:3]] == [2, 2] and api.calls[3][1] == 10
    ((update_id, message),) = llm.messages
    assert (update_id, message.album_members) == (1, 3)


def test_no_more_polls_once_four_photos_are_in_hand() -> None:
    api = ScriptedPolls([member(index, sent=100) for index in range(1, 5)])
    llm = _direct(api, [100.0, 100.0, 100.0])
    assert [timeout for _offset, timeout in api.calls] == [10, 10]
    ((_update_id, message),) = llm.messages
    assert message.photo_file_ids == ("file-1", "file-2", "file-3", "file-4")


# --- the adapter reads the group id -------------------------------------------------------------------------------


def test_the_adapter_reads_the_media_group_id_as_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.request

    from muscle50.infrastructure.telegram.bot_api import UrllibTelegramBotApi

    photo = [{"file_id": "a", "file_size": 10, "width": 5, "height": 5}]
    base = {"chat": {"id": 111}, "date": 1_790_000_000, "photo": photo}
    result = [
        {"update_id": 1, "message": {**base, "media_group_id": "13579"}},
        {"update_id": 2, "message": {**base, "media_group_id": 13579}},
        {"update_id": 3, "message": {**base, "media_group_id": ""}},
        {"update_id": 4, "message": base},
    ]
    body = json.dumps({"ok": True, "result": result}).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: io.BytesIO(body))
    updates = UrllibTelegramBotApi(v1.TOKEN).get_updates(None, 10)
    groups = [update.message.media_group_id if update.message is not None else "none" for update in updates]
    assert groups == ["13579", None, None, None]
    assert updates[0].message is not None and updates[0].message.photo_file_ids == ()  # filled by the collector only
