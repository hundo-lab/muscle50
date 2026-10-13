"""Telegram LLM v2: free text and photos to proposals, coach answers and menu rankings.

Pipeline for one allowed, fresh message (the bot has already saved its update id):

- `/ok_`, `/plain_`, `/no_`, `/eat_` and `/llm`, `/memory`, `/forget`, `/history` are handled here;
  every other command returns None and goes to the v1 parser unchanged.
- Non-command text and photos go to the LLM (`LlmProvider`), which only extracts and phrases. Its
  JSON is validated (`domain/telegram_llm.py`), foods are linked only by exact catalog lookup, dates
  come from the bot, and the result is a *proposal*: nothing is written before `/ok_<token>`, which
  runs the stored argv once (marked used first; refused while a migration is pending, without
  consuming it). Answers to questions pass the number guard or are replaced by the existing replies.
- Every exchange is appended to the history and the chat memory; their write failures are logged
  and the bot goes on. The state file (proposals) failing stops the bot (`TelegramStateError`).

Console lines are ASCII and never contain message text, LLM output or URLs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from decimal import Decimal
from typing import Any, Protocol

from muscle50.application.food_lookup import FoodLookup, ResolveFoodReference
from muscle50.application.llm_provider import LlmCallResult, LlmProvider, LlmRequest, SchemaName
from muscle50.application.nutrition_logging import (
    NutritionLoggingError,
    format_general_estimate,
    local_day_bounds,
)
from muscle50.application.telegram_bot import (
    PHOTO_MAX_BYTES,
    CliCommandRunner,
    CommandOutcome,
    IncomingMessage,
    LlmAction,
    LlmReply,
    ReplySummaries,
    RunConfirmed,
    SummaryUnavailableError,
    TelegramUnavailableError,
)
from muscle50.domain.llm_number_guard import allowed_numbers, unknown_numbers
from muscle50.domain.llm_settings import PROVIDER_COMPANIES, LlmSettings, ProviderName
from muscle50.domain.llm_today_totals import TodayTotals, amount_text, today_totals, totals_text
from muscle50.domain.menu_ranking import UNREADABLE, KcalContext, MenuRanking, RankItem, kcal_context, rank_menu
from muscle50.domain.nutrition import (
    Meal,
    MealType,
    NutrientField,
    NutritionSourceType,
    QuantityUnit,
    is_reserved_food_reference,
)
from muscle50.domain.telegram_commands import (
    MIGRATION_STATUS_UNKNOWN_TEXT,
    CliInvocation,
    ReplyKind,
    help_text,
    pending_migration_text,
    usage_text,
)
from muscle50.domain.telegram_llm import (
    EMPTY_MEMORY,
    PROPOSAL_TTL_S,
    ChatMemory,
    EditAction,
    Intent,
    Interpretation,
    ItemKind,
    LlmCommand,
    LlmState,
    MenuChoice,
    NutrientRanges,
    PhotoKind,
    Proposal,
    ProposalCommand,
    ProposalKind,
    ProposalState,
    SuggestCategory,
    SuggestResult,
    Tense,
    Topic,
    clean_memo,
    estimate_source,
    history_entry,
    meal_slot_for,
    memory_block,
    parse_answer,
    parse_interpretation,
    parse_llm_command,
    parse_suggestions,
    prune_proposals,
    remember,
    resolve_date_expression,
)
from muscle50.domain.telegram_llm_prompt import (
    CANCELLED_TEXT,
    COMMAND_ARGUMENT_TEXT,
    DATE_OTHER_TEXT,
    DOCUMENT_IMAGE_TEXT,
    EDIT_NO_MEAL_TEXT,
    EDIT_UNCLEAR_TEXT,
    FORGET_TEXT,
    HISTORY_USAGE_TEXT,
    LLM_USAGE_TEXT,
    MEAL_NAMES,
    MEMORY_EMPTY_TEXT,
    MEMORY_HEAD_TEXT,
    MENU_EMPTY_TEXT,
    MENU_NUMBER_UNKNOWN_TEXT,
    MENU_SLOT_UNKNOWN_TEXT,
    PHOTO_DOWNLOAD_FAILED_TEXT,
    PHOTO_KIND_UNCLEAR_TEXT,
    PHOTO_TOO_LARGE_TEXT,
    PLANNED_TEXT,
    PROPOSAL_CANCELLED_TEXT,
    PROPOSAL_EXPIRED_TEXT,
    PROPOSAL_NO_PLAIN_TEXT,
    PROPOSAL_UNKNOWN_TEXT,
    PROPOSAL_USED_TEXT,
    PROPOSAL_WRONG_KIND_TEXT,
    PROVIDER_FAILED_TEXT,
    QUESTION_TOPICS_TEXT,
    UNCLEAR_TEXT,
    PromptTask,
    build_prompt,
    llm_status_text,
    provider_default_text,
    provider_switched_text,
)

HISTORY_DEFAULT = 5
HISTORY_MAX = 20
_RECORDED_MEAL = re.compile(r"Recorded meal (\S+)\.")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TOPIC_COMMANDS = {Topic.TRAINING: "/today", Topic.NUTRITION: "/status", Topic.BODY: "/inbody"}
_CATEGORY_NAMES = {
    SuggestCategory.EATING_OUT: "외식",
    SuggestCategory.DELIVERY: "배달",
    SuggestCategory.CONVENIENCE_STORE: "편의점",
    SuggestCategory.HOME: "집밥",
}


# --- ports -----------------------------------------------------------------------------------------------


class TelegramFileApi(Protocol):
    def download_photo(self, file_id: str, max_bytes: int) -> bytes: ...


class MealsOfDay(Protocol):
    def list_eaten_between(self, start_inclusive: datetime, end_exclusive: datetime) -> tuple[Meal, ...]: ...


class ProposalStore(Protocol):
    def load(self) -> LlmState: ...

    def save(self, state: LlmState) -> None: ...


class MemoryStore(Protocol):
    def get(self, chat_id: int) -> ChatMemory: ...

    def put(self, chat_id: int, memory: ChatMemory) -> None: ...

    def clear(self, chat_id: int) -> None: ...


class HistoryLog(Protocol):
    def append(self, entry: dict[str, Any]) -> None: ...

    def read(self, *, last: int | None = None, day: date | None = None) -> tuple[dict[str, Any], ...]: ...


class PhotoKeeper(Protocol):
    def keep(self, data: bytes, day: date) -> str: ...


class CoachGuide(Protocol):
    def read(self) -> tuple[str | None, str | None]: ...


@dataclass(frozen=True)
class ReplyText:
    body: str
    """Sent in `<pre>`."""
    commands: tuple[str, ...] = ()
    """Lines after the body, outside `<pre>`, so `/ok_...` commands can be tapped."""

    def plain(self) -> str:
        return "\n".join([self.body, *self.commands]) if self.commands else self.body


@dataclass(frozen=True)
class ProposalItemView:
    text: str
    quantity_estimated: bool
    reason: str | None
    estimate: NutrientRanges


@dataclass(frozen=True)
class MealProposalView:
    token: str
    meal_type: MealType
    day: date
    label: str | None
    slot_from_time: bool
    duplicates: tuple[str, ...]
    items: tuple[ProposalItemView, ...]
    dropped: tuple[str, ...]
    plain: bool
    failed_photo: bool = False


@dataclass(frozen=True)
class MenuLineView:
    title: str
    kcal: tuple[Decimal, Decimal] | None
    protein: tuple[Decimal, Decimal] | None
    printed_kcal: bool
    printed_protein: bool
    label: str | None
    note: str | None


@dataclass(frozen=True)
class MenuView:
    token: str
    meal_type: MealType
    suggestion: bool
    ranking: MenuRanking
    protein_remaining: str | None
    kcal_budget: str | None
    totals: str | None
    lead: str | None
    lines: tuple[MenuLineView, ...]


@dataclass(frozen=True)
class EditView:
    token: str
    change: str
    command: str


class LlmReplies(Protocol):
    """Presentation of the LLM layer's data-driven replies (fixed texts live in the domain)."""

    def messages(self, reply: ReplyText) -> list[str]: ...

    def proposal(self, view: MealProposalView) -> ReplyText: ...

    def menu(self, view: MenuView) -> ReplyText: ...

    def edit(self, view: EditView) -> ReplyText: ...

    def candidates(self, meal_ids: Sequence[str]) -> ReplyText: ...

    def history(self, entries: Sequence[dict[str, Any]]) -> ReplyText: ...


