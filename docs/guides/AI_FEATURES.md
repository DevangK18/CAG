# AI Features Documentation

Comprehensive reference for all AI/LLM usage across the CAG Gateway project. This document catalogs every AI integration point, prompt design, model selection rationale, and cost implications.

## Overview

| Metric | Value |
|--------|-------|
| **Total AI Models Used** | 6 |
| **Total Distinct Prompts** | 23+ |
| **Offline Processing** | 12 prompt types |
| **Online (Per-Query)** | 3 prompt types |
| **Estimated Corpus Cost** | ~$15-25 for 1,297 reports |

## Multi-Model Strategy

The CAG Gateway uses 6 different AI models, each selected for specific tasks based on cost, capability, and latency requirements:

| Model | Provider | Tasks | Why Chosen |
|-------|----------|-------|------------|
| **Claude Haiku 4.5** | Anthropic | TOC Validation | Fast, cheap ($0.25/$1.25 per 1M tokens), good at structured extraction |
| **Claude Sonnet 4** | Anthropic | Overview Extraction, Summaries, RAG Chat | Balanced cost/quality, Extended Thinking support |
| **Claude Opus 4** | Anthropic | Deep Dive & Journalist Summaries | Highest quality for long-form content |
| **GPT-4o-mini** | OpenAI | Table Summaries, Query Enhancement, RAG Chat | Very cheap ($0.15/$0.60 per 1M), fast, good for simple tasks |
| **Gemini 2.5 Flash** | Google | Visual Extraction (Tables/Charts), RAG Chat | Vision capability, generous rate limits |
| **text-embedding-3-large** | OpenAI | Dense Embeddings | High-quality embeddings at reduced dimensionality |

### Cost Optimization Strategy

1. **Batch API (50% savings)**: All offline processing uses Claude/OpenAI Batch APIs
2. **Model Tiering**: Expensive models (Opus) only for quality-critical tasks
3. **Caching**: Query enhancement results cached per session
4. **Sparse + Dense**: BM25 built-in (no fastembed dependency, zero cost)

---

## Model Inventory

### Offline Models (Batch Processing)

| Model | Task | Cost per Call | Corpus Cost (1,297 reports) |
|-------|------|---------------|----------------------------|
| Claude Haiku 4.5 | TOC Validation | ~$0.01-0.02 | ~$1-3 (15% of reports) |
| Claude Sonnet 4 | Overview Extraction | ~$0.02-0.05 | ~$25-65 |
| Claude Sonnet 4 | Executive/Simple/Policy Summaries | ~$0.03-0.08 | ~$40-100 |
| Claude Opus 4 | Deep Dive/Journalist Summaries | ~$0.10-0.25 | ~$130-325 |
| Gemini 2.5 Flash | Table/Chart Extraction | ~$0.001-0.005 | ~$1-6 |
| GPT-4o-mini | Table Summaries (indexing) | ~$0.0001 | ~$0.50-2 |

### Online Models (Per-Query)

| Model | Task | Cost per Query | Monthly (1K queries) |
|-------|------|----------------|---------------------|
| GPT-4o-mini | Query Enhancement | ~$0.0002 | ~$0.20 |
| Claude Sonnet 4 / GPT-4o-mini | RAG Chat | ~$0.002-0.01 | ~$2-10 |
| text-embedding-3-large | Query Embedding | ~$0.0001 | ~$0.10 |

---

## Prompt Catalog

### 1. TOC Validation (Phase 5.7)

**Location:** `src/parsing_pipeline/modules/toc_llm_validator.py`

**Model:** `claude-haiku-4-5-20251001`

**When:** Offline — fires only when TOC quality < 50 (~15% of reports)

**Input:** First ~15 pages of raw text from PDF (max 8,000 chars)

**Output:** JSON array of TOC entries `[[level, "title", page], ...]`

**Cost:** ~$0.01-0.02 per report

**Why Claude Haiku:** Fastest and cheapest Claude model, excellent for structured extraction from semi-structured text.

**Fallback:** Returns original scaffold if LLM call fails.

#### System Prompt

```markdown
You are a document structure analyzer specializing in Indian government audit reports (CAG reports).

Your task: Extract or validate the Table of Contents from the provided text.

Rules:
1. Each TOC entry has: level (1=chapter, 2=section, 3=subsection), title, and page number
2. Common Level 1 entries: Preface, Executive Summary, Chapter I/II/III, Annexure, Glossary
3. Common Level 2 entries: numbered sections like 1.1, 2.3, or lettered like A. Karnataka
4. Common Level 3 entries: sub-sections like 1.1.1, 2.3.2
5. Page numbers in the TOC refer to PRINTED page numbers (not PDF page numbers)
6. Ignore table captions, figure numbers, headers/footers
```

#### User Prompt Template

```markdown
Here is text from the first pages of a CAG audit report.
{existing_toc_section}
Extract the complete Table of Contents. Return ONLY a JSON array where each entry is:
[level, "title", page_number]

Example:
[
  [1, "Preface", 1],
  [1, "Executive Summary", 3],
  [1, "Chapter I Introduction", 7],
  [2, "1.1 Background", 8],
  [2, "1.2 Audit Objectives", 10],
  [1, "Chapter II Compliance Audit", 15],
  [2, "2.1 Tax Assessment Issues", 16],
  [3, "2.1.1 Short Levy of Tax", 17]
]

Document text (first ~15 pages):
---
{document_text}
---

Return ONLY the JSON array, no explanations.
```

**Variables:**
- `{existing_toc_section}`: Preview of existing TOC (first 10 entries) if available, for correction
- `{document_text}`: Raw text from first ~15 pages (truncated to max_input_chars)

---

### 2. Overview Extraction (Phase 10a)

**Location:** `src/batch_pipeline/prompts/overview_extraction.py`

**Model:** `claude-sonnet-4-20250514` (via Batch API)

**When:** Offline — during Phase 10a enrichment batch

**Input:** TOC structure, intro/scope/objectives content, executive summary, glossary sections

**Output:** JSON with `audit_scope`, `audit_objectives`, `topics_covered`, `glossary_terms`

**Cost:** ~$0.02-0.05 per report

**Extended Thinking:** 5,000 budget tokens

