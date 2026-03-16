"""
Prompt for detecting implicit/hidden findings in CAG report chunks.

These are audit concerns NOT explicitly labeled as "findings" but represent issues:
- Budget variances without explanation
- Targets not met without explicit finding label
- Procedural gaps mentioned in passing
- Pending issues noted casually
- Performance shortfalls buried in tables or narrative

This prompt helps catch issues that Phase 1 pattern matching might miss.
"""

IMPLICIT_FINDING_PROMPT = """You are analyzing a CAG audit report chunk for IMPLICIT audit issues.

WHAT ARE IMPLICIT ISSUES?
These are problems NOT explicitly labeled as "audit findings" but represent concerns:
- Budget variances without clear explanation
- Performance targets not achieved (mentioned casually)
- Procedural gaps or missing documentation (noted in passing)
- Pending/outstanding issues (e.g., "pending since 2019")
- Unexplained differences between planned vs actual
- System weaknesses implied but not explicitly stated

TASK: Identify any implicit audit issues in this text.

For each implicit issue:
1. **issue_type**: Category
   - variance (budget/actual differences)
   - target_miss (objectives/targets not met)
   - procedural_gap (missing processes/controls)
   - pending_issue (delays, outstanding items)
   - performance_gap (shortfalls in performance)
   - unexplained_difference (discrepancies without explanation)
   - system_weakness (implied control deficiencies)
   - other

2. **description**: What the issue is (max 200 chars)
   - Be specific about what's wrong
   - Include relevant numbers/entities

3. **monetary_impact**: Amount in crore if mentioned (null otherwise)

4. **confidence**: Your confidence this represents a real audit concern (0.0-1.0)
   - 0.9-1.0: Clear issue, just not labeled as finding
   - 0.7-0.8: Likely issue, some ambiguity
   - 0.6: Borderline, might be explanatory rather than critical
   - <0.6: Don't include

5. **supporting_text**: The exact text indicating this issue (max 150 chars)
   - Quote the specific phrase that reveals the problem

TEXT:
{chunk_content}

GUIDELINES:
- Only include issues with confidence >= 0.6
- Focus on factual issues, not opinions or contextual information
- Distinguish between "variance" (neutral difference) and "shortfall" (problematic difference)
- Pending issues are only concerning if unreasonably delayed (>1 year typically)
- Missing documentation is only an issue if it was required

OUTPUT FORMAT (JSON only):
{{
  "implicit_issues": [
    {{
      "issue_type": "variance",
      "description": "Budget allocation of ₹500 crore exceeded by ₹120 crore without approval",
      "monetary_impact": 120.0,
      "confidence": 0.85,
      "supporting_text": "actual expenditure was ₹620 crore against budget of ₹500 crore"
    }},
    {{
      "issue_type": "pending_issue",
      "description": "Reconciliation of accounts pending since FY 2019-20",
      "monetary_impact": null,
      "confidence": 0.90,
      "supporting_text": "reconciliation pending since FY 2019-20"
    }}
  ]
}}

If no implicit issues found with confidence >= 0.6, return: {{"implicit_issues": []}}
"""


def build_implicit_prompt(chunk: dict) -> str:
    """
    Build the implicit finding prompt for a chunk.

    Args:
        chunk: ChildChunk dict with content

    Returns:
        Formatted prompt string
    """
    return IMPLICIT_FINDING_PROMPT.format(
        chunk_content=chunk.get("content", "")
    )
