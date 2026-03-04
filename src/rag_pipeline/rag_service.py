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

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

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
except ImportError:
    from src.core.config import RAGConfig, LLMProvider
    from models import RAGResponse, Citation, RetrievalResult, ParentContext
    from retrieval_service import RetrievalService

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

Your expertise includes:
- Analyzing audit findings, observations, and their monetary implications
- Understanding government accounting, budgeting, and financial procedures  
- Interpreting CAG terminology: "short levy", "excess expenditure", "revenue foregone", "infructuous expenditure"
- Synthesizing information from multiple sections of audit reports

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
    """

    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()

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
            if Anthropic is None:
                raise ImportError("Install anthropic: pip install anthropic")
            self.anthropic = Anthropic(api_key=self.config.anthropic_api_key)
            self.openai = OpenAI(api_key=self.config.openai_api_key)  # Still need OpenAI for QueryEnhancer
            self.gemini = None
        elif self.config.llm.provider == LLMProvider.GEMINI:
            # Lazy-init Gemini client
            self.gemini = self._init_gemini_client()
            self.openai = OpenAI(api_key=self.config.openai_api_key)  # Still need OpenAI for QueryEnhancer
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

        logger.info(
            f"RAG Service v3.2 initialized with {self.config.llm.provider.value}"
        )

    def ask(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
        style: Optional[ResponseStyle] = None,
    ) -> RAGResponse:
        """
        Ask a question and get an answer based on CAG reports.
        """
        # Default style
        if style is None:
            style = ResponseStyle.ADAPTIVE

        # ===== NEW: Query Enhancement (Phase 1) =====
        enhancement = None
        question_type = None
        adjusted_top_k = top_k

        if self.config.query_enhancement.enabled and self.query_enhancer:
            # Single LLM call for query enhancement
            enhancement = self.query_enhancer.enhance(question, style=style.value)
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
                logger.info(f"Detected {question_type} question, top_k → {adjusted_top_k}")

            # Auto-select style for specific question types
            if style == ResponseStyle.ADAPTIVE:
                if question_type == "comparison":
                    style = ResponseStyle.COMPARATIVE
                    logger.info("Auto-selected COMPARATIVE style")
                elif question_type == "explanation":
                    style = ResponseStyle.EXPLANATORY
                    logger.info("Auto-selected EXPLANATORY style")

        # ===== Retrieval (now with multi-query + auto-filters) =====
        retrieval_result = self.retrieval.retrieve(
            question,
            top_k=adjusted_top_k,
            filters=filters,
            enhancement=enhancement,  # NEW parameter
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

        # Generate
        answer = self._generate_answer(question, context, style, question_type)

        # Prepend caveat if context insufficient
        if not context_sufficient:
            caveat = (
                "⚠️ **Note**: The available reports may not contain specific information "
                "to fully answer this question. Based on the closest matches found:\n\n"
            )
            answer = caveat + answer

        # Build citations
        citations = self.build_citations(retrieval_result)

        return RAGResponse(
            query=question,
            answer=answer,
            citations=citations,
            sources_used=retrieval_result.total_after_rerank,
            context_length=len(context),
            reranker_used=retrieval_result.reranker_used,
            search_type=retrieval_result.search_type,
            model_used=self._get_model_name(),
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

        Returns True if sufficient, False if insufficient.
        """
        if not self.config.query_enhancement.enable_sufficiency_check:
            return True  # Skip check if disabled

        threshold = self.config.query_enhancement.min_rerank_score

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
        """Generate using Claude."""
        response = self.anthropic.messages.create(
            model=self.config.llm.claude_model,
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
            try:
                from google import genai
                _gemini_client = genai.Client()
                logger.info(f"Gemini client initialized with model: {self.config.llm.gemini_model}")
            except ImportError:
                raise ImportError("Install google-genai: pip install google-genai")
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
    ) -> RAGResponse:
        """
        Compare findings across multiple reports.

        v3.2: Enhanced year context injection and explicit year labeling.
        """
        registry = get_registry()
        all_contexts = []
        all_citations = []
        total_chunks = 0
        citation_num = 1
        years_covered = []

        for report_id in report_ids:
            report_info = registry.get_report(report_id)
            year_label = report_info.audit_year if report_info else report_id

            if year_label:
                years_covered.append(year_label)

            result = self.retrieval.retrieve(
                question,
                top_k=top_k_per_report,
                filters={"report_id": report_id},
            )

            if result.total_after_rerank > 0:
                # v3.2 POLISHED: Stronger year context header
                context = f"\n{'=' * 60}\n"
                context += f"📅 YEAR: {year_label}\n"
                context += f"📄 Report: {report_info.report_title if report_info else report_id}\n"
                context += f"{'=' * 60}\n\n"
                context += f"⚠️ All findings below are from {year_label}. Cite as: [{year_label} - Section X, p.XX]\n\n"
                context += result.to_context_string()
                all_contexts.append(context)
                total_chunks += result.total_after_rerank

                for parent in result.parents:
                    for child in parent.children:
                        all_citations.append(
                            Citation(
                                id=citation_num,
                                report_id=child.report_id,
                                section=parent.toc_entry,
                                page=child.page_physical + 1,
                                score=round(child.score, 3),
                                finding_type=child.finding_type,
                                severity=child.severity,
                                amount_crore=child.total_amount_crore,
                                report_title=report_info.report_title
                                if report_info
                                else "",
                                filename=report_info.filename if report_info else "",
                                audit_year=year_label,
                            )
                        )
                        citation_num += 1

        if not all_contexts:
            return RAGResponse(
                query=question,
                answer="No relevant information found in the specified reports.",
                citations=[],
                sources_used=0,
                context_length=0,
                reranker_used="none",
                search_type="hybrid",
                model_used=self._get_model_name(),
            )

        combined_context = "\n\n".join(all_contexts)
        years_str = (
            ", ".join(sorted(years_covered)) if years_covered else "multiple years"
        )

        system_prompt = TIME_SERIES_SYSTEM_PROMPT
        user_prompt = TIME_SERIES_QUERY_TEMPLATE.format(
            context=combined_context,
            question=question,
            years=years_str,
        )

        # v3.2: Add explicit reminder about years at end of prompt
        user_prompt += f"\n\n📌 REMINDER: You have data from these years: {years_str}. Include year in every citation."

        if self.config.llm.provider == LLMProvider.CLAUDE:
            answer = self._generate_claude(user_prompt, system_prompt)
        elif self.config.llm.provider == LLMProvider.GEMINI:
            answer = self._generate_gemini(user_prompt, system_prompt)
        else:
            answer = self._generate_openai(user_prompt, system_prompt)

        return RAGResponse(
            query=question,
            answer=answer,
            citations=all_citations,
            sources_used=total_chunks,
            context_length=len(combined_context),
            reranker_used="cohere",
            search_type="hybrid",
            model_used=self._get_model_name(),
        )


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================


def quick_ask(question: str, filters: Optional[Dict[str, Any]] = None) -> str:
    """Quick way to ask a question."""
    rag = RAGService()
    response = rag.ask(question, filters=filters)
    return response.answer
