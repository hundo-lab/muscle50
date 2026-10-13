"""`muscle50 telegram history [--last N | --date YYYY-MM-DD] [--json]`: read-only, ASCII labels, the same
entries as `/history`. Temporary MUSCLE50_HOME and synthetic entries only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from muscle50.cli import main
from muscle50.domain.telegram_llm import history_entry
from muscle50.infrastructure.telegram.history_log import JsonlHistoryLog
from muscle50.presentation.telegram_llm_replies import history_text


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    return root


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(["telegram", "history", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


ENTRIES = [
    history_entry(
        update_id=5512,
        at="2026-10-11T21:00:00+09:00",
        chat_id=111,
        kind="text",
        text="안녕",
        intent="chat",
        provider="codex",
        provider_result="ok",
        reply="반가워요.",
    ),
    history_entry(
        update_id=5513,
        at="2026-10-12T12:31:05+09:00",
        chat_id=111,
        kind="photo",
        caption="저녁",
        photo="telegram/photos/2026-10/ab12cd.jpg",
        intent="meal_log",
        provider="claude",
        model="sonnet",
        provider_result="ok",
        llm_output={"interpret": {"intent": "meal_log"}},
        reply="이렇게 기록할까요? (저녁, 10-12, 사진 추정)\n1. 일반식",
        proposal="91c0",
    ),
    history_entry(
        update_id=5514,
        at="2026-10-12T12:32:00+09:00",
        chat_id=111,
        kind="confirm",
        text="/ok_91c0",
        reply="Recorded meal 2026-10-12-dinner-1.",
        proposal="91c0",
        result={"exit_code": 0, "meal_id": "2026-10-12-dinner-1"},
    ),
]


def _write(home: Path, entries: list[dict[str, Any]]) -> None:
    log = JsonlHistoryLog(home / "telegram" / "history")
    for entry in entries:
        log.append(entry)


def test_missing_history_creates_nothing(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    assert _run(capsys) == (0, "No Telegram history yet.\n", "")
    assert not home.exists()


def test_missing_history_json_is_empty_entries_and_creates_nothing(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, err = _run(capsys, "--json")
    assert (code, err) == (0, "")
    assert json.loads(out) == {"entries": []}
    assert not home.exists()
    # Byte-identical to what an existing but empty history directory prints.
    empty_home = tmp_path / "empty-home"
    (empty_home / "telegram" / "history").mkdir(parents=True)
    monkeypatch.setenv("MUSCLE50_HOME", str(empty_home))
    assert _run(capsys, "--json") == (0, out, "")


def test_text_uses_ascii_labels(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _write(home, ENTRIES)
    before = sorted(path.as_posix() for path in home.rglob("*"))
    code, out, _err = _run(capsys)
    assert code == 0
    assert out.split("\n") == [
        "2026-10-11 21:00 +09:00 chat 111 text intent=chat codex/default ok",
        "  user: 안녕",
        "  bot: 반가워요.",
        "2026-10-12 12:31 +09:00 chat 111 photo intent=meal_log claude/sonnet ok proposal=91c0",
        "  user: [photo] 저녁 (telegram/photos/2026-10/ab12cd.jpg)",
        "  bot: 이렇게 기록할까요? (저녁, 10-12, 사진 추정)",
        "       1. 일반식",
        "2026-10-12 12:32 +09:00 chat 111 confirm proposal=91c0 exit=0 meal=2026-10-12-dinner-1",
        "  user: /ok_91c0",
        "  bot: Recorded meal 2026-10-12-dinner-1.",
        "",
    ]
    assert sorted(path.as_posix() for path in home.rglob("*")) == before


def test_last_date_and_json(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _write(home, ENTRIES)
    code, out, _err = _run(capsys, "--last", "1", "--json")
    assert code == 0 and json.loads(out) == {"entries": ENTRIES[-1:]}
    assert out == json.dumps({"entries": ENTRIES[-1:]}, indent=2, ensure_ascii=True) + "\n"
    code, out, _err = _run(capsys, "--date", "2026-10-12", "--json")
    assert json.loads(out) == {"entries": ENTRIES[1:]}
    code, out, _err = _run(capsys, "--date", "2026-10-13")
    assert (code, out) == (0, "No Telegram history entries.\n")


def test_same_entries_as_bot_history(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _write(home, ENTRIES)
    _code, out, _err = _run(capsys, "--json")
    entries = json.loads(out)["entries"]
    assert entries == ENTRIES
    telegram = history_text(entries)
    assert telegram.split("\n\n")[1].split("\n") == [
        "10-12 12:31 사진 · 식사 기록 · claude sonnet",
        "나: [사진] 저녁 (telegram/photos/2026-10/ab12cd.jpg)",
        "bot: 이렇게 기록할까요? (저녁, 10-12, 사진 추정)",
        "1. 일반식",
    ]
    assert telegram.endswith("결과: 기록 2026-10-12-dinner-1")


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("--last", "0"), "오류: --last는 1에서 1000 사이여야 합니다.\n"),
        (("--last", "1001"), "오류: --last는 1에서 1000 사이여야 합니다.\n"),
        (("--date", "2026-13-01"), "오류: --date는 YYYY-MM-DD 형식이어야 합니다.\n"),
    ],
)
def test_bad_arguments_exit_1(capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], message: str) -> None:
    assert _run(capsys, *argv) == (1, "", message)


def test_last_and_date_are_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["telegram", "history", "--last", "2", "--date", "2026-10-12"])
    assert raised.value.code == 2


def test_unreadable_line_is_an_error(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    directory = home / "telegram" / "history"
    directory.mkdir(parents=True)
    (directory / "2026-10.jsonl").write_text("not json\n", encoding="utf-8")
    code, out, err = _run(capsys)
    assert (code, out) == (1, "") and err.startswith("오류: 대화 기록 파일의 1번째 줄을 읽을 수 없습니다")
