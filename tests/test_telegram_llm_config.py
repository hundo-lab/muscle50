"""`config\\telegram_llm.json` (feature switch and settings) and the bot's own LLM files: state, memory,
history, photos, coach guide, and the read-only food catalog reader. Temporary folders only."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.telegram_bot import TelegramStateError
from muscle50.domain.llm_settings import DEFAULT_SETTINGS, ProviderName, ProviderSettings
from muscle50.domain.nutrition import MealType, NutrientField, NutritionSourceType
from muscle50.domain.telegram_llm import (
    EMPTY_MEMORY,
    EMPTY_STATE,
    ChatMemory,
    ChatTurn,
    LlmState,
    MenuChoice,
    Proposal,
    ProposalKind,
    ProposalState,
    history_entry,
)
from muscle50.infrastructure.sqlite.food_catalog_reader import SqliteFoodCatalogReader
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository
from muscle50.infrastructure.telegram.coach_guide_file import CoachGuideFile
from muscle50.infrastructure.telegram.history_log import HistoryReadError, JsonlHistoryLog
from muscle50.infrastructure.telegram.llm_config_file import LlmConfigError, load_llm_settings
from muscle50.infrastructure.telegram.llm_memory_store import JsonLlmMemoryStore, LlmMemoryError
from muscle50.infrastructure.telegram.llm_state_store import JsonLlmStateStore
from muscle50.infrastructure.telegram.photo_store import PhotoStore


def _write(path: Path, document: Any, *, bom: bool = False) -> Path:
    text = json.dumps(document, ensure_ascii=False)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path


def test_absent_file_means_off_and_empty_object_means_defaults(tmp_path: Path) -> None:
    assert load_llm_settings(tmp_path / "telegram_llm.json") is None
    assert load_llm_settings(_write(tmp_path / "a.json", {})) == DEFAULT_SETTINGS
    assert load_llm_settings(_write(tmp_path / "b.json", {}, bom=True)) == DEFAULT_SETTINGS


def test_full_document_is_read(tmp_path: Path) -> None:
    document = {
        "provider": "codex",
        "claude": {"model": "haiku", "executable": None},
        "codex": {"model": "gpt-5.5", "executable": r"C:\Tools\codex.exe"},
        "persona": {"name": "코치", "tone": "반말, 짧게"},
        "timeout_seconds": 30,
        "fallback_provider": "claude",
        "keep_photos": False,
    }
    settings = load_llm_settings(_write(tmp_path / "c.json", document))
    assert settings is not None
    assert (settings.provider, settings.fallback_provider) == (ProviderName.CODEX, ProviderName.CLAUDE)
    assert settings.codex == ProviderSettings("gpt-5.5", r"C:\Tools\codex.exe")
    assert settings.claude == ProviderSettings("haiku", None)
    assert (settings.persona_name, settings.persona_tone, settings.timeout_seconds, settings.keep_photos) == (
        "코치",
        "반말, 짧게",
        30,
        False,
    )


SECRET = "sk-synthetic-should-never-be-echoed"


@pytest.mark.parametrize(
    "document",
    [
        {"provider": SECRET},
        {"provider": "claude", "fallback_provider": "claude"},
        {"claude": {"model": SECRET + " x"}},
        {"claude": {"executable": "relative\\" + SECRET}},
        {"claude": {"api_key": SECRET}},
        {"persona": {"name": "x" * 21}},
        {"persona": {"tone": "a\nb" + SECRET}},
        {"timeout_seconds": 5},
        {"timeout_seconds": True},
        {"keep_photos": "yes"},
        {"token": SECRET},
        [SECRET],
    ],
)
def test_invalid_settings_are_refused_without_echoing_values(tmp_path: Path, document: Any) -> None:
    with pytest.raises(LlmConfigError) as raised:
        load_llm_settings(_write(tmp_path / "x.json", document))
    assert SECRET not in str(raised.value)


def test_bad_json_and_encoding_are_refused(tmp_path: Path) -> None:
    (tmp_path / "j.json").write_bytes(b'{"provider": ' + SECRET.encode())
    with pytest.raises(LlmConfigError, match="line 1"):
        load_llm_settings(tmp_path / "j.json")
    (tmp_path / "e.json").write_bytes(b"\xff\xfe{}")
    with pytest.raises(LlmConfigError, match="UTF-8"):
        load_llm_settings(tmp_path / "e.json")


# --- state ---------------------------------------------------------------------------------------------


def _proposal(token: str = "a1b2") -> Proposal:
    return Proposal(
        token=token,
        chat_id=111,
        kind=ProposalKind.MENU,
        created_unix=100,
        expires_unix=3700,
        state=ProposalState.OPEN,
        argv_ok=("nutrition", "log", "--meal", "lunch", "--general", "--general-note=제육"),
        choices=(MenuChoice("한식 제육", ((NutrientField.CALORIES_KCAL, Decimal(700), Decimal("950.5")),), False),),
        meal_type=MealType.LUNCH,
        day=date(2026, 10, 12),
        source=NutritionSourceType.VISUAL_ESTIMATE,
        reference="ref",
        label="메뉴 캡처 추정",
    )


def test_state_round_trips_and_is_written_atomically(tmp_path: Path) -> None:
    store = JsonLlmStateStore(tmp_path / "config" / "telegram_llm_state.json")
    assert store.load() == EMPTY_STATE
    state = LlmState("codex", (_proposal(), _proposal("ffff").with_state(ProposalState.USED)))
    store.save(state)
    assert store.load() == state
    assert [path.name for path in (tmp_path / "config").iterdir()] == ["telegram_llm_state.json"]
    assert b"\r\n" not in (tmp_path / "config" / "telegram_llm_state.json").read_bytes()


@pytest.mark.parametrize("content", [b"{", b"[]", b'{"schema_version": 2, "provider_override": null, "proposals": []}'])
def test_damaged_state_stops_the_bot(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "s.json"
    path.write_bytes(content)
    with pytest.raises(TelegramStateError, match="telegram LLM 상태 파일이 올바르지 않습니다"):
        JsonLlmStateStore(path).load()


# --- memory --------------------------------------------------------------------------------------------


def test_memory_is_per_chat_and_forget_clears_one_chat(tmp_path: Path) -> None:
    store = JsonLlmMemoryStore(tmp_path / "m.json")
    assert store.get(111) == EMPTY_MEMORY
    memory = ChatMemory("요약", (ChatTurn(5, "나", "bot"),))
    store.put(111, memory)
    store.put(222, ChatMemory(None, ()))
    assert store.get(111) == memory
    store.clear(111)
    assert store.get(111) == EMPTY_MEMORY
    assert store.get(222) == ChatMemory(None, ())


def test_damaged_memory_is_an_error_and_forget_resets_it(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text("{oops", encoding="utf-8")
    store = JsonLlmMemoryStore(path)
    with pytest.raises(LlmMemoryError) as raised:
        store.get(111)
    assert "oops" not in str(raised.value)
    store.clear(111)
    assert store.get(111) == EMPTY_MEMORY


# --- history -------------------------------------------------------------------------------------------


def _entry(update_id: int, at: str) -> dict[str, Any]:
    return history_entry(update_id=update_id, at=at, chat_id=111, kind="text", text="점심 기록", reply="응답")


def test_history_appends_monthly_jsonl_and_reads_last_or_one_day(tmp_path: Path) -> None:
    log = JsonlHistoryLog(tmp_path / "telegram" / "history")
    assert log.read(last=5) == () and not (tmp_path / "telegram").exists()
    entries = [
        _entry(1, "2026-09-30T23:59:00+09:00"),
        _entry(2, "2026-10-01T08:00:00+09:00"),
        _entry(3, "2026-10-01T12:00:00+09:00"),
    ]
    for entry in entries:
        log.append(entry)
    assert sorted(path.name for path in (tmp_path / "telegram" / "history").iterdir()) == [
        "2026-09.jsonl",
        "2026-10.jsonl",
    ]
    assert log.read(last=2) == tuple(entries[1:])
    assert log.read(day=date(2026, 10, 1)) == tuple(entries[1:])
    line = (tmp_path / "telegram" / "history" / "2026-09.jsonl").read_bytes()
    assert line.isascii() and line.endswith(b"\n") and list(json.loads(line)) == list(entries[0])


def test_unreadable_history_line_is_an_error(tmp_path: Path) -> None:
    directory = tmp_path / "h"
    directory.mkdir()
    (directory / "2026-10.jsonl").write_text('{"v": 1}\n', encoding="utf-8")
    with pytest.raises(HistoryReadError, match="1번째 줄"):
        JsonlHistoryLog(directory).read(last=5)


# --- photos and the coach guide ------------------------------------------------------------------------


def test_photos_are_content_addressed_and_written_once(tmp_path: Path) -> None:
    store = PhotoStore(tmp_path, tmp_path / "telegram" / "photos")
    photo = b"\xff\xd8\xffsynthetic"
    first = store.keep(photo, date(2026, 10, 12))
    assert first.startswith("telegram/photos/2026-10/") and first.endswith(".jpg")
    assert store.keep(photo, date(2026, 10, 12)) == first
    assert (tmp_path / first).read_bytes() == photo
    assert len(list((tmp_path / "telegram" / "photos" / "2026-10").iterdir())) == 1


def test_coach_guide_missing_too_long_or_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "telegram_llm_coach.md"
    assert CoachGuideFile(path).read() == (None, None)
    path.write_bytes("\ufeff# 코치\n저녁은 든든하게".encode())
    assert CoachGuideFile(path).read() == ("# 코치\n저녁은 든든하게", None)
    path.write_text("x" * 4001, encoding="utf-8")
    assert CoachGuideFile(path).read() == (None, "longer than 4000 characters")
    path.write_bytes(b"\xff\xfe")
    assert CoachGuideFile(path).read() == (None, "not UTF-8")


# --- read-only food catalog ----------------------------------------------------------------------------


def test_catalog_reader_creates_nothing_and_matches_the_repository(tmp_path: Path) -> None:
    database = tmp_path / "db" / "muscle50.sqlite3"
    reader = SqliteFoodCatalogReader(database)
    assert (reader.get("x"), reader.search("x")) == (None, ())
    assert not (tmp_path / "db").exists()
    repository = SqliteFoodNutritionRepository(database)
    repository.migrate()
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO nutrition_food_profiles (profile_id, name) VALUES ('rice', '햇반')")
    connection.execute("INSERT INTO nutrition_food_profile_aliases (profile_id, alias) VALUES ('rice', 'Rice')")
    connection.commit()
    connection.close()
    # Like SqliteNutritionReader, a mode=ro read of a WAL database may add the -wal/-shm files; it writes no row.
    found, by_name, by_alias = reader.get("rice"), reader.search("햇반"), reader.search("rice")
    assert found == repository.get("rice")
    assert by_alias == repository.search("rice") == by_name


def test_catalog_reader_on_a_database_without_nutrition_tables(tmp_path: Path) -> None:
    database = tmp_path / "old.sqlite3"
    sqlite3.connect(database).close()
    assert SqliteFoodCatalogReader(database).search("햇반") == ()
