"""
Phase 9 findings and recommendations from Gemini, one call per section.

The model never writes the text, page or amount of an item. It returns, for each
item it sees, the numbers of the chunks the item covers, the first words of the
item copied from the text (the anchor), its type, and the printed text of its
impact amount. Code then checks every item:

- the chunk numbers belong to the call;
- the anchor is found in one of the item's chunks (whitespace and case ignored);
- the amount is parsed from the chunk's own text by the money tokenizer, never
  from the model's digits.

Items that fail a check are dropped and counted. The two halves run in different
processes: plan_calls/run_calls (the Gemini calls) run in the pipeline's main
process, where the limiter lives; build_items (pure code) runs in the worker that
enriches the report.
"""

import hashlib
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

PROMPT_VERSION = "p9-v4"

# Chunks numbered in the prompt; the model may cite only these
ITEM_CONTENT_TYPES = ("paragraph", "list")

FINDING_TYPES = (
    "irregular_expenditure",
    "loss_of_revenue",
    "wasteful_expenditure",
    "non_compliance",
    "system_deficiency",
    "performance_shortfall",
    "fraud_misappropriation",
    "procedural_lapse",
    "idle_assets",
    "non_realization_of_dues",
    "incomplete_infrastructure",
    "accounting_irregularity",
    "fund_utilization_failure",
    "other",
)


# ── response schema ─────────────────────────────────────────────────────────


class ExtractedItem(BaseModel):
    kind: Literal["finding", "recommendation"]
    chunks: List[int] = Field(
        description="Chunk numbers the item covers, in order; the first is where it starts"
    )
    anchor: str = Field(
        description="The first 8 to 15 words of the item, copied exactly from the text"
    )
    finding_type: Optional[
        Literal[
            "irregular_expenditure",
            "loss_of_revenue",
            "wasteful_expenditure",
            "non_compliance",
            "system_deficiency",
            "performance_shortfall",
            "fraud_misappropriation",
            "procedural_lapse",
            "idle_assets",
            "non_realization_of_dues",
            "incomplete_infrastructure",
            "accounting_irregularity",
            "fund_utilization_failure",
            "other",
        ]
    ] = Field(default=None, description="Findings only")
    impact_chunk: Optional[int] = Field(
        default=None, description="Chunk number holding the impact amount"
    )
    impact_text: Optional[str] = Field(
        default=None,
        description="The impact amount exactly as printed, e.g. '₹3.15 crore'",
    )
    restatement: bool = Field(
        default=False,
        description="True when the item summarises a finding stated in full elsewhere in the report",
    )
    rec_number: Optional[str] = Field(
        default=None, description="Recommendations only: the printed number"
    )
    addressee: Optional[str] = Field(
        default=None, description="Recommendations only: who is asked to act"
    )


class ExtractionResponse(BaseModel):
    items: List[ExtractedItem]


# ── prompt ──────────────────────────────────────────────────────────────────