@dataclass
class _Exchange:
    """What one message produced, for the reply, the history line and the memory."""

    reply: ReplyText | None = None
    messages: tuple[str, ...] | None = None
    """Ready HTML (the fallback summaries); `reply` then holds what the history shows."""
    intent: str | None = None
    calls: list[LlmCallResult] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    proposal: str | None = None
    summary: str | None = None


class TelegramLlmHandler:
    def __init__(
        self,
        *,
        provider: LlmProvider,
        files: TelegramFileApi,
        catalog: FoodLookup,
        meals: MealsOfDay,
        proposals: ProposalStore,
        memory: MemoryStore,
        history: HistoryLog,
        photos: PhotoKeeper | None,
        coach: CoachGuide,
        commands: CliCommandRunner,
        pending_migrations: Callable[[], tuple[int, ...] | None],
        summaries: ReplySummaries,
        replies: LlmReplies,
        settings: LlmSettings,
        now: Callable[[], datetime],
        local_timezone: Callable[[date], tzinfo],
        new_token: Callable[[], str],
        log: Callable[[str], None],
    ) -> None:
        self._provider = provider
        self._files = files
        self._catalog = catalog
        self._meals = meals
        self._proposals = proposals
        self._memory = memory
        self._history = history
        self._photos = photos
        self._coach = coach
        self._commands = commands
        self._pending_migrations = pending_migrations
        self._summaries = summaries
        self._replies = replies
        self._settings = settings
        self._now = now
        self._local_timezone = local_timezone
        self._new_token = new_token
        self._log = log

    # --- entry ----------------------------------------------------------------------------------------

    def handle(self, chat_id: int, update_id: int, message: IncomingMessage, bot_username: str) -> LlmAction | None:
        text = message.text
        if text is not None and text.lstrip().startswith("/"):
            command = parse_llm_command(text.strip(), bot_username=bot_username)
            if command is None:
                return None
            if isinstance(command, ProposalCommand):
                return self._proposal_command(chat_id, update_id, command)
            return self._llm_command(chat_id, command)
        if text is not None:
            return self._message(chat_id, update_id, text=text, photo=None, caption=None, photo_path=None)
        if message.document_image:
            return self._fixed_photo_reply(chat_id, update_id, message, DOCUMENT_IMAGE_TEXT)
        if message.photo_too_large:
            return self._fixed_photo_reply(chat_id, update_id, message, PHOTO_TOO_LARGE_TEXT)
        if message.photo_file_id is None:
            return None
        try:
            photo = self._files.download_photo(message.photo_file_id, PHOTO_MAX_BYTES)
        except TelegramUnavailableError as exc:
            self._log(f"chat {chat_id}: photo download failed ({exc})")
            return self._fixed_photo_reply(chat_id, update_id, message, PHOTO_DOWNLOAD_FAILED_TEXT)
        path = None
        if self._photos is not None:
            try:
                path = self._photos.keep(photo, self._today())
            except OSError as exc:
                self._log(f"chat {chat_id}: photo not kept ({type(exc).__name__})")
        return self._message(chat_id, update_id, text=None, photo=photo, caption=message.caption, photo_path=path)

    # --- free text and photos ------------------------------------------------------------------------------

    def _message(
        self,
        chat_id: int,
        update_id: int,
        *,
        text: str | None,
        photo: bytes | None,
        caption: str | None,
        photo_path: str | None,
    ) -> LlmAction:
        words = text if text is not None else (caption or "")
        exchange = _Exchange()
        call = self._call(chat_id, SchemaName.INTERPRET, PromptTask.INTERPRET, words, photo, (), parse_interpretation)
        exchange.calls.append(call)
        if not call.ok:
            if photo is not None:
                self._photo_failed_proposal(chat_id, exchange)
            else:
                exchange.reply = ReplyText(PROVIDER_FAILED_TEXT)
        else:
            interpretation: Interpretation = call.document
            exchange.outputs["interpret"] = interpretation.document
            exchange.summary = interpretation.memory_summary
            exchange.intent = interpretation.intent.value
            if photo is not None:
                self._photo(chat_id, words, photo, interpretation, exchange)
            else:
                self._text(chat_id, words, interpretation, exchange)
        assert exchange.reply is not None
        user = text if text is not None else f"[사진] {caption or ''}".rstrip()
        self._record(
            chat_id,
            exchange,
            update_id=update_id,
            kind="text" if photo is None else "photo",
            text=text,
            caption=caption,
            photo=photo_path,
        )
        self._remember_turn(chat_id, user, exchange)
        messages = exchange.messages if exchange.messages is not None else tuple(self._replies.messages(exchange.reply))
        return LlmReply(messages)

    def _text(self, chat_id: int, words: str, interpretation: Interpretation, exchange: _Exchange) -> None:
        intent = interpretation.intent
        if intent is Intent.MEAL_LOG:
            if interpretation.tense is Tense.PLANNED:
                exchange.reply = ReplyText(PLANNED_TEXT)
                return
            self._meal_proposal(chat_id, interpretation, exchange, photo_digest=None)
        elif intent is Intent.MEAL_EDIT:
            self._edit(chat_id, interpretation, exchange)
        elif intent is Intent.QUESTION:
            self._question(chat_id, words, interpretation, exchange)
        elif intent in (Intent.MENU_SUGGEST, Intent.MENU):
            self._suggest(chat_id, words, interpretation, exchange)
        elif intent is Intent.CHAT:
            reply = interpretation.reply
            if reply is None or unknown_numbers(reply, allowed_numbers([])):
                self._log(f"chat {chat_id}: llm chat reply had numbers or was empty; sent the help")
                exchange.reply = ReplyText(help_text(True))
            else:
                exchange.reply = ReplyText(reply)
        else:
            exchange.reply = ReplyText(f"{UNCLEAR_TEXT}\n\n{help_text(True)}")

    def _photo(
        self, chat_id: int, words: str, photo: bytes, interpretation: Interpretation, exchange: _Exchange
    ) -> None:
        kind = interpretation.photo_kind
        if kind is PhotoKind.MEAL_PHOTO:
            self._meal_proposal(chat_id, interpretation, exchange, photo_digest=_digest(photo))
        elif kind is PhotoKind.MENU_CAPTURE:
            self._menu_capture(chat_id, interpretation, exchange, photo_digest=_digest(photo))
        else:
            exchange.reply = ReplyText(PHOTO_KIND_UNCLEAR_TEXT)

    def _fixed_photo_reply(self, chat_id: int, update_id: int, message: IncomingMessage, text: str) -> LlmAction:
        exchange = _Exchange(reply=ReplyText(text))
        self._record(chat_id, exchange, update_id=update_id, kind="photo", caption=message.caption)
        return LlmReply(tuple(self._replies.messages(ReplyText(text))))

    # --- meal proposals -------------------------------------------------------------------------------------

    def _meal_proposal(
        self, chat_id: int, interpretation: Interpretation, exchange: _Exchange, *, photo_digest: str | None
    ) -> None:
        day = resolve_date_expression(interpretation.date_expression, self._today())
        if day is None:
            exchange.reply = ReplyText(DATE_OTHER_TEXT)
            return
        meal_type = interpretation.meal_type
        slot_from_time = meal_type is None
        if meal_type is None:
            meal_type = meal_slot_for(self._now().time())
        source = estimate_source(photo_digest is not None)
        reference = self._reference(exchange.calls[-1], photo_digest)
        entries: list[_Entry] = []
        dropped: list[str] = []
        for item in interpretation.items:
            if photo_digest is None and item.kind is ItemKind.CATALOG:
                entry, reason = self._catalog_entry(item.food_text, item.quantity, item.unit, item.quantity_estimated)
                if entry is None:
                    dropped.append(reason or "")
                    continue
                if entry.food_id is None:
                    entry = _Entry(None, None, None, entry.memo, item.estimate, False, reason)
                entries.append(entry)
            else:
                memo = clean_memo(item.memo or item.food_text)
                entries.append(_Entry(None, None, None, memo, item.estimate, False, None))
        if not entries:
            reasons = "\n".join(dropped) if dropped else ""
            exchange.reply = ReplyText("\n".join(part for part in (reasons, usage_text("log")) if part))
            return
        label = "사진 추정" if photo_digest is not None else None
        self._store_meal_proposal(
            chat_id, exchange, day, meal_type, entries, dropped, source, reference, label, slot_from_time
        )

    def _catalog_entry(
        self, food_text: str, quantity: Decimal | None, unit: QuantityUnit | None, quantity_estimated: bool
    ) -> tuple[_Entry | None, str | None]:
        """A catalog entry, a general entry (food_id None) with the reason, or (None, dropped reason)."""
        amount = f" {amount_text(quantity)} {unit.value}" if quantity is not None and unit is not None else ""
        general = _Entry(None, None, None, clean_memo(f"{food_text}{amount}"), (), False, None)
        if is_reserved_food_reference(food_text):
            return general, "카탈로그에 없음"
        try:
            food_id = ResolveFoodReference(self._catalog).execute(food_text, label="")
        except NutritionLoggingError:
            return general, "이름이 여러 음식에 맞음"
        if food_id is None:
            return general, "카탈로그에 없음"
        if quantity is None or unit is None:
            return general, "수량·단위를 말하지 않음"
        profile = self._catalog.get(food_id)
        if profile is None:
            return general, "카탈로그에 없음"
        if all(profile.preferred_fact(unit, nutrient) is None for nutrient in NutrientField):
            units = ", ".join(sorted({fact.basis_unit.value for fact in profile.facts})) or "없음"
            return None, (
                f"빠짐: {profile.name} {amount_text(quantity)} {unit.value} - 이 음식은 {units} 기준 값만 있습니다"
                f"(단위 변환 없음). 1 {unit.value} 값을 등록: muscle50 nutrition food fact add {profile.profile_id} "
                f"--per 1 {unit.value} ... --new-unit"
            )
        text = f"{profile.name} ({profile.profile_id}) {amount_text(quantity)} {unit.value}"
        return _Entry(profile.profile_id, quantity, unit, text, (), quantity_estimated, None), None

    def _store_meal_proposal(
        self,
        chat_id: int,
        exchange: _Exchange,
        day: date,
        meal_type: MealType,
        entries: Sequence[_Entry],
        dropped: Sequence[str],
        source: NutritionSourceType,
        reference: str,
        label: str | None,
        slot_from_time: bool,
        *,
        failed_photo: bool = False,
    ) -> None:
        duplicates = self._existing_meals(chat_id, day, meal_type)
        head = ("nutrition", "log", "--date", day.isoformat(), "--meal", meal_type.value)
        tail = ("--additional",) if duplicates else ()
        argv_ok = (*head, *(arg for entry in entries for arg in entry.argv(source, reference, True)), *tail)
        has_estimate = any(entry.estimate for entry in entries)
        argv_plain = (*head, *(arg for entry in entries for arg in entry.argv(source, reference, False)), *tail)
        proposal = self._new_proposal(
            chat_id,
            ProposalKind.MEAL,
            argv_ok=argv_ok,
            argv_plain=argv_plain if has_estimate else (),
            meal_type=meal_type,
            day=day,
        )
        exchange.proposal = proposal.token
        items = tuple(
            ProposalItemView(entry.display(), entry.quantity_estimated, entry.reason, entry.estimate)
            for entry in entries
        )
        view = MealProposalView(
            proposal.token,
            meal_type,
            day,
            label,
            slot_from_time,
            duplicates,
            items,
            tuple(dropped),
            has_estimate,
            failed_photo,
        )
        exchange.reply = self._replies.proposal(view)

    def _photo_failed_proposal(self, chat_id: int, exchange: _Exchange) -> None:
        meal_type = meal_slot_for(self._now().time())
        entry = _Entry(None, None, None, None, (), False, None)
        self._store_meal_proposal(
            chat_id,
            exchange,
            self._today(),
            meal_type,
            [entry],
            [],
            NutritionSourceType.VISUAL_ESTIMATE,
            "",
            None,
            True,
            failed_photo=True,
        )

    def _existing_meals(self, chat_id: int, day: date, meal_type: MealType) -> tuple[str, ...]:
        try:
            meals = self._meals.list_eaten_between(*local_day_bounds(day, self._local_timezone(day)))
        except Exception as exc:  # a missing or unreadable DB: `nutrition log` itself refuses a duplicate
            self._log(f"chat {chat_id}: existing meals not read ({type(exc).__name__})")
            return ()
        return tuple(meal.meal_id for meal in meals if meal.meal_type is meal_type)

    # --- menus (captures and suggestions) ----------------------------------------------------------------

    def _menu_capture(
        self, chat_id: int, interpretation: Interpretation, exchange: _Exchange, *, photo_digest: str
    ) -> None:
        visible = interpretation.slots_visible
        slot = interpretation.meal_type
        if slot is None:
            if len(visible) == 1:
                slot = visible[0]
            else:
                by_time = meal_slot_for(self._now().time())
                if visible and by_time not in visible:
                    exchange.reply = ReplyText(MENU_SLOT_UNKNOWN_TEXT)
                    return
                slot = by_time
        items = [item for item in interpretation.menu_items if item.slot is None or item.slot is slot]
        if not items:
            exchange.reply = ReplyText(MENU_EMPTY_TEXT)
            return
        refused = self._migration_refusal(chat_id)
        if refused is not None:
            exchange.reply = ReplyText(refused)
            return
        status, totals, context = self._nutrition_context(chat_id)
        rank_items = []
        lines = []
        choices = []
        for index, item in enumerate(items, start=1):
            kcal = _bounds(item.estimate, NutrientField.CALORIES_KCAL)
            protein = _bounds(item.estimate, NutrientField.PROTEIN_G)
            if item.printed_kcal is not None:
                kcal = (item.printed_kcal, item.printed_kcal)
            if item.printed_protein_g is not None:
                protein = (item.printed_protein_g, item.printed_protein_g)
            rank_items.append(RankItem(index, kcal, protein))
            title = f"{item.corner}: {item.name}" if item.corner else item.name
            lines.append(
                MenuLineView(
                    title, kcal, protein, item.printed_kcal is not None, item.printed_protein_g is not None, None, None
                )
            )
            ranges = _replace_ranges(item.estimate, kcal, protein)
            memo = clean_memo(f"{item.corner} {item.name}" if item.corner else item.name) or item.name
            choices.append(
                MenuChoice(memo, ranges, item.printed_kcal is not None or item.printed_protein_g is not None)
            )
        self._menu_reply(
            chat_id,
            exchange,
            slot,
            rank_items,
            lines,
            choices,
            status,
            totals,
            context,
            source=NutritionSourceType.VISUAL_ESTIMATE,
            reference=self._reference(exchange.calls[-1], photo_digest),
            label="메뉴 캡처 추정",
            lead=None,
        )

    def _suggest(self, chat_id: int, words: str, interpretation: Interpretation, exchange: _Exchange) -> None:
        refused = self._migration_refusal(chat_id)
        if refused is not None:
            exchange.reply = ReplyText(refused)
            return
        status, totals, context = self._nutrition_context(chat_id)
        data: list[tuple[str, Any]] = []
        if status is not None:
            data.append(("nutrition status --json", status))
        if totals is not None:
            data.append(("오늘 누적", totals_text(totals)))
        recommendation = self._read_json(chat_id, ("recommend", "--date", self._today().isoformat(), "--json"))
        if recommendation is not None:
            data.append(("recommend --json", recommendation))
        eaten = self._eaten_today(chat_id)
        if eaten:
            data.append(("오늘 먹은 것", eaten))
        call = self._call(chat_id, SchemaName.SUGGEST, PromptTask.SUGGEST, words, None, data, parse_suggestions)
        exchange.calls.append(call)
        if not call.ok:
            exchange.reply = ReplyText(PROVIDER_FAILED_TEXT)
            return
        result: SuggestResult = call.document
        exchange.outputs["suggest"] = result.document
        exchange.summary = result.memory_summary or exchange.summary
        allowed = allowed_numbers([document for _label, document in data])
        meal_type = interpretation.meal_type or meal_slot_for(self._now().time())
        rank_items, lines, choices = [], [], []
        for index, suggestion in enumerate(result.suggestions, start=1):
            kcal = _bounds(suggestion.estimate, NutrientField.CALORIES_KCAL)
            protein = _bounds(suggestion.estimate, NutrientField.PROTEIN_G)
            rank_items.append(RankItem(index, kcal, protein))
            notes = [text for text in (suggestion.description, suggestion.note) if text]
            kept = [text for text in notes if not unknown_numbers(text, allowed)]
            if len(kept) != len(notes):
                self._log(f"chat {chat_id}: suggestion text with numbers outside the data was left out")
            title = f"{suggestion.name} ({_CATEGORY_NAMES[suggestion.category]})"
            lines.append(MenuLineView(title, kcal, protein, False, False, None, " ".join(kept) or None))
            choices.append(MenuChoice(clean_memo(suggestion.name) or suggestion.name, suggestion.estimate, False))
        lead = result.lead if result.lead and not unknown_numbers(result.lead, allowed) else None
        self._menu_reply(
            chat_id,
            exchange,
            meal_type,
            rank_items,
            lines,
            choices,
            status,
            totals,
            context,
            source=NutritionSourceType.LANGUAGE_ESTIMATE,
            reference=self._reference(call, None),
            label="메뉴 제안 추정",
            lead=lead,
        )

    def _menu_reply(
        self,
        chat_id: int,
        exchange: _Exchange,
        meal_type: MealType,
        rank_items: Sequence[RankItem],
        lines: Sequence[MenuLineView],
        choices: Sequence[MenuChoice],
        status: Any,
        totals: TodayTotals | None,
        context: KcalContext,
        *,
        source: NutritionSourceType,
        reference: str,
        label: str,
        lead: str | None,
    ) -> None:
        ranking = rank_menu(tuple(rank_items), context)
        ordered = [entry.index - 1 for entry in ranking.order]
        ranked_lines = tuple(
            MenuLineView(
                lines[index].title,
                lines[index].kcal,
                lines[index].protein,
                lines[index].printed_kcal,
                lines[index].printed_protein,
                entry.label,
                lines[index].note,
            )
            for entry, index in zip(ranking.order, ordered, strict=True)
        )
        proposal = self._new_proposal(
            chat_id,
            ProposalKind.MENU,
            choices=tuple(choices[index] for index in ordered),
            meal_type=meal_type,
            day=self._today(),
            source=source,
            reference=reference,
            label=label,
        )
        exchange.proposal = proposal.token
        protein_remaining = kcal_budget = None
        if context.readable:
            try:
                remaining = status["nutrients"][NutrientField.PROTEIN_G.value]["remaining"]
            except (KeyError, TypeError):
                remaining = None
            protein_remaining = remaining if isinstance(remaining, str) else None
            kcal_budget = amount_text(context.budget) if context.budget is not None else None
        view = MenuView(
            proposal.token,
            meal_type,
            label == "메뉴 제안 추정",
            ranking,
            protein_remaining,
            kcal_budget,
            totals_text(totals) if totals is not None else None,
            lead,
            ranked_lines,
        )
        exchange.reply = self._replies.menu(view)

    def _nutrition_context(self, chat_id: int) -> tuple[Any, TodayTotals | None, KcalContext]:
        status = self._read_json(chat_id, ("nutrition", "status", "--json"))
        day = self._read_json(chat_id, ("nutrition", "day", "--json")) if status is not None else None
        totals = None
        if status is not None and day is not None:
            try:
                totals = today_totals(status, day)
            except (KeyError, TypeError, ValueError) as exc:
                self._log(f"chat {chat_id}: today totals not computed ({type(exc).__name__})")
        try:
            context = kcal_context(status, totals) if status is not None else UNREADABLE
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            self._log(f"chat {chat_id}: nutrition status not usable ({type(exc).__name__})")
            context = UNREADABLE
        return status, totals, context

    def _eaten_today(self, chat_id: int) -> list[str]:
        day = self._read_json(chat_id, ("nutrition", "day", "--json"))
        names: list[str] = []
        try:
            for meal in day["meals"] if isinstance(day, dict) else []:
                for item in meal["items"]:
                    names.append(item.get("note") or item["food_name"])
        except (KeyError, TypeError):
            return []
        return names

    # --- questions ------------------------------------------------------------------------------------------

    def _question(self, chat_id: int, words: str, interpretation: Interpretation, exchange: _Exchange) -> None:
        topics = interpretation.question_topics
        if not topics:
            exchange.reply = ReplyText(QUESTION_TOPICS_TEXT)
            return
        if Topic.NUTRITION in topics:
            refused = self._migration_refusal(chat_id)
            if refused is not None:
                exchange.reply = ReplyText(refused)
                return
        data: list[tuple[str, Any]] = []
        documents: dict[Topic, Any] = {}
        for topic in topics:
            if topic is Topic.TRAINING:
                argv: tuple[str, ...] = ("recommend", "--date", self._today().isoformat(), "--json")
            elif topic is Topic.NUTRITION:
                argv = ("nutrition", "status", "--json")
            else:
                argv = ("inbody", "trend", "--json")
            document = self._read_json(chat_id, argv)
            if document is not None:
                documents[topic] = document
                data.append((" ".join(argv), document))
        if Topic.NUTRITION in documents:
            day = self._read_json(chat_id, ("nutrition", "day", "--json"))
            try:
                if day is not None:
                    data.append(("오늘 누적", totals_text(today_totals(documents[Topic.NUTRITION], day))))
            except (KeyError, TypeError, ValueError) as exc:
                self._log(f"chat {chat_id}: today totals not computed ({type(exc).__name__})")
        sources = ", ".join(_TOPIC_COMMANDS[topic] for topic in topics)
        if data:
            call = self._call(chat_id, SchemaName.ANSWER, PromptTask.ANSWER, words, None, data, parse_answer)
            exchange.calls.append(call)
            if call.ok:
                exchange.outputs["answer"] = call.document.document
                exchange.summary = call.document.memory_summary or exchange.summary
                unknown = unknown_numbers(call.document.answer, allowed_numbers([doc for _label, doc in data]))
                if not unknown:
                    exchange.reply = ReplyText(f"{call.document.answer}\n(근거: {sources})")
                    return
                self._log(
                    f"chat {chat_id}: llm answer had {len(unknown)} numbers outside the data; sent the existing replies"
                )
        self._existing_replies(chat_id, topics, documents, exchange, sources)

    def _existing_replies(
        self, chat_id: int, topics: Sequence[Topic], documents: dict[Topic, Any], exchange: _Exchange, sources: str
    ) -> None:
        messages: list[str] = []
        for topic in topics:
            document = documents.get(topic)
            try:
                if topic is Topic.TRAINING and document is not None:
                    messages.extend(self._summaries.summary(ReplyKind.TODAY_SUMMARY, document))
                    continue
                if topic is Topic.NUTRITION and document is not None:
                    messages.extend(self._summaries.summary(ReplyKind.STATUS_SUMMARY, document))
                    continue
            except SummaryUnavailableError:
                pass
            if topic is Topic.BODY:
                try:
                    outcome = self._commands.run(("inbody", "trend"))
                    text = outcome.stdout.removesuffix("\n") or outcome.stderr.removesuffix("\n")
                except Exception as exc:
                    self._log(f"chat {chat_id}: inbody trend failed ({type(exc).__name__})")
                    text = "답을 만들지 못했습니다. 확인: /inbody"
                messages.extend(self._replies.messages(ReplyText(text)))
            else:
                command = _TOPIC_COMMANDS[topic]
                messages.extend(self._replies.messages(ReplyText(f"답을 만들지 못했습니다. 확인: {command}")))
        exchange.messages = tuple(messages)
        exchange.reply = ReplyText(f"(LLM 답 대신 기존 답장: {sources})")

    # --- meal edits ------------------------------------------------------------------------------------------

    def _edit(self, chat_id: int, interpretation: Interpretation, exchange: _Exchange) -> None:
        edit = interpretation.edit
        if edit.action is None:
            exchange.reply = ReplyText(EDIT_UNCLEAR_TEXT)
            return
        day = resolve_date_expression(interpretation.date_expression, self._today())
        if day is None:
            exchange.reply = ReplyText(DATE_OTHER_TEXT)
            return
        try:
            meals = self._meals.list_eaten_between(*local_day_bounds(day, self._local_timezone(day)))
        except Exception as exc:
            self._log(f"chat {chat_id}: meals not read for an edit ({type(exc).__name__})")
            meals = ()
        if interpretation.meal_type is not None:
            meals = tuple(meal for meal in meals if meal.meal_type is interpretation.meal_type)
        if not meals:
            exchange.reply = ReplyText(EDIT_NO_MEAL_TEXT)
            return
        action = edit.action
        if action in (EditAction.VOID_MEAL, EditAction.CHANGE_MEAL_TYPE, EditAction.ADD_ITEM):
            if len(meals) != 1:
                exchange.reply = self._replies.candidates([meal.meal_id for meal in meals])
                return
            meal = meals[0]
            name = f"{MEAL_NAMES[meal.meal_type]} {meal.meal_id}"
            if action is EditAction.VOID_MEAL:
                argv: tuple[str, ...] = ("nutrition", "meal", "void", meal.meal_id, "--reason=Telegram 문장으로 취소")
                change = f"{name} 기록 취소(void)"
            elif action is EditAction.CHANGE_MEAL_TYPE:
                if edit.new_meal_type is None:
                    exchange.reply = ReplyText(EDIT_UNCLEAR_TEXT)
                    return
                argv = ("nutrition", "meal", "edit", meal.meal_id, "--meal", edit.new_meal_type.value)
                change = f"{name}: 끼니 {MEAL_NAMES[meal.meal_type]} → {MEAL_NAMES[edit.new_meal_type]}"
            else:
                added = self._edit_entry(edit.new_food_text, edit.new_quantity, edit.new_unit, None)
                if isinstance(added, str):
                    exchange.reply = ReplyText(added)
                    return
                argv = ("nutrition", "meal", "add-item", meal.meal_id, *added[0])
                change = f"{name}: 추가 {added[1]}"
            self._store_edit(chat_id, exchange, meal.meal_id, argv, change)
            return
        target = self._edit_target(meals, edit.target_food_text)
        if target is None:
            exchange.reply = self._replies.candidates([meal.meal_id for meal in meals])
            return
        meal, number = target
        item = next(entry for entry in meal.items if entry.sequence == number)
        before = _item_text(item)
        name = f"{MEAL_NAMES[meal.meal_type]} {meal.meal_id} item {number}"
        if action is EditAction.REMOVE_ITEM:
            remove: tuple[str, ...] = ("nutrition", "meal", "remove-item", meal.meal_id, "--item-number", str(number))
            self._store_edit(chat_id, exchange, meal.meal_id, remove, f"{name}: {before} 빼기")
            return
        if action is EditAction.CHANGE_QUANTITY:
            if item.is_general or item.food_profile_id is None:
                exchange.reply = ReplyText(EDIT_UNCLEAR_TEXT)  # a general meal has no amount to change
                return
            food_text = item.food_profile_id
        else:
            food_text = edit.new_food_text or ""
        replacement = self._edit_entry(
            food_text, edit.new_quantity or item.quantity, edit.new_unit or item.quantity_unit, item.food_profile_id
        )
        if isinstance(replacement, str):
            exchange.reply = ReplyText(replacement)
            return
        replace_argv = (
            "nutrition",
            "meal",
            "replace-item",
            meal.meal_id,
            "--item-number",
            str(number),
            *replacement[0],
        )
        self._store_edit(chat_id, exchange, meal.meal_id, replace_argv, f"{name}: {before} → {replacement[1]}")

    def _edit_target(self, meals: Sequence[Meal], target_text: str | None) -> tuple[Meal, int] | None:
        if target_text is None:
            items = [(meal, item.sequence) for meal in meals for item in meal.items]
            return items[0] if len(items) == 1 else None
        try:
            food_id = ResolveFoodReference(self._catalog).execute(target_text, label="")
        except NutritionLoggingError:
            return None
        if food_id is None:
            return None
        matches = [(meal, item.sequence) for meal in meals for item in meal.items if item.food_profile_id == food_id]
        return matches[0] if len(matches) == 1 else None

    def _edit_entry(
        self, food_text: str | None, quantity: Decimal | None, unit: QuantityUnit | None, current_food: str | None
    ) -> tuple[tuple[str, ...], str] | str:
        """(`--item ...` or `--general ...` argv, display) or a refusal text."""
        if not food_text:
            return EDIT_UNCLEAR_TEXT
        entry, reason = self._catalog_entry(food_text, quantity, unit, False)
        if entry is None:
            return reason or EDIT_UNCLEAR_TEXT
        if entry.food_id is None:
            memo = clean_memo(food_text)
            argv: tuple[str, ...] = ("--general", *((f"--general-note={memo}",) if memo else ()))
            return argv, f"일반식 (메모: {memo})" if memo else "일반식"
        assert entry.quantity is not None and entry.unit is not None
        argv = ("--item", entry.food_id, amount_text(entry.quantity), entry.unit.value)
        return argv, entry.display()

    def _store_edit(self, chat_id: int, exchange: _Exchange, meal_id: str, argv: tuple[str, ...], change: str) -> None:
        proposal = self._new_proposal(chat_id, ProposalKind.EDIT, argv_ok=argv, meal_id=meal_id)
        exchange.proposal = proposal.token
        exchange.reply = self._replies.edit(EditView(proposal.token, change, " ".join(argv)))

    # --- proposal commands -------------------------------------------------------------------------------

    def _proposal_command(self, chat_id: int, update_id: int, command: ProposalCommand) -> LlmAction:
        kind = {"ok": "confirm", "plain": "plain", "no": "cancel", "eat": "eat"}[command.action]
        typed = f"/{command.action}_{command.token}" + (f"_{command.number}" if command.number is not None else "")
        state = self._proposals.load()
        proposal = next(
            (item for item in state.proposals if item.token == command.token and item.chat_id == chat_id), None
        )
        refusal = self._proposal_refusal(proposal, command)
        if refusal is not None or proposal is None:
            text = refusal or PROPOSAL_UNKNOWN_TEXT
            self._log(f"chat {chat_id}: /{command.action} {command.token} refused")
            return self._simple(chat_id, update_id, kind, text, proposal=command.token, typed=typed)
        if command.action == "no":
            self._update(state, proposal.with_state(ProposalState.CANCELLED))
            self._log(f"chat {chat_id}: proposal {proposal.token} cancelled")
            return self._simple(chat_id, update_id, kind, CANCELLED_TEXT, proposal=proposal.token, typed=typed)
        if command.action == "eat":
            return self._eat(chat_id, update_id, proposal, command.number or 0)
        refused = self._migration_refusal(chat_id)
        if refused is not None:  # not consumed: it can be confirmed once the migration is applied
            return self._simple(chat_id, update_id, kind, refused, proposal=proposal.token, typed=typed)
        self._update(state, proposal.with_state(ProposalState.USED))  # before it runs: at most once
        argv = proposal.argv_plain if command.action == "plain" else proposal.argv_ok
        edit = proposal.kind is ProposalKind.EDIT
        history_kind = "edit" if edit else kind
        invocation = CliInvocation("ok" if command.action == "ok" else "plain", argv, True, False, not edit)
        self._log(f"chat {chat_id}: proposal {proposal.token} confirmed")

        def on_outcome(outcome: CommandOutcome, text: str) -> str:
            meal_id = proposal.meal_id if edit else _recorded_meal_id(outcome.stdout)
            if outcome.exit_code == 0:
                if edit and meal_id is not None:
                    text = f"{text}\n확인: /show {meal_id}"
                totals = self._totals_line(chat_id)
                if totals is not None:
                    text = f"{text}\n{totals}"
            result = {"exit_code": outcome.exit_code, "meal_id": meal_id if outcome.exit_code == 0 else None}
            self._append_history(
                chat_id,
                history_entry(
                    update_id=update_id,
                    at=self._at(),
                    chat_id=chat_id,
                    kind=history_kind,
                    text=typed,
                    reply=text,
                    proposal=proposal.token,
                    result=result,
                ),
            )
            return text

        return RunConfirmed(invocation, on_outcome)

    def _proposal_refusal(self, proposal: Proposal | None, command: ProposalCommand) -> str | None:
        if proposal is None:
            return PROPOSAL_UNKNOWN_TEXT
        is_menu = proposal.kind is ProposalKind.MENU
        if (command.action == "eat") != is_menu and command.action != "no":
            return PROPOSAL_WRONG_KIND_TEXT
        if proposal.state is ProposalState.USED:
            return PROPOSAL_USED_TEXT
        if proposal.state is ProposalState.CANCELLED:
            return PROPOSAL_CANCELLED_TEXT
        if int(self._now().timestamp()) >= proposal.expires_unix:
            return PROPOSAL_EXPIRED_TEXT
        if command.action == "plain" and not proposal.argv_plain:
            return PROPOSAL_NO_PLAIN_TEXT.format(token=proposal.token)
        return None

    def _eat(self, chat_id: int, update_id: int, menu: Proposal, number: int) -> LlmAction:
        if not 1 <= number <= len(menu.choices) or menu.meal_type is None or menu.day is None:
            typed = f"/eat_{menu.token}_{number}"
            return self._simple(chat_id, update_id, "eat", MENU_NUMBER_UNKNOWN_TEXT, proposal=menu.token, typed=typed)
        choice = menu.choices[number - 1]
        source = menu.source or NutritionSourceType.VISUAL_ESTIMATE
        entry = _Entry(None, None, None, choice.memo, choice.ranges, False, None)
        exchange = _Exchange(intent="eat")
        self._store_meal_proposal(
            chat_id, exchange, menu.day, menu.meal_type, [entry], [], source, menu.reference or "", menu.label, False
        )
        assert exchange.reply is not None
        self._record(chat_id, exchange, update_id=update_id, kind="eat", text=f"/eat_{menu.token}_{number}")
        return LlmReply(tuple(self._replies.messages(exchange.reply)))

    def _simple(
        self, chat_id: int, update_id: int, kind: str, text: str, *, proposal: str | None, typed: str
    ) -> LlmAction:
        self._append_history(
            chat_id,
            history_entry(
                update_id=update_id,
                at=self._at(),
                chat_id=chat_id,
                kind=kind,
                text=typed,
                reply=text,
                proposal=proposal,
            ),
        )
        return LlmReply(tuple(self._replies.messages(ReplyText(text))))

    # --- /llm, /memory, /forget, /history -----------------------------------------------------------------

    def _llm_command(self, chat_id: int, command: LlmCommand) -> LlmAction:
        name, argument = command.name, command.argument
        if name in ("memory", "forget") and argument:
            text = COMMAND_ARGUMENT_TEXT.format(name=name)
        elif name == "llm":
            text = self._llm_setting(chat_id, argument)
        elif name == "memory":
            block = self._memory_block(chat_id)
            text = f"{MEMORY_HEAD_TEXT}\n{block}" if block is not None else MEMORY_EMPTY_TEXT
        elif name == "forget":
            try:
                self._memory.clear(chat_id)
            except Exception as exc:
                self._log(f"chat {chat_id}: memory not cleared ({type(exc).__name__})")
            self._log(f"chat {chat_id}: memory cleared")
            text = FORGET_TEXT
        else:
            return LlmReply(tuple(self._replies.messages(self._history_reply(chat_id, argument))))
        return LlmReply(tuple(self._replies.messages(ReplyText(text))))

    def _llm_setting(self, chat_id: int, argument: str) -> str:
        state = self._proposals.load()
        configured = self._settings.provider
        if argument == "":
            active = self.active_provider(state)
            first = llm_status_text(
                active,
                self._settings.provider_settings(active),
                self._settings.fallback_provider,
                self._settings.timeout_seconds,
            )
            if state.provider_override is None:
                other = "codex" if active is ProviderName.CLAUDE else "claude"
                second = f"바꾸기: /llm {other} · 설정 파일로 되돌리기: /llm default"
            else:
                second = f"(채팅에서 바꿈, 설정 파일: {configured.value})"
            return f"{first}\n{second}"
        if argument == "default":
            self._proposals.save(LlmState(None, state.proposals))
            self._log(f"chat {chat_id}: llm provider back to the config file ({configured.value})")
            return provider_default_text(configured.value, PROVIDER_COMPANIES[configured])
        if argument in (ProviderName.CLAUDE.value, ProviderName.CODEX.value):
            chosen = ProviderName(argument)
            self._proposals.save(LlmState(chosen.value, state.proposals))
            self._log(f"chat {chat_id}: llm provider set to {chosen.value}")
            return provider_switched_text(chosen.value, PROVIDER_COMPANIES[chosen])
        return LLM_USAGE_TEXT

    def _history_reply(self, chat_id: int, argument: str) -> ReplyText:
        last: int | None = HISTORY_DEFAULT
        day: date | None = None
        if argument:
            if argument.isdigit() and argument.isascii() and 1 <= int(argument) <= HISTORY_MAX:
                last = int(argument)
            elif _DATE.fullmatch(argument):
                try:
                    day, last = date.fromisoformat(argument), None
                except ValueError:
                    return ReplyText(HISTORY_USAGE_TEXT)
            else:
                return ReplyText(HISTORY_USAGE_TEXT)
        try:
            entries = self._history.read(last=last, day=day)
        except Exception as exc:
            self._log(f"chat {chat_id}: history not read ({type(exc).__name__})")
            return ReplyText(f"오류: 대화 기록을 읽지 못했습니다 ({type(exc).__name__}).")
        return self._replies.history(entries)

    def active_provider(self, state: LlmState | None = None) -> ProviderName:
        override = (state if state is not None else self._proposals.load()).provider_override
        return ProviderName(override) if override is not None else self._settings.provider

    # --- shared helpers ------------------------------------------------------------------------------------

    def _call(
        self,
        chat_id: int,
        schema: SchemaName,
        task: PromptTask,
        words: str,
        photo: bytes | None,
        data: Sequence[tuple[str, Any]],
        validate: Callable[[Any], Any],
    ) -> LlmCallResult:
        guide, reason = self._coach.read()
        if reason is not None:
            self._log(f"coach guide ignored ({reason})")
        prompt = build_prompt(
            task,
            persona_name=self._settings.persona_name,
            persona_tone=self._settings.persona_tone,
            coach_guide=guide,
            memory=self._memory_block(chat_id),
            data=[(label, _data_text(document)) for label, document in data],
            message=words,
            has_photo=photo is not None,
        )
        result = self._provider.call(LlmRequest(prompt, schema, photo, validate), self.active_provider())
        self._log(f"chat {chat_id}: llm {schema.value} -> {result.outcome} ({result.provider.value})")
        return result

    def _memory_block(self, chat_id: int) -> str | None:
        try:
            memory = self._memory.get(chat_id)
        except Exception as exc:
            self._log(f"chat {chat_id}: memory not read ({type(exc).__name__})")
            memory = EMPTY_MEMORY
        return memory_block(memory, int(self._now().timestamp()))

    def _remember_turn(self, chat_id: int, user: str, exchange: _Exchange) -> None:
        if not exchange.calls:
            return
        try:
            memory = self._memory.get(chat_id)
            assert exchange.reply is not None
            updated = remember(
                memory,
                user=user,
                bot=exchange.reply.plain(),
                summary=exchange.summary,
                now_unix=int(self._now().timestamp()),
            )
            self._memory.put(chat_id, updated)
        except Exception as exc:
            self._log(f"chat {chat_id}: memory not written ({type(exc).__name__})")

    def _record(
        self,
        chat_id: int,
        exchange: _Exchange,
        *,
        update_id: int,
        kind: str,
        text: str | None = None,
        caption: str | None = None,
        photo: str | None = None,
    ) -> None:
        last = exchange.calls[-1] if exchange.calls else None
        assert exchange.reply is not None
        entry = history_entry(
            update_id=update_id,
            at=self._at(),
            chat_id=chat_id,
            kind=kind,
            text=text,
            caption=caption,
            photo=photo,
            intent=exchange.intent,
            provider=last.provider.value if last is not None else None,
            model=last.model if last is not None else None,
            provider_result=last.outcome if last is not None else None,
            llm_output=exchange.outputs or None,
            reply=exchange.reply.plain(),
            proposal=exchange.proposal,
            retried=last.retried if last is not None else None,
            attempts=_attempts_document(last),
        )
        self._append_history(chat_id, entry)
        self._log(
            f"chat {chat_id}: llm {kind} -> {exchange.intent or 'none'}"
            + (f", proposal {exchange.proposal}" if exchange.proposal else "")
        )

    def _append_history(self, chat_id: int, entry: dict[str, Any]) -> None:
        try:
            self._history.append(entry)
        except Exception as exc:
            self._log(f"chat {chat_id}: history write failed ({type(exc).__name__})")

    def _new_proposal(self, chat_id: int, kind: ProposalKind, **fields: Any) -> Proposal:
        state = self._proposals.load()
        now = int(self._now().timestamp())
        proposals = prune_proposals(state.proposals, now)
        used = {proposal.token for proposal in proposals}
        token = self._new_token()
        for _attempt in range(100):
            if token not in used:
                break
            token = self._new_token()
        else:
            raise RuntimeError("no free proposal token")
        proposal = Proposal(token, chat_id, kind, now, now + PROPOSAL_TTL_S, ProposalState.OPEN, **fields)
        self._proposals.save(LlmState(state.provider_override, (*proposals, proposal)))
        return proposal

    def _update(self, state: LlmState, proposal: Proposal) -> None:
        proposals = tuple(
            proposal if item.token == proposal.token and item.chat_id == proposal.chat_id else item
            for item in state.proposals
        )
        self._proposals.save(LlmState(state.provider_override, proposals))

    def _migration_refusal(self, chat_id: int) -> str | None:
        pending = self._pending_migrations()
        if pending is None:
            self._log(f"chat {chat_id}: llm request not run (cannot read schema_migrations)")
            return MIGRATION_STATUS_UNKNOWN_TEXT
        if pending:
            numbers = ", ".join(f"{version:03d}" for version in pending)
            self._log(f"chat {chat_id}: llm request not run (migration {numbers} not applied)")
            return pending_migration_text(pending)
        return None

    def _read_json(self, chat_id: int, argv: tuple[str, ...]) -> Any:
        try:
            outcome = self._commands.run(argv)
        except Exception as exc:
            self._log(f"chat {chat_id}: {argv[0]} read failed ({type(exc).__name__})")
            return None
        if outcome.exit_code != 0 or not outcome.stdout:
            self._log(f"chat {chat_id}: {argv[0]} read -> exit {outcome.exit_code}")
            return None
        try:
            return json.loads(outcome.stdout)
        except ValueError:
            return None

    def _totals_line(self, chat_id: int) -> str | None:
        status = self._read_json(chat_id, ("nutrition", "status", "--json"))
        day = self._read_json(chat_id, ("nutrition", "day", "--json"))
        if status is None or day is None:
            return None
        try:
            return totals_text(today_totals(status, day))
        except (KeyError, TypeError, ValueError) as exc:
            self._log(f"chat {chat_id}: today totals not computed ({type(exc).__name__})")
            return None

    def _reference(self, call: LlmCallResult, photo_digest: str | None) -> str:
        what = f"photo sha256:{photo_digest[:12]}" if photo_digest is not None else "text"
        return f"telegram-llm {what} ({call.provider.value} {call.model or 'default'})"

    def _today(self) -> date:
        return self._now().date()

    def _at(self) -> str:
        return self._now().replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class _Entry:
    """One proposed item: a catalog food with an amount, or a general meal (food_id None)."""

    food_id: str | None
    quantity: Decimal | None
    unit: QuantityUnit | None
    memo: str | None
    """Catalog: the display text; general: the memo."""
    estimate: NutrientRanges
    quantity_estimated: bool
    reason: str | None

    def argv(self, source: NutritionSourceType, reference: str, with_estimate: bool) -> tuple[str, ...]:
        if self.food_id is not None and self.quantity is not None and self.unit is not None:
            return ("--item", self.food_id, amount_text(self.quantity), self.unit.value)
        args = ["--general"]
        if self.memo:
            args.append(f"--general-note={self.memo}")
        if with_estimate and self.estimate:
            args.append(f"--general-estimate={format_general_estimate(source, self.estimate)}")
            if reference:
                args.append(f"--general-estimate-ref={reference}")
        return tuple(args)

    def display(self) -> str:
        if self.food_id is not None:
            return self.memo or self.food_id
        return f"일반식 (메모: {self.memo})" if self.memo else "일반식"


