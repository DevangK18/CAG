"""
CAG RAG Pipeline - RAG Service (v3.2 - Polished)
=================================================

Response Styles (matching frontend):
1. CONCISE - Quick 3-5 sentence answers
2. DETAILED - Comprehensive multi-paragraph responses
3. EXECUTIVE - Bottom-line up front with bullet points
4. TECHNICAL - Deep technical analysis with data
5. COMPARATIVE - Theme-based cross-year analysis
6. ADAPTIVE - Auto-detects question type

Additional backend-only styles:
7. EXPLANATORY - Detailed reasoning for "why" questions
8. REPORT - Formal document structure

v3.2 Polish:
- Citation placement: END of sentence, never break flow
- Time Series: Mandatory year in citations (system prompt level)
- No-Data handling: Explicit "Data not available for 202X" instruction
- Stronger year context injection in ask_comparative
"""

import logging
from typing import List, Dict, Any, Optional
from enum import Enum
from pathlib import Path

try:
    from .report_registry import get_registry, init_registry
except ImportError:
    from report_registry import get_registry, init_registry

# Anthropic client - uses Vertex AI wrapper when USE_VERTEX_AI=true
try:
    from src.core.vertex_client import (
        get_anthropic_client,
        is_vertex_ai_enabled,
        get_vertex_model_name,
    )

    _use_vertex_ai = is_vertex_ai_enabled()
except ImportError:
    # Fallback to direct import if vertex_client not available
    from anthropic import Anthropic as _DirectAnthropic

    def get_anthropic_client():
        import os

        return _DirectAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def is_vertex_ai_enabled():
        return False

    def get_vertex_model_name(model):
        return model

    _use_vertex_ai = False

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("Install openai: pip install openai")

# Gemini client is lazy-initialized to avoid startup crash if not selected
_gemini_client = None

try:
    from ..core.config import RAGConfig, LLMProvider
    from .models import RAGResponse, Citation, RetrievalResult, ParentContext
    from .retrieval_service import RetrievalService
    from .auto_filter import AutoFilterExtractor
    from .retrieval_utils import merge_filters, has_explicit_report_filter
except ImportError:
    from src.core.config import RAGConfig, LLMProvider
    from models import RAGResponse, Citation, RetrievalResult, ParentContext
    from retrieval_service import RetrievalService
    from auto_filter import AutoFilterExtractor
    from retrieval_utils import merge_filters, has_explicit_report_filter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# RESPONSE STYLES - Aligned with Frontend
# =============================================================================


class ResponseStyle(Enum):
    """
    Available response styles for RAG answers.

    Frontend modes (primary):
    - CONCISE, DETAILED, EXECUTIVE, TECHNICAL, COMPARATIVE, ADAPTIVE

    Backend-only modes (additional):
    - EXPLANATORY, REPORT
    """

    # Frontend modes
    CONCISE = "concise"
    DETAILED = "detailed"
    EXECUTIVE = "executive"
    TECHNICAL = "technical"
    COMPARATIVE = "comparative"
    ADAPTIVE = "adaptive"

    # Backend-only modes
    EXPLANATORY = "explanatory"
    REPORT = "report"


# =============================================================================
# CORE SYSTEM PROMPTS
# =============================================================================

BASE_EXPERTISE = """You are an expert analyst for the Comptroller and Auditor General (CAG) of India.

CAG audits cover three tiers of government:
- **Union**: Central government ministries and departments, audited through the office of the CAG
- **State**: State government departments, audited by the State Accountant General (AG) under CAG's mandate
- **Local Bodies**: Panchayati Raj Institutions (PRIs) and Urban Local Bodies (ULBs), audited through Annual Technical Inspection Reports (ATIRs) and Local Fund Audits

Your expertise includes:
- Analyzing audit findings, observations, and their monetary implications
- Understanding government accounting, budgeting, and financial procedures
- Interpreting CAG terminology: "short levy", "excess expenditure", "revenue foregone", "infructuous expenditure"
- Synthesizing information from multiple sections of audit reports
- Union audit concepts: Consolidated Fund of India, Parliamentary committees, Central ministries
- State audit concepts: State Exchequer, State Consolidated Fund, State PSEs (Public Sector Enterprises), State AG reports, District-level audits
- Local Body concepts: Gram Panchayat (GP), Zila Parishad (ZP), Panchayat Samiti, Municipal Corporation, Town Council, PRIASoft accounting, Local Fund Audit, three-tier Panchayati Raj system, 73rd/74th Constitutional Amendments

## CRITICAL RULES (NEVER violate):
1. ONLY state facts explicitly present in the provided context
2. NEVER invent, extrapolate, or estimate amounts - use exact figures from context
3. If information is not in context, say: "This information is not available in the indexed reports."
4. When listing items, ONLY include items explicitly mentioned in context
5. For aggregation questions, sum ONLY values explicitly stated - do not estimate totals"""


ANTI_PATTERN_RULES = """

## ⛔ FORBIDDEN PATTERNS (NEVER use these):
- ❌ "The question is asking for..." or "This question asks about..."
- ❌ "Based on the context provided..." or "According to the documents..."
- ❌ "Let me analyze..." or "I'll examine..." or "I will now..."
- ❌ "To answer this question..." or "In response to your query..."
- ❌ Starting with "1. **Finding One**" inline (use proper markdown)
- ❌ Visible markdown syntax like **bold** that isn't rendered
- ❌ Long run-on paragraphs with inline numbered lists
- ❌ "Here's what I found..." or "Here is the information..."

## ✅ CORRECT APPROACH:
- Start DIRECTLY with the answer or key finding
- Use proper markdown headers (##, ###) for sections
- Use proper bullet points on new lines
- Keep paragraphs focused (3-4 sentences max)
- Let the content speak for itself"""


# =============================================================================
# v3.2 POLISHED: Citation rules with explicit placement guidance
# =============================================================================

CITATION_RULES = """

## CITATION FORMAT & PLACEMENT

### Format (STRICT - do not deviate):
⚠️ CRITICAL: Each source passage is labeled with [Source: ...] at the top.
⚠️ When citing information, you MUST copy the EXACT text from the [Source: ...] label as your citation.
⚠️ NEVER invent section numbers or reformat the label.

### How to Cite:
1. Find the [Source: ...] label above the passage you're citing
2. Copy the EXACT text from inside the brackets
3. Wrap it in square brackets in your response

### Examples:
✓ CORRECT:
  - Passage labeled: [Source: Executive Summary, p.11]
  - Your citation: [Executive Summary, p.11]

✓ CORRECT:
  - Passage labeled: [Source: 3.2 Revenue Collection, p.45]
  - Your citation: [3.2 Revenue Collection, p.45]

✗ WRONG: Don't invent or reformat
  - Passage labeled: [Source: Executive Summary, p.11]
  - Your citation: [Section 1, p.11] ← WRONG! You invented "Section 1"

### Placement (CRITICAL for readability):
⚠️ PLACEMENT RULE: Put citations at the END of the sentence or bullet point.
⚠️ DO NOT break the flow of reading with mid-sentence citations.

✓ CORRECT: "Revenue loss was ₹64.60 crore due to toll collection delays. [Executive Summary, p.11]"
✗ WRONG: "Revenue loss was ₹64.60 crore [Executive Summary, p.11] due to toll collection delays."

✓ CORRECT: "The fiscal deficit stood at 6.4% of GDP, exceeding the 5.9% target. [2.3 Fiscal Management, p.24]"
✗ WRONG: "The fiscal deficit [2.3 Fiscal Management, p.24] stood at 6.4% of GDP."

### For Multiple Facts in One Sentence:
- Group related facts, cite once at the end
- Copy the exact source label
- Example: "Revenue deficit was ₹423 crore while capital expenditure fell short by ₹125 crore. [2.3 Budget Analysis, p.24]"

### For Lists:
- Each bullet gets its citation at the END of that bullet
- Copy the exact source label for each
- Example:
  - **Revenue Deficit**: ₹423.50 crore shortfall. [2.3 Fiscal Analysis, p.24]
  - **Capital Gap**: ₹125.00 crore underutilized. [4.2 Capital Expenditure, p.67]

### Requirements:
1. ALWAYS copy the [Source: ...] label EXACTLY as it appears
2. EVERY amount (₹X crore, X%, X LMT) MUST have a citation
3. EVERY specific finding MUST have a citation
4. Citation goes at END of sentence/bullet, NEVER mid-sentence
5. DO NOT invent section numbers or modify the source label"""


FORMATTING_GUIDELINES = """

## FORMATTING GUIDELINES

### CRITICAL MARKDOWN LINE BREAKS (MANDATORY):
⚠️ ALWAYS use proper markdown with line breaks. ReactMarkdown requires block elements on their own lines.

**REQUIRED LINE BREAKS:**
- Put a blank line (two newlines \\n\\n) BEFORE each heading (##, ###, ####)
- Put a blank line AFTER each heading before body text
- Put a blank line before the first list item
- Each list item (- ) must be on its own line
- Separate paragraphs with blank lines
- For markdown tables, each row must be on its own line

**Example of CORRECT formatting:**

### Key Findings

**Safety Compliance**: Bhilai Steel Plant had all 158 recommendations complied. [Section 2.1, p.15]

- **Production Targets**: SAIL aimed for 35.80 million tonnes by 2025-26. [Section 1.3, p.8]
- **Historical Performance**: Under the 2008 Modernization Plan, capacity targets were missed. [Section 3.2, p.42]

### Context & Background

The audit was initiated in response to the National Steel Policy, 2017. [Section 1.1, p.3]

**Example of INCORRECT formatting (DO NOT DO THIS):**
### Key Findings **Safety Compliance**: Bhilai Steel Plant had all 158 recommendations complied. - **Production Targets**: SAIL aimed for 35.80 million tonnes

### Visual Hierarchy:
- Use ### for main section headers (with blank lines before and after)
- Use **bold** for key terms and amounts (sparingly)
- Use bullet points for lists (each on new line)

### Paragraph Structure:
- Keep paragraphs to 3-4 sentences maximum
- One main idea per paragraph
- Always add blank line between paragraphs

### Numbers & Amounts:
- Always use ₹ symbol for Indian currency
- Format as "₹X.XX crore" or "₹X.XX lakh crore"
- Include percentages where relevant

### Lists Format (with proper line breaks):

- **Item One**: Description and details. [Citation]
- **Item Two**: Description and details. [Citation]
- **Item Three**: Description and details. [Citation]

NOT inline like: 1. **Item** - details 2. **Item** - details"""