**Why Claude Sonnet:** Requires understanding of document structure and nuanced extraction of objectives/topics.

#### Full Prompt

```markdown
You are extracting specific metadata from a CAG (Comptroller and Auditor General of India) audit report.

## CONTEXT
Report: {report_title}
Type: {report_type}
Ministry: {ministry}
Year: {report_year}

## ALREADY EXTRACTED (do NOT repeat these - they exist in the JSON):
- Report metadata (title, ministry, year, type) ✓
- Table of Contents structure ✓
- Findings with severity and monetary amounts ✓
- Recommendations ✓
- Section classifications ✓
- Statistics (totals, breakdowns) ✓

## YOUR TASK: Extract ONLY these 4 fields

### 1. audit_scope
From the Scope of Audit / Introduction sections, extract:
```json
{
  "period": {
    "start": "YYYY-YY format (e.g., '2020-21')",
    "end": "YYYY-YY format (e.g., '2022-23')",
    "description": "e.g., '3 Financial Years' or 'April 2020 to March 2023'"
  },
  "geographic_coverage": ["list of states/regions/units if mentioned, or ['All India'] if national scope"],
  "sample_size": {
    "total": number or null if not specified,
    "description": "e.g., '8,470 cases from 15 Commissionerates' or null"
  },
  "entities_covered": ["list of organizations/departments/units examined"]
}
```
If any sub-field is not found in the content, use null.

### 2. audit_objectives
From the Audit Objectives section (usually in Chapter 1 or Introduction), extract as array:
```json
["objective 1 as stated in report", "objective 2", "objective 3", ...]
```
Rules:
- Copy the EXACT wording from the report where possible
- Usually 3-7 objectives
- If no explicit "objectives" section, extract the main audit questions or examination areas
- Keep each objective concise (1-2 sentences max)

### 3. topics_covered
Create NEUTRAL topic names from the Table of Contents structure:
```json
[
  {
    "name": "neutral descriptive topic name",
    "sections": ["2.1", "2.2", "2.3"],
    "page_start": 18,
    "page_end": 35,
    "description": "brief one-line description of what this topic covers"
  }
]
```

CRITICAL RULES for topics:
- Use NEUTRAL names - describe WHAT was examined, not WHAT was found wrong
- Topics should help a reader navigate to areas of interest
- ✅ GOOD: "Tax Assessment Procedures", "Revenue Collection Mechanisms", "Storage and Warehousing Operations", "Procurement Processes", "Financial Management"
- ❌ BAD: "Assessment Errors", "Revenue Loss", "Storage Deficiencies", "Non-compliance Issues", "Irregularities"
- Create 8-15 topics covering the main themes of the report
- Group related sub-sections under single topics
- Include page ranges for navigation

### 4. glossary_terms
Extract abbreviations and technical terms used in the report:
```json
[
  {
    "term": "full term name",
    "abbreviation": "ABC",
    "definition": "brief definition if provided in report, else null",
    "category": "organizational|technical|financial|legal|procedural"
  }
]
```
Common CAG/Government terms to look for:
- AO (Assessing Officer), AY (Assessment Year), FY (Financial Year)
- CBDT, CIT, PCIT, TDS, GST, CGST, SGST, IGST
- CAG, PAC, FRBM, BE, RE, Actuals
- Ministry/Department-specific abbreviations
- Any abbreviation that appears multiple times in the report

## INPUT DATA

### Table of Contents:
{toc_text}

### Introduction / Scope / Objectives Content:
{intro_content}

### Executive Summary / Preface (additional context):
{exec_content}

### Glossary Section (if available):
{glossary_content}

## OUTPUT FORMAT
Return ONLY a valid JSON object with these exact keys:
```json
{
  "audit_scope": { ... },
  "audit_objectives": [ ... ],
  "topics_covered": [ ... ],
  "glossary_terms": [ ... ]
}
```

IMPORTANT:
- No markdown code blocks around the JSON
- No explanatory text before or after
- Just the raw JSON object
- Ensure all JSON is properly formatted and valid
```

**Variables:**
- `{toc_text}`: First 60 parent chunks formatted as TOC (max 8,000 chars)
- `{intro_content}`: Content from Introduction/Scope/Objectives sections (max 12,000 chars)
- `{exec_content}`: Content from Executive Summary/Preface (max 4,000 chars)
- `{glossary_content}`: Content from Glossary/Abbreviations section (max 4,000 chars)

---

### 3. Summary Generation — Executive Brief (Phase 10a)

**Location:** `src/batch_pipeline/prompts/summary_variants.py`

**Model:** `claude-sonnet-4-20250514` (via Batch API)

**When:** Offline — during Phase 10a batch processing

**Extended Thinking:** 8,000 budget tokens

**Target Words:** 2,200-2,500

#### Full Prompt

```markdown
You are creating an Executive Brief summary of this CAG audit report for senior government officials.

## Target Audience
- Ministry secretaries and joint secretaries
- Department heads
- Decision-makers who need to understand key issues quickly
- People preparing for parliamentary committee meetings

## Required Sections

### 1. Context & Scope (200-250 words)
- What entity/area was audited and why it matters
- Time period covered
- Type of audit (Performance/Compliance/Financial)
- Scale of operations examined

### 2. Critical Findings (800-1000 words)
- Present the TOP 7-10 most significant findings
- Order by monetary impact (highest first)
- For each finding include:
  - Clear statement of the issue
  - Specific amount in ₹ Crores
  - Reference to section/paragraph
  - Brief implication
- Use sub-headers to group related findings

### 3. Financial Impact Summary (300-400 words)
- Total monetary impact across all findings
- Breakdown by category (non-compliance, revenue loss, irregular expenditure, etc.)
- Breakdown by severity (critical, high, medium)
- Any recurring vs. one-time issues

### 4. Key Recommendations (400-500 words)
- Summarize the main recommendations from the report
- Group by theme/area
- Indicate which require immediate attention
- Note any systemic changes recommended

### 5. Action Items (200-250 words)
- Immediate steps required (0-3 months)
- Short-term actions (3-12 months)
- Key accountability points
- Suggested monitoring mechanisms

## Style Guidelines
- Formal, professional tone suitable for government communication
- Use bullet points strategically for scanability
- Always include specific numbers (₹X.XX Crore)
- Reference source sections (Section 3.4, Para 2.5.1)
- NO meta-commentary like "This report discusses..." - start directly with content
- Use tables where they aid comprehension

## Report Data:
{input}

## Output:
Write the Executive Brief in clean markdown format. Target ~2200-2500 words total.
Start directly with "# Executive Brief" followed by the content.
```