INSTRUCTIONS = """You read a report of the Comptroller and Auditor General of India (CAG) and list every audit finding and every recommendation in the text you are given.

{report_line}
{type_guidance}

The text is part of the report. Each paragraph or list item is numbered like [C12]. Lines starting with # are headings (they carry the chapter and paragraph numbers); lines in square brackets without a number mark tables and are not items.

FINDING: an audit observation, grounded in audit evidence, that states something wrong with what the auditee did or achieved: a deficiency, irregularity, non-compliance, loss, shortfall, delay, idle or wasted resource, weak control, or an adverse outcome.
- Include paragraphs that state a deficiency without a cue such as "Audit observed", case-study paragraphs that say what went wrong, and adverse statements in the executive summary, overview, conclusion, or the summary or highlights box at the start of a chapter.
- Exclude background (scheme descriptions, organisation, budget, legal framework), audit objectives, criteria, scope, methodology and sampling, neutral statistics and trends, management replies ("The Ministry stated (June 2024) that ..."), positive observations, and recommendations.
- Audit's answer to a reply ("The reply is not acceptable because ...") belongs to the finding it answers: do not list it separately.
- One item per audit paragraph: the paragraph as numbered in the report (e.g. 3.2.1), or each distinct observation paragraph within it. A finding that continues over several numbered chunks is one item listing all of them.

RECOMMENDATION: an action the audit asks the auditee or government to take: recommendation boxes, "Audit recommends ...", "It is recommended that ...", "The Ministry may consider ...", and advisory forms such as "... may be ensured" or "... should be strengthened".
- One item per numbered or bulleted recommendation.
- Exclude rules or guidelines quoted as audit criteria, recommendations of other committees or consultants, commitments made by management, and past-tense "should have" (that is a finding).

For each item give:
- kind: "finding" or "recommendation";
- chunks: the chunk numbers it covers, in order, starting with the chunk where it begins;
- anchor: the first 8 to 15 words of the item, copied exactly from that chunk;
- finding_type (findings): the closest type, or "other";
- impact_chunk and impact_text (findings): the chunk number and the exact printed text of the single amount that quantifies the finding's impact (the loss, irregular payment, idle investment, short levy, funds left unspent or surrendered), e.g. "₹3.15 crore"; null when the finding has no rupee impact. A sanctioned, granted, released or budgeted amount, or the value of an asset, is the impact only when the finding says that money was lost, wasted, left unused (for example released too late in the year to be spent) or spent irregularly. Quantities that are not money are never amounts;
- restatement (findings): true when the item summarises a finding the report states in full elsewhere (executive summary, overview, conclusion, chapter highlights), false for the full statement itself;
- rec_number and addressee (recommendations): the printed number if any, and who is asked to act.

Several items may start in the same chunk. List every finding and recommendation in the text, in reading order. Return an empty list when there are none."""

TYPE_GUIDANCE = {
    "atir": (
        "This is an Annual Technical Inspection Report (ATIR) on local bodies (Panchayati Raj "
        "Institutions and Urban Local Bodies). Its findings are the deficiencies reported for the "
        "inspected units or themes: accounts not maintained or reconciled, utilisation certificates "
        "pending, funds unspent or diverted, irregular or excess payments, assets idle, records missing. "
        "Its recommendations are often phrased as suggestions, to the department or to the primary "
        "auditor (the State Audit Department); each numbered suggestion is a recommendation."
    ),
    "state_finances": (
        "This is a State Finances Audit Report. Besides compliance observations, its findings include "
        "adverse analytical observations: deficits or debt above the fiscal responsibility targets, "
        "unspent or parked balances, off-budget borrowing, pending utilisation certificates, persistent "
        "savings, excess expenditure without regularisation, unreconciled balances."
    ),
    "compliance": "This is a compliance audit: findings are departures from rules, procedures and sanctions, and the losses they caused.",
    "performance": "This is a performance audit: findings are failures of economy, efficiency or effectiveness, missed targets, delays and their effects.",
    "financial": "This is a financial audit: findings are misstatements, unreconciled or unexplained balances, wrong classification and non-disclosure.",
    "state_performance": "This is a performance audit of a State scheme: findings are incomplete works, unspent funds, missed targets, delays and non-compliance.",
    "state_commercial": "This is an audit of State public sector enterprises: findings are idle assets, unrealised dues, revenue loss and wasteful or irregular expenditure.",
    "general": "",
}


def guidance_key(report_type: str, report_metadata: Dict[str, Any]) -> str:
    """Which TYPE_GUIDANCE applies (State Finances reports are typed 'financial')."""
    title = str(report_metadata.get("report_title") or "").lower()
    if "state finances" in title or "state finance audit" in title:
        return "state_finances"
    return report_type if report_type in TYPE_GUIDANCE else "general"


def system_instruction(report_type: str, report_metadata: Dict[str, Any]) -> str:
    title = (
        report_metadata.get("report_title") or report_metadata.get("report_id") or ""
    )
    return INSTRUCTIONS.format(
        report_line=f"Report: {title}".strip(),
        type_guidance=TYPE_GUIDANCE.get(guidance_key(report_type, report_metadata), ""),
    )