# =============================================================================
# STYLE-SPECIFIC PROMPTS
# =============================================================================

STYLE_PROMPTS = {
    # =========================================================================
    # CONCISE - Quick answers (50-100 words)
    # =========================================================================
    ResponseStyle.CONCISE: BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Concise

### What to deliver:
A focused, direct answer in 3-5 sentences. No headers, no bullet points.

### Structure:
1. Lead with the key finding/answer
2. Include the main amount (₹ crore)
3. Add 1-2 supporting details
4. End with citation(s)

### Word count: 50-100 words

### Example:
The audit identified revenue loss of ₹64.60 crore due to delayed toll collection at NHAI projects. Non-functional electronic equipment at 12 toll plazas was the primary cause, representing a 23% increase from the previous year. The Ministry has acknowledged these findings. [Section 3.2.1, p.36]"""
    + CITATION_RULES,
    # =========================================================================
    # DETAILED - Comprehensive responses (300-500 words)
    # =========================================================================
    ResponseStyle.DETAILED: BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Detailed

### What to deliver:
A comprehensive, well-structured response covering all relevant aspects of the query.

### Structure:
```
### Overview
[2-3 sentences introducing the topic and key takeaway]

### Key Findings
[Main findings with amounts and citations - use bullets if 3+ items]

### Context & Background
[Additional relevant details, causes, or circumstances]

### Implications
[Significance, impact, or recommendations if mentioned]
```

### Requirements:
- Cover ALL relevant information from context
- Use headers to organize (###)
- Include specific amounts with citations
- Provide context and implications
- Every major claim needs a citation

### Word count: 300-500 words

### Example structure:
### Overview
The CAG audit of FRBM compliance for 2022-23 revealed significant fiscal management challenges, with total non-compliance valued at ₹847.23 crore across multiple categories. [Section 2.1, p.15]

### Key Findings
- **Revenue Deficit**: Shortfall of ₹423.50 crore against budgeted receipts due to lower-than-projected tax collections. [Section 2.3, p.24]
- **Off-Budget Borrowings**: ₹298.73 crore in undisclosed liabilities routed through PSU borrowings, circumventing FRBM limits. [Section 3.1, p.45]
- **Misclassification**: Revenue expenditure of ₹125.00 crore incorrectly shown as capital expenditure. [Section 4.2, p.67]

### Context & Background
These issues stem from structural weaknesses in fiscal reporting mechanisms. The revenue deficit was primarily driven by GST collection shortfalls in Q3 and Q4. [Section 2.4, p.28]

### Implications
The audit recommends strengthening the fiscal monitoring framework and ensuring transparent reporting of all borrowings. [Section 6.1, p.112]"""
    + CITATION_RULES
    + FORMATTING_GUIDELINES,
    # =========================================================================
    # EXECUTIVE - Bottom-line up front (150-250 words)
    # =========================================================================
    ResponseStyle.EXECUTIVE: BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Executive Summary

### What to deliver:
A business-focused summary with the bottom line first, followed by key supporting points.

### Structure:
```
### Key Finding
[One sentence: Main finding + primary amount + citation]

### Summary
- **[Category 1]**: Amount and finding. [Citation]
- **[Category 2]**: Amount and finding. [Citation]
- **[Category 3]**: Amount and finding. [Citation]
- **[Category 4]**: Amount and finding. [Citation]

### Action Required
[One sentence on implications or recommended action]
```

### Requirements:
- Bottom line FIRST (most important finding)
- 3-5 bullet points maximum
- Each bullet: specific amount + finding + citation
- End with implication/action
- No lengthy explanations

### Word count: 150-250 words

### Example:
### Key Finding
FRBM compliance audit identified ₹847.23 crore in fiscal irregularities for 2022-23. [Section 2.1, p.15]

### Summary
- **Revenue Deficit**: ₹423.50 crore shortfall in budgeted receipts. [Section 2.3, p.24]
- **Off-Budget Borrowings**: ₹298.73 crore undisclosed PSU liabilities. [Section 3.1, p.45]
- **Expenditure Misclassification**: ₹125.00 crore wrongly classified. [Section 4.2, p.67]

### Action Required
Immediate strengthening of fiscal transparency mechanisms is recommended to ensure FRBM compliance."""
    + CITATION_RULES,
    # =========================================================================
    # TECHNICAL - Deep technical analysis (400-600 words)
    # =========================================================================
    ResponseStyle.TECHNICAL: BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Technical Analysis

### What to deliver:
A deep, analytical examination of the findings with technical detail, data analysis, and systemic insights.

### Structure:
```
### Executive Summary
[2-3 sentences with key metrics and overall assessment]

### Detailed Analysis

#### [Theme/Category 1]
[Technical analysis with specific data points, percentages, trends]
[Multiple citations throughout]

#### [Theme/Category 2]
[Technical analysis with specific data points, percentages, trends]
[Multiple citations throughout]

### Data Highlights
| Metric | Value | Reference |
|--------|-------|-----------|
| [Metric 1] | ₹XX crore | [Citation] |
| [Metric 2] | XX% | [Citation] |

### Systemic Issues
[Analysis of root causes, patterns, structural problems]

### Technical Recommendations
[Specific technical/procedural recommendations from audit]
```

### Requirements:
- Include ALL relevant numerical data
- Show calculations or breakdowns where available
- Analyze patterns and root causes
- Use tables for comparative data
- Technical terminology appropriate
- Every data point cited

### Word count: 400-600 words

### Approach:
1. Identify all quantitative data in context
2. Organize by technical theme
3. Analyze relationships between findings
4. Highlight systemic patterns
5. Include technical recommendations"""
    + CITATION_RULES
    + FORMATTING_GUIDELINES,
    # =========================================================================
    # COMPARATIVE - Time Series analysis (300-500 words)
    # =========================================================================
    ResponseStyle.COMPARATIVE: BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Comparative Analysis

### What to deliver:
Cross-year or cross-report analysis organized by THEME (not chronologically).

### Structure:
```
### Overview
[1-2 sentences on scope and key trend]

### [Theme 1: e.g., Fiscal Deficit]
**Trend**: [↑ Improving / ↓ Worsening / → Stable]

- **[Year 1]**: [Value/Finding]. [Year - Section, p.XX]
- **[Year 2]**: [Value/Finding]. [Year - Section, p.XX]
- **[Year 3]**: [Value/Finding]. [Year - Section, p.XX]

[1-2 sentences analyzing this theme's trend]

### [Theme 2: e.g., Revenue Collection]
**Trend**: [↑/↓/→]

- **[Year 1]**: [Value/Finding]. [Year - Section, p.XX]
- **[Year 2]**: [Value/Finding]. [Year - Section, p.XX]

### Key Patterns
[2-3 sentences on recurring issues or notable changes]
```

### Requirements:
- Organize by THEME, not by year
- Show trend direction (↑ ↓ →)
- MUST include year in citations: [2022-23 - Section 3.2, p.54]
- Highlight improvements AND deteriorations
- Note persistent/recurring issues

### Word count: 300-500 words

### ⛔ DO NOT:
- List Year 1 findings, then Year 2 findings, then Year 3 findings
- Organize chronologically instead of thematically
- Forget to include year in citations

### Example:
### Overview
FRBM compliance from 2021-22 to 2023-24 shows improving fiscal deficit but persistent revenue collection challenges.

### Fiscal Deficit
**Trend**: ↑ Improving

- **2021-22**: 6.71% of GDP, exceeding target by 0.21%. [2021-22 - Section 2.3, p.25]
- **2022-23**: 6.4% of GDP, within FRBM ceiling. [2022-23 - Section 2.3, p.24]
- **2023-24**: 5.9% of GDP, meeting revised target. [2023-24 - Section 2.3, p.26]

Progressive reduction indicates improved fiscal consolidation efforts."""
    + CITATION_RULES
    + FORMATTING_GUIDELINES,
    # =========================================================================
    # EXPLANATORY - For "why" questions (250-400 words)
    # =========================================================================
    ResponseStyle.EXPLANATORY: BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Explanatory

### What to deliver:
Clear explanation of causes, reasons, and mechanisms behind findings.

### Structure:
```
### The Finding
[What happened - the fact being explained]

### Root Causes
[Primary reasons/causes with evidence]

### Contributing Factors
[Secondary factors that contributed]

### Consequences
[Impact or implications of the finding]
```

### Requirements:
- Clearly connect cause to effect
- Provide evidence for each causal claim
- Distinguish primary from secondary causes
- Explain mechanisms, not just list facts
- Use logical flow

### Word count: 250-400 words

### Example:
### The Finding
Revenue loss of ₹64.60 crore occurred at NHAI toll plazas during 2022-23. [Section 3.2.1, p.36]

### Root Causes
The primary cause was non-functional Electronic Toll Collection (ETC) equipment at 12 toll plazas. Equipment failures went unaddressed for an average of 8 months due to delayed procurement of replacement parts. [Section 3.2.2, p.38]

### Contributing Factors
- **Procurement Delays**: Centralized procurement process added 4-6 months to replacement timelines. [Section 3.2.3, p.40]
- **Maintenance Gaps**: Preventive maintenance schedules were not followed at 67% of plazas. [Section 3.2.4, p.42]
- **Staffing Issues**: Shortage of trained technical staff to perform routine repairs. [Section 3.2.5, p.44]

### Consequences
The revenue shortfall impacted project financing, delaying maintenance works on 340 km of highway. [Section 3.3, p.48]"""
    + CITATION_RULES
    + FORMATTING_GUIDELINES,
    # =========================================================================
    # REPORT - Formal document structure (500-800 words)
    # =========================================================================
    ResponseStyle.REPORT: BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Formal Report

### What to deliver:
A structured, formal document suitable for official use.

### Structure:
```
### 1. Introduction
[Scope, period, and audit mandate]

### 2. Key Findings

#### 2.1 [Finding Category 1]
[Detailed finding with amounts and citations]

#### 2.2 [Finding Category 2]
[Detailed finding with amounts and citations]

### 3. Financial Impact

| Category | Amount (₹ crore) | Reference |
|----------|------------------|-----------|
| [Type 1] | [Amount] | [Citation] |
| [Type 2] | [Amount] | [Citation] |
| **Total** | **[Sum]** | - |

### 4. Audit Recommendations
[Key recommendations from the audit]

### 5. Ministry Response
[Response/acceptance status if mentioned]

### 6. Conclusion
[Summary assessment]
```

### Requirements:
- Use numbered sections
- Formal, objective tone
- Include all relevant amounts
- Use tables for financial data
- CAG terminology
- Every claim cited

### Word count: 500-800 words"""
    + CITATION_RULES
    + FORMATTING_GUIDELINES,
    # =========================================================================
    # ADAPTIVE - Auto-detect question type
    # =========================================================================
    ResponseStyle.ADAPTIVE: BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Adaptive

Analyze the question and respond with the appropriate format:

### For FACTUAL questions ("What was X?", "How much was Y?")
→ Direct answer in 2-4 sentences
→ Key finding first, then supporting detail
→ 50-100 words

### For LIST questions ("List all...", "What are the...", "Name the...")
→ Proper bullet format:
  - **Item 1**: Description. [Citation]
  - **Item 2**: Description. [Citation]
→ Include ALL items from context
→ 100-300 words

### For AGGREGATION questions ("What was total...", "How much overall...")
→ State the total if explicitly in context
→ If no total stated: "Components include: [list them]"
→ NEVER calculate totals yourself
→ 50-150 words

### For COMPARISON questions ("Compare...", "How has X changed...", "Trend...")
→ Organize by THEME, not by year
→ Use trend indicators (↑ ↓ →)
→ Include year in citations: [2022-23 - Section X, p.XX]
→ 200-400 words

### For EXPLANATION questions ("Why...", "Explain...", "What caused...")
→ Structure: Finding → Causes → Factors → Consequences
→ Connect cause to effect clearly
→ 200-350 words

### For STATUS/OVERVIEW questions ("What is the status...", "Describe...")
→ Use ### headers for organization
→ Cover all relevant aspects
→ 250-400 words

### Always:
- Start DIRECTLY with the answer
- Include citations for all facts
- Use exact amounts from context"""
    + CITATION_RULES
    + FORMATTING_GUIDELINES,
}


# =============================================================================
# QUERY TEMPLATES
# =============================================================================

QUERY_TEMPLATES = {
    ResponseStyle.CONCISE: """Context:
{context}

---
Question: {question}

Respond in 3-5 sentences. Start with the key finding. Citation at END of sentence.""",
    ResponseStyle.DETAILED: """Context from CAG Reports:
{context}

---
Question: {question}

Provide a comprehensive response with:
- Overview (2-3 sentences)
- Key findings with amounts
- Context/background
- Implications
Use ### headers. Target: 300-500 words.
Remember: Citations go at END of sentences, never mid-sentence.""",
    ResponseStyle.EXECUTIVE: """Context from CAG Reports:
{context}

---
Question: {question}

Provide executive summary:
- Key Finding (one sentence, main amount)
- 3-5 bullet points with amounts
- Action required
Target: 150-250 words.
Each bullet ends with its citation.""",
    ResponseStyle.TECHNICAL: """Context from CAG Reports:
{context}

---
Question: {question}

Provide technical analysis:
- Executive summary with key metrics
- Detailed analysis by theme
- Data highlights (table if multiple metrics)
- Systemic issues and root causes
- Technical recommendations
Target: 400-600 words.""",
    ResponseStyle.COMPARATIVE: """Context from Multiple Years/Reports:
{context}

---
Question: {question}

Provide comparative analysis:
- Organize by THEME (not by year)
- Show trends (↑ improving, ↓ worsening, → stable)
- MUST include year in citations: [YEAR - Section, p.XX]
- Note patterns and changes
Target: 300-500 words.""",
    ResponseStyle.EXPLANATORY: """Context from CAG Reports:
{context}

---
Question: {question}

Explain the causes and reasons:
- The finding (what happened)
- Root causes (primary reasons)
- Contributing factors (secondary)
- Consequences (impact)
Target: 250-400 words.""",
    ResponseStyle.REPORT: """Context from CAG Reports:
{context}

---
Question: {question}

Structure as formal report:
1. Introduction
2. Key Findings (with sub-sections)
3. Financial Impact (table)
4. Recommendations
5. Ministry Response
6. Conclusion
Target: 500-800 words.""",
    ResponseStyle.ADAPTIVE: """Context from CAG Reports:
{context}

---
Question: {question}

Identify question type and respond appropriately:
- FACTUAL → 2-4 sentences, direct answer
- LIST → Bullet points with all items
- AGGREGATION → State total or list components
- COMPARISON → Theme-based with trends
- EXPLANATION → Causes and consequences
- STATUS → Comprehensive overview

Start directly with the answer. Citations at END of sentences.""",
}


# =============================================================================
# v3.2 POLISHED: TIME SERIES PROMPTS with mandatory year citation & no-data handling
# =============================================================================

TIME_SERIES_SYSTEM_PROMPT = (
    BASE_EXPERTISE
    + ANTI_PATTERN_RULES
    + """

## RESPONSE STYLE: Time Series Comparative Analysis

You are analyzing data across multiple years of CAG audit reports.

### Structure:
```
### Overview
[Key trend summary in 1-2 sentences]

### [Theme 1]
**Trend**: [↑/↓/→]
- **[Year]**: Finding. [Year - Section, p.XX]
- **[Year]**: Finding. [Year - Section, p.XX]
[Brief analysis]

### [Theme 2]
**Trend**: [↑/↓/→]
...

### Key Patterns
[Recurring issues, notable changes]
```

### ⚠️ MANDATORY YEAR CITATION RULE:
When citing ANY fact, you MUST include the year to distinguish sources.
Format: [2022-23 - Section 3.1, p.45]

✓ CORRECT: "Fiscal deficit was 6.4% of GDP. [2022-23 - Section 2.3, p.24]"
✗ WRONG: "Fiscal deficit was 6.4% of GDP. [Section 2.3, p.24]"

### ⚠️ HANDLING MISSING DATA:
If a specific metric/finding is NOT available for a particular year in the context:
- Explicitly state: "Data not available for [YEAR]" or "[YEAR]: Data not found in context"
- Do NOT guess, estimate, or omit the year silently
- Do NOT hallucinate values for missing years

Example:
### Revenue Collection
**Trend**: → Mixed
- **2021-22**: ₹45,230 crore collected. [2021-22 - Section 3.1, p.34]
- **2022-23**: Data not available for this year
- **2023-24**: ₹52,180 crore collected. [2023-24 - Section 3.1, p.36]

### Requirements:
1. Organize by THEME, not by year
2. Show trends: ↑ (improving), ↓ (worsening), → (stable)
3. ALWAYS include year in citations
4. Explicitly note missing data for any year
5. Highlight significant changes

### ⛔ DO NOT:
- Dump findings year by year chronologically
- Forget year prefix in citations
- Silently skip years with missing data
- Guess or estimate values not in context
- Start with "The question is asking..."
"""
    + CITATION_RULES
    + FORMATTING_GUIDELINES
)


TIME_SERIES_QUERY_TEMPLATE = """Context from Multiple Years:
{context}

---
Question: {question}
Years covered: {years}

IMPORTANT INSTRUCTIONS:
1. Organize by THEME (not year)
2. Include trend indicators (↑↓→)
3. MUST cite as: [YEAR - Section X, p.XX]
4. If data missing for a year, state "Data not available for [YEAR]"

Target: 400-600 words."""


# =============================================================================
# RAG SERVICE CLASS
# =============================================================================


class RAGService:
    """
    RAG Service v3.2 - Polished

    Response styles match frontend exactly:
    - concise, detailed, executive, technical, comparative, adaptive

    Additional backend styles:
    - explanatory, report

    v3.2 improvements:
    - Citation placement at END of sentences
    - Mandatory year in time series citations
    - Explicit handling of missing year data

    Bridge C additions:
    - Query observability logging via QueryLogger
    """

    def __init__(self, config: RAGConfig = None, query_logger=None):
        self.config = config or RAGConfig()
        self.query_logger = query_logger

        # Validate
        errors = self.config.validate()
        relevant = [e for e in errors if "OPENAI" in e or "ANTHROPIC" in e]
        if relevant:
            raise ValueError(f"Configuration errors: {relevant}")

        # Initialize services
        self.retrieval = RetrievalService(self.config)

        processed_dir = Path("data/processed")
        init_registry(processed_dir)

        # Initialize LLM clients
        if self.config.llm.provider == LLMProvider.CLAUDE:
            # Use Vertex AI wrapper when enabled, else direct API
            self.anthropic = get_anthropic_client()
            if _use_vertex_ai:
                logger.info("Using Claude via Vertex AI")
            self.openai = OpenAI(
                api_key=self.config.openai_api_key
            )  # Still need OpenAI for QueryEnhancer
            self.gemini = None
        elif self.config.llm.provider == LLMProvider.GEMINI:
            # Lazy-init Gemini client
            self.gemini = self._init_gemini_client()
            self.openai = OpenAI(
                api_key=self.config.openai_api_key
            )  # Still need OpenAI for QueryEnhancer
            self.anthropic = None
        else:
            self.openai = OpenAI(api_key=self.config.openai_api_key)
            self.anthropic = None
            self.gemini = None

        # Initialize Query Enhancer (Phase 1)
        self.query_enhancer = None
        if self.config.query_enhancement.enabled:
            try:
                try:
                    from .query_enhancer import QueryEnhancer
                except ImportError:
                    from query_enhancer import QueryEnhancer

                self.query_enhancer = QueryEnhancer(
                    config=self.config.query_enhancement,
                    openai_client=self.openai,
                )
                logger.info("Query Enhancement enabled (Phase 1)")
            except ImportError as e:
                logger.warning(f"Could not import QueryEnhancer: {e}")
                self.config.query_enhancement.enabled = False

        # Phase 13: Initialize Groundedness Service
        self.groundedness_service = None
        if self.config.groundedness.enabled:
            try:
                try:
                    from .groundedness_service import GroundednessService
                except ImportError:
                    from groundedness_service import GroundednessService

                self.groundedness_service = GroundednessService(
                    config=self.config.groundedness,
                    openai_client=self.openai,
                    anthropic_client=self.anthropic,
                    gemini_client=self.gemini,
                )
                logger.info("Groundedness verification enabled (Phase 13)")
            except ImportError as e:
                logger.warning(f"Could not import GroundednessService: {e}")
                self.config.groundedness.enabled = False

        # Phase 11: Initialize Agentic Service
        self.agentic_service = None
        if self.config.agentic.enabled:
            try:
                try:
                    from .agentic_service import AgenticRAGService
                except ImportError:
                    from agentic_service import AgenticRAGService

                self.agentic_service = AgenticRAGService(
                    rag_service=self,
                    config=self.config.agentic,
                )
                logger.info("Agentic RAG enabled (Phase 11)")
            except ImportError as e:
                logger.warning(f"Could not import AgenticRAGService: {e}")
                self.config.agentic.enabled = False

        # Initialize Auto-Filter Extractor
        self.auto_filter_extractor = None
        if self.config.auto_filter.enabled:
            self.auto_filter_extractor = AutoFilterExtractor(self.config.auto_filter)
            logger.info("Auto-Filter extraction enabled")

        # ===== SOTA RAG Features Initialization =====

        # Query Router (SOTA Feature 2)
        self.query_router = None
        if self.config.query_routing.enabled:
            try:
                try:
                    from .query_router import QueryRouter
                except ImportError:
                    from query_router import QueryRouter

                self.query_router = QueryRouter(
                    config=self.config.query_routing,
                    openai_client=self.openai,
                )
                logger.info("Query Routing enabled (SOTA Feature 2)")
            except ImportError as e:
                logger.warning(f"Could not import QueryRouter: {e}")
                self.config.query_routing.enabled = False

        # Self-RAG / Retrieval Decider (SOTA Feature 3)
        self.retrieval_decider = None
        self.parametric_responder = None
        if self.config.self_rag.enabled:
            try:
                try:
                    from .retrieval_decider import RetrievalDecider, ParametricResponder
                except ImportError:
                    from retrieval_decider import RetrievalDecider, ParametricResponder

                self.retrieval_decider = RetrievalDecider(self.config.self_rag)
                self.parametric_responder = ParametricResponder(
                    llm_client=self.openai,
                    model="gpt-4o-mini",
                )
                logger.info("Self-RAG enabled (SOTA Feature 3)")
            except ImportError as e:
                logger.warning(f"Could not import RetrievalDecider: {e}")
                self.config.self_rag.enabled = False

        # Corrective RAG (SOTA Feature 4)
        self.corrective_service = None
        if self.config.corrective_rag.enabled:
            try:
                try:
                    from .corrective_rag import CorrectiveRAGService
                except ImportError:
                    from corrective_rag import CorrectiveRAGService

                self.corrective_service = CorrectiveRAGService(
                    config=self.config.corrective_rag,
                    openai_client=self.openai,
                )
                logger.info("Corrective RAG enabled (SOTA Feature 4)")
            except ImportError as e:
                logger.warning(f"Could not import CorrectiveRAGService: {e}")
                self.config.corrective_rag.enabled = False

        # Hierarchical Retriever (SOTA Feature 1 - RAPTOR)
        self.hierarchical_retriever = None
        if self.config.hierarchical.enabled:
            try:
                try:
                    from .hierarchical_retriever import HierarchicalRetriever
                except ImportError:
                    from hierarchical_retriever import HierarchicalRetriever

                # Note: HierarchicalRetriever requires qdrant_service and embedding_service
                # which are initialized in RetrievalService. We'll initialize it lazily.
                logger.info("Hierarchical Retrieval enabled (SOTA Feature 1 - RAPTOR)")
            except ImportError as e:
                logger.warning(f"Could not import HierarchicalRetriever: {e}")
                self.config.hierarchical.enabled = False

        logger.info(
            f"RAG Service v3.3 initialized with {self.config.llm.provider.value}"
        )
        logger.info(
            f"SOTA Features: Routing={self.config.query_routing.enabled}, "
            f"Self-RAG={self.config.self_rag.enabled}, "
            f"Corrective={self.config.corrective_rag.enabled}, "
            f"Hierarchical={self.config.hierarchical.enabled}"
        )

    def ask(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
        style: Optional[ResponseStyle] = None,
        client_session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> RAGResponse:
        """
        Ask a question and get an answer based on CAG reports.
        """
        # Default style
        if style is None:
            style = ResponseStyle.ADAPTIVE

        # Determine interaction mode for logging
        interaction_mode = "directory" if filters and "report_id" in filters else "home"

        # Extract report_ids for logging
        report_ids_filter = None
        if filters and "report_id" in filters:
            rid = filters["report_id"]
            report_ids_filter = rid if isinstance(rid, list) else [rid]

        # Start query logging context (if logger available)
        log_ctx = None
        if self.query_logger:
            log_ctx = self.query_logger.start_query(
                query_text=question,
                interaction_mode=interaction_mode,
                report_ids_filter=report_ids_filter,
                explicit_filters=filters,
                style=style.value if style else None,
                client_session_id=client_session_id,
                user_agent=user_agent,
            )
            log_ctx = log_ctx.__enter__()
            log_ctx.start_phase("enhancement")

        try:
            return self._ask_impl(
                question=question,
                filters=filters,
                top_k=top_k,
                style=style,
                log_ctx=log_ctx,
            )
        except Exception as e:
            if log_ctx:
                log_ctx.record_error(str(e))
            raise
        finally:
            if log_ctx:
                log_ctx.__exit__(None, None, None)

    def _ask_impl(
        self,
        question: str,
        filters: Optional[Dict[str, Any]],
        top_k: int,
        style: ResponseStyle,
        log_ctx=None,
    ) -> RAGResponse:
        """Internal implementation of ask() with logging support."""

        # ===== SOTA: Self-RAG Check (Feature 3) =====
        # Check if retrieval is needed - skip for definitional queries
        if self.retrieval_decider:
            try:
                from .retrieval_decider import RetrievalDecision
            except ImportError:
                from retrieval_decider import RetrievalDecision

            decision = self.retrieval_decider.decide(question)

            if decision.decision == RetrievalDecision.SKIP:
                logger.info(f"Self-RAG: Skipping retrieval - {decision.reasoning}")

                # Generate parametric response without retrieval
                parametric_answer = decision.parametric_answer
                if not parametric_answer and self.parametric_responder:
                    parametric_answer = self.parametric_responder.respond(question)

                if parametric_answer:
                    return RAGResponse(
                        query=question,
                        answer=parametric_answer,
                        citations=[],
                        sources_used=0,
                        context_length=0,
                        reranker_used="none",
                        search_type="parametric",
                        model_used="parametric",
                        sota_features={
                            "self_rag": "skip",
                            "routing": "none",
                            "corrective": False,
                        }
                    )

            elif decision.decision == RetrievalDecision.MULTI_RETRIEVE:
                # Use agentic service for complex queries
                if self.agentic_service:
                    logger.info("Self-RAG: Routing to agentic retrieval")
                    return self.agentic_service.ask(
                        question=question,
                        filters=filters,
                        style=style,
                    )

        # ===== SOTA: Query Routing (Feature 2) =====
        routing_decision = None
        if self.query_router:
            routing_decision = self.query_router.route(question)
            logger.info(
                f"Query Routing: {routing_decision.route.value} "
                f"(confidence: {routing_decision.confidence:.2f})"
            )

            # Apply routing-suggested filters
            if routing_decision.filters_suggested:
                if filters is None:
                    filters = {}
                # Routing filters have lower priority than explicit filters
                for key, value in routing_decision.filters_suggested.items():
                    if key not in filters and value is not None:
                        filters[key] = value
                        logger.info(f"Routing added filter: {key}={value}")

        # ===== Tier context lookup for query enhancement =====
        tier_context_for_enhancer = None
        if filters and "report_id" in filters:
            registry = get_registry()
            report_id = filters["report_id"]
            # Handle both single report_id and list of report_ids
            if isinstance(report_id, list):
                report_id = report_id[0]  # Use first report for context
            report_info = registry.get_report(report_id)
            if report_info:
                govt_type = (
                    getattr(report_info, "government_body_type", None) or "union"
                )
                if govt_type != "union":
                    tier_label = "State" if govt_type == "state" else "Local Body"
                    tier_context_for_enhancer = f"{tier_label} audit report"
                    state_name = getattr(report_info, "state_name", None)
                    if state_name:
                        tier_context_for_enhancer += f" from {state_name}"
                    department = getattr(report_info, "department", None)
                    if department and department.lower() not in ("unknown", "n/a", ""):
                        tier_context_for_enhancer += f", department: {department}"

        # ===== NEW: Query Enhancement (Phase 1) =====
        enhancement = None
        question_type = None
        adjusted_top_k = top_k

        if self.config.query_enhancement.enabled and self.query_enhancer:
            # Single LLM call for query enhancement
            enhancement = self.query_enhancer.enhance(
                question,
                style=style.value,
                tier_context=tier_context_for_enhancer,
            )
            question_type = enhancement.question_type

            # Apply recommended style if adaptive
            if style == ResponseStyle.ADAPTIVE and enhancement.recommended_style:
                try:
                    style = ResponseStyle(enhancement.recommended_style)
                    logger.info(f"QueryEnhancer recommended style: {style.value}")
                except ValueError:
                    pass  # Keep adaptive if recommendation is invalid

            # Use enhancement's top_k
            adjusted_top_k = enhancement.top_k
        else:
            # Legacy path: use existing regex detection
            question_type = self._detect_question_type(question)

            # Increase context for complex questions
            if question_type in ["list", "aggregation", "comparison"]:
                adjusted_top_k = max(top_k, 15)
                logger.info(
                    f"Detected {question_type} question, top_k → {adjusted_top_k}"
                )

            # Auto-select style for specific question types
            if style == ResponseStyle.ADAPTIVE:
                if question_type == "comparison":
                    style = ResponseStyle.COMPARATIVE
                    logger.info("Auto-selected COMPARATIVE style")
                elif question_type == "explanation":
                    style = ResponseStyle.EXPLANATORY
                    logger.info("Auto-selected EXPLANATORY style")

        # Log query enhancement
        if log_ctx:
            log_ctx.record_query_enhancement(enhancement)
            log_ctx.end_phase("enhancement")
            log_ctx.start_phase("retrieval")

        # ===== Auto-Filter Extraction =====
        # Only apply when caller didn't specify report_id
        auto_filters = None
        if self.auto_filter_extractor and not has_explicit_report_filter(filters):
            auto_filters = self.auto_filter_extractor.extract(question, enhancement)
            filters = merge_filters(filters, auto_filters)

        # Log filters
        if log_ctx:
            log_ctx.record_auto_filters(auto_filters)
            log_ctx.record_merged_filters(filters)

        # ===== SOTA: Route-based Retrieval =====
        # Check if we should use hierarchical retrieval (RAPTOR)
        use_hierarchical = False
        if routing_decision:
            try:
                from .query_router import QueryRoute
            except ImportError:
                from query_router import QueryRoute

            if routing_decision.route == QueryRoute.SUMMARY_ONLY:
                use_hierarchical = True
                logger.info(
                    f"Routing to hierarchical retrieval (L{routing_decision.hierarchy_level or 2})"
                )

        # Hierarchical retrieval for summary queries
        if use_hierarchical and self.config.hierarchical.enabled:
            # Lazy initialization of hierarchical retriever
            if self.hierarchical_retriever is None:
                try:
                    from .hierarchical_retriever import HierarchicalRetriever
                except ImportError:
                    from hierarchical_retriever import HierarchicalRetriever

                self.hierarchical_retriever = HierarchicalRetriever(
                    qdrant_service=self.retrieval.qdrant,
                    embedding_service=self.retrieval.embedding,
                    config=self.config,
                )

            retrieval_result = self.hierarchical_retriever.retrieve(
                query=question,
                level=routing_decision.hierarchy_level if routing_decision else 2,
                report_id=filters.get("report_id") if filters else None,
                top_k=adjusted_top_k,
            )
        else:
            # Standard retrieval (now with multi-query + auto-filters)
            retrieval_result = self.retrieval.retrieve(
                question,
                top_k=adjusted_top_k,
                filters=filters,
                enhancement=enhancement,
            )

        # ===== SOTA: Corrective RAG - Relevance Check (Feature 4) =====
        correction_info = None
        if self.corrective_service and retrieval_result.total_after_rerank > 0:
            # Define re-retrieve function for corrective flow
            def retrieve_fn(reformulated_query):
                return self.retrieval.retrieve(
                    reformulated_query,
                    top_k=adjusted_top_k,
                    filters=filters,
                    enhancement=None,  # Don't re-enhance reformulated query
                )

            retrieval_result, correction_info = self.corrective_service.check_and_correct_retrieval(
                query=question,
                retrieval_result=retrieval_result,
                retrieve_fn=retrieve_fn,
            )

            if correction_info.get("retrieval_attempts", 1) > 1:
                logger.info(
                    f"Corrective RAG: {correction_info['retrieval_attempts']} retrieval attempts, "
                    f"final assessment: {correction_info.get('final_assessment', {}).get('suggestion', 'unknown')}"
                )

        # Log retrieval results
        if log_ctx:
            log_ctx.end_phase("retrieval")
            include_full = (
                self.config.observability.dev_debug
                if hasattr(self.config, "observability")
                else False
            )
            log_ctx.record_retrieval(
                retrieval_result,
                reranker_used=retrieval_result.reranker_used,
                include_full_content=include_full,
            )

        if retrieval_result.total_after_rerank == 0:
            return RAGResponse(
                query=question,
                answer="I couldn't find relevant information in the CAG reports for this question. Try:\n- Rephrasing your question\n- Checking if the topic is covered\n- Adjusting filters",
                citations=[],
                sources_used=0,
                context_length=0,
                reranker_used="none",
                search_type=retrieval_result.search_type,
                model_used=self._get_model_name(),
            )

        # ===== NEW: Passage Reordering =====
        if self.config.query_enhancement.enable_passage_reordering:
            retrieval_result.parents = self._reorder_for_attention(
                retrieval_result.parents
            )

        # ===== NEW: Context Sufficiency Check =====
        context_sufficient = self._check_context_sufficiency(retrieval_result)

        # Log context sufficiency
        if log_ctx:
            log_ctx.record_context_sufficient(context_sufficient)
            log_ctx.start_phase("generation")

        # Build context
        context = retrieval_result.to_context_string(
            include_neighbors=self.config.llm.include_neighbor_context,
            include_semantic_tags=self.config.llm.include_semantic_tags,
        )

        # Adjust context limit (use enhancement if available)
        max_context = (
            enhancement.max_context_chars
            if enhancement
            else self.config.llm.max_context_chars
        )
        if not enhancement and question_type in ["list", "aggregation", "comparison"]:
            max_context = int(max_context * 1.5)

        if len(context) > max_context:
            context = context[:max_context] + "\n\n[Context truncated...]"

        # Inject tier context for State/Local Body reports (non-streaming path)
        tier_context = self._build_tier_context(retrieval_result)
        if tier_context:
            context = tier_context + "\n\n" + context

        # Get prepared prompts for logging (use style-specific prompts)
        system_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS[ResponseStyle.ADAPTIVE])
        query_template = QUERY_TEMPLATES.get(style, QUERY_TEMPLATES[ResponseStyle.ADAPTIVE])
        user_prompt = query_template.format(context=context, question=question)

        # Generate
        answer = self._generate_answer(question, context, style, question_type)

        # ===== SOTA: Corrective RAG - Citation Validation (Feature 4) =====
        citation_validation = None
        if self.corrective_service and self.config.corrective_rag.validate_citations:
            answer, citation_validation = self.corrective_service.validate_and_clean_answer(
                answer=answer,
                retrieval_result=retrieval_result,
            )
            if citation_validation and not citation_validation.all_valid:
                logger.info(
                    f"Citation validation: {len(citation_validation.valid_citations)} valid, "
                    f"{len(citation_validation.invalid_citations)} invalid (stripped)"
                )

        # Log generation
        if log_ctx:
            log_ctx.end_phase("generation")
            log_ctx.record_generation(
                answer=answer,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response=answer,  # Same as answer for non-streaming
                provider=self.config.llm.provider.value,
                model=self._get_model_name(),
                prompt_tokens=None,  # Would need tiktoken to estimate
                completion_tokens=None,
            )

        # Prepend caveat if context insufficient
        if not context_sufficient:
            caveat = (
                "⚠️ **Note**: The available reports may not contain specific information "
                "to fully answer this question. Based on the closest matches found:\n\n"
            )
            answer = caveat + answer

        # Phase 13: Groundedness verification (runs for ALL queries, not just insufficient)
        groundedness_dict = None
        if self.groundedness_service:
            if log_ctx:
                log_ctx.start_phase("groundedness")
            report = self.groundedness_service.verify(answer, retrieval_result)
            groundedness_dict = report.to_dict()
            if log_ctx:
                log_ctx.end_phase("groundedness")
                log_ctx.record_groundedness(groundedness_dict)

            # Optional: prepend caveat if verification failed AND block_on_failure is on
            if not report.verified and self.config.groundedness.block_on_failure:
                gcaveat = (
                    f"⚠️ **Groundedness check**: Only {report.num_grounded} of "
                    f"{report.num_claims} factual claims in this answer could be "
                    f"verified against the retrieved sources. Treat with caution.\n\n"
                )
                answer = gcaveat + answer

        # Build citations
        citations = self.build_citations(retrieval_result)

        # Build SOTA features summary
        sota_features = {}
        if routing_decision:
            sota_features["routing"] = routing_decision.route.value
            sota_features["routing_confidence"] = routing_decision.confidence
        if correction_info:
            sota_features["corrective_attempts"] = correction_info.get("retrieval_attempts", 1)
            sota_features["corrective_reformulations"] = len(correction_info.get("reformulations", []))
        if citation_validation:
            sota_features["citation_valid"] = len(citation_validation.valid_citations)
            sota_features["citation_invalid"] = len(citation_validation.invalid_citations)
        if use_hierarchical:
            sota_features["hierarchical_level"] = routing_decision.hierarchy_level if routing_decision else 2

        return RAGResponse(
            query=question,
            answer=answer,
            citations=citations,
            sources_used=retrieval_result.total_after_rerank,
            context_length=len(context),
            reranker_used=retrieval_result.reranker_used,
            search_type=retrieval_result.search_type,
            model_used=self._get_model_name(),
            groundedness=groundedness_dict,
            sota_features=sota_features if sota_features else None,
        )

    # =========================================================================
    # Streaming Support
    # =========================================================================

    def prepare_generation_inputs(
        self,
        question: str,
        retrieval_result: RetrievalResult,
        style: ResponseStyle = ResponseStyle.ADAPTIVE,
        is_time_series: bool = False,
        years: Optional[List[str]] = None,
        question_type: Optional[str] = None,
        max_context_chars: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Prepare inputs for LLM generation (for streaming).

        Args:
            question: User's question
            retrieval_result: Retrieved context
            style: Response style
            is_time_series: Whether this is a time series query
            years: Years being analyzed (for time series)
            question_type: Optional pre-detected question type (from QueryEnhancer)
            max_context_chars: Optional max context length (from QueryEnhancer)
        """
        # Use provided question_type or detect it
        if question_type is None:
            question_type = self._detect_question_type(question)

        # Auto-select style
        if style == ResponseStyle.ADAPTIVE:
            if question_type == "comparison":
                style = ResponseStyle.COMPARATIVE
            elif question_type == "explanation":
                style = ResponseStyle.EXPLANATORY

        # Build context
        context = retrieval_result.to_context_string(
            include_neighbors=self.config.llm.include_neighbor_context,
            include_semantic_tags=self.config.llm.include_semantic_tags,
        )

        # Use provided max_context_chars or default
        if max_context_chars is not None:
            max_context = max_context_chars
        else:
            max_context = self.config.llm.max_context_chars
            if question_type in ["list", "aggregation", "comparison"]:
                max_context = int(max_context * 1.5)

        if len(context) > max_context:
            context = context[:max_context] + "\n\n[Context truncated...]"

        # Select prompts
        if is_time_series or style == ResponseStyle.COMPARATIVE:
            system_prompt = TIME_SERIES_SYSTEM_PROMPT
            years_str = ", ".join(years) if years else "multiple years"
            user_prompt = TIME_SERIES_QUERY_TEMPLATE.format(
                context=context,
                question=question,
                years=years_str,
            )
        else:
            system_prompt = STYLE_PROMPTS.get(
                style, STYLE_PROMPTS[ResponseStyle.ADAPTIVE]
            )
            query_template = QUERY_TEMPLATES.get(
                style, QUERY_TEMPLATES[ResponseStyle.ADAPTIVE]
            )
            user_prompt = query_template.format(context=context, question=question)

        # Add hints
        type_hints = {
            "list": "\n\n⚠️ LIST: Include ALL items. Use bullets. Citation at end of each bullet.",
            "aggregation": "\n\n⚠️ AGGREGATION: Report stated totals only. Citation at end of sentence.",
            "comparison": "\n\n⚠️ COMPARISON: Organize by theme. MUST include year in citations.",
            "explanation": "\n\n⚠️ EXPLANATION: Connect causes to effects. Citations at end of sentences.",
        }
        user_prompt += type_hints.get(question_type, "")

        # Inject tier context for State/Local Body reports
        tier_context = self._build_tier_context(retrieval_result)
        if tier_context:
            user_prompt = tier_context + "\n\n" + user_prompt

        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "question_type": question_type,
            "context_length": len(context),
            "style_used": style.value,
        }

    # =========================================================================
    # Query Enhancement Features (Phase 1)
    # =========================================================================

    @staticmethod
    def _reorder_for_attention(parents: List[ParentContext]) -> List[ParentContext]:
        """
        Reorder parent contexts to mitigate 'lost in the middle' effect.

        Research (ICLR 2025) shows LLMs attend most to content at the
        beginning and end of context, with degraded attention in the middle.

        Strategy: interleave by relevance score.
        - Position 1: highest-scored parent (best content first)
        - Position 2: lowest-scored parent
        - Position 3: second-highest
        - Position 4: second-lowest
        - etc.

        This ensures the most and least relevant are at attention-optimal positions.
        """
        if len(parents) <= 2:
            return parents

        # Score each parent by its best child's score
        scored = []
        for p in parents:
            best_child_score = max((c.score for c in p.children), default=0.0)
            scored.append((p, best_child_score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Interleave: best, worst, 2nd best, 2nd worst, ...
        reordered = []
        left = 0
        right = len(scored) - 1
        toggle = True  # True = take from left (high), False = take from right (low)

        while left <= right:
            if toggle:
                reordered.append(scored[left][0])
                left += 1
            else:
                reordered.append(scored[right][0])
                right -= 1
            toggle = not toggle

        return reordered

    def _check_context_sufficiency(
        self,
        retrieval_result: RetrievalResult,
    ) -> bool:
        """
        Check if retrieved context is likely sufficient to answer the question.

        Uses the top reranker score as a proxy. If the best chunk scores
        below the threshold, the context is likely insufficient.

        The threshold is lowered by 30% for State/Local Body reports because
        their vocabulary may score slightly lower with the Cohere reranker
        (trained on general English and Union audit language).

        Returns True if sufficient, False if insufficient.
        """
        if not self.config.query_enhancement.enable_sufficiency_check:
            return True  # Skip check if disabled

        threshold = self.config.query_enhancement.min_rerank_score

        # Lower threshold for State/Local Body reports (vocabulary differences)
        # The Cohere reranker was calibrated for Union reports; State/Local
        # terminology may score slightly lower but answers are still good.
        report_ids = set()
        for parent in retrieval_result.parents:
            for child in parent.children:
                report_ids.add(child.report_id)

        registry = get_registry()
        for rid in report_ids:
            info = registry.get_report(rid)
            if info:
                govt_type = getattr(info, "government_body_type", None) or "union"
                if govt_type != "union":
                    threshold *= 0.7  # 30% lower threshold for non-Union
                    logger.debug(
                        f"Lowered sufficiency threshold to {threshold:.3f} for {govt_type} report"
                    )
                    break

        # Find the best score across all children in all parents
        best_score = 0.0
        for parent in retrieval_result.parents:
            for child in parent.children:
                best_score = max(best_score, child.score)

        sufficient = best_score >= threshold

        if not sufficient:
            logger.info(
                f"Context sufficiency check FAILED: best_score={best_score:.3f} < threshold={threshold}"
            )

        return sufficient

    def _build_tier_context(self, retrieval_result: RetrievalResult) -> str:
        """
        Build tier-aware context header for State/Local Body reports.

        This helps the LLM understand the government tier context and use
        appropriate terminology when generating responses.

        Returns empty string for Union reports (no extra context needed).
        """
        # Get unique report_ids from retrieval results
        report_ids = set()
        for parent in retrieval_result.parents:
            for child in parent.children:
                report_ids.add(child.report_id)

        if not report_ids:
            return ""

        registry = get_registry()

        # For single-report chat (most common case)
        if len(report_ids) == 1:
            report_info = registry.get_report(report_ids.pop())
            if not report_info:
                return ""

            # Get government_body_type - default to "union" if not set
            govt_type = getattr(report_info, "government_body_type", None) or "union"
            if govt_type == "union":
                return ""  # No extra context needed for Union

            tier_label = (
                "State"
                if govt_type == "state"
                else "Local Body (Panchayati Raj Institutions / Urban Local Bodies)"
            )

            parts = [f"📋 REPORT CONTEXT: This is a {tier_label} audit report"]

            state_name = getattr(report_info, "state_name", None)
            if state_name:
                parts[0] += f" from {state_name}"
            parts[0] += "."

            department = getattr(report_info, "department", None)
            if department and department.lower() not in ("unknown", "n/a", ""):
                parts.append(f"Department/Sector: {department}")

            audit_category = getattr(report_info, "audit_category", None)
            if audit_category:
                parts.append(f"Audit type: {audit_category.title()} Audit")

            # Add tier-specific terminology hints
            if govt_type == "state":
                parts.append(
                    "Note: State audit terminology may include 'State AG', 'State Exchequer', "
                    "'State Consolidated Fund', 'SPSE' (State Public Sector Enterprise)."
                )
            elif govt_type == "local_body":
                parts.append(
                    "Note: Local Body terminology may include 'PRI' (Panchayati Raj Institution), "
                    "'ULB' (Urban Local Body), 'GP' (Gram Panchayat), 'ZP' (Zila Parishad), "
                    "'ATIR' (Annual Technical Inspection Report), 'PRIASoft', 'Local Fund Audit'."
                )

            return "\n".join(parts)

        # For multi-report chat (cross-report analysis)
        # Just note the tiers involved
        tiers = set()
        states = set()
        for rid in report_ids:
            info = registry.get_report(rid)
            if info:
                govt_type = getattr(info, "government_body_type", None) or "union"
                tiers.add(govt_type)
                state_name = getattr(info, "state_name", None)
                if state_name:
                    states.add(state_name)

        if tiers == {"union"}:
            return ""

        tier_labels = [t.replace("_", " ").title() for t in tiers]
        context = f"📋 REPORT CONTEXT: These reports span {', '.join(tier_labels)} government tiers"
        if states:
            context += f" covering {', '.join(sorted(states))}"
        context += "."
        return context

    # =========================================================================
    # Smart Report Selection for Comparative Queries
    # =========================================================================

    def _smart_select_reports(
        self,
        report_ids: List[str],
        question: str,
        matched_entities: Optional[List[Dict[str, Any]]],
        cap: int,
    ) -> List[str]:
        """
        Intelligently select top N reports when the set exceeds the cap.

        Selection strategies (in priority order):
        1. If matched_entities: rank by entity mention count in each report
        2. Else if years in question: rank by proximity to mentioned years
        3. Else: rank by report_year descending (most recent first)

        Args:
            report_ids: Full list of candidate report IDs
            question: User's question (used for year extraction)
            matched_entities: Entities matched from entity graph (may be None)
            cap: Maximum number of reports to return

        Returns:
            List of top N report IDs
        """
        registry = get_registry()

        # Strategy 1: Rank by entity mention count
        if matched_entities:
            try:
                try:
                    from src.entity_graph.entity_service import get_entity_service
                except ImportError:
                    from entity_graph.entity_service import get_entity_service

                entity_service = get_entity_service()
                if entity_service:
                    # Score each report by sum of mention counts for matched entities
                    report_scores: Dict[str, int] = {}
                    for report_id in report_ids:
                        score = 0
                        for ent in matched_entities:
                            mentions = entity_service.get_mentions(
                                entity_id=ent["id"],
                                report_id=report_id,
                            )
                            score += len(mentions) if mentions else 0
                        report_scores[report_id] = score

                    # Sort by score descending, take top N
                    sorted_reports = sorted(
                        report_ids,
                        key=lambda r: report_scores.get(r, 0),
                        reverse=True,
                    )
                    logger.info(
                        f"Smart-select by entity mentions: top scores = "
                        f"{[(r, report_scores.get(r, 0)) for r in sorted_reports[:5]]}"
                    )
                    return sorted_reports[:cap]
            except Exception as e:
                logger.warning(f"Entity-based smart select failed: {e}")
                # Fall through to next strategy

        # Strategy 2: Rank by year proximity
        import re
        year_pattern = re.compile(r'\b(20\d{2})\b')
        year_matches = year_pattern.findall(question)

        if year_matches:
            target_years = [int(y) for y in year_matches]
            avg_target_year = sum(target_years) / len(target_years)

            def year_proximity(report_id: str) -> float:
                """Lower is better (closer to target year)."""
                info = registry.get_report(report_id)
                if info and info.report_year:
                    return abs(info.report_year - avg_target_year)
                return float('inf')  # Unknown year goes last

            sorted_reports = sorted(report_ids, key=year_proximity)
            logger.info(
                f"Smart-select by year proximity to {target_years}: "
                f"selected {sorted_reports[:cap]}"
            )
            return sorted_reports[:cap]

        # Strategy 3: Most recent first
        def report_year_desc(report_id: str) -> int:
            """Higher year is better (more recent)."""
            info = registry.get_report(report_id)
            if info and info.report_year:
                return -info.report_year  # Negative for descending sort
            return 0  # Unknown year goes last

        sorted_reports = sorted(report_ids, key=report_year_desc)
        logger.info(f"Smart-select by recency: selected {sorted_reports[:cap]}")
        return sorted_reports[:cap]

    # =========================================================================
    # Question Type Detection
    # =========================================================================

    def _detect_question_type(self, question: str) -> str:
        """Detect question type for appropriate handling."""
        q_lower = question.lower()

        # List
        list_kw = [
            "list",
            "what are the",
            "what were the",
            "name all",
            "enumerate",
            "what issues",
            "what findings",
            "what problems",
            "what recommendations",
            "how many",
            "which states",
            "which ministries",
            "main issues",
            "key findings",
            "major issues",
            "all the",
        ]
        if any(kw in q_lower for kw in list_kw):
            return "list"

        # Aggregation
        agg_kw = [
            "total",
            "aggregate",
            "overall",
            "sum of",
            "combined",
            "how much in total",
            "what is the total",
            "cumulative",
        ]
        if any(kw in q_lower for kw in agg_kw):
            return "aggregation"

        # Comparison
        comp_kw = [
            "compare",
            "comparison",
            "difference between",
            "vs",
            "versus",
            "how does",
            "differ from",
            "changed from",
            "trend",
            "over the years",
            "year over year",
            "year-over-year",
            "across years",
            "between years",
            "how has",
            "evolution",
            "progression",
        ]
        if any(kw in q_lower for kw in comp_kw):
            return "comparison"

        # Explanation
        exp_kw = [
            "why",
            "explain",
            "reason",
            "cause",
            "how did",
            "what caused",
            "what led to",
            "due to what",
        ]
        if any(kw in q_lower for kw in exp_kw):
            return "explanation"

        return "factual"

    # =========================================================================
    # Answer Generation
    # =========================================================================

    def _generate_answer(
        self,
        question: str,
        context: str,
        style: ResponseStyle = ResponseStyle.ADAPTIVE,
        question_type: str = "factual",
    ) -> str:
        """Generate answer with style-specific prompting."""
        system_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS[ResponseStyle.ADAPTIVE])
        query_template = QUERY_TEMPLATES.get(
            style, QUERY_TEMPLATES[ResponseStyle.ADAPTIVE]
        )

        type_hints = {
            "list": "\n\n⚠️ LIST: Enumerate ALL items with bullets. Citation at end of each.",
            "aggregation": "\n\n⚠️ AGGREGATION: Use stated totals only. Citation at end of sentence.",
            "comparison": "\n\n⚠️ COMPARISON: Theme-based, not chronological. Year in citations.",
            "explanation": "\n\n⚠️ EXPLANATION: Show cause → effect. Citations at sentence end.",
        }

        prompt = query_template.format(context=context, question=question)
        prompt += type_hints.get(question_type, "")

        if self.config.llm.provider == LLMProvider.CLAUDE:
            return self._generate_claude(prompt, system_prompt)
        elif self.config.llm.provider == LLMProvider.GEMINI:
            return self._generate_gemini(prompt, system_prompt)
        else:
            return self._generate_openai(prompt, system_prompt)

    def _generate_claude(self, prompt: str, system_prompt: str) -> str:
        """Generate using Claude (via Vertex AI when enabled)."""
        # Map model name for Vertex AI if enabled
        model_name = self.config.llm.claude_model
        if _use_vertex_ai:
            model_name = get_vertex_model_name(model_name)

        response = self.anthropic.messages.create(
            model=model_name,
            max_tokens=self.config.llm.max_tokens,
            temperature=self.config.llm.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def _generate_openai(self, prompt: str, system_prompt: str) -> str:
        """Generate using OpenAI."""
        response = self.openai.chat.completions.create(
            model=self.config.llm.openai_model,
            max_tokens=self.config.llm.max_tokens,
            temperature=self.config.llm.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content

    def _init_gemini_client(self):
        """Initialize Gemini client lazily."""
        global _gemini_client
        if _gemini_client is None:
            from src.core.gemini_client import get_gemini_client
            _gemini_client = get_gemini_client()
            logger.info(
                f"Gemini client initialized with model: {self.config.llm.gemini_model}"
            )
        return _gemini_client

    def _generate_gemini(self, prompt: str, system_prompt: str) -> str:
        """Generate using Gemini."""
        from google.genai import types

        # Gemini uses a combined prompt (system + user)
        combined_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

        response = self.gemini.models.generate_content(
            model=self.config.llm.gemini_model,
            contents=[types.Part.from_text(text=combined_prompt)],
            config=types.GenerateContentConfig(
                temperature=self.config.llm.temperature,
                max_output_tokens=self.config.llm.max_tokens,
            ),
        )
        return response.text

    # =========================================================================
    # Citation Building
    # =========================================================================

    def build_citations(self, result: RetrievalResult) -> List[Citation]:
        """Build citations with full report metadata."""
        registry = get_registry()
        citations = []
        num = 1

        for parent in result.parents:
            for child in parent.children:
                report_info = registry.get_report(child.report_id)

                citations.append(
                    Citation(
                        id=num,
                        report_id=child.report_id,
                        section=parent.toc_entry,
                        page=child.page_physical + 1,
                        score=round(child.score, 3),
                        finding_type=child.finding_type,
                        severity=child.severity,
                        amount_crore=child.total_amount_crore,
                        report_title=report_info.report_title if report_info else "",
                        filename=report_info.filename if report_info else "",
                        audit_year=report_info.audit_year if report_info else "",
                        # Item 7: Enhanced semantic fields
                        entities_mentioned=child.entities_mentioned or [],
                        section_type=child.section_type,
                        is_recommendation=child.is_recommendation,
                    )
                )
                num += 1

        return citations

    def _get_model_name(self) -> str:
        """Get current model name."""
        if self.config.llm.provider == LLMProvider.CLAUDE:
            return self.config.llm.claude_model
        elif self.config.llm.provider == LLMProvider.GEMINI:
            return self.config.llm.gemini_model
        return self.config.llm.openai_model

    # =========================================================================
    # v3.2 POLISHED: Comparative Analysis with stronger year context
    # =========================================================================

    def ask_comparative(
        self,
        question: str,
        report_ids: List[str],
        top_k_per_report: int = 5,
        client_session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> RAGResponse:
        """
        Cross-report comparative query.

        Phase 12 changes:
        - Optionally narrows report_ids using entity graph (if entity_graph.enabled
          and enable_comparative_filtering=True and query mentions a known entity)
        - Builds per-report RetrievalResult objects, then merges via
          retrieval_utils.merge_retrieval_results
        - Runs groundedness verification on the merged result
        """
        # Start query logging context
        log_ctx = None
        if self.query_logger:
            log_ctx = self.query_logger.start_query(
                query_text=question,
                interaction_mode="comparative",
                report_ids_filter=report_ids,
                explicit_filters={"report_id": report_ids},
                style="comparative",
                client_session_id=client_session_id,
                user_agent=user_agent,
            )
            log_ctx = log_ctx.__enter__()
            log_ctx.start_phase("retrieval")

        try:
            return self._ask_comparative_impl(
                question=question,
                report_ids=report_ids,
                top_k_per_report=top_k_per_report,
                log_ctx=log_ctx,
            )
        except Exception as e:
            if log_ctx:
                log_ctx.record_error(str(e))
            raise
        finally:
            if log_ctx:
                log_ctx.__exit__(None, None, None)

    def _ask_comparative_impl(
        self,
        question: str,
        report_ids: List[str],
        top_k_per_report: int,
        log_ctx=None,
    ) -> RAGResponse:
        """Internal implementation of ask_comparative() with logging support."""
        try:
            from .retrieval_utils import merge_retrieval_results
        except ImportError:
            from retrieval_utils import merge_retrieval_results

        logger.info(f"Comparative query across {len(report_ids)} reports: '{question}'")

        # ---- Auto-Filter Extraction for comparative queries ----
        # Extract any auto-filters (year, tier, category) from the question
        # These will be merged into per-report filters below
        comparative_auto_filters: Dict[str, Any] = {}
        if self.auto_filter_extractor:
            comparative_auto_filters = self.auto_filter_extractor.extract(question, None)
            if comparative_auto_filters:
                logger.info(f"Comparative auto-filters: {comparative_auto_filters}")

        # ---- Phase 12: optionally narrow report set via entity graph ----
        narrowed_report_ids = list(report_ids)
        entity_filter_applied = False
        matched_entities: Optional[List[Dict[str, Any]]] = None

        if (
            hasattr(self.config, 'entity_graph')
            and self.config.entity_graph.enabled
            and self.config.entity_graph.enable_comparative_filtering
        ):
            try:
                from src.entity_graph.entity_service import get_entity_service
            except ImportError:
                from entity_graph.entity_service import get_entity_service

            entity_service = get_entity_service()
            if entity_service:
                matched_entities = entity_service.extract_entities_from_query(question)
                if matched_entities:
                    # Union of reports that mention ANY of the matched entities,
                    # intersected with original report_ids
                    candidate_reports: set = set()
                    for ent in matched_entities:
                        candidate_reports.update(
                            entity_service.get_reports_for_entity(ent["id"])
                        )
                    intersected = [r for r in report_ids if r in candidate_reports]
                    if intersected:
                        narrowed_report_ids = intersected
                        entity_filter_applied = True
                        logger.info(
                            f"Entity-graph narrowing: {len(report_ids)} → "
                            f"{len(intersected)} reports (matched: "
                            f"{[e['canonical_name'] for e in matched_entities]})"
                        )
                    else:
                        logger.info(
                            f"Entity match found ({[e['canonical_name'] for e in matched_entities]}) "
                            f"but no reports in series mention them; "
                            f"falling back to original report_ids"
                        )

        # ---- Smart cap: limit reports when set is too large ----
        cap = self.config.entity_graph.comparative_max_reports
        if len(narrowed_report_ids) > cap:
            original_count = len(narrowed_report_ids)
            narrowed_report_ids = self._smart_select_reports(
                narrowed_report_ids, question, matched_entities, cap
            )
            logger.info(f"Capped narrowed reports {original_count} → {cap}")

        # ---- Per-report retrieval ----
        per_report_retrievals: List[RetrievalResult] = []
        years_covered: set = set()

        for report_id in narrowed_report_ids:
            try:
                # Merge report_id with any auto-detected filters (year, tier, category)
                report_filter = merge_filters(
                    {"report_id": report_id},
                    comparative_auto_filters,
                )
                result = self.retrieval.retrieve(
                    question,
                    top_k=top_k_per_report,
                    filters=report_filter,
                    enhancement=None,  # comparative doesn't need expansion
                )
                if result.total_after_rerank > 0:
                    per_report_retrievals.append(result)
                    # Track years for prompt context
                    for parent in result.parents:
                        for child in parent.children:
                            if child.report_year:
                                years_covered.add(str(child.report_year))
            except Exception as e:
                logger.warning(f"Comparative retrieval failed for {report_id}: {e}")
                continue

        if not per_report_retrievals:
            return RAGResponse(
                query=question,
                answer="No relevant information found in the specified reports.",
                citations=[],
                sources_used=0,
                context_length=0,
                reranker_used="none",
                search_type="comparative_empty",
                model_used=self._get_model_name(),
                groundedness=None,
                agentic_trace=None,
            )

        # ---- Merge into single RetrievalResult ----
        merged = merge_retrieval_results(per_report_retrievals)

        # Log retrieval results
        if log_ctx:
            log_ctx.end_phase("retrieval")
            include_full = (
                self.config.observability.dev_debug
                if hasattr(self.config, "observability")
                else False
            )
            log_ctx.record_retrieval(
                merged,
                reranker_used=merged.reranker_used,
                include_full_content=include_full,
            )
            log_ctx.record_auto_filters(comparative_auto_filters)
            log_ctx.start_phase("generation")

        # ---- Build context string ----
        context = merged.to_context_string(
            include_neighbors=False,  # Cross-report comparison: skip neighbors for clarity
            include_semantic_tags=True,
        )

        years_str = (
            ", ".join(sorted(years_covered)) if years_covered else "multiple years"
        )

        # ---- Generate ----
        system_prompt = TIME_SERIES_SYSTEM_PROMPT
        user_prompt = TIME_SERIES_QUERY_TEMPLATE.format(
            context=context,
            question=question,
            years=years_str,
        )
        user_prompt += (
            f"\n\n📌 REMINDER: You have data from these years: {years_str}. "
            f"Include year in every citation."
        )

        if self.config.llm.provider == LLMProvider.CLAUDE:
            answer = self._generate_claude(user_prompt, system_prompt)
        elif self.config.llm.provider == LLMProvider.GEMINI:
            answer = self._generate_gemini(user_prompt, system_prompt)
        else:
            answer = self._generate_openai(user_prompt, system_prompt)

        # Log generation
        if log_ctx:
            log_ctx.end_phase("generation")
            log_ctx.record_generation(
                answer=answer,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response=answer,
                provider=self.config.llm.provider.value,
                model=self._get_model_name(),
            )

        # ---- Phase 13: groundedness verification on merged result ----
        groundedness_dict = None
        if self.groundedness_service:
            if log_ctx:
                log_ctx.start_phase("groundedness")
            try:
                report = self.groundedness_service.verify(answer, merged)
                groundedness_dict = report.to_dict()
                if log_ctx:
                    log_ctx.end_phase("groundedness")
                    log_ctx.record_groundedness(groundedness_dict)
                if (
                    not report.verified
                    and self.config.groundedness.block_on_failure
                ):
                    gcaveat = (
                        f"⚠️ **Groundedness check**: Only {report.num_grounded} of "
                        f"{report.num_claims} factual claims could be verified "
                        f"against the retrieved sources. Treat with caution.\n\n"
                    )
                    answer = gcaveat + answer
            except Exception as e:
                logger.warning(f"Comparative groundedness failed: {e}")
                if log_ctx:
                    log_ctx.end_phase("groundedness")

        # ---- Build citations from merged result ----
        citations = self.build_citations(merged)

        return RAGResponse(
            query=question,
            answer=answer,
            citations=citations,
            sources_used=merged.total_after_rerank,
            context_length=len(context),
            reranker_used=merged.reranker_used,
            search_type="comparative",
            model_used=self._get_model_name(),
            groundedness=groundedness_dict,
            agentic_trace=(
                {"entity_filter_applied": entity_filter_applied,
                 "narrowed_from": len(report_ids),
                 "narrowed_to": len(narrowed_report_ids)}
                if entity_filter_applied
                else None
            ),
        )


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================


def quick_ask(question: str, filters: Optional[Dict[str, Any]] = None) -> str:
    """Quick way to ask a question."""
    rag = RAGService()
    response = rag.ask(question, filters=filters)
    return response.answer