---

### 4. Summary Generation — Journalist's Take (Phase 10a)

**Location:** `src/batch_pipeline/prompts/summary_variants.py`

**Model:** `claude-opus-4-20250514` (via Batch API)

**When:** Offline — during Phase 10a batch processing

**Extended Thinking:** 12,000 budget tokens

**Target Words:** 2,000-2,200

**Why Claude Opus:** Requires creative writing skill for news-style engagement while maintaining accuracy.

#### Full Prompt

```markdown
You are a senior investigative journalist at a major national newspaper (like The Hindu, Indian Express, or Times of India) writing about this CAG audit report.

## Your Mission
Transform this government audit into a compelling news story that:
- Leads with the most dramatic yet accurate finding
- Makes complex government issues accessible to the general public
- Serves the public interest by highlighting accountability gaps
- Could actually run in tomorrow's paper

## Required Sections

### 1. The Headlines (5-7 options)
Write potential news headlines that could run in major papers:
- One main headline (dramatic but 100% accurate)
- 4-6 alternative angles for different editorial choices
- Style examples:
  - "₹3.5 Lakh Crore Gap: CAG Audit Exposes Tax Collection Failures"
  - "Railway Safety Funds Unspent as Accidents Continue, Reveals CAG"
  - "Government Lost ₹12,000 Crore to Contract Irregularities: Audit"

### 2. The Lead Paragraph (150 words)
Classic inverted pyramid - most important facts first:
- What's the biggest finding?
- How much money is involved?
- Who is responsible?
- Why should readers care?

### 3. The Full Story (800-1000 words)
Write as a complete news article:
- Lead with the biggest revelation
- Include specific ₹ amounts throughout
- Use direct quotes/references from the report
- Explain what this means for ordinary citizens/taxpayers
- Include reactions/implications
- Build narrative tension

### 4. By The Numbers
Create a "fast facts" sidebar with 8-12 key statistics:
- Format: "₹X Crore - brief description"
- Most shocking/impactful numbers first
- Make numbers relatable where possible

### 5. The Context (200-250 words)
Background information:
- Why this sector/ministry matters to the public
- Any historical context
- Previous audit findings if referenced
- Scale of operations involved

### 6. What Happens Next (150-200 words)
- What actions should the government take
- Timeline for expected responses
- Who will face questions (PAC, ministry officials)
- What citizens can watch for

### 7. Quotable Findings
Extract 5-7 findings suitable for pulling out as quotes:
- Dramatic, specific, and attributable
- Include exact rupee amounts
- Could be used as pull-quotes or social media posts

## Style Guidelines
- Active voice throughout ("The ministry failed to..." not "Failures were observed...")
- Short paragraphs (2-3 sentences maximum)
- Explain jargon in parentheses: "AO (Assessing Officer)"
- Make amounts relatable: "₹12,000 Crore—enough to build 2,400 government schools"
- Be dramatic but NEVER exaggerate beyond what the data supports
- Write with controlled outrage appropriate for public interest journalism
- NO meta-commentary - write as if filing an actual story

## Report Data:
{input}

## Output:
Write as if you're filing for tomorrow's front page. ~2000-2200 words total.
Start directly with "# Headlines" followed by your story.
```

---

### 5. Summary Generation — Deep Dive (Phase 10a)

**Location:** `src/batch_pipeline/prompts/summary_variants.py`

**Model:** `claude-opus-4-20250514` (via Batch API)

**When:** Offline — during Phase 10a batch processing

**Extended Thinking:** 16,000 budget tokens

**Target Words:** 3,500-4,000

**Why Claude Opus:** Longest, most complex summary requiring deep analytical reasoning.

#### Full Prompt

```markdown
You are creating a comprehensive academic analysis of this CAG audit report for researchers, policy analysts, and serious students of governance.

## Target Audience
- Academic researchers studying Indian governance
- Policy analysts at think tanks (CPR, ORF, PRS, etc.)
- PhD students in public administration, economics, or political science
- International organizations studying audit systems
- Parliamentary research staff

## Required Sections

### 1. Audit Framework & Institutional Context (400-500 words)
- Legal basis for this audit (CAG Act, Constitution Article 151)
- Type of audit (Performance/Compliance/Financial) and its significance
- Audit standards applied (SAI standards, international benchmarks)
- Institutional relationship between CAG, PAC, and audited entity
- Historical context of CAG audits in this sector

### 2. Methodology Analysis (500-600 words)
- Scope and coverage of the audit
- Sampling methodology used
- Time period and rationale for selection
- Selection criteria for cases/units examined
- Data sources (records, field visits, third-party data)
- Analytical methods employed
- Limitations acknowledged by CAG

### 3. Findings Analysis by Theme (1500-2000 words)
For EACH major thematic area:
- Key findings with exact paragraph/section references
- Methodology used for that specific examination
- Quantitative data and statistical patterns
- Cross-case patterns and variations
- Severity distribution within theme
- Causal analysis where provided

### 4. Quantitative Summary (400-500 words)
- Complete statistical breakdown of findings
- Cross-tabulations (severity × type, ministry × amount)
- Geographic or temporal distribution if applicable
- Trend analysis if historical comparisons made
- Statistical significance of samples

### 5. Systemic Issues Identified (400-500 words)
- Root causes identified by the audit
- Structural/institutional problems
- Regulatory and policy gaps
- Information system weaknesses
- Capacity and resource constraints
- Inter-agency coordination failures

### 6. Recommendations Analysis (400-500 words)
- Complete list of all recommendations
- Classification by type:
  - Policy-level changes
  - Process improvements
  - System/IT changes
  - Capacity building
  - Legal/regulatory amendments
- Feasibility assessment based on past implementation
- Comparison with recommendations from previous audits

### 7. Research Implications (300-400 words)
- Questions for further academic research
- Data gaps that future studies could address
- Methodological contributions of this audit
- Comparative research possibilities (other states, countries)
- Policy evaluation opportunities

### 8. Technical Appendix
- Complete list of major sections with page numbers
- Glossary of technical terms and abbreviations used
- List of Acts, Rules, and Regulations referenced
- Key entities and their roles
- Timeline of events if relevant

## Style Guidelines
- Academic tone throughout
- Use formal citation style: (Section 3.4.2, p. 45)
- Include verbatim quotes with exact references
- Present data in tabular format where appropriate
- Maintain analytical objectivity
- Acknowledge limitations and alternative interpretations
- Use proper academic structure (1.1, 1.2, etc.)

## Report Data:
{input}

## Output:
Write as a comprehensive research summary suitable for an academic working paper. ~3500-4000 words total.
Start directly with "# Deep Dive Analysis" followed by the content.
```

