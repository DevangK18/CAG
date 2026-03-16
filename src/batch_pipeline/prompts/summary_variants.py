"""
Prompts for generating the 5 summary variants.

Variants:
- executive: Boardroom-ready, action-oriented
- journalist: News-style, headlines, public interest
- deep_dive: Academic analysis, methodology, research
- simple: Plain language for general public
- policy: Government action plan, compliance focus
"""

import json

VARIANTS = ["executive", "journalist", "deep_dive", "simple", "policy"]

VARIANT_INFO = {
    "executive": {
        "name": "Executive Brief",
        "icon": "📋",
        "description": "Boardroom-ready summary with key findings and action items",
        "target_words": "2200-2500",
    },
    "journalist": {
        "name": "Journalist's Take",
        "icon": "📰",
        "description": "News-style writeup with headlines and quotable findings",
        "target_words": "2000-2200",
    },
    "deep_dive": {
        "name": "Deep Dive",
        "icon": "🔬",
        "description": "Comprehensive academic analysis for researchers",
        "target_words": "3500-4000",
    },
    "simple": {
        "name": "Simple Explainer",
        "icon": "💡",
        "description": "Plain language explanation for everyone",
        "target_words": "1200-1500",
    },
    "policy": {
        "name": "Policy Brief",
        "icon": "🏛️",
        "description": "Actionable insights for government officials",
        "target_words": "2200-2500",
    },
}