# ── planning ────────────────────────────────────────────────────────────────


@dataclass
class SectionCall:
    call_id: str
    section: str
    numbers: List[int]  # chunk numbers in this call
    text: str


@dataclass
class ExtractionPlan:
    report_id: str
    report_type: str
    instruction: str
    numbering: Dict[int, str]  # chunk number -> chunk_id
    calls: List[SectionCall] = field(default_factory=list)


def _section_of(chunk: Dict[str, Any]) -> str:
    hierarchy = chunk.get("hierarchy") or {}
    return hierarchy.get("level_1") or hierarchy.get("level_2") or ""


def _line_for(chunk: Dict[str, Any], number: Optional[int]) -> Optional[str]:
    content = (chunk.get("content") or "").strip()
    ctype = chunk.get("content_type")
    if number is not None:
        return f"[C{number}] {content}"
    if ctype == "header" and content:
        return f"# {content}"
    if ctype == "table_markdown":
        caption = ((chunk.get("structured_data") or {}).get("caption") or "").strip()
        return f"[Table{': ' + caption if caption else ''}]"
    return None  # footnotes, captions and images are not shown


def plan_calls(
    report_id: str,
    report_metadata: Dict[str, Any],
    child_chunks: List[Dict[str, Any]],
    report_type: str,
    max_chars: int = 24000,
) -> ExtractionPlan:
    """
    Number the paragraph and list chunks and pack them into calls.

    A call holds whole sections (the top heading level) in reading order, up to
    max_chars of text. A longer section is split at chunk boundaries.
    """
    plan = ExtractionPlan(
        report_id=report_id,
        report_type=report_type,
        instruction=system_instruction(report_type, report_metadata),
        numbering={},
    )
    sections: List[Tuple[str, List[Tuple[Optional[int], str]]]] = []
    number = 0
    for chunk in child_chunks:
        n = None
        if (
            chunk.get("content_type") in ITEM_CONTENT_TYPES
            and (chunk.get("content") or "").strip()
        ):
            number += 1
            n = number
            plan.numbering[n] = chunk.get("chunk_id", "")
        line = _line_for(chunk, n)
        if line is None:
            continue
        title = _section_of(chunk)
        if not sections or sections[-1][0] != title:
            sections.append((title, []))
        sections[-1][1].append((n, line))

    current: List[str] = []
    current_numbers: List[int] = []
    current_titles: List[str] = []
    size = 0

    def flush():
        nonlocal current, current_numbers, current_titles, size
        if current_numbers:
            plan.calls.append(
                SectionCall(
                    call_id=f"{report_id}:{len(plan.calls) + 1}",
                    section=" | ".join(dict.fromkeys(t for t in current_titles if t)),
                    numbers=list(current_numbers),
                    text="\n".join(current),
                )
            )
        current, current_numbers, current_titles, size = [], [], [], 0

    for title, lines in sections:
        heading = f"## Section: {title}" if title else "## Section"
        section_size = sum(len(line) + 1 for _, line in lines)
        if size and size + section_size > max_chars:
            flush()
        current.append(heading)
        current_titles.append(title)
        for n, line in lines:
            if size + len(line) > max_chars and current_numbers:
                flush()
                current.append(f"{heading} (continued)")
                current_titles.append(title)
            current.append(line)
            size += len(line) + 1
            if n is not None:
                current_numbers.append(n)
    flush()
    return plan


# ── calls ───────────────────────────────────────────────────────────────────


@dataclass
class CallResult:
    call_id: str
    status: str  # ok, failed, deadline
    items: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    seconds: float = 0.0