---

### 6. Summary Generation — Simple Explainer (Phase 10a)

**Location:** `src/batch_pipeline/prompts/summary_variants.py`

**Model:** `claude-sonnet-4-20250514` (via Batch API)

**When:** Offline — during Phase 10a batch processing

**Extended Thinking:** 6,000 budget tokens

**Target Words:** 1,200-1,500

#### Full Prompt

```markdown
You are explaining this government audit report to regular citizens who have no background in finance, accounting, or government procedures.

## Your Goal
Make this completely understandable to:
- A college student who doesn't study economics
- A small shop owner or farmer
- A retired person reading the newspaper
- Anyone who pays taxes but doesn't understand government jargon
- Someone who has 10 minutes to understand what happened

## Required Sections (Use Q&A Format with Simple Headers)

### What Is This Report About?
- Explain like you're telling a neighbor over tea
- NO jargon whatsoever (or explain it immediately in simple terms)
- What government department or program was checked?
- What were the auditors (think of them as government accountants/inspectors) looking for?
- Why should ordinary people care?

### What Did They Find Wrong?
- Top 5-7 problems in plain, everyday language
- Use relatable analogies: "It's like if you gave money to a contractor to build your house, but they used cheaper materials and kept the difference..."
- Make amounts relatable:
  - "₹12,000 Crore—that's enough money to give ₹1,000 to 12 crore families"
  - "₹500 Crore—that could build 100 new hospitals"
  - "This is like losing ₹90 from every ₹100 collected"

### Why Should I Care?
- How does this directly affect regular people?
- What services might be worse because of this?
- What happens to "your tax money"?
- Are there safety or health implications?

### Who Is Responsible?
- Which government department or officials
- What were they supposed to do?
- What did they actually do (or not do)?
- Keep it factual, don't be preachy or political

### What Should Happen Now?
- What the government should fix
- Simple action items anyone can understand
- How long these fixes might take
- What citizens can watch for

### The Bottom Line (5-6 bullets)
- Most important takeaways in one sentence each
- Amounts in relatable terms
- What this means for India

## Style Guidelines
- Write for someone who is intelligent but knows nothing about government accounting
- Very short sentences (under 15-20 words)
- Use "you" and "your taxes" and "your money"
- ZERO jargon without explanation:
  - AO → "the tax officer"
  - FY → "financial year (April to March)"
  - Crore → (explain once that 1 crore = 100 lakhs = 1 million)
  - Non-compliance → "not following the rules"
- Use everyday analogies from household, business, or daily life
- Be honest and clear, but not angry or preachy
- Treat readers as smart people who just need translation

## Report Data:
{input}

## Output:
Write in a friendly, clear, conversational tone. Use headers as questions people would ask.
Target ~1200-1500 words. Start directly with "# What Is This Report About?"
```

---

### 7. Summary Generation — Policy Brief (Phase 10a)

**Location:** `src/batch_pipeline/prompts/summary_variants.py`

**Model:** `claude-sonnet-4-20250514` (via Batch API)

**When:** Offline — during Phase 10a batch processing

**Extended Thinking:** 10,000 budget tokens

**Target Words:** 2,200-2,500

#### Full Prompt

```markdown
You are creating a Policy Brief for government officials who need to prepare formal responses to this CAG audit and implement corrective actions.

## Target Audience
- Ministry officials preparing Action Taken Notes
- Department heads implementing reforms
- Policy advisors drafting compliance responses
- Parliamentary committee members reviewing audit findings
- Legal and compliance teams

## Required Sections

### 1. Policy & Regulatory Context (300-350 words)
- Relevant laws, rules, and regulations governing the audited area
- Policy framework under which the audited entity operates
- Regulatory oversight structure (which bodies supervise)
- Recent policy changes that may be relevant
- Any pending reforms or proposed changes

### 2. Compliance Gaps Identified (500-600 words)

**A. Regulatory Non-Compliance**
- Specific statutory provisions violated (cite Act/Rule/Section)
- Frequency and extent of violations
- Whether systemic or isolated incidents
- Potential legal implications

**B. Process & Procedural Failures**
- Standard operating procedures not followed
- Documentation and record-keeping gaps
- Approval and authorization process issues
- Internal control weaknesses

**C. System & Monitoring Weaknesses**
- IT system deficiencies
- Data integrity and reliability problems
- MIS and monitoring mechanism failures
- Inter-system integration issues

### 3. Financial Implications (300-350 words)
- Total revenue loss or potential recovery amount
- Breakdown by category of irregularity
- Recurring versus one-time financial impact
- Compound effects and cascading losses
- Recovery potential and timeframe

### 4. Prioritized Action Plan (600-700 words)

**IMMEDIATE ACTIONS (0-3 months)**
- Quick fixes and interim measures
- Policy clarifications and instructions needed
- Circulars/Office Memoranda to be issued
- Emergency reviews to be initiated

**SHORT-TERM ACTIONS (3-12 months)**
- Process re-engineering requirements
- Training and capacity building needs
- System modifications and IT fixes
- Monitoring mechanism improvements

**MEDIUM-TERM ACTIONS (1-2 years)**
- Legislative or regulatory amendments
- Major system overhauls
- Structural and organizational reforms
- Inter-agency coordination improvements

### 5. Implementation Framework (300-350 words)
- Responsible officers/departments for each action
- Monitoring mechanisms and review frequency
- Reporting requirements and formats
- Success metrics and KPIs
- Escalation procedures

### 6. Risk Assessment (200-250 words)
- Consequences if issues continue unaddressed
- Potential escalation scenarios (PAC proceedings, court cases)
- Reputational and political risks
- Legal and regulatory exposure

### 7. Draft Response Template
Provide an outline for the ministry's formal Action Taken Note:
- Para-wise response structure
- Points to be accepted
- Points requiring factual clarification
- Points where action is already initiated
- Timeline commitments to be made

## Style Guidelines
- Use government/bureaucratic terminology appropriately
- Include specific section/rule/para references from the audit
- Format for easy tracking of action items
- Include suggested realistic timelines
- Be practical about implementation challenges
- Reference relevant GFR/CVC/DoPT guidelines where applicable

## Report Data:
{input}

## Output:
Write in formal policy document style suitable for ministry circulation. ~2200-2500 words total.
Start directly with "# Policy Brief" followed by the content.
```

