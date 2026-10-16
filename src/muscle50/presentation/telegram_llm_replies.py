"""Telegram LLM v2 presentation: proposal, menu, edit and `/history` replies, and `telegram history` output.

Bot replies are Korean; the body goes in `<pre>` and the `/ok_...`, `/eat_...` lines after it, outside
`<pre>`, so one tap sends them (`BotReply`). Every number shown comes from the validated LLM output or
the CLI's own JSON; estimates are always shown as ranges marked `estimated`. The `telegram history`
CLI text uses ASCII labels (message and reply text are the user's own); its JSON is the stored lines.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from muscle50.application.telegram_llm import (
    EditView,
    MealProposalView,
    MenuLineView,
    MenuView,
    MultiMealProposalView,
    OverlapView,
    ProposalItemView,
    ReplyText,
)
from muscle50.domain.llm_today_totals import amount_text, display_amount
from muscle50.domain.menu_ranking import RankMode
from muscle50.domain.nutrition import MealType, NutrientField
from muscle50.domain.telegram_llm import NutrientRanges
from muscle50.domain.telegram_llm_check import CHECK_REASON_TEXTS, OUTCOME_HISTORY_TEXTS, RecheckOutcome
from muscle50.domain.telegram_llm_prompt import (
    CHECK_LINE_HEAD,
    CHECK_MARKER,
    HISTORY_EMPTY_TEXT,
    MEAL_NAMES,
    duplicate_text,
    multi_proposal_head,
    overlap_text,
    photo_failed_head,
    proposal_head,
    superseded_line,
    web_search_line,
)
from muscle50.presentation.telegram_format import BotReply, reply_messages

_NUTRIENT_NAMES = {
    NutrientField.CALORIES_KCAL: "kcal",
    NutrientField.PROTEIN_G: "단백질",
    NutrientField.CARBOHYDRATE_G: "탄수화물",
    NutrientField.FAT_G: "지방",
}
_KIND_NAMES = {
    "text": "문장",
    "photo": "사진",
    "confirm": "확인",
    "plain": "일반식만 확인",
    "cancel": "취소",
    "eat": "메뉴 고르기",
    "edit": "수정 확인",
    "fix": "고치기 선택",
}
MEAL_NAMES_BY_VALUE = {meal.value: name for meal, name in MEAL_NAMES.items()}
_INTENT_NAMES = {
    "meal_log": "식사 기록",
    "question": "질문",
    "menu": "메뉴",
    "menu_suggest": "메뉴 제안",
    "meal_edit": "식사 수정",
    "chat": "잡담",
    "unclear": "모름",
    "eat": "메뉴 고르기",
    "fix": "고치기 선택",
}


class TelegramLlmReplies:
    """The `LlmReplies` port."""

    def messages(self, reply: ReplyText) -> list[str]:
        rich = tuple(((line,),) for line in reply.commands)
        return reply_messages(BotReply(reply.body, rich))

    def proposal(self, view: MealProposalView) -> ReplyText:
        return proposal_reply(view)

    def multi_proposal(self, view: MultiMealProposalView) -> ReplyText:
        return multi_proposal_reply(view)

    def menu(self, view: MenuView) -> ReplyText:
        return menu_reply(view)

    def edit(self, view: EditView) -> ReplyText:
        return ReplyText(f"이렇게 고칠까요?\n{view.change}", (f"고치기: /ok_{view.token}   취소: /no_{view.token}",))

    def candidates(self, meal_ids: Sequence[str]) -> ReplyText:
        lines = ["어느 식사(또는 음식)인지 하나로 정하지 못해 아무것도 바꾸지 않았습니다. 후보:"]
        lines.extend(f"/show {meal_id}" for meal_id in meal_ids)
        lines.append("끼니와 음식 이름을 더 구체적으로 적어 다시 보내 주세요.")
        return ReplyText("\n".join(lines))

    def item_candidates(self, lines: Sequence[str]) -> ReplyText:
        head = "어느 음식인지 하나로 정하지 못해 아무것도 바꾸지 않았습니다. 후보:"
        return ReplyText("\n".join([head, *lines, "음식 이름을 더 구체적으로 적어 다시 보내 주세요."]))

    def history(self, entries: Sequence[dict[str, Any]]) -> ReplyText:
        return ReplyText(history_text(entries))


def proposal_reply(view: MealProposalView) -> ReplyText:
    day = view.day.isoformat()[5:]
    # What the proposal does to an already recorded meal is the first thing the user reads.
    lines = _overlap_lines(view.overlap, view.duplicates, view.meal_type)
    if view.failed_photo:
        lines.append(photo_failed_head(view.meal_type, day))
    else:
        lines.append(proposal_head(view.meal_type, day, view.label))
    if view.slot_from_time:
        lines.append("(끼니: 지금 시각 기준)")
    for number, item in enumerate(view.items, start=1):
        lines.extend(_item_lines(number, item, indent=""))
    lines.extend(view.dropped)
    if view.searches:
        lines.append(web_search_line(view.searches))
    if view.superseded:
        lines.append(superseded_line(view.superseded))
    token = view.token
    plain = f"   일반식만 기록(값 없이): /plain_{token}" if view.plain else ""
    overlap = view.overlap
    if overlap is None:
        return ReplyText("\n".join(lines), (f"기록: /ok_{token}{plain}   취소: /no_{token}",))
    fix = f"기존 {MEAL_NAMES[overlap.meal_type]} 고치기: /fix_{token}   " if overlap.fix else ""
    return ReplyText("\n".join(lines), (f"{fix}하나 더 기록: /ok_{token}{plain}   취소: /no_{token}",))


def multi_proposal_reply(view: MultiMealProposalView) -> ReplyText:
    """Two or more meals: one block per meal; one `/ok_` records them all, meal by meal."""
    lines: list[str] = []
    for block in view.meals:
        lines.extend(_overlap_lines(block.overlap, block.duplicates, block.meal_type, hints=False))
    lines.append(multi_proposal_head(view.day.isoformat()[5:], len(view.meals), view.label))
    for block in view.meals:
        lines.append(MEAL_NAMES[block.meal_type])
        for number, item in enumerate(block.items, start=1):
            lines.extend(_item_lines(number, item, indent="  "))
    if view.searches:
        lines.append(web_search_line(view.searches))
    if view.superseded:
        lines.append(superseded_line(view.superseded))
    token = view.token
    plain = f"   값 없이 일반식만 기록: /plain_{token}" if view.plain else ""
    record = "기록(겹치는 끼니는 하나 더)" if any(block.overlap for block in view.meals) else "기록"
    return ReplyText("\n".join(lines), (f"{record}: /ok_{token}{plain}   취소: /no_{token}",))


def _overlap_lines(
    overlap: OverlapView | None, duplicates: Sequence[str], meal_type: MealType, *, hints: bool = True
) -> list[str]:
    """The first lines of a proposal that lands in a day's meal of the same type: the overlap notice (with why
    there is no `/fix_`), or the `--additional` notice when nothing overlaps."""
    if overlap is not None:
        lines = [overlap_text(overlap.when, overlap.meal_type, overlap.meal_id, overlap.names)]
        if hints and overlap.hint:
            lines.append(overlap.hint)
        return lines
    return [duplicate_text(meal_type, duplicates)] if duplicates else []


def _item_lines(number: int, item: ProposalItemView, *, indent: str) -> list[str]:
    """The item line and its detail lines (estimate, check reasons, assumption, source, unit hint)."""
    text = f"{indent}{number}. {item.text}"
    if item.quantity_estimated:
        text += " (수량 추정)"
    if item.reason:
        text += f" - {item.reason}"
    lines = [text]
    sub = f"{indent}   "
    if item.estimate:
        estimate = (
            f"{sub}라벨: {ranges_text(item.estimate)}"
            if item.label
            else f"{sub}추정: {ranges_text(item.estimate)} (estimated)"
        )
        lines.append(f"{estimate} {CHECK_MARKER}" if item.check else estimate)
    if item.check:
        lines.append(f"{sub}{CHECK_LINE_HEAD}{', '.join(CHECK_REASON_TEXTS[code] for code in item.check)}")
    if item.portions:
        lines.append(f"{sub}양 가정: {item.portions}")
    if item.assumption:
        lines.append(f"{sub}가정: {item.assumption}")
    if item.source:
        lines.append(f"{sub}출처: {item.source}")
    if item.hint:
        lines.append(f"{sub}{item.hint}")
    return lines


def menu_reply(view: MenuView) -> ReplyText:
    meal = MEAL_NAMES[view.meal_type]
    what = f"{meal} 메뉴 제안이에요." if view.suggestion else f"오늘 {meal} 메뉴예요."
    ranking = view.ranking
    if ranking.mode is RankMode.KNOWN:
        protein = f"단백질 {view.protein_remaining} g" if view.protein_remaining is not None else "단백질 알 수 없음"
        head = f"{what} 남은 양: {protein}, kcal {view.kcal_budget} (/status)"
    elif ranking.mode is RankMode.RANGE:
        assert ranking.budget_low is not None and ranking.budget_high is not None
        head = (
            f"{what} 남은 kcal 약 {display_amount(ranking.budget_low)}~{display_amount(ranking.budget_high)} "
            "(추정 포함) (/status)"
        )
    else:
        reasons = ", ".join(ranking.reasons)
        head = f"{what} 남은 양을 몰라 단백질/kcal 비율 순" + (f" ({reasons})" if reasons else "")
    lines = [head]
    if ranking.target_met:
        lines.append("오늘 kcal은 목표에 도달했습니다 (/status)")
    if view.totals is not None:
        lines.append(view.totals)
    if view.lead:
        lines.append(view.lead)
    lines.append("추천 (값은 추정, estimated)" if view.suggestion else "추천 순서 (메뉴 값은 사진 추정, estimated)")
    for number, line in enumerate(view.lines, start=1):
        lines.append(f"{number}. {_menu_line(line)}")
    eat = " ".join(f"/eat_{view.token}_{number}" for number in range(1, len(view.lines) + 1))
    return ReplyText("\n".join(lines), (f"먹을 메뉴: {eat}",))


def _menu_line(line: MenuLineView) -> str:
    protein = _bounds_text(line.protein, " g", printed=line.printed_protein)
    kcal = _bounds_text(line.kcal, "", printed=line.printed_kcal)
    text = f"{line.title}   단백질 {protein}, kcal {kcal}"
    if line.label:
        text += f" {line.label}"
    if line.note:
        text += f" - {line.note}"
    return text


def _bounds_text(bounds: tuple[Decimal, Decimal] | None, unit: str, *, printed: bool) -> str:
    if bounds is None:
        return "알 수 없음"
    low, high = bounds
    value = amount_text(low) if low == high else f"{amount_text(low)}~{amount_text(high)}"
    return f"{value}{unit}" + (" (메뉴판 표기)" if printed else "")


def ranges_text(ranges: NutrientRanges) -> str:
    parts = []
    for nutrient, low, high in ranges:
        unit = "" if nutrient is NutrientField.CALORIES_KCAL else " g"
        value = amount_text(low) if low == high else f"{amount_text(low)}~{amount_text(high)}"
        parts.append(f"{_NUTRIENT_NAMES[nutrient]} {value}{unit}")
    return ", ".join(parts)


# --- /history and `telegram history` -------------------------------------------------------------------


def history_text(entries: Sequence[dict[str, Any]]) -> str:
    """`/history`: one block per entry, oldest first (Korean)."""
    if not entries:
        return HISTORY_EMPTY_TEXT
    blocks = []
    for entry in entries:
        at = entry["at"]
        head = [f"{at[5:10]} {at[11:16]} {_KIND_NAMES.get(entry['kind'], entry['kind'])}"]
        if entry["intent"]:
            head.append(_INTENT_NAMES.get(entry["intent"], entry["intent"]))
        if entry["provider"]:
            head.append(f"{entry['provider']} {entry['model'] or '기본'}{_retry_note(entry)}")
        if entry.get("web_searches"):
            head.append(web_search_line(entry["web_searches"]))
        recheck = _recheck_outcome(entry)
        if recheck is not None:
            head.append(f"재확인({OUTCOME_HISTORY_TEXTS[recheck]})")
        lines = [" · ".join(head), f"나: {_user_text(entry, photo_word='사진', not_kept='보관 안 함')}"]
        if entry["reply"]:
            lines.append(f"bot: {entry['reply']}")
        result = entry["result"]
        if isinstance(result, dict):
            recorded = ", ".join(result["meal_ids"]) if result.get("meal_ids") else (result.get("meal_id") or "")
            if result.get("exit_code") == 0:
                verb = "수정" if entry["kind"] == "edit" else "기록"
                lines.append(f"결과: {verb} {recorded}".rstrip())
            elif result.get("meal_ids"):
                failed_value = str(result.get("failed") or "")
                failed = MEAL_NAMES_BY_VALUE.get(failed_value, failed_value)
                lines.append(f"결과: 일부 기록 {recorded} (실패: {failed})")
            else:
                lines.append(f"결과: 실패 (exit {result.get('exit_code')})")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_telegram_history(entries: Sequence[dict[str, Any]]) -> str:
    """`muscle50 telegram history`: ASCII labels; message and reply text are shown as stored."""
    if not entries:
        return "No Telegram history entries."
    lines = []
    for entry in entries:
        at = entry["at"]
        head = [f"{at[:10]} {at[11:16]} {at[19:] or 'local'}", f"chat {entry['chat_id']}", entry["kind"]]
        if entry["intent"]:
            head.append(f"intent={entry['intent']}")
        chain = _attempt_chain(entry)
        if chain is not None:
            head.append(chain)
        else:
            if entry["provider"]:
                head.append(f"{entry['provider']}/{entry['model'] or 'default'}")
            if entry["provider_result"]:
                head.append(str(entry["provider_result"]))
        if entry.get("web_searches") is not None:
            head.append(f"web={entry['web_searches']}")
        recheck = _recheck_outcome(entry)
        if recheck is not None:
            head.append(f"recheck={recheck.value}")
        if entry["proposal"]:
            head.append(f"proposal={entry['proposal']}")
        result = entry["result"]
        if isinstance(result, dict):
            head.append(f"exit={result.get('exit_code')}")
            if result.get("meal_ids"):
                head.append(f"meals={','.join(result['meal_ids'])}")
            elif result.get("meal_id"):
                head.append(f"meal={result['meal_id']}")
        lines.append(" ".join(head))
        lines.append(f"  user: {_user_text(entry, photo_word='photo', not_kept='not kept')}")
        if entry["reply"]:
            reply_lines = str(entry["reply"]).split("\n")
            lines.append(f"  bot: {reply_lines[0]}")
            lines.extend(f"       {line}" for line in reply_lines[1:])
    return "\n".join(lines)


def render_telegram_history_json(entries: Sequence[dict[str, Any]]) -> str:
    return json.dumps({"entries": list(entries)}, indent=2, ensure_ascii=True)


def _recheck_outcome(entry: dict[str, Any]) -> RecheckOutcome | None:
    """The numeric re-check outcome of a v2.2 line; None for older lines and for messages that needed none."""
    recheck = entry.get("recheck")
    return RecheckOutcome(recheck["outcome"]) if isinstance(recheck, dict) else None


def _retry_note(entry: dict[str, Any]) -> str:
    """` (재시도, 처음 <model> 형식 실패)` for a message whose last call was re-run on the retry model."""
    if entry.get("retried") is not True:
        return ""
    attempts = entry.get("attempts") or []
    for index, attempt in enumerate(attempts):
        if attempt["retry"] and index > 0:
            return f" (재시도, 처음 {attempts[index - 1]['model'] or '기본'} 형식 실패)"
    return ""


def _attempt_chain(entry: dict[str, Any]) -> str | None:
    """`claude/haiku bad_output -> retry claude/sonnet ok`; None unless the last call ran more than once."""
    attempts = entry.get("attempts")
    if not attempts or len(attempts) < 2:
        return None
    parts = []
    for index, attempt in enumerate(attempts):
        label = f"{attempt['provider']}/{attempt['model'] or 'default'} {attempt['outcome']}"
        if index == 0:
            parts.append(label)
        else:
            parts.append(f"{'retry' if attempt['retry'] else 'fallback'} {label}")
    return " -> ".join(parts)


def _user_text(entry: dict[str, Any], *, photo_word: str, not_kept: str) -> str:
    if entry["kind"] == "photo":
        caption = f" {entry['caption']}" if entry["caption"] else ""
        return f"[{photo_word}]{caption} ({entry['photo'] or not_kept})"
    return str(entry["text"] or "")
