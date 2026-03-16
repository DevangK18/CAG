"""
Prompt for extracting explicit audit findings from CAG report chunks.

Used by: OpenAI Batch (high volume) and Anthropic Batch (complex cases)

This prompt is designed to extract structured finding data including:
- Finding type classification
- Monetary amounts with proper unit handling
- Severity assessment
- Entity mentions (ministries, departments, schemes)
- Evidence references (tables, paragraphs)
"""

FINDING_EXTRACTION_PROMPT = """You are analyzing a chunk from a CAG (Comptroller and Auditor General of India) audit report.

TASK: Extract all audit findings from this text.

For each finding, provide:
1. **finding_type**: One of:
   - irregular_expenditure (unauth­orized or improper spending)
   - loss_of_revenue (revenue not collected/recovered)
   - wasteful_expenditure (unnecessary or unproductive spending)
   - non_compliance (violation of rules/regulations)
   - system_deficiency (weaknesses in processes/controls)
   - performance_shortfall (targets/objectives not met)
   - fraud_misappropriation (deliberate misuse of funds)
   - procedural_lapse (failure to follow procedures)
   - other (if none of the above fit)

2. **summary**: One sentence summary (max 150 chars)

3. **monetary_amount**: Numeric value in the specified unit (null if no amount mentioned)

4. **currency_unit**: One of "crore", "lakh", "thousand", or null

5. **severity**: Based on monetary value and impact:
   - critical: >₹100 crore OR systemic fraud/failure
   - high: ₹10-100 crore OR significant non-compliance
   - medium: ₹1-10 crore OR moderate issues
   - low: <₹1 crore OR minor procedural lapses

6. **entities**: List of specific entities mentioned (ministries, departments, schemes, PSUs, states)
   - Be specific: "Ministry of Railways", not just "Railways"
   - Include scheme names if mentioned

7. **evidence_refs**: Any table/para/annexure references mentioned
   - Examples: "Table 3.1", "Para 4.2.3", "Annexure A", "page 42"

TEXT:
{chunk_content}

HIERARCHY CONTEXT:
{hierarchy}

IMPORTANT INSTRUCTIONS:
- Only extract findings that are explicitly stated as audit observations
- If no findings exist, return {{"findings": []}}
- For monetary amounts, handle Indian number formats (crore/lakh)
- Consider parenthetical amounts as negative (e.g., "(₹50 crore)" = -50)
- Extract all findings, even minor ones - severity scoring handles prioritization

OUTPUT FORMAT (JSON only):
{{
  "findings": [
    {{
      "finding_type": "irregular_expenditure",
      "summary": "Unauthorized expenditure on construction without approval",
      "monetary_amount": 847.71,
      "currency_unit": "crore",
      "severity": "high",
      "entities": ["Ministry of Railways", "Northern Railway Zone"],
      "evidence_refs": ["Table 3.2", "Para 4.1.5"]
    }}
  ]
}}

If no findings, return: {{"findings": []}}
"""


def build_finding_prompt(chunk: dict) -> str:
    """
    Build the finding extraction prompt for a chunk.

    Args:
        chunk: ChildChunk dict with content, hierarchy, etc.

    Returns:
        Formatted prompt string
    """
    # Extract hierarchy context
    hierarchy = chunk.get("hierarchy", {})
    hierarchy_str = " > ".join(
        f"{level}: {title}" for level, title in hierarchy.items() if title
    )

    # Fallback if no hierarchy
    if not hierarchy_str:
        hierarchy_str = "N/A (no hierarchy information available)"

    return FINDING_EXTRACTION_PROMPT.format(
        chunk_content=chunk.get("content", ""),
        hierarchy=hierarchy_str,
    )