---

### 8. Visual Extraction — Tables (Gemini)

**Location:** `src/batch_pipeline/enrichment/gemini_visual_extractor.py`

**Model:** `gemini-2.5-flash`

**When:** Offline — Phase 10b, for tables that failed pdfplumber and Docling

**Input:** PNG image of table cropped from PDF (200 DPI)

**Output:** JSON with markdown table, title, monetary unit, row/col counts

**Cost:** ~$0.001-0.005 per table

**Why Gemini:** Best vision model for structured data extraction, generous rate limits.

#### Full Prompt

```markdown
You are an expert at extracting structured data from Indian government audit report tables.

Analyze this table image and extract ALL data into a clean markdown table.

CRITICAL RULES:
1. Preserve EVERY row and column — do not skip or summarize
2. Indian number formats: use commas as-is (e.g., 1,23,456.78)
3. Fiscal years: preserve format exactly (e.g., 2021-22)
4. Currency: preserve units (crore, lakh) if shown in headers
5. Merged cells: repeat the value in each spanned cell
6. Multi-level headers: flatten into single header row with combined labels
7. "(continued)" or "Contd." markers: this is a continuation table, include all data rows
8. Empty cells: leave blank (don't write "N/A" or "-" unless that's what's printed)

OUTPUT FORMAT — respond with ONLY a JSON object, no markdown fences:
{
  "title": "Table title if visible, or null",
  "markdown": "| Header1 | Header2 |\n| --- | --- |\n| data | data |",
  "monetary_unit": "crore/lakh/null — if indicated in header or caption",
  "extraction_notes": ["any issues encountered"],
  "row_count": 10,
  "col_count": 5
}
```

---

### 9. Visual Extraction — Charts (Gemini)

**Location:** `src/batch_pipeline/enrichment/gemini_visual_extractor.py`

**Model:** `gemini-2.5-flash`

**When:** Offline — Phase 10b, for all chart/figure images

**Input:** PNG image of chart cropped from PDF (200 DPI)

**Output:** JSON with chart type, axes, data series, entities, time periods

**Cost:** ~$0.001-0.005 per chart

#### Full Prompt

```markdown
You are an expert at extracting structured data from charts in Indian government audit reports.

Analyze this chart image and extract ALL visible data points.

CRITICAL RULES:
1. Read EVERY data point — use axis gridlines to estimate values
2. Indian number formats: preserve commas (1,23,456)
3. Fiscal years: preserve format (2021-22, FY2023)
4. Percentage values: include % symbol
5. For bar/line charts: read each bar/point against the Y-axis
6. For pie charts: extract label + percentage/value for each slice
7. Multi-series: identify each series by its legend label

OUTPUT FORMAT — respond with ONLY a JSON object, no markdown fences:
{
  "title": "Chart title",
  "chart_type": "bar|line|pie|scatter|area|combo|unknown",
  "x_axis_label": "X axis label",
  "y_axis_label": "Y axis label",
  "monetary_unit": "crore/lakh/null",
  "series": [
    {
      "name": "Series name from legend",
      "data_points": [
        {"category": "2021-22", "value": 1234.56},
        {"category": "2022-23", "value": 2345.67}
      ]
    }
  ],
  "extraction_notes": ["any issues: blurry text, estimated values, etc."],
  "description": "One-sentence summary of what the chart shows"
}
```

---

### 10. Multi-Page Table Extraction (Gemini)

**Location:** `src/batch_pipeline/enrichment/gemini_visual_extractor.py`

**Model:** `gemini-2.5-flash`

**When:** Offline — Phase 10b, for tables spanning multiple pages

**Input:** Multiple PNG images (one per page), sent in single request

**Output:** Unified JSON with merged markdown table

**Cost:** ~$0.005-0.02 per multi-page table

#### Full Prompt

```markdown
You are an expert at extracting structured data from multi-page tables in Indian government audit reports.

The following images show a SINGLE TABLE that spans multiple pages. Extract ALL data into one unified markdown table.

CRITICAL RULES:
1. The table continues across pages — merge all data rows into one table
2. Headers may repeat on each page — include them only ONCE in the output
3. Preserve EVERY data row from ALL pages
4. Indian number formats: use commas as-is (e.g., 1,23,456.78)
5. Fiscal years: preserve format exactly (e.g., 2021-22)
6. Page {page_num} images are provided in order — merge top to bottom
7. "(continued)" or "Contd." markers indicate continuation — include the data, not the marker

OUTPUT FORMAT — respond with ONLY a JSON object, no markdown fences:
{
  "title": "Table title from first page",
  "markdown": "| Header1 | Header2 |\n| --- | --- |\n| all rows merged |",
  "monetary_unit": "crore/lakh/null",
  "extraction_notes": ["any issues encountered"],
  "row_count": 25,
  "col_count": 5,
  "pages_merged": [1, 2, 3]
}
```

---

### 11. Table Summary (Indexing)

**Location:** `src/rag_pipeline/embedding_service.py`

**Class:** `TableSummaryService`

**Model:** `gpt-4o-mini`

**When:** Offline — during RAG indexing for each table chunk

**Input:** Markdown table (max 2,000 chars) + section context