def run_call(
    plan: ExtractionPlan,
    call: SectionCall,
    model: str,
    thinking_level: Optional[str] = "low",
    max_output_tokens: int = 32768,
    client=None,
) -> CallResult:
    """One Gemini call through the limiter (group phase9). Never raises."""
    from google.genai import types

    from src.core.gemini_client import generate_with_retry
    from src.core.gemini_limiter import GeminiDeadlineExceeded

    started = time.monotonic()
    config = types.GenerateContentConfig(
        system_instruction=plan.instruction,
        response_mime_type="application/json",
        response_schema=ExtractionResponse,
        max_output_tokens=max_output_tokens,
        # Temperature left at the default: Google advises against lowering it for Gemini 3
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level)
        if thinking_level
        else None,
    )
    try:
        response = generate_with_retry(
            client=client,
            tag="phase9.findings",
            model=model,
            contents=[types.Part.from_text(text=call.text)],
            config=config,
        )
        parsed = response.parsed
        if parsed is None:
            parsed = ExtractionResponse.model_validate_json(response.text)
        items = [item.model_dump() for item in parsed.items]
        return CallResult(call.call_id, "ok", items, seconds=time.monotonic() - started)
    except GeminiDeadlineExceeded as e:
        return CallResult(
            call.call_id, "deadline", error=str(e), seconds=time.monotonic() - started
        )
    except Exception as e:  # one section must never sink the report
        logger.warning(f"Phase 9 extraction call {call.call_id} failed: {e}")
        return CallResult(
            call.call_id,
            "failed",
            error=str(e)[:500],
            seconds=time.monotonic() - started,
        )


def extraction_record(
    plan: ExtractionPlan, results: List[CallResult], settings: Dict[str, Any]
) -> Dict[str, Any]:
    """What the worker needs: the numbering, each call's chunk numbers and its items."""
    by_id = {r.call_id: r for r in results}
    return {
        "report_id": plan.report_id,
        "report_type": plan.report_type,
        "prompt_version": PROMPT_VERSION,
        **settings,
        "numbering": {str(k): v for k, v in plan.numbering.items()},
        "calls": [
            {
                "call_id": call.call_id,
                "section": call.section,
                "numbers": call.numbers,
                **asdict(
                    by_id.get(
                        call.call_id,
                        CallResult(call.call_id, "failed", error="not run"),
                    )
                ),
            }
            for call in plan.calls
        ],
    }


# ── checking items (worker side) ────────────────────────────────────────────

_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+")


def _norm(text: str) -> str:
    return _WS.sub(" ", (text or "").replace(" ", " ")).strip().lower()


# Between two anchor words: punctuation, spaces or footnote markers ("commitments[^8] in")
_GAP = r"(?:[^a-z0-9]|\[\^\d{1,3}\])*"


def find_anchor(content: str, anchor: str) -> int:
    """
    Character offset of the anchor in content, or -1.

    The anchor's words must appear in order; case, punctuation and footnote
    markers between them are ignored (the model drops quote marks and markers).
    """
    if not anchor or not content:
        return -1
    words = _WORD.findall(anchor.lower())
    if len(words) < 3:
        return -1
    pattern = _GAP.join(re.escape(w) for w in words[:12])
    match = re.search(pattern, content.lower())
    return match.start() if match else -1


def locate_anchor(contents: List[str], anchor: str) -> Tuple[int, int]:
    """
    (index of the chunk where the anchor starts, offset in it), or (-1, -1).

    The anchor may run on from a lead-in chunk ("Audit noticed that:") into the
    next one, so it is looked for in the chunks joined in order.
    """
    joined, starts = "", []
    for content in contents:
        starts.append(len(joined))
        joined += (content or "") + " "
    at = find_anchor(joined, anchor)
    if at < 0:
        return -1, -1
    index = max(i for i, s in enumerate(starts) if s <= at)
    return index, at - starts[index]


def _short_chunk_id(chunk_id: str, report_id: str) -> str:
    return (
        chunk_id[len(report_id) + 1 :]
        if chunk_id.startswith(report_id + "_")
        else chunk_id
    )


