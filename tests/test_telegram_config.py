"""`config\\telegram.json` (user-written) and `config\\telegram_state.json` (owned by `telegram run`).

Strict reading with exact error texts that never echo the token or a value; atomic state writes.
Temporary directories and synthetic values only.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.telegram_bot import HandledUpdates, TelegramStateError
from muscle50.infrastructure.telegram.config_file import TelegramConfig, TelegramConfigError, load_telegram_config
from muscle50.infrastructure.telegram.state_store import JsonHandledUpdateStore

TOKEN = "123456789:AAFakeSyntheticToken_ab-cd"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("no network in tests"))


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)
    return path


def _config(tmp_path: Path, document: Any) -> Path:
    return _write(tmp_path / "config" / "telegram.json", json.dumps(document))


def test_valid_config_is_loaded_and_the_token_is_hidden_from_repr(tmp_path: Path) -> None:
    path = _config(tmp_path, {"bot_token": TOKEN, "allowed_chat_ids": [111, -100222]})
    config = load_telegram_config(path)
    assert config == TelegramConfig(TOKEN, frozenset({111, -100222}))
    assert TOKEN not in repr(config)
    assert TOKEN not in str(config)


def test_a_notepad_bom_is_accepted(tmp_path: Path) -> None:
    content = json.dumps({"bot_token": TOKEN, "allowed_chat_ids": [111]}).encode("utf-8")
    path = _write(tmp_path / "telegram.json", b"\xef\xbb\xbf" + content)
    assert load_telegram_config(path).allowed_chat_ids == frozenset({111})


CONFIG_CASES: list[tuple[str, Any, str]] = [
    ("not utf-8", b"\xff\xfe{}", "telegram 설정 파일이 UTF-8이 아닙니다: {path}"),
    (
        "bad json",
        '{\n  "bot_token": "' + TOKEN + '",\n  "allowed_chat_ids": [111,]\n}',
        "telegram 설정 파일이 올바른 JSON이 아닙니다: {path} (line 3, column 28)",
    ),
    ("not an object", "[]", "telegram 설정 파일에는 bot_token과 allowed_chat_ids 두 key만 있어야 합니다: {path}"),
    (
        "missing key",
        {"bot_token": TOKEN},
        "telegram 설정 파일에는 bot_token과 allowed_chat_ids 두 key만 있어야 합니다: {path}",
    ),
    (
        "extra key",
        {"bot_token": TOKEN, "allowed_chat_ids": [1], "debug": True},
        "telegram 설정 파일에는 bot_token과 allowed_chat_ids 두 key만 있어야 합니다: {path}",
    ),
    (
        "token not a string",
        {"bot_token": 123, "allowed_chat_ids": [1]},
        "bot_token은 BotFather가 준 token 문자열(숫자:문자)이어야 합니다.",
    ),
    (
        "token placeholder",
        {"bot_token": "<BotFather가 준 token>", "allowed_chat_ids": [1]},
        "bot_token은 BotFather가 준 token 문자열(숫자:문자)이어야 합니다.",
    ),
    (
        "token with space",
        {"bot_token": TOKEN + " ", "allowed_chat_ids": [1]},
        "bot_token은 BotFather가 준 token 문자열(숫자:문자)이어야 합니다.",
    ),
    (
        "ids not a list",
        {"bot_token": TOKEN, "allowed_chat_ids": 111},
        "allowed_chat_ids는 chat id 정수의 목록이어야 합니다.",
    ),
    (
        "ids empty",
        {"bot_token": TOKEN, "allowed_chat_ids": []},
        "allowed_chat_ids가 비어 있습니다. 허용할 chat id를 하나 이상 넣으세요.",
    ),
    (
        "id quoted",
        {"bot_token": TOKEN, "allowed_chat_ids": [111, "222"]},
        "allowed_chat_ids의 2번째 값은 따옴표 없는 정수여야 합니다.",
    ),
    (
        "id bool",
        {"bot_token": TOKEN, "allowed_chat_ids": [True]},
        "allowed_chat_ids의 1번째 값은 따옴표 없는 정수여야 합니다.",
    ),
    (
        "id float",
        {"bot_token": TOKEN, "allowed_chat_ids": [1.0]},
        "allowed_chat_ids의 1번째 값은 따옴표 없는 정수여야 합니다.",
    ),
    (
        "id duplicate",
        {"bot_token": TOKEN, "allowed_chat_ids": [111, 222, 111]},
        "allowed_chat_ids에 같은 chat id가 두 번 있습니다: 111",
    ),
]


@pytest.mark.parametrize(("case", "content", "message"), CONFIG_CASES, ids=[case[0] for case in CONFIG_CASES])
def test_invalid_config_has_an_exact_error_without_the_token(
    tmp_path: Path, case: str, content: Any, message: str
) -> None:
    path = tmp_path / "config" / "telegram.json"
    _write(path, content if isinstance(content, (str, bytes)) else json.dumps(content))
    with pytest.raises(TelegramConfigError) as raised:
        load_telegram_config(path)
    assert str(raised.value) == message.format(path=path)
    assert TOKEN not in str(raised.value)
    assert raised.value.__cause__ is None


def test_missing_and_unreadable_config(tmp_path: Path) -> None:
    missing = tmp_path / "config" / "telegram.json"
    with pytest.raises(TelegramConfigError) as raised:
        load_telegram_config(missing)
    assert str(raised.value) == (
        f'telegram 설정 파일이 없습니다: {missing}. docs/telegram-bot.md의 "설정"대로 만드세요.'
    )
    directory = tmp_path / "config" / "is_a_directory.json"
    directory.mkdir(parents=True)
    with pytest.raises(TelegramConfigError) as raised:
        load_telegram_config(directory)
    assert str(raised.value).startswith(f"telegram 설정 파일을 읽을 수 없습니다: {directory} (")


# --- state file ---------------------------------------------------------------------------------


def test_missing_state_is_none_and_load_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "config" / "telegram_state.json"
    assert JsonHandledUpdateStore(path).load() is None
    assert not (tmp_path / "config").exists()


def test_state_document_is_exact_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config" / "telegram_state.json"
    store = JsonHandledUpdateStore(path)
    store.save(HandledUpdates(1234567890, (5500, 5501)))
    assert path.read_bytes() == (
        b'{\n  "schema_version": 1,\n  "bot_id": 1234567890,\n  "handled_update_ids": [\n    5500,\n    5501\n  ]\n}\n'
    )
    assert store.load() == HandledUpdates(1234567890, (5500, 5501))
    assert [item.name for item in path.parent.iterdir()] == ["telegram_state.json"]


def _state_error(path: Path, reason: str) -> str:
    return (
        f"telegram 상태 파일이 올바르지 않습니다: {path} ({reason}). telegram run이 만드는 파일입니다. "
        "지우고 다시 시작해도 됩니다(bot 시작 전에 보낸 메시지는 실행하지 않습니다)."
    )


STATE_CASES: list[tuple[str, Any, str]] = [
    ("not utf-8", b"\xff", "not UTF-8"),
    ("bad json", "{", "not valid JSON: line 1, column 2"),
    (
        "extra key",
        {"schema_version": 1, "bot_id": 1, "handled_update_ids": [], "x": 1},
        "expected exactly the keys schema_version, bot_id and handled_update_ids",
    ),
    ("version", {"schema_version": 2, "bot_id": 1, "handled_update_ids": []}, "unsupported schema_version 2"),
    ("bot id", {"schema_version": 1, "bot_id": "1", "handled_update_ids": []}, "bot_id must be an integer"),
    (
        "ids type",
        {"schema_version": 1, "bot_id": 1, "handled_update_ids": [1, "2"]},
        "handled_update_ids must be a list of at most 100 distinct integers",
    ),
    (
        "ids duplicate",
        {"schema_version": 1, "bot_id": 1, "handled_update_ids": [1, 1]},
        "handled_update_ids must be a list of at most 100 distinct integers",
    ),
    (
        "ids too many",
        {"schema_version": 1, "bot_id": 1, "handled_update_ids": list(range(101))},
        "handled_update_ids must be a list of at most 100 distinct integers",
    ),
]


@pytest.mark.parametrize(("case", "content", "reason"), STATE_CASES, ids=[case[0] for case in STATE_CASES])
def test_corrupt_state_is_an_exact_error(tmp_path: Path, case: str, content: Any, reason: str) -> None:
    path = tmp_path / "config" / "telegram_state.json"
    _write(path, content if isinstance(content, (str, bytes)) else json.dumps(content))
    with pytest.raises(TelegramStateError) as raised:
        JsonHandledUpdateStore(path).load()
    assert str(raised.value) == _state_error(path, reason)


def test_failed_replace_keeps_the_old_state_and_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config" / "telegram_state.json"
    store = JsonHandledUpdateStore(path)
    store.save(HandledUpdates(1, (10,)))
    before = path.read_bytes()

    def fail(source: object, target: object) -> None:
        raise PermissionError(13, "synthetic denial")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(TelegramStateError) as raised:
        store.save(HandledUpdates(1, (10, 11)))
    assert str(raised.value) == (
        f"telegram 상태 파일을 쓸 수 없습니다: {path} (synthetic denial). 명령은 실행하지 않았습니다."
    )
    assert path.read_bytes() == before
    assert [item.name for item in path.parent.iterdir()] == ["telegram_state.json"]
    monkeypatch.undo()
    assert store.load() == HandledUpdates(1, (10,))