**Output:** 1-2 sentence natural language summary

**Cost:** ~$0.0001 per table (~$0.15/1M tokens)

**Why GPT-4o-mini:** Extremely cheap, fast, good enough for simple summarization.

**Fallback:** Rule-based extraction if LLM fails (extracts headers + row count).

#### Full Prompt

```markdown
Summarize this table from a CAG (Comptroller and Auditor General) audit report in 1-2 sentences.
Focus on: what data it shows, time period covered, key totals or trends.

Context: {context}

Table:
{table_text}

Summary (1-2 sentences, be specific about numbers and entities):
```

**Variables:**
- `{context}`: Section hierarchy (e.g., "Chapter 2 > Revenue Collection > Tax Assessment")
- `{table_text}`: Markdown table content (truncated to 2,000 chars)

---

### 12. Query Enhancement (RAG Phase 1)

**Location:** `src/rag_pipeline/query_enhancer.py`

**Model:** `gpt-4o-mini` (default) or `gemini-2.5-flash` (configurable)

**When:** Online — per user query

**Input:** User's question

**Output:** JSON with question type, expanded queries, filter suggestions, retrieval params

**Cost:** ~$0.0002 per query

**Why GPT-4o-mini:** Fast, cheap, reliable JSON output with `response_format={"type": "json_object"}`.

#### System Prompt

```markdown
You analyze questions about Indian CAG (Comptroller and Auditor General) audit reports.

Return ONLY valid JSON (no markdown, no backticks) with this exact schema:
{
  "question_type": "factual|list|aggregation|comparison|explanation|procedural",
  "expanded_queries": ["original query reworded for search", "alternative phrasing with domain terms"],
  "suggested_filters": {},
  "retrieval_params": {"top_k": 10, "initial_candidates": 50, "max_context_chars": 15000},
  "recommended_style": "concise|detailed|executive|technical|comparative|explanatory"
}

Rules for expanded_queries:
- Generate exactly 2 alternative queries (the original is added automatically)
- Rephrase using CAG/audit domain vocabulary (e.g., "money lost" → "revenue loss quantified in crore")
- Include specific terms likely in audit reports (findings, observations, recommendations, compliance)
- If the query mentions an entity, include its full name AND acronym in different queries

Rules for suggested_filters:
- Only include filters you're confident about. Empty {} is fine.
- Valid filter keys: "finding_type" (loss_of_revenue|non_compliance|fraud_misappropriation|wasteful_expenditure|performance_shortfall), "severity" (critical|high|medium|low)
- Do NOT guess report_id — leave that to the caller

Rules for retrieval_params:
- factual: {"top_k": 8, "initial_candidates": 30, "max_context_chars": 10000}
- list/aggregation: {"top_k": 18, "initial_candidates": 80, "max_context_chars": 25000}
- comparison: {"top_k": 15, "initial_candidates": 60, "max_context_chars": 22000}
- explanation: {"top_k": 12, "initial_candidates": 50, "max_context_chars": 18000}
- procedural: {"top_k": 10, "initial_candidates": 40, "max_context_chars": 15000}

Rules for recommended_style:
- factual → "concise", list → "detailed", aggregation → "executive"
- comparison → "comparative", explanation → "explanatory", procedural → "technical"
```

---

### 13. RAG Chat — Base System Prompt

**Location:** `src/rag_pipeline/rag_service.py`

**Models:** Claude Sonnet 4 / GPT-4o-mini / Gemini 2.5 Flash (configurable via `LLM_PROVIDER`)

**When:** Online — per user query

This base expertise prompt is included in ALL style variants:

```markdown
You are an expert analyst for the Comptroller and Auditor General (CAG) of India.

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
5. For aggregation questions, sum ONLY values explicitly stated - do not estimate totals
```

---

### 14. RAG Chat — Anti-Pattern Rules

Appended to base expertise for all styles:

```markdown
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
- Let the content speak for itself
```

---

### 15. RAG Chat — Citation Rules

Appended for all styles:

```markdown
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
5. DO NOT invent section numbers or modify the source label
```

---

### 16. RAG Chat — CONCISE Style

```markdown
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
The audit identified revenue loss of ₹64.60 crore due to delayed toll collection at NHAI projects. Non-functional electronic equipment at 12 toll plazas was the primary cause, representing a 23% increase from the previous year. The Ministry has acknowledged these findings. [Section 3.2.1, p.36]
```

---

### 17. RAG Chat — DETAILED Style

```markdown
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
```

---

### 18. RAG Chat — EXECUTIVE Style

```markdown
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
```

---

### 19. RAG Chat — TECHNICAL Style

```markdown
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
```

---

### 20. RAG Chat — COMPARATIVE Style

```markdown
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
```

---

### 21. RAG Chat — ADAPTIVE Style

```markdown
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
- Use exact amounts from context
```

---

### 22. RAG Chat — EXPLANATORY Style

```markdown
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
```

---

### 23. RAG Chat — REPORT Style

```markdown
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

### Word count: 500-800 words
```

---

### 24. Time Series System Prompt

**Location:** `src/rag_pipeline/rag_service.py`

**When:** Online — for cross-year queries and COMPARATIVE style

```markdown
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
```

---

### 25. Finding Extraction (Batch Enrichment)

**Location:** `src/batch_pipeline/prompts/finding_extraction.py`

**Model:** GPT-4o-mini (OpenAI Batch) or Claude Sonnet 4 (Anthropic Batch)

**When:** Offline — P2-1 LLM-Augmented Enrichment

**Input:** Chunk content + hierarchy context

**Output:** JSON with findings array (type, summary, amount, severity, entities, evidence)

```markdown
You are analyzing a chunk from a CAG (Comptroller and Auditor General of India) audit report.

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
- If no findings exist, return {"findings": []}
- For monetary amounts, handle Indian number formats (crore/lakh)
- Consider parenthetical amounts as negative (e.g., "(₹50 crore)" = -50)
- Extract all findings, even minor ones - severity scoring handles prioritization

OUTPUT FORMAT (JSON only):
{
  "findings": [
    {
      "finding_type": "irregular_expenditure",
      "summary": "Unauthorized expenditure on construction without approval",
      "monetary_amount": 847.71,
      "currency_unit": "crore",
      "severity": "high",
      "entities": ["Ministry of Railways", "Northern Railway Zone"],
      "evidence_refs": ["Table 3.2", "Para 4.1.5"]
    }
  ]
}

If no findings, return: {"findings": []}
```