def stable_id(report_id: str, kind: str, chunk_id: str, position: int) -> str:
    """Same report, chunk and position give the same ID on every run."""
    tag = "finding" if kind == "finding" else "rec"
    short = _short_chunk_id(chunk_id, report_id)
    if len(short) > 48:
        short = hashlib.sha1(short.encode()).hexdigest()[:12]
    return f"{report_id}_{tag}_{short}_{position}"


@dataclass
class CheckedItem:
    kind: str
    chunk_ids: List[str]
    start: int  # anchor offset in the first chunk
    end: Optional[int]  # end offset in the last chunk (None = to its end)
    text: str
    page: int
    finding_type: Optional[str]
    impact_chunk_id: Optional[str]
    impact_text: Optional[str]
    rec_number: Optional[str]
    addressee: Optional[str]
    call_id: str
    restatement: bool = False
    item_id: str = ""


def check_items(
    record: Dict[str, Any], child_chunks: List[Dict[str, Any]]
) -> Tuple[List[CheckedItem], Dict[str, Any]]:
    """
    Keep the items whose chunk numbers and anchor check out; build each item's
    text from the chunks. Returns (items in reading order, counts of what was dropped).
    """
    numbering = {int(k): v for k, v in (record.get("numbering") or {}).items()}
    by_id = {c.get("chunk_id"): c for c in child_chunks}
    order = {c.get("chunk_id"): i for i, c in enumerate(child_chunks)}
    stats = {
        "returned": 0,
        "kept": 0,
        "bad_chunk_number": 0,
        "anchor_not_found": 0,
        "duplicate": 0,
    }
    kept: List[CheckedItem] = []
    seen = set()

    for call in record.get("calls") or []:
        if call.get("status") != "ok":
            continue
        allowed = set(call.get("numbers") or [])
        for raw in call.get("items") or []:
            stats["returned"] += 1
            numbers = [n for n in (raw.get("chunks") or []) if isinstance(n, int)]
            if not numbers or any(
                n not in allowed or n not in numbering for n in numbers
            ):
                stats["bad_chunk_number"] += 1
                continue
            numbers = sorted(dict.fromkeys(numbers))
            chunk_ids = [numbering[n] for n in numbers]
            if any(cid not in by_id for cid in chunk_ids):
                stats["bad_chunk_number"] += 1
                continue
            # The anchor must be in the item's chunks; the item starts there
            first, start = locate_anchor(
                [by_id[cid].get("content") or "" for cid in chunk_ids],
                raw.get("anchor") or "",
            )
            if start < 0:
                stats["anchor_not_found"] += 1
                continue
            chunk_ids = chunk_ids[first:]
            key = (raw.get("kind"), chunk_ids[0], start)
            if key in seen:
                stats["duplicate"] += 1
                continue
            seen.add(key)
            impact_chunk_id = (
                numbering.get(raw.get("impact_chunk"))
                if raw.get("impact_chunk")
                else None
            )
            kept.append(
                CheckedItem(
                    kind=raw.get("kind"),
                    chunk_ids=chunk_ids,
                    start=start,
                    end=None,
                    text="",
                    page=int(by_id[chunk_ids[0]].get("source_page_physical") or 0),
                    finding_type=raw.get("finding_type"),
                    impact_chunk_id=impact_chunk_id,
                    impact_text=raw.get("impact_text"),
                    rec_number=raw.get("rec_number"),
                    addressee=raw.get("addressee"),
                    call_id=call.get("call_id", ""),
                    restatement=bool(raw.get("restatement")),
                )
            )

    kept.sort(key=lambda it: (order.get(it.chunk_ids[0], 0), it.start))
    # An item ends where the next item starts in its last chunk
    starts: Dict[str, List[int]] = {}
    for it in kept:
        starts.setdefault(it.chunk_ids[0], []).append(it.start)
    positions: Dict[str, int] = {}
    for it in kept:
        last = it.chunk_ids[-1]
        later = [
            s for s in starts.get(last, []) if (last != it.chunk_ids[0] or s > it.start)
        ]
        it.end = min(later) if later else None
        parts = []
        for i, cid in enumerate(it.chunk_ids):
            content = by_id[cid].get("content") or ""
            lo = it.start if i == 0 else 0
            hi = (
                it.end
                if (i == len(it.chunk_ids) - 1 and it.end is not None)
                else len(content)
            )
            parts.append(content[lo:hi].strip())
        it.text = "\n\n".join(p for p in parts if p)
        positions[it.chunk_ids[0]] = positions.get(it.chunk_ids[0], 0) + 1
        it.item_id = stable_id(
            record.get("report_id", ""),
            it.kind,
            it.chunk_ids[0],
            positions[it.chunk_ids[0]],
        )
    stats["kept"] = len(kept)
    return kept, stats