def _bounds(ranges: NutrientRanges, nutrient: NutrientField) -> tuple[Decimal, Decimal] | None:
    return next(((low, high) for field_, low, high in ranges if field_ is nutrient), None)


def _replace_ranges(
    ranges: NutrientRanges, kcal: tuple[Decimal, Decimal] | None, protein: tuple[Decimal, Decimal] | None
) -> NutrientRanges:
    """The estimate with printed values (min = max) in place of the estimated kcal/protein."""
    by_field = {nutrient: (low, high) for nutrient, low, high in ranges}
    if kcal is not None:
        by_field[NutrientField.CALORIES_KCAL] = kcal
    if protein is not None:
        by_field[NutrientField.PROTEIN_G] = protein
    return tuple((nutrient, *by_field[nutrient]) for nutrient in NutrientField if nutrient in by_field)


def _item_text(item: Any) -> str:
    if item.quantity is not None and item.quantity_unit is not None:
        return f"{item.food_name} {amount_text(item.quantity)} {item.quantity_unit.value}"
    return f"{item.food_name}" + (f" (메모: {item.serving_description})" if item.serving_description else "")


def _attempts_document(call: LlmCallResult | None) -> list[dict[str, Any]] | None:
    """The attempts of the last LLM call for the history line; None when there was no call or no attempt record."""
    if call is None or not call.attempts:
        return None
    return [
        {"provider": item.provider.value, "model": item.model, "outcome": item.outcome, "retry": item.retry}
        for item in call.attempts
    ]


def _recorded_meal_id(stdout: str) -> str | None:
    match = _RECORDED_MEAL.fullmatch(stdout.split("\n", 1)[0])
    return match.group(1) if match else None


def _digest(photo: bytes) -> str:
    return hashlib.sha256(photo).hexdigest()


def _data_text(document: Any) -> str:
    return document if isinstance(document, str) else json.dumps(document, ensure_ascii=False, indent=1)