---

### 26. Entity Extraction (Batch Enrichment)

**Location:** `src/batch_pipeline/prompts/entity_extraction.py`

**Model:** GPT-4o-mini (OpenAI Batch)

**When:** Offline — P2-1 LLM-Augmented Enrichment

```markdown
You are analyzing a CAG audit report chunk to extract structured entity information.

TASK: Extract all mentioned entities and classify them.

Entity Categories:
1. **ministries**: Central government ministries
   - Format: "Ministry of [Name]"
   - Examples: "Ministry of Railways", "Ministry of Finance"

2. **departments**: Departments under ministries
   - Format: "Department of [Name]"
   - Examples: "Department of Revenue", "Department of Posts"

3. **directorates**: Directorates and subordinate offices
   - Examples: "Directorate General of Supplies and Disposals"

4. **psus**: Public Sector Undertakings
   - Examples: "Indian Railways", "NHAI", "BSNL"

5. **autonomous_bodies**: Autonomous organizations
   - Examples: "ICMR", "ICAR", "National Highway Authority"

6. **state_governments**: State/UT governments
   - Format: "Government of [State]"
   - Examples: "Government of Tamil Nadu", "Government of Delhi"

7. **schemes**: Government schemes and programs
   - Examples: "Pradhan Mantri Gram Sadak Yojana", "MGNREGA"

8. **laws_regulations**: Acts, rules, regulations referenced
   - Examples: "General Financial Rules 2017", "Income Tax Act 1961"

9. **geographic**: States, districts, regions mentioned
   - Examples: "Maharashtra", "North-Eastern States"

TEXT:
{chunk_content}

GUIDELINES:
- Use full official names (not abbreviations) where possible
- If both abbreviation and full form appear, use full form
- For schemes, capture the full official name
- Avoid generic terms like "the Ministry" - be specific
- Only extract entities explicitly mentioned in the text

OUTPUT FORMAT (JSON only):
{
  "entities": {
    "ministries": ["Ministry of Railways"],
    "departments": ["Department of Posts"],
    "directorates": [],
    "psus": ["National Highways Authority of India"],
    "autonomous_bodies": [],
    "state_governments": ["Government of Uttar Pradesh"],
    "schemes": ["Pradhan Mantri Gram Sadak Yojana"],
    "laws_regulations": ["General Financial Rules 2017"],
    "geographic": ["Uttar Pradesh", "Bihar"]
  }
}

If no entities found in a category, use empty list [].
```

---

### 27. Implicit Finding Detection (Batch Enrichment)

**Location:** `src/batch_pipeline/prompts/implicit_finding.py`

**Model:** Claude Sonnet 4 (Anthropic Batch) — for complex analysis

**When:** Offline — P2-1 LLM-Augmented Enrichment

```markdown
You are analyzing a CAG audit report chunk for IMPLICIT audit issues.

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
{
  "implicit_issues": [
    {
      "issue_type": "variance",
      "description": "Budget allocation of ₹500 crore exceeded by ₹120 crore without approval",
      "monetary_impact": 120.0,
      "confidence": 0.85,
      "supporting_text": "actual expenditure was ₹620 crore against budget of ₹500 crore"
    }
  ]
}

If no implicit issues found with confidence >= 0.6, return: {"implicit_issues": []}
```

---

### 28. Chart Extraction (Anthropic Batch)

**Location:** `src/batch_pipeline/prompts/chart_extraction.py`

**Model:** Claude Sonnet 4 (for complex charts via Anthropic Batch)

**When:** Offline — P2-2 Chart Data Extraction (alternative to Gemini)

This is a comprehensive 200+ line prompt for extracting structured data from chart images with detailed guidance on:
- Chart type classification (bar, line, pie, scatter, area, combo)
- Axis identification and type inference
- Data point extraction with value estimation
- Indian monetary unit recognition (crore/lakh)
- Fiscal year format normalization
- Entity recognition (ministries, states, schemes)
- Confidence scoring (0.0-1.0)
- Multi-series chart handling

*(Full prompt available in `src/batch_pipeline/prompts/chart_extraction.py`)*

---

## Batch API Architecture

### Overview

The CAG Gateway uses batch APIs from both Anthropic and OpenAI for offline processing, achieving 50% cost reduction compared to synchronous API calls.

### Job Lifecycle

```
1. SUBMIT → 2. PROCESSING → 3. COMPLETED → 4. RESULTS DOWNLOADED → 5. HYDRATED
```

### Folder Structure

```
data/batch_jobs/
├── jobs/
│   ├── job_YYYYMMDD_HHMMSS.json          # Job tracker
│   └── job_YYYYMMDD_HHMMSS_mapping.json  # custom_id → report_id mapping
├── overviews/
│   └── {report_id}_overview_llm.json     # LLM-extracted overview data
├── summaries/
│   └── {report_id}_summaries.json        # All 5 summary variants
├── enrichment/
│   └── enrichment_YYYYMMDD_HHMMSS.json   # P2-1 enrichment tracker
└── visual_extraction/
    └── visual_extraction_YYYYMMDD.json   # Gemini extraction tracker
```

### Request-to-Report Mapping

Each batch request has a `custom_id` (max 64 chars) that maps back to the source:

```python
# Format: {prefix}_{hash}_{truncated_report_id}
# Examples:
"ov_a1b2c3d4_CAG_Railways_2023"           # Overview extraction
"sm_ex_a1b2c3d4_CAG_Railways_2023"        # Executive summary
"sm_jo_a1b2c3d4_CAG_Railways_2023"        # Journalist summary
```

Mapping stored in `job_*_mapping.json`:
```json
{
  "sm_ex_a1b2c3d4_CAG_Railways_2023": {
    "report_id": "CAG_Railways_Performance_2023_24",
    "variant": "executive"
  }
}
```

### Extended Thinking Configuration

Claude batch jobs use Extended Thinking for higher quality outputs:

