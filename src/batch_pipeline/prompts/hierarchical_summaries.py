"""
RAPTOR Hierarchical Summary Prompts for Phase 10c.

Creates summaries at two levels:
- Level 2 (Chapter): 3-5 sentences summarizing a chapter
- Level 1 (Section): 1-2 sentences summarizing a section

These summaries enable efficient retrieval for high-level queries
without scanning hundreds of chunks.
"""

from typing import Optional


def build_chapter_summary_prompt(
    chapter_title: str,
    chapter_content: str,
    tier: str = "union",
    report_title: Optional[str] = None,
) -> str:
    """
    Build prompt for chapter-level (L2) summary.

    Args:
        chapter_title: Title of the chapter (e.g., "Chapter 3: Revenue Collection")
        chapter_content: Concatenated content from all sections in the chapter
        tier: Government tier (union/state/local_body) for terminology hints
        report_title: Optional report title for context

    Returns:
        Prompt string for LLM
    """
    tier_context = _get_tier_context(tier)
    report_context = f"Report: {report_title}\n" if report_title else ""

    # Truncate content to avoid token limits (Haiku context is 200K but we want efficiency)
    max_content_chars = 12000  # ~3000 tokens
    if len(chapter_content) > max_content_chars:
        chapter_content = chapter_content[:max_content_chars] + "\n\n[Content truncated...]"

    return f"""Summarize this chapter from a CAG {tier} audit report in 3-5 sentences.

{tier_context}

## Instructions:
1. Focus on: key audit findings, monetary impacts (in ₹ crore), and main recommendations
2. Include specific amounts where mentioned
3. Capture the essence of what was audited and what was found
4. Use objective, formal tone appropriate for government audit summaries
5. Do NOT include phrases like "This chapter..." or "The audit found..." - start directly with findings

{report_context}
## Chapter: {chapter_title}

## Content:
{chapter_content}

## Summary (3-5 sentences, focus on findings and amounts):"""


def build_section_summary_prompt(
    section_title: str,
    section_content: str,
    tier: str = "union",
    chapter_title: Optional[str] = None,
) -> str:
    """
    Build prompt for section-level (L1) summary.

    Args:
        section_title: Title of the section (e.g., "3.2.1 Toll Collection Shortfall")
        section_content: Content of this section
        tier: Government tier (union/state/local_body) for terminology hints
        chapter_title: Optional parent chapter title for context

    Returns:
        Prompt string for LLM
    """
    tier_context = _get_tier_context(tier)
    chapter_context = f"Chapter: {chapter_title}\n" if chapter_title else ""

    # Truncate content for efficiency
    max_content_chars = 6000  # ~1500 tokens
    if len(section_content) > max_content_chars:
        section_content = section_content[:max_content_chars] + "\n\n[Content truncated...]"

    return f"""Summarize this section from a CAG {tier} audit report in 1-2 sentences.

{tier_context}

## Instructions:
1. Capture the main finding or observation
2. Include any monetary amount (in ₹ crore) if mentioned
3. Be specific and factual
4. Do NOT use phrases like "This section..." - start directly with the finding

{chapter_context}
## Section: {section_title}

## Content:
{section_content}

## Summary (1-2 sentences, include key finding and amount if any):"""


def build_node_summary_prompt(
    title: str,
    path: list,
    own_text: str,
    child_summaries: list,
    tier: str = "union",
    report_title: Optional[str] = None,
    is_chapter: bool = False,
) -> str:
    """
    Prompt for one node of the bottom-up summary tree: its own text plus the
    summaries of its sub-sections (already written), so a chapter summary rests
    on the whole chapter, not on its first pages.

    Args:
        title: The node's heading
        path: Headings from the chapter down to this node
        own_text: Text that sits directly under this heading (may be empty)
        child_summaries: [(sub-section title, summary)] in reading order
        tier: Government tier for terminology hints
        report_title: Report title for context
        is_chapter: Chapter (4-6 sentences) or section (2-4 sentences)
    """
    unit = "chapter" if is_chapter else "section"
    length = "4-6 sentences" if is_chapter else "2-4 sentences"
    parts = []
    if report_title:
        parts.append(f"Report: {report_title}")
    if len(path) > 1:
        parts.append("Location: " + " > ".join(path[:-1]))
    parts.append(f"## {unit.title()}: {title}")
    if child_summaries:
        parts.append("## Summaries of its sub-sections (in order)")
        parts.extend(f"- {t}: {summary}" for t, summary in child_summaries)
    if own_text:
        parts.append("## Its own text" if child_summaries else "## Text")
        parts.append(own_text)
    body = "\n\n".join(parts)
    return f"""Summarise this {unit} of a CAG {tier} audit report in {length}.

{_get_tier_context(tier)}

## Instructions:
1. Cover what was examined and the main audit findings, with their amounts as the report states them
2. Include the main recommendation if there is one
3. Every number you give must appear in the text below; never add amounts together or derive new figures
4. Objective, formal tone; start directly with the substance (not "This {unit}...")

{body}

## Summary ({length}):"""


def _get_tier_context(tier: str) -> str:
    """Get tier-specific terminology hints."""
    if tier == "state":
        return """## Tier Context: State Government Audit
Terminology: State AG, State Exchequer, State Consolidated Fund, State PSE, District-level audits"""
    elif tier == "local_body":
        return """## Tier Context: Local Body Audit (PRI/ULB)
Terminology: Gram Panchayat (GP), Zila Parishad (ZP), Urban Local Body (ULB), ATIR, PRIASoft, Local Fund Audit"""
    else:
        return """## Tier Context: Union Government Audit
Terminology: CAG, Consolidated Fund of India, Central ministries, Parliamentary committees"""


# Prompt for overview-level (L3) summaries - these already exist in Phase 10a
# This is provided for reference/completeness
REPORT_SUMMARY_PROMPT = """Summarize this CAG audit report in 5-7 sentences.

Focus on:
1. What was audited (scope and period)
2. Major findings with amounts (₹ crore)
3. Key recommendations
4. Overall assessment

Be factual and specific. Include monetary figures where available."""