def build_summary_input(json_data: dict) -> str:
    """
    Build optimized input for summary generation.
    Uses pre-extracted data from JSON to minimize tokens while maximizing signal.
    Target: ~12,000-15,000 tokens of high-signal content.
    """
    parts = []

    meta = json_data.get("report_metadata", {})
    enrichment = json_data.get("semantic_enrichment", {})
    stats = enrichment.get("statistics", {})
    findings_stats = stats.get("findings", {})

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 1: REPORT CONTEXT
    # ═══════════════════════════════════════════════════════════════════════

    parts.append(f"""# REPORT: {meta.get("report_title", "N/A")}

## Basic Information
- Report Number: {meta.get("report_no", "N/A")}
- Type: {meta.get("report_type", "N/A")}
- Ministry: {meta.get("ministry", "N/A")}
- Sector: {meta.get("sector", "N/A")}
- Publication Date: {meta.get("publication_date", "N/A")}

## Findings Overview
- Total Findings: {findings_stats.get("total_count", 0)}
- Total Monetary Impact: ₹{findings_stats.get("total_monetary_crore", 0):,.2f} Crore
- By Severity: {json.dumps(findings_stats.get("by_severity", {}))}
- By Type: {json.dumps({k: v.get("count", 0) for k, v in findings_stats.get("by_type", {}).items()})}
""")

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 2: DETAILED FINDINGS (Pre-extracted from semantic_enrichment)
    # ═══════════════════════════════════════════════════════════════════════

    findings = enrichment.get("findings", [])

    if findings:
        # Sort by monetary amount (highest first)
        sorted_findings = sorted(
            findings, key=lambda x: x.get("total_amount_inr", 0), reverse=True
        )

        parts.append("\n# DETAILED FINDINGS (sorted by monetary impact)\n")

        for i, f in enumerate(sorted_findings[:25], 1):  # Top 25 findings
            amount_cr = f.get("total_amount_inr", 0) / 10000000
            text = f.get("text", f.get("summary", ""))[:600]

            parts.append(f"""
## Finding {i} [{f.get("severity", "N/A").upper()}]
- Type: {f.get("finding_type", "N/A")}
- Amount: ₹{amount_cr:,.2f} Crore
- Location: {f.get("chapter", "N/A")} > {f.get("section", "N/A")} (p.{f.get("page", "N/A")})

{text}
""")
    else:
        parts.append(
            "\n# FINDINGS: No structured findings extracted from this report.\n"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 3: RECOMMENDATIONS (Pre-extracted)
    # ═══════════════════════════════════════════════════════════════════════

    recs = enrichment.get("recommendations", [])

    if recs:
        parts.append("\n# RECOMMENDATIONS\n")
        for i, r in enumerate(recs[:20], 1):  # Top 20 recommendations
            text = r.get("text", r.get("summary", ""))
            chapter = r.get("chapter", "")
            page = r.get("page", "")
            parts.append(f"{i}. {text}")
            if chapter:
                parts.append(f"   [{chapter}, p.{page}]")
            parts.append("")
    else:
        parts.append("\n# RECOMMENDATIONS: No structured recommendations extracted.\n")

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 4: EXECUTIVE SUMMARY (if available in child_chunks)
    # ═══════════════════════════════════════════════════════════════════════

    exec_content = _get_executive_summary_content(json_data)
    if exec_content:
        parts.append("\n# EXECUTIVE SUMMARY (Original Text from Report)\n")
        parts.append(exec_content[:6000])

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 5: KEY TABLES (for data-heavy summaries)
    # ═══════════════════════════════════════════════════════════════════════

    tables = [
        c
        for c in json_data.get("child_chunks", [])
        if c.get("content_type") == "table_markdown"
    ][:8]  # First 8 tables

    if tables:
        parts.append("\n# KEY TABLES\n")
        for t in tables:
            page = t.get("source_page_physical", "N/A")
            hierarchy = t.get("hierarchy", {})
            section = list(hierarchy.values())[-1] if hierarchy else "Unknown Section"
            parts.append(f"\n**Table from {section} (p.{page})**")
            parts.append(t.get("content", "")[:1200])  # Truncate large tables

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6: ENTITIES (for context)
    # ═══════════════════════════════════════════════════════════════════════

    entities = enrichment.get("entities", {})
    if entities:
        parts.append("\n# KEY ENTITIES MENTIONED\n")
        if entities.get("ministries"):
            parts.append(
                f"- Ministries/Departments: {', '.join(entities['ministries'][:10])}"
            )
        if entities.get("organizations"):
            parts.append(
                f"- Organizations: {', '.join(entities['organizations'][:10])}"
            )
        if entities.get("schemes"):
            parts.append(f"- Schemes/Programs: {', '.join(entities['schemes'][:10])}")

    return "\n".join(parts)


def _get_executive_summary_content(json_data: dict) -> str:
    """Extract Executive Summary section content from child_chunks."""
    content = []

    for chunk in json_data.get("child_chunks", []):
        if chunk.get("content_type") not in ["paragraph", "text"]:
            continue

        hierarchy = chunk.get("hierarchy", {})
        hierarchy_str = " ".join(str(v) for v in hierarchy.values()).lower()

        if "executive summary" in hierarchy_str or "preface" in hierarchy_str:
            chunk_content = chunk.get("content", "")
            if chunk_content and len(chunk_content) > 50:
                content.append(chunk_content)

    return "\n\n".join(content[:25])  # Limit to 25 chunks


def get_summary_prompt(variant: str, summary_input: str, json_data: dict) -> str:
    """Get the prompt for a specific summary variant."""

    meta = json_data.get("report_metadata", {})

    prompts = {
        "executive": _get_executive_prompt(),
        "journalist": _get_journalist_prompt(),
        "deep_dive": _get_deep_dive_prompt(),
        "simple": _get_simple_prompt(),
        "policy": _get_policy_prompt(),
    }

    return prompts[variant].format(
        input=summary_input,
        report_title=meta.get("report_title", "N/A"),
        report_type=meta.get("report_type", "N/A"),
        ministry=meta.get("ministry", "N/A"),
    )


def _get_executive_prompt() -> str:
    return """You are creating an Executive Brief summary of this CAG audit report for senior government officials.

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
"""


def _get_journalist_prompt() -> str:
    return """You are a senior investigative journalist at a major national newspaper (like The Hindu, Indian Express, or Times of India) writing about this CAG audit report.

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
"""


def _get_deep_dive_prompt() -> str:
    return """You are creating a comprehensive academic analysis of this CAG audit report for researchers, policy analysts, and serious students of governance.

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
"""


def _get_simple_prompt() -> str:
    return """You are explaining this government audit report to regular citizens who have no background in finance, accounting, or government procedures.

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
"""


def _get_policy_prompt() -> str:
    return """You are creating a Policy Brief for government officials who need to prepare formal responses to this CAG audit and implement corrective actions.

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
"""