| Summary Variant | Model | Max Tokens | Thinking Budget |
|----------------|-------|------------|-----------------|
| Overview | Claude Sonnet 4 | 16,000 | 5,000 |
| Executive | Claude Sonnet 4 | 16,000 | 8,000 |
| Journalist | Claude Opus 4 | 20,000 | 12,000 |
| Deep Dive | Claude Opus 4 | 24,000 | 16,000 |
| Simple | Claude Sonnet 4 | 12,000 | 6,000 |
| Policy | Claude Sonnet 4 | 16,000 | 10,000 |

### Error Handling and Retries

- Failed requests return `result.type == "errored"` with error message
- Expired requests return `result.type == "expired"`
- Canceled requests return `result.type == "canceled"`
- Per-report results tracked in job tracker for retry identification

---

## Prompt Engineering Patterns

### JSON Output Enforcement

All prompts that require structured output use these techniques:

1. **Explicit Schema**: Full JSON schema with examples in prompt
2. **Output Guards**: "Return ONLY valid JSON, no markdown fences"
3. **OpenAI JSON Mode**: `response_format={"type": "json_object"}` where supported
4. **Gemini MIME Type**: `response_mime_type="application/json"`
5. **Fallback Parsing**: Strip markdown fences if present

### Anti-Hallucination Guardrails

1. **CRITICAL RULES section** in all RAG prompts
2. **Explicit "information not available" instruction**
3. **"NEVER invent, extrapolate, or estimate"** language
4. **Source-label citation requirement** — forces LLM to reference actual labels

### Citation Format Standardization

- **Source Labels**: Backend adds `[Source: section, p.XX]` to each context passage
- **Citation Rule**: LLM must copy label exactly
- **Placement Rule**: Citations at END of sentence, never mid-sentence
- **Match Rate**: ~95% with this approach

### Word Count Control

Each style prompt includes:
- Target word count range (e.g., "300-500 words")
- Per-section word allocations
- "Word count: X-Y words" as final reminder

### Audience Adaptation

Summary variants demonstrate audience targeting:
- **Executive**: "Ministry secretaries", formal government tone
- **Journalist**: "readers of major newspapers", active voice
- **Academic**: "PhD students", citation style, methodology focus
- **Simple**: "shop owner or farmer", "explain like neighbor over tea"
- **Policy**: "officials preparing Action Taken Notes", bureaucratic terminology

### Missing Data Handling

Time Series prompts explicitly address missing data:
```
If a specific metric is NOT available for a particular year:
- Explicitly state: "Data not available for [YEAR]"
- Do NOT guess, estimate, or omit silently
- Do NOT hallucinate values for missing years
```

---

## Cost Architecture

### Per-Model Cost Table

| Model | Input (per 1M) | Output (per 1M) | Batch Discount |
|-------|----------------|-----------------|----------------|
| Claude Haiku 4.5 | $0.25 | $1.25 | 50% |
| Claude Sonnet 4 | $3.00 | $15.00 | 50% |
| Claude Opus 4 | $15.00 | $75.00 | 50% |
| GPT-4o-mini | $0.15 | $0.60 | 50% |
| Gemini 2.5 Flash | ~$0.075 | ~$0.30 | N/A |
| text-embedding-3-large | $0.13 | N/A | N/A |

### Offline Processing Costs (Per Report)

| Task | Model | Est. Cost |
|------|-------|-----------|
| TOC Validation (15% of reports) | Claude Haiku | ~$0.015 |
| Overview Extraction | Claude Sonnet (Batch) | ~$0.035 |
| Executive Summary | Claude Sonnet (Batch) | ~$0.04 |
| Journalist Summary | Claude Opus (Batch) | ~$0.15 |
| Deep Dive Summary | Claude Opus (Batch) | ~$0.20 |
| Simple Summary | Claude Sonnet (Batch) | ~$0.03 |
| Policy Summary | Claude Sonnet (Batch) | ~$0.04 |
| Visual Extraction (avg 5 items) | Gemini 2.5 Flash | ~$0.01 |
| Table Summaries (avg 10 tables) | GPT-4o-mini | ~$0.001 |
| Embeddings (avg 100 chunks) | text-embedding-3-large | ~$0.002 |

**Total per report: ~$0.50-0.55** (with Opus summaries)
**Total per report: ~$0.15-0.20** (without Opus summaries)

### Full Corpus Estimates (1,297 Reports)

| Scenario | Cost |
|----------|------|
| Minimal (TOC + Overview + Sonnet summaries) | ~$200-250 |
| Standard (+ Opus for journalist/deep_dive) | ~$450-550 |
| Full (+ all enrichment + visual) | ~$600-750 |

### Online Query Costs

| Task | Model | Cost per Query |
|------|-------|----------------|
| Query Enhancement | GPT-4o-mini | ~$0.0002 |
| Query Embedding | text-embedding-3-large | ~$0.0001 |
| RAG Generation (Claude) | Claude Sonnet | ~$0.005-0.01 |
| RAG Generation (GPT) | GPT-4o-mini | ~$0.001-0.003 |
| Reranking | Cohere | ~$0.002 |

**Cost per query: ~$0.008-0.015** (Claude) or **~$0.003-0.006** (GPT-4o-mini)

### Monthly Projections

| Query Volume | Claude RAG | GPT RAG |
|--------------|------------|---------|
| 1,000/month | ~$10-15 | ~$4-6 |
| 10,000/month | ~$100-150 | ~$40-60 |
| 100,000/month | ~$1,000-1,500 | ~$400-600 |

### Cost Optimization Strategies

1. **Batch API**: 50% discount on all Anthropic/OpenAI batch processing
2. **Model Tiering**: Opus only for quality-critical long-form (2 of 5 summaries)
3. **Haiku for Validation**: Cheapest Claude model for TOC correction
4. **GPT-4o-mini for Simple Tasks**: 20x cheaper than Sonnet
5. **Built-in BM25**: Zero-cost sparse embeddings (no fastembed)
6. **Dimensionality Reduction**: 1536 instead of 3072 for embeddings (50% cost)
7. **Query Enhancement Caching**: Results cached per session
8. **Context Truncation**: Limit context to 15-25K chars based on question type