def impact_amount(
    item: CheckedItem, by_id: Dict[str, Dict[str, Any]], monetary_processor
):
    """
    (classified amounts of the item's text, the primary one) with the primary
    amount chosen by the model's printed impact text and parsed by the tokenizer.

    The printed text must be found in the named chunk (or in the item's own text);
    the amount is the tokenizer's value at that place. Without a match, no amount
    is primary.
    """
    classified = [
        cv
        for cv in monetary_processor.extract_with_context(item.text)
        if cv.value.currency == "INR"
    ]
    for cv in classified:
        cv.is_primary = False
    if not item.impact_text:
        return classified, None
    target = _norm(item.impact_text)
    digits = re.sub(r"[^0-9.]", "", target)
    if not digits:
        return classified, None
    # Where in the item's text the printed amount sits
    text_norm = item.text.lower()
    candidates = [
        m.start()
        for m in re.finditer(re.escape(item.impact_text.strip().lower()), text_norm)
    ]
    for cv in classified:
        raw_digits = re.sub(r"[^0-9.]", "", cv.value.raw_text)
        at_place = any(cv.value.start - 2 <= pos <= cv.value.end for pos in candidates)
        if at_place or (raw_digits and raw_digits == digits):
            cv.is_primary = True
            return classified, cv
    # The amount may sit in a chunk outside the item's own span (the model named it)
    chunk = by_id.get(item.impact_chunk_id) if item.impact_chunk_id else None
    if chunk is not None and chunk.get("chunk_id") not in item.chunk_ids:
        for cv in monetary_processor.extract_with_context(chunk.get("content") or ""):
            raw_digits = re.sub(r"[^0-9.]", "", cv.value.raw_text)
            if cv.value.currency == "INR" and raw_digits == digits:
                cv.is_primary = True
                return classified + [cv], cv
    return classified, None


# ── running every report's calls (main process) ─────────────────────────────


def settings_from_config(cfg=None) -> Dict[str, Any]:
    """Model and thinking level from parsing_config.yaml (semantic_enrichment)."""
    if cfg is None:
        from src.parsing_pipeline.config import get_config

        cfg = get_config().semantic_enrichment
    return {
        "model": cfg.llm_model,
        "thinking_level": cfg.llm_thinking_level or None,
        "temperature": "default",
        "max_chars_per_call": cfg.llm_max_chars_per_call,
    }


def run_plans(plans: List[ExtractionPlan], settings: Dict[str, Any], client=None):
    """
    Yield (report_id, extraction record) as each report's calls finish. Every call
    of every report is submitted at once; the limiter decides how many run.
    """
    from concurrent.futures import ThreadPoolExecutor

    from src.core.gemini_limiter import get_limiter

    if not plans:
        return
    workers = max(1, get_limiter().ceiling(settings["model"]))
    record_settings = {
        k: settings[k] for k in ("model", "thinking_level", "temperature")
    }
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="phase9") as pool:
        futures = {
            plan.report_id: [
                pool.submit(
                    run_call,
                    plan,
                    call,
                    settings["model"],
                    settings["thinking_level"],
                    client=client,
                )
                for call in plan.calls
            ]
            for plan in plans
        }
        for plan in plans:
            results = [f.result() for f in futures[plan.report_id]]
            yield plan.report_id, extraction_record(plan, results, record_settings)
