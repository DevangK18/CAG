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
