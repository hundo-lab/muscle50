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
from dataclasses import dataclass, field, replace
from datetime import date, datetime, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from muscle50.application.food_lookup import FoodLookup, ResolveFoodReference
from muscle50.application.llm_provider import LlmCallResult, LlmProvider, LlmRequest, RunPin, SchemaName
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
    RunConfirmedSequence,
    SequenceStep,
    SummaryUnavailableError,
    TelegramUnavailableError,
)
from muscle50.domain.llm_number_guard import allowed_numbers, unknown_numbers
from muscle50.domain.llm_settings import PROVIDER_COMPANIES, LlmSettings, ProviderName
from muscle50.domain.llm_today_totals import (
    NUTRIENT_NAMES,
    TODAY_LABEL,
    TodayTotals,
    amount_text,
    display_remaining,
    today_totals,
    totals_text,
)
from muscle50.domain.menu_ranking import UNREADABLE, KcalContext, MenuRanking, RankItem, kcal_context, rank_menu
from muscle50.domain.nutrition import (
    FoodNutritionProfile,
    Meal,
    MealItem,
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
    MENU_PROPOSAL_TTL_S,
    PROPOSAL_TTL_S,
    ChatMemory,
    EditAction,
    Intent,
    Interpretation,
    InterpretItem,
    ItemKind,
    LlmCommand,
    LlmState,
    MealCommand,
    MenuChoice,
    NutrientRanges,
    PhotoKind,
    Portion,
    Proposal,
    ProposalCommand,
    ProposalKind,
    ProposalState,
    Refers,
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
from muscle50.domain.telegram_llm_check import (
    CHECK_REASON_TEXTS,
    CheckCode,
    CheckFailure,
    RecheckOutcome,
    check_estimate,
    recheck_note,
)
from muscle50.domain.telegram_llm_corrections import (
    RECENT_MEALS,
    Candidate,
    FixPlan,
    ItemRef,
    find_overlaps,
    general_ranges,
    item_memo,
    item_summary,
    match_items,
    menu_block,
    menu_name_matches,
    merge_estimate,
    open_proposal_block,
    overlap_name,
    pick_meals,
    plan_fix,
    ranges_summary,
    recent_meal_ids,
    recent_meals_block,
    recent_menu,
)
from muscle50.domain.telegram_llm_meals import (
    catalog_prompt,
    dish_memo,
    estimate_reference,
    group_meals,
    is_label_estimate,
    is_meal_word,
    portions_text,
    registered_units,
)
from muscle50.domain.telegram_llm_prompt import (
    CANCELLED_TEXT,
    CHECK_LINE_HEAD,
    CHECK_MARKER,
    COMMAND_ARGUMENT_TEXT,
    DATE_OTHER_TEXT,
    DOCUMENT_IMAGE_TEXT,
    EDIT_CATALOG_ESTIMATE_TEXT,
    EDIT_NO_MEAL_TEXT,
    EDIT_NO_OPEN_TEXT,
    EDIT_NO_RECENT_TEXT,
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
    OVERLAP_MANY_TEXT,
    OVERLAP_SAME_TEXT,
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
    REASON_AMBIGUOUS,
    REASON_BAD_ID,
    REASON_NO_AMOUNT,
    REASON_NOT_IN_CATALOG,
    SEQUENCE_HINT,
    SYNC_HINT_TEXT,
    UNCLEAR_TEXT,
    PromptTask,
    build_prompt,
    llm_status_text,
    menu_expired_text,
    provider_default_text,
    provider_switched_text,
    sequence_failed_line,
    sequence_not_run_line,
    unregistered_unit_hint,
    unregistered_unit_reason,
)

HISTORY_DEFAULT = 5
HISTORY_MAX = 20
HISTORY_SCAN = 200
"""The newest history lines read to find the chat's last recorded meals (a bounded read: a month file can be big)."""
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

    def get_active(self, meal_id: str) -> Meal | None:
        """One meal by ID; None when it does not exist or was voided (read-only)."""
        ...


class FoodCatalog(FoodLookup, Protocol):
    """The catalog reads the handler needs: the exact lookup plus the list sent to the LLM."""

    def list_all(self) -> tuple[FoodNutritionProfile, ...]: ...


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
    hint: str | None = None
    """A command to register a missing unit (`등록: muscle50 nutrition food fact add ...`)."""
    assumption: str | None = None
    source: str | None = None
    check: tuple[CheckCode, ...] = ()
    """The failed numeric checks: the item is shown with `(값 확인 필요)` and the reasons."""
    label: bool = False
    """The estimate is a label value: `라벨:` instead of `추정:` and no `(estimated)`."""
    portions: str | None = None
    """`닭 150~200 g, 감자 100~150 g`: the assumed grams (shown as `양 가정:`)."""
    printed: bool = False
    """The values are the menu's printed numbers (`(메뉴판 표기)`)."""


@dataclass(frozen=True)
class OverlapView:
    """A proposed meal whose food is already recorded in that day's meal of the same type."""

    meal_type: MealType
    meal_id: str
    names: tuple[str, ...]
    when: str
    """`오늘`, or `MM-DD` for another day."""
    fix: bool
    """`/fix_` is offered: the recorded meal can be made equal to the proposal with exactly one command."""
    hint: str | None = None
    """Why there is no `/fix_` (the same content is already recorded, or it takes several changes)."""


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
    searches: int = 0
    """Web searches made for this proposal (`웹 검색 N회` when above 0)."""
    superseded: str | None = None
    """The token of the open proposal this one replaces (cancelled in the same save)."""
    overlap: OverlapView | None = None


@dataclass(frozen=True)
class MealBlockView:
    meal_type: MealType
    duplicates: tuple[str, ...]
    items: tuple[ProposalItemView, ...]
    overlap: OverlapView | None = None


@dataclass(frozen=True)
class MultiMealProposalView:
    """Two or more meals from one message: one `/ok_` records each with its own `nutrition log`."""

    token: str
    day: date
    meals: tuple[MealBlockView, ...]
    plain: bool
    searches: int = 0
    label: str | None = None
    """`사진 추정` for a photo, as in the single-meal proposal head."""
    superseded: str | None = None


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

    def multi_proposal(self, view: MultiMealProposalView) -> ReplyText: ...

    def menu(self, view: MenuView) -> ReplyText: ...

    def edit(self, view: EditView) -> ReplyText: ...

    def candidates(self, meal_ids: Sequence[str]) -> ReplyText: ...

    def item_candidates(self, lines: Sequence[str]) -> ReplyText: ...

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
    recheck: dict[str, Any] | None = None
    """`{"reasons": [...], "outcome": ...}` when the numeric re-check found something (None: nothing failed)."""
    data: tuple[tuple[str, Any], ...] = ()
    """The `[데이터]` pairs of the interpret call; the numeric re-ask sends the same ones."""
    menu: Proposal | None = None
    """The recent menu offered to the LLM (`menu_ref` points into its choices); None for a photo message."""


class TelegramLlmHandler:
    def __init__(
        self,
        *,
        provider: LlmProvider,
        files: TelegramFileApi,
        catalog: FoodCatalog,
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
        exchange.data = self._interpret_data(chat_id, words, exchange, text_only=photo is None)
        call = self._call(
            chat_id,
            SchemaName.INTERPRET,
            PromptTask.INTERPRET,
            words,
            photo,
            exchange.data,
            parse_interpretation,
            web_search=self._web_search_on(),
        )
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
            self._meal_proposal(chat_id, words, None, interpretation, exchange, photo_digest=None)
        elif intent is Intent.MEAL_EDIT:
            self._edit(chat_id, interpretation, exchange)
        elif intent is Intent.QUESTION:
            self._question(chat_id, words, interpretation, exchange)
        elif intent in (Intent.MENU_SUGGEST, Intent.MENU):
            self._suggest(chat_id, words, interpretation, exchange)
        elif intent is Intent.SYNC_REQUEST:
            # Nothing runs and nothing is stored: only the buttons for `/daily` and `/refresh`.
            exchange.reply = ReplyText(SYNC_HINT_TEXT, ("/daily", "/refresh"))
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
            self._meal_proposal(chat_id, words, photo, interpretation, exchange, photo_digest=_digest(photo))
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
        self,
        chat_id: int,
        words: str,
        photo: bytes | None,
        interpretation: Interpretation,
        exchange: _Exchange,
        *,
        photo_digest: str | None,
    ) -> None:
        day = resolve_date_expression(interpretation.date_expression, self._today())
        if day is None:
            exchange.reply = ReplyText(DATE_OTHER_TEXT)
            return
        cancel: str | None = None
        if photo is None and interpretation.refers_to is Refers.OPEN_PROPOSAL:
            # The message corrects the proposal that is still open: the corrected one replaces it (never a stray meal).
            opened = self._open_meal_proposal(chat_id)
            if opened is None:
                exchange.reply = ReplyText(EDIT_NO_OPEN_TEXT)
                return
            cancel = opened.token
        entries = self._link_items(chat_id, interpretation, exchange.menu)
        if not entries:
            exchange.reply = ReplyText(usage_text("log"))
            return
        used = exchange.calls[-1]
        failures = _failures(entries)
        if failures:
            entries, interpretation, day, used = self._recheck(
                chat_id, words, photo, photo_digest, interpretation, day, entries, failures, exchange
            )
        label = "사진 추정" if photo_digest is not None else None
        self._store_proposal(
            chat_id,
            exchange,
            day,
            interpretation.meal_type,
            entries,
            estimate_source(photo_digest is not None),
            self._reference(used, photo_digest),
            label,
            cancel=cancel,
        )

    # --- linking ---------------------------------------------------------------------------------------------

    def _link_items(self, chat_id: int, interpretation: Interpretation, menu: Proposal | None = None) -> list[_Entry]:
        """One entry per item that is not just a meal word: a catalog entry or a general estimate (never dropped).

        ``menu``: the recent menu the LLM was shown; an item whose `menu_ref` names one of its choices (and whose
        name agrees) takes that choice's memo and values. A reference that does not check out is ignored.
        """
        entries: list[_Entry] = []
        meal_words = ignored = 0
        for index, item in enumerate(interpretation.items, start=1):
            if is_meal_word(item.food_text):
                meal_words += 1
                continue
            picked = _menu_entry(index, item, menu)
            if picked is None and item.menu_ref is not None:
                ignored += 1
            entries.append(picked if picked is not None else self._link_item(index, item))
        if meal_words:
            self._log(f"chat {chat_id}: {meal_words} meal-word items left out")
        if ignored:
            self._log(f"chat {chat_id}: {ignored} menu references ignored")
        return entries

    def _link_item(self, index: int, item: InterpretItem) -> _Entry:
        """Exact lookup of the user's words first; the LLM's `food_id` only when that finds nothing (the user
        confirms the shown catalog name at `/ok`). Anything that cannot be linked stays a general estimate."""
        amount = (
            f" {amount_text(item.quantity)} {item.unit.value}"
            if item.quantity is not None and item.unit is not None
            else ""
        )

        def general(reason: str | None, hint: str | None = None, *, memo: str | None = None) -> _Entry:
            text = memo if memo is not None else clean_memo(f"{item.food_text}{amount}")
            return _Entry(
                None,
                None,
                None,
                text,
                item.estimate,
                False,
                reason,
                hint,
                source=item.source,
                assumption=item.assumption,
                index=index,
                meal_type=item.meal_type,
                own_quantity=item.quantity,
                label=is_label_estimate(item.estimate, item.from_label),
                portions=item.portions,
            )

        if item.kind is ItemKind.GENERAL:
            return general(None, memo=clean_memo(dish_memo(item.food_text, item.memo)))
        if is_reserved_food_reference(item.food_text):
            return general(REASON_NOT_IN_CATALOG)
        via: str | None = None
        try:
            food_id = ResolveFoodReference(self._catalog).execute(item.food_text, label="")
        except NutritionLoggingError:
            return general(REASON_AMBIGUOUS)  # an ambiguous exact match is never overridden
        if food_id is None:
            if item.food_id is None:
                return general(REASON_NOT_IN_CATALOG)
            if is_reserved_food_reference(item.food_id) or self._catalog.get(item.food_id) is None:
                return general(REASON_BAD_ID)
            food_id, via = item.food_id, item.food_text
        profile = self._catalog.get(food_id)
        if profile is None:
            return general(REASON_NOT_IN_CATALOG)
        if item.quantity is None or item.unit is None:
            return general(REASON_NO_AMOUNT)
        units = registered_units(profile)
        if item.unit not in units:
            reason = unregistered_unit_reason([unit.value for unit in units])
            return general(reason, unregistered_unit_hint(profile.profile_id, item.unit.value))
        text = f"{profile.name} ({profile.profile_id}) {amount_text(item.quantity)} {item.unit.value}"
        return _Entry(
            profile.profile_id,
            item.quantity,
            item.unit,
            text,
            (),
            item.quantity_estimated,
            None,
            via=via,
            index=index,
            meal_type=item.meal_type,
        )

    # --- the numeric re-check -------------------------------------------------------------------------------

    def _recheck(
        self,
        chat_id: int,
        words: str,
        photo: bytes | None,
        photo_digest: str | None,
        interpretation: Interpretation,
        day: date,
        entries: list[_Entry],
        failures: list[tuple[_Entry, CheckFailure]],
        exchange: _Exchange,
    ) -> tuple[list[_Entry], Interpretation, date, LlmCallResult]:
        """At most one corrective re-ask (one run on the retry model, no format retry, no fallback).

        Returns what the proposal is built from. A fixed answer replaces the first; a still inconsistent answer or
        a failed re-ask leaves the items marked `(값 확인 필요)` for the user to decide at `/ok`.
        """
        first = exchange.calls[-1]
        codes = list(dict.fromkeys(failure.code for _entry, failure in failures))
        model = self._settings.provider_settings(first.provider).retry_model or first.model
        counts = ", ".join(f"{code.value} x{sum(1 for _e, f in failures if f.code is code)}" for code in codes)
        self._log(f"llm interpret recheck: {counts}; asking again ({model or 'default model'})")
        second = self._call(
            chat_id,
            SchemaName.INTERPRET,
            PromptTask.INTERPRET,
            words,
            photo,
            exchange.data,
            parse_interpretation,
            web_search=self._web_search_on() and first.provider is ProviderName.CLAUDE,
            recheck_note=recheck_note([(entry.index, failure) for entry, failure in failures]),
            pin=RunPin(model),
            provider=first.provider,
        )
        exchange.calls.append(second)
        answer = self._usable_second_answer(chat_id, second, photo_digest, exchange.menu)
        if answer is None:
            outcome = RecheckOutcome.REASK_FAILED
            detail = "unusable answer" if second.ok else second.outcome.replace("_", " ")
            self._log(f"llm interpret recheck: re-ask failed ({detail}); shown with a marker")
            final = (_mark(entries, failures), interpretation, day, first)
        else:
            candidate, candidate_day, candidate_entries = answer
            exchange.outputs["interpret_first"] = interpretation.document
            exchange.outputs["interpret"] = candidate.document
            exchange.summary = candidate.memory_summary or exchange.summary
            again = _failures(candidate_entries)
            if again:
                outcome = RecheckOutcome.STILL_INCONSISTENT
                self._log("llm interpret recheck: still inconsistent; shown with a marker")
            else:
                outcome = RecheckOutcome.FIXED
                self._log("llm interpret recheck: fixed")
            final = (_mark(candidate_entries, again), candidate, candidate_day, second)
        exchange.recheck = {"reasons": [code.value for code in codes], "outcome": outcome.value}
        return final

    def _usable_second_answer(
        self, chat_id: int, second: LlmCallResult, photo_digest: str | None, menu: Proposal | None
    ) -> tuple[Interpretation, date, list[_Entry]] | None:
        """The re-ask's answer when it is still an eaten meal log with a date and items; else None."""
        if not second.ok:
            return None
        candidate: Interpretation = second.document
        if candidate.intent is not Intent.MEAL_LOG or candidate.tense is Tense.PLANNED:
            return None
        if photo_digest is not None and candidate.photo_kind is not PhotoKind.MEAL_PHOTO:
            return None
        day = resolve_date_expression(candidate.date_expression, self._today())
        if day is None:
            return None
        entries = self._link_items(chat_id, candidate, menu)
        return (candidate, day, entries) if entries else None

    # --- storing proposals ---------------------------------------------------------------------------------

    def _store_proposal(
        self,
        chat_id: int,
        exchange: _Exchange,
        day: date,
        default_meal: MealType | None,
        entries: Sequence[_Entry],
        source: NutritionSourceType,
        reference: str,
        label: str | None,
        *,
        cancel: str | None = None,
    ) -> None:
        """One meal: the v2 proposal. Two or more meals: one proposal that `/ok_` records meal by meal.

        ``cancel``: the token of the open proposal this one corrects; it is cancelled in the same state save.
        """
        meals: dict[MealType, list[_Entry]] = {}
        slot_from_time = False
        for group in group_meals(entries, default_meal):
            meal_type = group.meal_type
            if meal_type is None:
                meal_type, slot_from_time = meal_slot_for(self._now().time()), True
            meals.setdefault(meal_type, []).extend(group.items)
        searches = _searches(exchange.calls) or 0
        if len(meals) == 1:
            ((meal_type, items),) = meals.items()
            self._store_meal_proposal(
                chat_id,
                exchange,
                day,
                meal_type,
                items,
                [],
                source,
                reference,
                label,
                slot_from_time,
                searches=searches,
                cancel=cancel,
            )
            return
        commands = []
        blocks = []
        for meal_type, items in meals.items():
            existing = self._existing_meals(chat_id, day, meal_type)
            duplicates = tuple(meal.meal_id for meal in existing)
            head = ("nutrition", "log", "--date", day.isoformat(), "--meal", meal_type.value)
            tail = ("--additional",) if duplicates else ()
            argv_ok = (*head, *(arg for entry in items for arg in entry.argv(source, reference, True)), *tail)
            argv_plain = (*head, *(arg for entry in items for arg in entry.argv(source, reference, False)), *tail)
            has_estimate = any(entry.estimate for entry in items)
            commands.append(MealCommand(meal_type, argv_ok, argv_plain if has_estimate else ()))
            overlap = self._overlap(day, meal_type, existing, items, fixable=False)
            blocks.append(MealBlockView(meal_type, duplicates, _item_views(items), overlap[0]))
        proposal = self._new_proposal(
            chat_id,
            ProposalKind.MEAL,
            cancel=cancel,
            meals=tuple(commands),
            day=day,
            outline=_multi_outline(blocks),
        )
        exchange.proposal = proposal.token
        view = MultiMealProposalView(
            proposal.token,
            day,
            tuple(blocks),
            any(command.argv_plain for command in commands),
            searches,
            label,
            cancel,
        )
        exchange.reply = self._replies.multi_proposal(view)

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
        searches: int = 0,
        cancel: str | None = None,
    ) -> None:
        existing = self._existing_meals(chat_id, day, meal_type)
        duplicates = tuple(meal.meal_id for meal in existing)
        overlap, fix_argv, fix_change = self._overlap(
            day, meal_type, existing, entries, fixable=True, source=source, reference=reference
        )
        head = ("nutrition", "log", "--date", day.isoformat(), "--meal", meal_type.value)
        tail = ("--additional",) if duplicates else ()
        argv_ok = (*head, *(arg for entry in entries for arg in entry.argv(source, reference, True)), *tail)
        has_estimate = any(entry.estimate for entry in entries)
        argv_plain = (*head, *(arg for entry in entries for arg in entry.argv(source, reference, False)), *tail)
        views = _item_views(entries)
        proposal = self._new_proposal(
            chat_id,
            ProposalKind.MEAL,
            cancel=cancel,
            argv_ok=argv_ok,
            argv_plain=argv_plain if has_estimate else (),
            meal_type=meal_type,
            day=day,
            outline=_outline(views),
            fix_argv=fix_argv,
            fix_change=fix_change,
        )
        exchange.proposal = proposal.token
        view = MealProposalView(
            proposal.token,
            meal_type,
            day,
            label,
            slot_from_time,
            duplicates,
            views,
            tuple(dropped),
            has_estimate,
            failed_photo,
            searches,
            cancel,
            overlap,
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

    def _existing_meals(self, chat_id: int, day: date, meal_type: MealType) -> tuple[Meal, ...]:
        try:
            meals = self._meals.list_eaten_between(*local_day_bounds(day, self._local_timezone(day)))
        except Exception as exc:  # a missing or unreadable DB: `nutrition log` itself refuses a duplicate
            self._log(f"chat {chat_id}: existing meals not read ({type(exc).__name__})")
            return ()
        return tuple(meal for meal in meals if meal.meal_type is meal_type)

    def _overlap(
        self,
        day: date,
        meal_type: MealType,
        existing: Sequence[Meal],
        entries: Sequence[_Entry],
        *,
        fixable: bool,
        source: NutritionSourceType = NutritionSourceType.LANGUAGE_ESTIMATE,
        reference: str = "",
    ) -> tuple[OverlapView | None, tuple[str, ...], str]:
        """The overlap notice of a proposed meal and, for a single-meal proposal, its one `/fix_` command.

        Deterministic: a catalog food by ID, a general item by normalized memo. `/fix_` makes the recorded meal equal
        to the proposal and is offered only when exactly one command does it (a replace of one differing item, or
        one add of all the new items); several commands, or nothing to change, are hinted instead.
        """
        candidates = [
            Candidate(
                entry.food_id, entry.memo if entry.food_id is None else None, entry.estimate, entry.quantity, entry.unit
            )
            for entry in entries
        ]
        overlaps = find_overlaps(existing, candidates)
        if not overlaps:
            return None, (), ""
        when = "오늘" if day == self._today() else f"{day:%m-%d}"
        names = tuple(dict.fromkeys(overlap_name(overlap.item) for overlap in overlaps))
        plan = plan_fix(overlaps, len(entries)) if fixable else None
        argv: tuple[str, ...] = ()
        change = ""
        if plan is not None and plan.operations == 1:
            argv, change = _fix_command(plan, entries, source, reference)
        hint = None
        if fixable and not argv:
            hint = OVERLAP_SAME_TEXT if plan is not None and plan.operations == 0 else OVERLAP_MANY_TEXT
        view = OverlapView(meal_type, overlaps[0].meal.meal_id, names, when, bool(argv), hint)
        return view, argv, change

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
            protein_remaining = _display_text(remaining) if isinstance(remaining, str) else None
            kcal_budget = display_remaining(context.budget) if context.budget is not None else None
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
        """A correction of a recorded meal as an edit proposal (nothing is written before `/ok`).

        The LLM only extracts words; the meal and the item are found here and never guessed: a target that is not
        exactly one meal (or item) gives the candidates and writes nothing.
        """
        edit = interpretation.edit
        if edit.action is None:
            exchange.reply = ReplyText(EDIT_UNCLEAR_TEXT)
            return
        pool = self._edit_pool(chat_id, interpretation, exchange)
        if pool is None:
            return
        action = edit.action
        if action in (EditAction.VOID_MEAL, EditAction.CHANGE_MEAL_TYPE, EditAction.ADD_ITEM):
            self._edit_meal(chat_id, interpretation, pool, exchange)
            return
        target = self._edit_item(pool, edit.target_food_text, exchange)
        if target is None:
            return
        meal, item = target.meal, target.item
        number = item.sequence
        before = _item_text(item)
        name = f"{MEAL_NAMES[meal.meal_type]} {meal.meal_id} item {number}"
        if action is EditAction.REMOVE_ITEM:
            remove: tuple[str, ...] = ("nutrition", "meal", "remove-item", meal.meal_id, "--item-number", str(number))
            self._store_edit(chat_id, exchange, meal, remove, f"{name}: {before} 빼기")
            return
        if action is EditAction.CHANGE_ESTIMATE:
            self._edit_estimate(chat_id, interpretation, meal, item, name, before, exchange)
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
        self._store_edit(chat_id, exchange, meal, replace_argv, f"{name}: {before} → {replacement[1]}")

    def _edit_pool(self, chat_id: int, interpretation: Interpretation, exchange: _Exchange) -> tuple[Meal, ...] | None:
        """The meals a correction may be about, or None with the reply already set.

        `last_recorded`: the chat's last recorded meals (at most two). Otherwise the day's active meals, narrowed by
        the meal type and by the ordinal (`아침 1식` is the 1st active breakfast, not the ID suffix). An ordinal
        always means the day's meals; an ordinal without a meal type is never resolved.
        """
        edit = interpretation.edit
        if interpretation.refers_to is Refers.LAST_RECORDED and edit.ordinal is None:
            recent = self._recent_meals(chat_id)
            if interpretation.meal_type is not None:
                recent = tuple(meal for meal in recent if meal.meal_type is interpretation.meal_type)
            if not recent:
                exchange.reply = ReplyText(EDIT_NO_RECENT_TEXT)
                return None
            return recent
        day = resolve_date_expression(interpretation.date_expression, self._today())
        if day is None:
            exchange.reply = ReplyText(DATE_OTHER_TEXT)
            return None
        try:
            day_meals = self._meals.list_eaten_between(*local_day_bounds(day, self._local_timezone(day)))
        except Exception as exc:
            self._log(f"chat {chat_id}: meals not read for an edit ({type(exc).__name__})")
            day_meals = ()
        if edit.ordinal is not None and interpretation.meal_type is None and day_meals:
            exchange.reply = self._replies.candidates([meal.meal_id for meal in day_meals])
            return None
        meals = pick_meals(day_meals, interpretation.meal_type, edit.ordinal)
        if not meals:
            exchange.reply = ReplyText(EDIT_NO_MEAL_TEXT)
            return None
        return meals

    def _exact_food_id(self, text: str | None) -> str | None:
        """The catalog food the words name exactly (None when there is none or the name is ambiguous)."""
        if text is None:
            return None
        try:
            return ResolveFoodReference(self._catalog).execute(text, label="")
        except NutritionLoggingError:
            return None

    def _edit_meal(
        self, chat_id: int, interpretation: Interpretation, pool: Sequence[Meal], exchange: _Exchange
    ) -> None:
        """`void_meal`, `change_meal_type` and `add_item`: the one meal of the pool (the words narrow it)."""
        edit = interpretation.edit
        action = edit.action
        matched = tuple(pool)
        if edit.target_food_text is not None and action is not EditAction.ADD_ITEM:
            refs = match_items(pool, food_id=self._exact_food_id(edit.target_food_text), text=edit.target_food_text)
            with_item = {ref.meal.meal_id for ref in refs}
            if with_item:
                matched = tuple(meal for meal in pool if meal.meal_id in with_item)
        if len(matched) != 1:
            exchange.reply = self._replies.candidates([meal.meal_id for meal in matched])
            return
        meal = matched[0]
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
        self._store_edit(chat_id, exchange, meal, argv, change)

    def _edit_item(self, pool: Sequence[Meal], target_text: str | None, exchange: _Exchange) -> ItemRef | None:
        """The one item the words name, or None with the candidates replied (nothing is guessed)."""
        everything = [ItemRef(meal, item) for meal in pool for item in meal.items]
        if target_text is None:
            refs = everything
        else:
            refs = list(match_items(pool, food_id=self._exact_food_id(target_text), text=target_text))
        if len(refs) == 1:
            return refs[0]
        meal_ids = list(dict.fromkeys(ref.meal.meal_id for ref in refs))
        if len(meal_ids) > 1 or (not refs and len(pool) > 1):
            exchange.reply = self._replies.candidates(meal_ids or [meal.meal_id for meal in pool])
            return None
        listed = refs or everything
        exchange.reply = self._replies.item_candidates(
            [f"{ref.meal.meal_id} item {ref.item.sequence}: {item_summary(ref.item)}" for ref in listed]
        )
        return None

    def _edit_estimate(
        self,
        chat_id: int,
        interpretation: Interpretation,
        meal: Meal,
        item: MealItem,
        name: str,
        before: str,
        exchange: _Exchange,
    ) -> None:
        """`change_estimate`: replace a general item by one with the merged estimate and/or the new memo.

        Only the nutrients the user named change; the others keep their stored range (a nutrient that was never
        known stays unknown). The merged estimate runs the usual numeric checks; a failure only marks the proposal
        (`값 확인 필요`, no re-ask) and the reference.
        """
        edit = interpretation.edit
        if not item.is_general:
            exchange.reply = ReplyText(EDIT_CATALOG_ESTIMATE_TEXT)
            return
        current = general_ranges(item)
        merged = merge_estimate(current, edit.estimate)
        memo = clean_memo(edit.new_memo) if edit.new_memo else item_memo(item)
        fact = item.general_estimate
        label = edit.from_label and bool(edit.estimate) and all(low == high for _n, low, high in edit.estimate)
        codes: tuple[CheckCode, ...] = ()
        args: list[str] = ["--general"]
        if memo:
            args.append(f"--general-note={memo}")
        if merged and fact is not None and not edit.estimate:
            # A memo-only edit sends the stored estimate again, with its own source and reference.
            args.append(f"--general-estimate={format_general_estimate(fact.provenance.source_type, merged)}")
            args.append(f"--general-estimate-ref={fact.provenance.source_reference}")
        elif merged:
            codes = tuple(
                dict.fromkeys(
                    failure.code for failure in check_estimate(merged, assumption=None, quantity=None, label=label)
                )
            )
            call = exchange.calls[-1]
            reference = estimate_reference(
                f"telegram-llm edit ({call.provider.value} {call.model or 'default'})",
                None,
                None,
                check_needed=bool(codes),
                label=label,
            )
            args.append(f"--general-estimate={format_general_estimate(estimate_source(False), merged)}")
            args.append(f"--general-estimate-ref={reference}")
        lines = [f"{name}: {before}"]
        old = {nutrient: (low, high) for nutrient, low, high in current}
        for nutrient, low, high in edit.estimate:
            unit = "" if nutrient is NutrientField.CALORIES_KCAL else " g"
            was = f"{_range_text(old[nutrient])}{unit}" if nutrient in old else "알 수 없음"
            line = f"  {NUTRIENT_NAMES[nutrient]} {was} → {_range_text((low, high))}{unit}"
            lines.append(line + (" (라벨)" if label else "") + (f" {CHECK_MARKER}" if codes else ""))
        if edit.new_memo and memo != item_memo(item):
            lines.append(f"  메모: {item_memo(item) or '없음'} → {memo}")
        if codes:
            lines.append(f"  {CHECK_LINE_HEAD}{', '.join(CHECK_REASON_TEXTS[code] for code in codes)}")
        argv = (
            "nutrition",
            "meal",
            "replace-item",
            meal.meal_id,
            "--item-number",
            str(item.sequence),
            *args,
        )
        self._store_edit(chat_id, exchange, meal, argv, "\n".join(lines))

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

    def _store_edit(self, chat_id: int, exchange: _Exchange, meal: Meal, argv: tuple[str, ...], change: str) -> None:
        # The edit proposal records the meal's own day, so the totals after `/ok` are that day's.
        day = meal.eaten_at.astimezone(self._local_timezone(meal.eaten_at.date())).date()
        proposal = self._new_proposal(chat_id, ProposalKind.EDIT, argv_ok=argv, meal_id=meal.meal_id, day=day)
        exchange.proposal = proposal.token
        exchange.reply = self._replies.edit(EditView(proposal.token, change, " ".join(argv)))

    # --- proposal commands -------------------------------------------------------------------------------

    def _proposal_command(self, chat_id: int, update_id: int, command: ProposalCommand) -> LlmAction:
        kind = {"ok": "confirm", "plain": "plain", "no": "cancel", "eat": "eat", "fix": "fix"}[command.action]
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
        if command.action == "fix":
            return self._fix(chat_id, update_id, proposal)
        refused = self._migration_refusal(chat_id)
        if refused is not None:  # not consumed: it can be confirmed once the migration is applied
            return self._simple(chat_id, update_id, kind, refused, proposal=proposal.token, typed=typed)
        self._update(state, proposal.with_state(ProposalState.USED))  # before it runs: at most once
        if proposal.meals:
            self._log(f"chat {chat_id}: proposal {proposal.token} confirmed ({len(proposal.meals)} meals)")
            return self._run_meals(chat_id, update_id, proposal, command.action, kind, typed)
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
                totals = self._totals_line(chat_id, proposal.day)
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

    def _run_meals(
        self, chat_id: int, update_id: int, proposal: Proposal, action: str, kind: str, typed: str
    ) -> LlmAction:
        """`/ok_` or `/plain_` of a multi-meal proposal: one `nutrition log` per meal, in order, stopping at the
        first failure. Meals already recorded stay recorded (each has its own undo line)."""
        plain = action == "plain"
        meals = proposal.meals
        invocations = tuple(
            CliInvocation(
                "plain" if plain else "ok",
                (meal.argv_plain or meal.argv_ok) if plain else meal.argv_ok,
                True,
                False,
                True,
            )
            for meal in meals
        )

        def on_done(steps: tuple[SequenceStep, ...]) -> str:
            blocks: list[str] = []
            recorded: list[str] = []
            failed: MealType | None = None
            failed_code = 0
            for meal, step in zip(meals, steps, strict=False):
                if step.ok:
                    blocks.append(step.text)
                    meal_id = _recorded_meal_id(step.outcome.stdout) if step.outcome is not None else None
                    if meal_id is not None:
                        recorded.append(meal_id)
                else:
                    failed = meal.meal_type
                    failed_code = step.outcome.exit_code if step.outcome is not None and step.outcome.exit_code else 1
                    blocks.append(sequence_failed_line(meal.meal_type, step.text))
            not_run = [meal.meal_type for meal in meals[len(steps) :]]
            if failed is not None and not_run:
                blocks[-1] = f"{blocks[-1]}\n{sequence_not_run_line(not_run)}\n{SEQUENCE_HINT}"
            text = "\n\n".join(blocks)
            if recorded:
                totals = self._totals_line(chat_id, proposal.day)
                if totals is not None:
                    text = f"{text}\n{totals}" if failed is not None else f"{text}\n\n{totals}"
            result = {
                "exit_code": failed_code,
                "meal_id": recorded[0] if recorded else None,
                "meal_ids": recorded,
                "failed": failed.value if failed is not None else None,
                "not_run": [meal.value for meal in not_run],
            }
            self._append_history(
                chat_id,
                history_entry(
                    update_id=update_id,
                    at=self._at(),
                    chat_id=chat_id,
                    kind=kind,
                    text=typed,
                    reply=text,
                    proposal=proposal.token,
                    result=result,
                ),
            )
            return text

        return RunConfirmedSequence(invocations, on_done)

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
            if is_menu:
                return menu_expired_text(proposal.expires_unix - proposal.created_unix)
            return PROPOSAL_EXPIRED_TEXT
        if command.action == "plain" and not proposal.plain_available:
            return PROPOSAL_NO_PLAIN_TEXT.format(token=proposal.token)
        if command.action == "fix" and (proposal.kind is not ProposalKind.MEAL or not proposal.fix_argv):
            return PROPOSAL_WRONG_KIND_TEXT
        return None

    def _fix(self, chat_id: int, update_id: int, overlap: Proposal) -> LlmAction:
        """`/fix_<token>`: the recorded meal is corrected instead of recording another one. Nothing is written
        here: a new edit proposal (`/ok_` runs the stored command) replaces the overlap proposal in one state save,
        so the overlap proposal's `/ok_` and `/fix_` stop working."""
        meal_id = overlap.fix_argv[3]  # nutrition meal replace-item|add-item <meal_id> ...
        proposal = self._new_proposal(
            chat_id, ProposalKind.EDIT, cancel=overlap.token, argv_ok=overlap.fix_argv, meal_id=meal_id, day=overlap.day
        )
        exchange = _Exchange(intent="fix", proposal=proposal.token)
        exchange.reply = self._replies.edit(EditView(proposal.token, overlap.fix_change, " ".join(overlap.fix_argv)))
        self._record(chat_id, exchange, update_id=update_id, kind="fix", text=f"/fix_{overlap.token}")
        self._log(f"chat {chat_id}: proposal {overlap.token} fixed into edit proposal {proposal.token}")
        return LlmReply(tuple(self._replies.messages(exchange.reply)))

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
        *,
        web_search: bool = False,
        recheck_note: str | None = None,
        pin: RunPin | None = None,
        provider: ProviderName | None = None,
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
            web_search_max=self._settings.web_search_max if web_search else None,
            recheck_note=recheck_note,
        )
        request = LlmRequest(prompt, schema, photo, validate, web_search=web_search, pin=pin)
        result = self._provider.call(request, provider if provider is not None else self.active_provider())
        self._log(f"chat {chat_id}: llm {schema.value} -> {result.outcome} ({result.provider.value})")
        return result

    def _web_search_on(self) -> bool:
        """Interpret calls (text and photo) offer the search tool when it is on and Claude can answer."""
        if not self._settings.web_search:
            return False
        return ProviderName.CLAUDE in (self.active_provider(), self._settings.fallback_provider)

    def _catalog_data(self, chat_id: int, words: str) -> tuple[tuple[str, Any], ...]:
        """The `[카탈로그]` data pair of an interpret call: the foods the LLM may link by ID (none when unreadable)."""
        try:
            profiles = self._catalog.list_all()
        except Exception as exc:  # exact lookup still works without the list
            self._log(f"chat {chat_id}: catalog list not read ({type(exc).__name__})")
            return ()
        prompt = catalog_prompt(profiles, words)
        if prompt is None:
            return ()
        if prompt.shown < prompt.total:
            self._log(f"chat {chat_id}: catalog list cut: {prompt.shown} of {prompt.total}")
        return (("카탈로그", prompt.text),)

    def _interpret_data(
        self, chat_id: int, words: str, exchange: _Exchange, *, text_only: bool
    ) -> tuple[tuple[str, Any], ...]:
        """The `[데이터]` pairs of an interpret call: the catalog and, for a text message, the chat's last recorded
        meals, its open meal proposal and its recent menu (a block with nothing in it is left out)."""
        data = list(self._catalog_data(chat_id, words))
        if not text_only:
            return tuple(data)
        recent = self._recent_meals(chat_id)
        if recent:
            data.append(("직전 기록", recent_meals_block(recent)))
        opened = self._open_meal_proposal(chat_id)
        if opened is not None and opened.outline:
            data.append(("열린 제안", open_proposal_block(opened)))
        exchange.menu = recent_menu(self._proposals.load().proposals, chat_id=chat_id, now_unix=self._now_unix())
        if exchange.menu is not None:
            data.append(("최근 메뉴", menu_block(exchange.menu)))
        return tuple(data)

    def _recent_meals(self, chat_id: int) -> tuple[Meal, ...]:
        """The chat's last `RECENT_MEALS` recorded meals that are still active, newest first.

        From the history (confirm, plain and edit lines, no time limit), so it survives a restart. History writes are
        best effort: a lost line means the meal is not known here.
        """
        try:
            entries = self._history.read(last=HISTORY_SCAN)
            found: list[Meal] = []
            for meal_id in recent_meal_ids(entries, chat_id=chat_id):
                meal = self._meals.get_active(meal_id)
                if meal is not None:
                    found.append(meal)
                if len(found) == RECENT_MEALS:
                    break
        except Exception as exc:
            self._log(f"chat {chat_id}: recent meals not read ({type(exc).__name__})")
            return ()
        return tuple(found)

    def _open_meal_proposal(self, chat_id: int) -> Proposal | None:
        """The chat's newest meal proposal that can still be confirmed (open, not expired), or None."""
        now = int(self._now().timestamp())
        open_ones = [
            proposal
            for proposal in self._proposals.load().proposals
            if proposal.chat_id == chat_id
            and proposal.kind is ProposalKind.MEAL
            and proposal.state is ProposalState.OPEN
            and now < proposal.expires_unix
        ]
        return max(open_ones, key=lambda proposal: proposal.created_unix, default=None)

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
            web_searches=_searches(exchange.calls),
            recheck=exchange.recheck,
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

    def _new_proposal(self, chat_id: int, kind: ProposalKind, *, cancel: str | None = None, **fields: Any) -> Proposal:
        """Store a new open proposal in one state save; ``cancel`` is an open proposal of this chat that it replaces,
        left cancelled by the same save (so at no point are both open)."""
        state = self._proposals.load()
        now = int(self._now().timestamp())
        proposals = prune_proposals(state.proposals, now)
        if cancel is not None:
            proposals = tuple(
                item.with_state(ProposalState.CANCELLED)
                if item.token == cancel and item.chat_id == chat_id and item.state is ProposalState.OPEN
                else item
                for item in proposals
            )
        used = {proposal.token for proposal in proposals}
        token = self._new_token()
        for _attempt in range(100):
            if token not in used:
                break
            token = self._new_token()
        else:
            raise RuntimeError("no free proposal token")
        lifetime = MENU_PROPOSAL_TTL_S if kind is ProposalKind.MENU else PROPOSAL_TTL_S
        proposal = Proposal(token, chat_id, kind, now, now + lifetime, ProposalState.OPEN, **fields)
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

    def _totals_line(self, chat_id: int, day: date | None = None) -> str | None:
        """The running totals of ``day`` (today when None): `오늘 누적` for today, `MM-DD 누적` for another day."""
        shown = day if day is not None and day != self._today() else None
        extra = ("--date", shown.isoformat()) if shown is not None else ()
        status = self._read_json(chat_id, ("nutrition", "status", *extra, "--json"))
        day_document = self._read_json(chat_id, ("nutrition", "day", *extra, "--json"))
        if status is None or day_document is None:
            return None
        try:
            return totals_text(
                today_totals(status, day_document), f"{shown:%m-%d}" if shown is not None else TODAY_LABEL
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._log(f"chat {chat_id}: today totals not computed ({type(exc).__name__})")
            return None

    def _reference(self, call: LlmCallResult, photo_digest: str | None) -> str:
        what = f"photo sha256:{photo_digest[:12]}" if photo_digest is not None else "text"
        return f"telegram-llm {what} ({call.provider.value} {call.model or 'default'})"

    def _today(self) -> date:
        return self._now().date()

    def _now_unix(self) -> int:
        return int(self._now().timestamp())

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
    hint: str | None = None
    """A command that registers the missing unit (shown under the item)."""
    via: str | None = None
    """The user's own word, when the LLM's catalog ID linked the item (shown as `← "word"`)."""
    source: str | None = None
    assumption: str | None = None
    index: int = 0
    """The item's 1-based number in the LLM's answer (for the re-ask note)."""
    meal_type: MealType | None = None
    own_quantity: Decimal | None = None
    """The quantity the user gave a general item (the assumption may mention it)."""
    check: tuple[CheckCode, ...] = ()
    """The numeric checks this estimate still fails after the re-check: it is marked `(값 확인 필요)`."""
    label: bool = False
    """The values are single values read from a nutrition label (shown as `라벨:`, stored as an estimate)."""
    portions: tuple[Portion, ...] = ()
    """The grams the LLM assumed per component (shown as `양 가정:`, kept in the estimate reference)."""
    menu_source: NutritionSourceType | None = None
    """A recent menu item the user picked by name: its source type, reference and printed flag replace the
    proposal's, and the values are not re-checked (they come from a list the user already saw)."""
    menu_reference: str | None = None
    printed: bool = False

    def argv(self, source: NutritionSourceType, reference: str, with_estimate: bool) -> tuple[str, ...]:
        if self.food_id is not None and self.quantity is not None and self.unit is not None:
            return ("--item", self.food_id, amount_text(self.quantity), self.unit.value)
        args = ["--general"]
        if self.memo:
            args.append(f"--general-note={self.memo}")
        if with_estimate and self.estimate:
            args.append(f"--general-estimate={format_general_estimate(self.menu_source or source, self.estimate)}")
            if self.menu_reference is not None:
                args.append(f"--general-estimate-ref={estimate_reference(self.menu_reference, None, None)}")
            elif reference:
                note = estimate_reference(
                    reference,
                    self.source,
                    self.assumption,
                    check_needed=bool(self.check),
                    label=self.label,
                    portions=self.portions,
                )
                args.append(f"--general-estimate-ref={note}")
        return tuple(args)

    def display(self) -> str:
        if self.food_id is not None:
            text = self.memo or self.food_id
            return f'{text} ← "{self.via}"' if self.via else text
        return f"일반식 (메모: {self.memo})" if self.memo else "일반식"


def _item_views(entries: Sequence[_Entry]) -> tuple[ProposalItemView, ...]:
    return tuple(
        ProposalItemView(
            entry.display(),
            entry.quantity_estimated,
            entry.reason,
            entry.estimate,
            entry.hint,
            entry.assumption if entry.food_id is None else None,
            entry.source if entry.food_id is None else None,
            entry.check,
            entry.label,
            portions_text(entry.portions) if entry.food_id is None else None,
            entry.printed,
        )
        for entry in entries
    )


def _fix_command(
    plan: FixPlan, entries: Sequence[_Entry], source: NutritionSourceType, reference: str
) -> tuple[tuple[str, ...], str]:
    """The single command that makes the recorded meal equal to the proposal, and what it changes."""
    meal = plan.meal
    name = f"{MEAL_NAMES[meal.meal_type]} {meal.meal_id}"
    if plan.replacements:
        overlap = plan.replacements[0]
        entry = entries[overlap.index]
        number = overlap.item.sequence
        argv = (
            "nutrition",
            "meal",
            "replace-item",
            meal.meal_id,
            "--item-number",
            str(number),
            *entry.argv(source, reference, True),
        )
        return argv, _replace_change(name, number, overlap.item, entry)
    added = [entries[index] for index in plan.additions]
    argv = (
        "nutrition",
        "meal",
        "add-item",
        meal.meal_id,
        *(arg for entry in added for arg in entry.argv(source, reference, True)),
    )
    return argv, f"{name}: 추가 {'; '.join(_valued(entry) for entry in added)}"


def _valued(entry: _Entry) -> str:
    """An entry as the user is asked to confirm it: its name and, for an estimate, the values it would store."""
    if entry.food_id is not None or not entry.estimate:
        return entry.display()
    text = f"{entry.display()}: {ranges_summary(entry.estimate)}"
    if entry.label:
        text += " (라벨)"
    return f"{text} {CHECK_MARKER}" if entry.check else text


def _replace_change(name: str, number: int, old: MealItem, entry: _Entry) -> str:
    """What `/fix_` replaces. A general item has the same name on both sides, so the values that change (the stored
    range and the proposed one, with its label or check marker) are shown on a line of their own."""
    head = f"{name} item {number}: {item_summary(old)}"
    if entry.food_id is not None:
        return f"{head} → {entry.display()}"
    was = ranges_summary(general_ranges(old)) or "값 없음"
    now = ranges_summary(entry.estimate) or "값 없음"
    line = f"  {was} → {now}" + (" (라벨)" if entry.label else "") + (f" {CHECK_MARKER}" if entry.check else "")
    lines = [head, line]
    if entry.check:
        lines.append(f"  {CHECK_LINE_HEAD}{', '.join(CHECK_REASON_TEXTS[code] for code in entry.check)}")
    return "\n".join(lines)


def _menu_entry(index: int, item: InterpretItem, menu: Proposal | None) -> _Entry | None:
    """The entry for an item the user picked from the recent menu by name, or None when `menu_ref` is unset or does
    not check out (no menu, a number out of range, or a name that does not agree with the menu item's)."""
    ref = item.menu_ref
    if ref is None or menu is None or not 1 <= ref <= len(menu.choices):
        return None
    choice = menu.choices[ref - 1]
    if not menu_name_matches(item.food_text, choice.memo):
        return None
    where = "메뉴판 표기" if choice.printed else "메뉴 항목"
    return _Entry(
        None,
        None,
        None,
        choice.memo,
        choice.ranges,
        False,
        None,
        index=index,
        meal_type=item.meal_type,
        menu_source=menu.source or NutritionSourceType.VISUAL_ESTIMATE,
        menu_reference=f"{menu.reference or 'telegram-llm menu'}; {where}",
        printed=choice.printed,
    )


def _outline(views: Sequence[ProposalItemView], *, indent: str = "") -> tuple[str, ...]:
    """The item lines of a meal proposal as the LLM sees them while it is open (`1. 일반식 (메모: ...) | 라벨: ...`)."""
    lines = []
    for number, view in enumerate(views, start=1):
        text = f"{indent}{number}. {view.text}"
        if view.estimate:
            text += f" | {'라벨' if view.label else '추정'}: {ranges_summary(view.estimate)}"
        lines.append(text)
    return tuple(lines)


def _multi_outline(blocks: Sequence[MealBlockView]) -> tuple[str, ...]:
    lines: list[str] = []
    for block in blocks:
        lines.append(MEAL_NAMES[block.meal_type])
        lines.extend(_outline(block.items, indent="  "))
    return tuple(lines)


def _failures(entries: Sequence[_Entry]) -> list[tuple[_Entry, CheckFailure]]:
    """The failed numeric checks of the entries that will be stored as general estimates."""
    return [
        (entry, failure)
        for entry in entries
        if entry.food_id is None and entry.estimate
        if entry.menu_source is None
        for failure in check_estimate(
            entry.estimate,
            assumption=entry.assumption,
            quantity=entry.own_quantity,
            label=entry.label,
            portions=entry.portions,
        )
    ]


def _mark(entries: Sequence[_Entry], failures: Sequence[tuple[_Entry, CheckFailure]]) -> list[_Entry]:
    """The entries with the codes they fail attached (those that pass are the same objects)."""
    marked = []
    for entry in entries:
        codes = tuple(dict.fromkeys(failure.code for failed, failure in failures if failed.index == entry.index))
        marked.append(replace(entry, check=codes) if codes else entry)
    return marked


def _searches(calls: Sequence[LlmCallResult]) -> int | None:
    """The web searches of all LLM calls of one message; None when no call was offered the tool."""
    counts = [call.web_searches for call in calls if call.web_searches is not None]
    return sum(counts) if counts else None


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


def _range_text(bounds: tuple[Decimal, Decimal]) -> str:
    low, high = bounds
    return amount_text(low) if low == high else f"{amount_text(low)}~{amount_text(high)}"


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


def _display_text(text: str) -> str:
    """A decimal string of the CLI's JSON as the CLI prints it (rounded to 0.1); other text is left as it is."""
    try:
        return display_remaining(Decimal(text))
    except InvalidOperation:
        return text


def _digest(photo: bytes) -> str:
    return hashlib.sha256(photo).hexdigest()


def _data_text(document: Any) -> str:
    return document if isinstance(document, str) else json.dumps(document, ensure_ascii=False, indent=1)
