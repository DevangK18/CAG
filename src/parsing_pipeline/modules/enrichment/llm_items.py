"""
Findings and recommendations from checked Gemini items (worker side of Phase 9).

- Each item becomes a Finding or Recommendation with a stable ID; text, page and
  amount come from the chunks, never from the model.
- A section whose call failed (after retries, or past the phase deadline) keeps
  the regex result for that section, marked regex_fallback.
- The regex extractors run as a cross-check: what they find that the model did
  not is counted, not added.
- Executive summary and conclusion findings are restatements: each is linked to
  the chapter finding it restates when one matches (`restates`).
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.core.data_contracts import Finding, Recommendation, SectionClassification
from src.parsing_pipeline.modules.enrichment.finding_extractor import FindingType
from src.parsing_pipeline.modules.enrichment.llm_finding_extractor import (
    PROMPT_VERSION,
    check_items,
    impact_amount,
)

logger = logging.getLogger(__name__)

PAISE_PER_CRORE = 1_000_000_000

_EXEC = re.compile(
    r"executive\s+summary|\boverview\b|\bsummary\s+of\s+(?:findings|audit)", re.I
)
_CONCLUSION = re.compile(r"\bconclusions?\b", re.I)
_PARA_CITE = re.compile(
    r"(?:\bparas?(?:graphs?)?\.?\s*(?:no\.?\s*)?|\()\s*(\d+(?:\.\d+)+(?:\s*(?:,|and|&|to)\s*\d+(?:\.\d+)+)*)",
    re.I,
)
_PARA_NO = re.compile(r"\d+(?:\.\d+)+")
_SECTION_NO = re.compile(r"\s*(\d+(?:\.\d+)+)")
_WORD = re.compile(r"[a-z]{4,}")


def chunk_location(chunk: Dict[str, Any], parent_types: Dict[str, str]) -> str:
    """'executive_summary', 'conclusion' or 'chapter', from the section classification and headings."""
    section_type = parent_types.get(chunk.get("parent_chunk_id") or "")
    if section_type == "executive_summary":
        return "executive_summary"
    if section_type == "conclusion":
        return "conclusion"
    hierarchy = chunk.get("hierarchy") or {}
    top = hierarchy.get("level_1") or ""
    if _EXEC.search(top):
        return "executive_summary"
    if _CONCLUSION.search(top) or _CONCLUSION.match(hierarchy.get("level_2") or ""):
        return "conclusion"
    return "chapter"


def cited_paragraphs(text: str) -> List[str]:
    """Paragraph numbers a text cites: "(Paragraph 3.2.1)", "Paras 2.3 and 2.4"."""
    found: List[str] = []
    for m in _PARA_CITE.finditer(text or ""):
        for number in _PARA_NO.findall(m.group(1)):
            if number not in found:
                found.append(number)
    return found


def _section_no(text: Optional[str]) -> Optional[str]:
    m = _SECTION_NO.match(text or "")
    return m.group(1) if m else None


def _words(text: str) -> Set[str]:
    return set(_WORD.findall((text or "").lower()))


def mark_restatements(
    findings: List[Finding],
    child_chunks: List[Dict[str, Any]],
    section_classifications: List[SectionClassification],
) -> None:
    """
    Executive summary and conclusion findings restate the chapters: mark them and
    link each to the chapter finding it restates (cited paragraph, same amount or
    shared wording), when one matches.
    """
    parent_types = {s.chunk_id: s.section_type for s in section_classifications}
    by_id = {c.get("chunk_id"): c for c in child_chunks}
    for f in findings:
        chunk = by_id.get(f.source_chunk_id) or {}
        f.location = (
            chunk_location(chunk, parent_types) if chunk else (f.location or "chapter")
        )
        # A chapter's highlights box restates the chapter too: the model flags it
        f.is_restatement = f.location != "chapter" or f.is_restatement
        f.is_executive_summary = (
            f.is_executive_summary or f.location == "executive_summary"
        )

    chapter = [f for f in findings if not f.is_restatement]
    words = {f.finding_id: _words(f.text) for f in findings}
    for f in findings:
        if not f.is_restatement:
            continue
        cited = cited_paragraphs(f.text)
        best, best_score = None, 0.0
        for c in chapter:
            score = 0.0
            sec = _section_no(c.section)
            if sec and any(
                sec == p or sec.startswith(p + ".") or p.startswith(sec + ".")
                for p in cited
            ):
                score += 2.0
            if (
                f.monetary_value_paise
                and c.monetary_value_paise == f.monetary_value_paise
            ):
                score += 2.0
            shared = words[f.finding_id] & words[c.finding_id]
            if shared:
                score += len(shared) / max(len(words[f.finding_id]), 1)
            if score > best_score:
                best, best_score = c, score
        # A cited paragraph or an equal amount, or most of the restatement's words
        if best is not None and best_score >= 0.6:
            f.restates = best.finding_id


def _parent_lookup(parent_chunks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for p in parent_chunks:
        pid = p.get("chunk_id") or p.get("parent_chunk_id")
        if pid:
            out[pid] = p
    return out


def _place(
    chunk: Dict[str, Any], parents: Dict[str, Dict[str, Any]]
) -> Tuple[Optional[str], Optional[str]]:
    """(chapter, section) as the regex extractor sets them."""
    hierarchy = chunk.get("hierarchy") or {}
    chapter = hierarchy.get("level_1") or hierarchy.get("level_2")
    parent = parents.get(chunk.get("parent_chunk_id") or "", {})
    section = (
        parent.get("toc_entry") or hierarchy.get("level_3") or hierarchy.get("level_4")
    )
    return chapter, section


def build_from_llm(
    svc,
    report_id: str,
    parent_chunks: List[Dict[str, Any]],
    child_chunks: List[Dict[str, Any]],
    section_classifications: List[SectionClassification],
    government_body_type: str,
    record: Dict[str, Any],
    regex_findings: List[Finding],
    regex_recs: List[Recommendation],
    trace_emitter,
):
    """(findings, recommendations, extraction statistics) from one report's Gemini items."""
    items, check_stats = check_items(record, child_chunks)
    by_id = {c.get("chunk_id"): c for c in child_chunks}
    parents = _parent_lookup(parent_chunks)
    numbering = {int(k): v for k, v in (record.get("numbering") or {}).items()}
    mp = svc._finding_extractor._monetary_processor
    fx = svc._finding_extractor

    findings: List[Finding] = []
    recommendations: List[Recommendation] = []
    amounts_grounded = amounts_named = 0
    for item in items:
        first = by_id[item.chunk_ids[0]]
        chapter, section = _place(first, parents)
        if item.kind == "finding":
            classified, primary = impact_amount(item, by_id, mp)
            amounts_named += bool(item.impact_text)
            amounts_grounded += primary is not None
            primary_paise = primary.value.normalized_paise if primary else None
            try:
                finding_type = FindingType(item.finding_type or "other")
            except ValueError:
                finding_type = FindingType.OTHER
            total = primary_paise or 0
            findings.append(
                Finding(
                    finding_id=item.item_id,
                    report_id=report_id,
                    text=item.text,
                    summary=fx._generate_summary(item.text),
                    finding_type=finding_type.value,
                    severity=fx._calculate_severity(
                        primary_paise or 0, finding_type, government_body_type
                    ).value,
                    monetary_values=[
                        {
                            **cv.value.to_dict(),
                            "context": cv.context.value,
                            "is_primary": cv.is_primary,
                        }
                        for cv in classified
                    ],
                    total_amount_paise=total,
                    total_amount_inr=total,
                    monetary_value_paise=primary_paise,
                    monetary_value=primary_paise,
                    monetary_value_crore=round(primary_paise / PAISE_PER_CRORE, 4)
                    if primary_paise
                    else None,
                    confidence=1.0,
                    chapter=chapter,
                    section=section,
                    page=item.page,
                    source_chunk_id=item.chunk_ids[0],
                    source_chunk_ids=item.chunk_ids,
                    extraction_method="llm",
                    is_restatement=item.restatement,
                )
            )
        else:
            citations = cited_paragraphs(item.text)
            recommendations.append(
                Recommendation(
                    recommendation_id=item.item_id,
                    report_id=report_id,
                    text=item.text,
                    summary=item.text[:200],
                    target_entity=item.addressee or None,
                    chapter=chapter,
                    section=section,
                    page=item.page,
                    source_chunk_id=item.chunk_ids[0],
                    source_chunk_ids=item.chunk_ids,
                    status="pending",
                    extraction_strategy="llm",
                    rec_number=item.rec_number or None,
                    paragraph_citations=citations,
                )
            )

    # Sections whose call failed keep the regex result for their chunks
    failed_calls = [c for c in record.get("calls") or [] if c.get("status") != "ok"]
    fallback_chunks: Set[str] = {
        numbering[n]
        for c in failed_calls
        for n in c.get("numbers") or []
        if n in numbering
    }
    for f in regex_findings:
        if f.source_chunk_id in fallback_chunks:
            f.extraction_method = "regex_fallback"
            findings.append(f)
    for r in regex_recs:
        if r.source_chunk_id in fallback_chunks:
            r.extraction_strategy = "regex_fallback"
            recommendations.append(r)

    # Cross-check: chunks the regex extractors accept that no Gemini item covers
    covered = {cid for it in items for cid in it.chunk_ids} | fallback_chunks
    regex_only_f = [
        f.source_chunk_id for f in regex_findings if f.source_chunk_id not in covered
    ]
    regex_only_r = [
        r.source_chunk_id for r in regex_recs if r.source_chunk_id not in covered
    ]

    order = {c.get("chunk_id"): i for i, c in enumerate(child_chunks)}
    findings.sort(key=lambda f: order.get(f.source_chunk_id, 0))
    recommendations.sort(key=lambda r: order.get(r.source_chunk_id, 0))
    mark_restatements(findings, child_chunks, section_classifications)
    for r in recommendations:
        chunk = by_id.get(r.source_chunk_id) or {}
        r.location = chunk_location(
            chunk, {s.chunk_id: s.section_type for s in section_classifications}
        )

    calls = record.get("calls") or []
    stats = {
        "method": "llm",
        "model": record.get("model"),
        "prompt_version": record.get("prompt_version", PROMPT_VERSION),
        "thinking_level": record.get("thinking_level"),
        "temperature": record.get("temperature", "default"),
        "calls": len(calls),
        "calls_failed": len(failed_calls),
        "seconds": round(sum(c.get("seconds") or 0 for c in calls), 1),
        "fallback_sections": [
            {
                "call_id": c.get("call_id"),
                "section": c.get("section"),
                "status": c.get("status"),
                "error": c.get("error"),
            }
            for c in failed_calls
        ],
        "items": check_stats,
        "impact_amounts": {"named": amounts_named, "found_in_text": amounts_grounded},
        "regex_only_findings": len(regex_only_f),
        "regex_only_recommendations": len(regex_only_r),
        "regex_only_chunk_ids": {
            "findings": regex_only_f[:20],
            "recommendations": regex_only_r[:20],
        },
    }
    dropped = check_stats["bad_chunk_number"] + check_stats["anchor_not_found"]
    if dropped:
        trace_emitter.emit_red_flag(
            "9", "llm_items_dropped", {"report_id": report_id, **check_stats}
        )
    if failed_calls:
        trace_emitter.emit_red_flag(
            "9",
            "llm_extraction_fallback",
            {"report_id": report_id, "sections": len(failed_calls)},
        )
    return findings, recommendations, stats
