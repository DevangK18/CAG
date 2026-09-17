"""
Prompts for generating the 5 summary variants.

Variants:
- executive: Boardroom-ready, action-oriented
- journalist: News-style, headlines, public interest
- deep_dive: Academic analysis, methodology, research
- simple: Plain language for general public
- policy: Government action plan, compliance focus

Supports tier-aware context for Union, State, and Local Body reports.
"""

import json

VARIANTS = ["executive", "journalist", "deep_dive", "simple", "policy"]

# ═══════════════════════════════════════════════════════════════════════════════
# TIER CONTEXT DICTIONARY
# ═══════════════════════════════════════════════════════════════════════════════

TIER_CONTEXT = {
    "union": {
        "name": "Union",
        "submitted_to": "President of India",
        "legislature": "Parliament",
        "oversight_committee": "Public Accounts Committee (PAC)",
        "primary_audience": [
            "Cabinet Ministers and Ministry Secretaries",
            "Joint Secretaries and Department heads",
            "PAC and COPU members",
            "Officials preparing for parliamentary committee meetings",
        ],
        "legal_framework": "CAG DPC Act 1971, GFR 2017, CVC Guidelines",
        "financial_scale": {
            "critical": "₹100 Crore",
            "high": "₹10 Crore",
            "example_large": "₹12,000 Crore",
            "example_medium": "₹500 Crore",
            "relatable": "₹12,000 Crore—enough to build 2,400 government schools",
        },
        "action_channels": "Ministry circulars, Office Memoranda, Cabinet notes",
        "media_context": "major national newspaper (The Hindu, Indian Express, Times of India)",
        "entity_examples": "Central Ministries, PSUs like NHAI/FCI, national schemes like PMAY",
        "headline_examples": [
            "₹3.5 Lakh Crore Gap: CAG Audit Exposes Tax Collection Failures",
            "Railway Safety Funds Unspent as Accidents Continue, Reveals CAG",
            "Government Lost ₹12,000 Crore to Contract Irregularities: Audit",
        ],
    },
    "state": {
        "name": "State",
        "submitted_to": "Governor of {state_name}",
        "legislature": "State Legislature (Vidhan Sabha)",
        "oversight_committee": "State Public Accounts Committee",
        "primary_audience": [
            "Chief Secretary and Additional Chief Secretaries",
            "Department Secretaries and Special Secretaries",
            "Heads of Departments and Directors",
            "State PAC members and MLAs",
            "Officials preparing for State Assembly committee meetings",
        ],
        "legal_framework": "Article 151, State Financial Rules, State Treasury Code, AG guidelines",
        "financial_scale": {
            "critical": "₹50 Crore",
            "high": "₹5 Crore",
            "example_large": "₹500 Crore",
            "example_medium": "₹50 Crore",
            "relatable": "₹500 Crore—the annual budget of 50 district hospitals",
        },
        "action_channels": "Government Orders (GOs), Department circulars, Secretariat instructions",
        "media_context": "major regional newspaper (Dainik Bhaskar, Amar Ujala, Eenadu, Mathrubhumi)",
        "entity_examples": "State departments, State PSEs (SPSEs), state-level schemes",
        "headline_examples": [
            "₹500 Crore Meant for State Roads Diverted: CAG Audit",
            "State Health Department Failed to Spend ₹200 Crore: Audit Reveals",
            "Power Distribution Losses Cost State ₹1,200 Crore Annually: CAG",
        ],
    },
    "local_body": {
        "name": "Local Body",
        "submitted_to": "State Government ({state_name})",
        "legislature": "State Legislature (for information)",
        "oversight_committee": "District-level review committees, State PAC",
        "primary_audience": [
            "District Collectors and Additional District Magistrates",
            "Block Development Officers (BDOs) and Circle Officers",
            "Municipal Commissioners and Executive Officers",
            "Director of Panchayats / Municipal Administration",
            "Sarpanches, Panchayat Secretaries, and elected representatives",
        ],
        "legal_framework": "State Panchayat Act, Municipal Act, 73rd/74th Constitutional Amendments, SFC/CFC guidelines",
        "financial_scale": {
            "critical": "₹10 Crore",
            "high": "₹1 Crore",
            "medium": "₹10 Lakh",
            "example_large": "₹25 Crore",
            "example_medium": "₹2 Crore",
            "example_small": "₹50 Lakh",
            "relatable": "₹50 Lakh—the annual budget of 5 Gram Panchayats",
        },
        "action_channels": "District Collector orders, Panchayat resolutions, Municipal council decisions",
        "media_context": "regional and local newspapers with grassroots impact framing",
        "entity_examples": "Gram Panchayats, Zilla Parishads, Municipal Corporations, Block offices, DRDA",
        "headline_examples": [
            "₹25 Crore for Village Roads Unused: CAG Finds 200 GPs Never Spent Their Grants",
            "60% of Gram Panchayats Haven't Been Audited in 3 Years: CAG Report",
            "Municipal Corporations Failed to Collect ₹15 Crore in Property Tax: Audit",
        ],
    },
}


def _build_government_context(meta: dict) -> str:
    """Build tier-aware Government Context block for summary prompts."""
    government_body_type = meta.get("government_body_type", "union")
    state_name = meta.get("state_name")
    department = meta.get("department")

    if government_body_type == "union":
        # Minimal addition for backward compatibility
        return ""

    elif government_body_type == "state":
        dept_display = department or "Multiple departments"
        return f"""## Government Context
Government Level: State Government
State: {state_name}
Submitted To: Governor of {state_name}
Legal Basis: Article 151 of the Constitution
Department: {dept_display}
"""

    elif government_body_type == "local_body":
        dept_display = department or "Panchayati Raj / Urban Development"
        return f"""## Government Context
Government Level: Local Body (PRIs and ULBs)
State: {state_name}
Submitted To: Government of {state_name}
Legal Basis: Section 20(1) of CAG DPC Act 1971
Department: {dept_display}
"""

    return ""

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

    # Build tier-aware government context
    govt_context = _build_government_context(meta)

    parts.append(f"""# REPORT: {meta.get("report_title", "N/A")}

{govt_context}## Basic Information
- Report Number: {meta.get("report_no", "N/A")}
- Type: {meta.get("report_type", "N/A")}
- Ministry/Department: {meta.get("department") or meta.get("ministry", "N/A")}
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
    """Get the prompt for a specific summary variant with tier-specific customization."""

    meta = json_data.get("report_metadata", {})
    audit_category = meta.get("audit_category", "")
    tier = meta.get("government_body_type", "union")
    state_name = meta.get("state_name")

    prompts = {
        "executive": _get_executive_prompt(tier, state_name),
        "journalist": _get_journalist_prompt(tier, state_name, audit_category),
        "deep_dive": _get_deep_dive_prompt(tier, state_name),
        "simple": _get_simple_prompt(tier, state_name, audit_category),
        "policy": _get_policy_prompt(tier, state_name),
    }

    return prompts[variant].format(
        input=summary_input,
        report_title=meta.get("report_title", "N/A"),
        report_type=meta.get("report_type", "N/A"),
        ministry=meta.get("department") or meta.get("ministry", "N/A"),
    )


def _get_executive_prompt(tier: str = "union", state_name: str = None) -> str:
    """Dispatcher for tier-specific executive prompts."""
    if tier == "state":
        return _get_executive_prompt_state(state_name)
    elif tier == "local_body":
        return _get_executive_prompt_local(state_name)
    else:
        return _get_executive_prompt_union()


def _get_executive_prompt_union() -> str:
    """Executive Brief for Union (Central Government) reports."""
    return """You are creating an Executive Brief summary of this CAG audit report for senior Central Government officials.

## Target Audience
- Ministry Secretaries and Joint Secretaries
- Department heads and senior bureaucrats
- Decision-makers who need to understand key issues quickly
- Officials preparing for Parliamentary committee meetings (PAC, COPU)

## Required Sections

### 1. Context & Scope (200-250 words)
- What Central Government entity/ministry was audited and why it matters nationally
- Time period covered
- Type of audit (Performance/Compliance/Financial)
- Scale of operations examined (budget size, geographic spread)

### 2. Critical Findings (800-1000 words)
- Present the TOP 7-10 most significant findings
- Order by monetary impact (highest first)
- For each finding include:
  - Clear statement of the issue
  - Specific amount in ₹ Crores
  - Reference to section/paragraph
  - Brief implication for national programs/taxpayers
- Use sub-headers to group related findings

### 3. Financial Impact Summary (300-400 words)
- Total monetary impact across all findings
- Breakdown by category (non-compliance, revenue loss, irregular expenditure, etc.)
- Breakdown by severity (critical ≥₹100 Cr, high ≥₹10 Cr, medium ≥₹1 Cr)
- Any recurring vs. one-time issues

### 4. Key Recommendations (400-500 words)
- Summarize the main recommendations from the report
- Group by theme/area
- Indicate which require immediate attention
- Note any systemic changes recommended

### 5. Action Items (200-250 words)
- Ministry circulars/Office Memoranda to be issued (0-3 months)
- Process changes and system fixes (3-12 months)
- Key accountability points
- Parliamentary question preparation points

## Style Guidelines
- Formal, professional tone suitable for Central Government communication
- Use bullet points strategically for scanability
- Always include specific numbers (₹X.XX Crore)
- Reference source sections (Section 3.4, Para 2.5.1)
- Reference GFR/CVC guidelines where applicable
- NO meta-commentary like "This report discusses..." - start directly with content
- Use tables where they aid comprehension

## Report Data:
{input}

## Output:
Write the Executive Brief in clean markdown format. Target ~2200-2500 words total.
Start directly with "# Executive Brief" followed by the content.
"""


def _get_executive_prompt_state(state_name: str = None) -> str:
    """Executive Brief for State Government reports."""
    state_display = state_name or "the State"
    return f"""You are creating an Executive Brief summary of this CAG State audit report for senior {state_display} Government officials.

## Target Audience
- Chief Secretary and Additional Chief Secretaries
- Department Secretaries and Special Secretaries
- Heads of Departments and Directors
- State PAC members and MLAs
- Officials preparing for State Assembly committee meetings

## Required Sections

### 1. Context & Scope (200-250 words)
- What state entity/department in {state_display} was audited
- Time period covered
- Type of audit (Performance/Compliance/Financial)
- Scale of operations examined within the state

### 2. Critical Findings (700-900 words)
- Present the TOP 5-7 most significant findings
- Order by monetary impact (highest first)
- For each finding include:
  - Clear statement of the issue
  - Specific amount in ₹ Crores
  - Reference to section/paragraph
  - Implication for state finances/services
- Use sub-headers to group related findings

### 3. Financial Impact Summary (250-350 words)
- Total monetary impact across all findings
- Breakdown by category (non-compliance, revenue loss, irregular expenditure)
- Breakdown by severity (critical ≥₹50 Cr, high ≥₹5 Cr, medium ≥₹0.5 Cr)
- Comparison to state budget allocations where relevant
- Recurring vs. one-time issues

### 4. Key Recommendations (350-450 words)
- Summarize main recommendations
- Group by department/theme
- Indicate which require immediate attention
- Note systemic changes recommended

### 5. Action Items (200-250 words)
- Government Orders (GOs) to be issued
- Department-level instructions needed
- Review mechanisms to establish
- State Assembly question preparation points

## Style Guidelines
- Formal, professional tone suitable for state government communication
- Reference State Financial Rules and Treasury Code where applicable
- Include specific amounts (₹X.XX Crore)
- Reference source sections (Section 3.4, Para 2.5.1)
- NO meta-commentary - start directly with content
- Use tables where they aid comprehension

## Report Data:
{input}

## Output:
Write the Executive Brief in clean markdown format. Target ~2000-2300 words total.
Start directly with "# Executive Brief" followed by the content.
"""


def _get_executive_prompt_local(state_name: str = None) -> str:
    """Executive Brief for Local Body (PRI/ULB) reports."""
    state_display = state_name or "the State"
    return f"""You are creating an Executive Brief summary of this CAG Local Body audit report for district administration and local governance officials in {state_display}.

## Target Audience
- District Collectors and Additional District Magistrates
- Block Development Officers (BDOs) and Circle Officers
- Municipal Commissioners and Executive Officers
- Director of Panchayats / Municipal Administration
- Sarpanches and elected representatives (for awareness)
- State Panchayati Raj / Urban Development Department officials

## Required Sections

### 1. Context & Scope (200-250 words)
- Which PRIs (Gram Panchayats, Panchayat Samitis, Zilla Parishads) and/or ULBs (Municipal Corporations, Municipalities, Nagar Panchayats) were audited
- Time period covered
- Type of report (ATIR / Performance Audit)
- Number and types of local bodies covered
- Key schemes/functions examined (own revenue, grants, scheme implementation)

### 2. Critical Findings (600-800 words)
- Present the TOP 5 most significant findings
- Order by impact (financial + institutional)
- For each finding include:
  - Clear statement of the issue
  - Amount involved (use ₹ Lakhs for smaller amounts, ₹ Crores for larger)
  - Number of local bodies affected
  - Reference to section/paragraph
  - Direct impact on citizens/service delivery
- Group by: Financial Management, Scheme Implementation, Institutional Compliance

### 3. Financial Impact Summary (200-300 words)
- Total monetary irregularities
- Breakdown by:
  - Own revenue vs grant funds
  - SFC/CFC grant utilization issues
  - Scheme-wise irregularities (MGNREGA, housing, sanitation, etc.)
- Impact on local body financial health

### 4. Institutional Compliance Issues (200-250 words)
- Gram Sabha/Ward Sabha meeting compliance
- Account maintenance and audit arrears
- Staff vacancy and capacity issues
- IT system compliance (PRIASoft, PFMS)
- Election of statutory committees

### 5. Key Recommendations (300-400 words)
- District-level actions required
- Block-level monitoring improvements
- Capacity building needs
- System and process improvements

### 6. Action Items (150-200 words)
- District Collector directives needed
- Panchayat/Municipal resolution requirements
- Training programs to initiate
- Review meeting agenda items

## Style Guidelines
- Clear language accessible to elected representatives
- Explain technical terms (SFC = State Finance Commission grants, CFC = Central Finance Commission)
- Use ₹ Lakhs for amounts under ₹1 Crore
- Reference Panchayat Act / Municipal Act provisions
- Focus on improving local self-governance capacity
- NO meta-commentary - start directly with content

## Report Data:
{input}

## Output:
Write the Executive Brief in clean markdown format. Target ~1800-2200 words total.
Start directly with "# Executive Brief" followed by the content.
"""


def _get_journalist_prompt(tier: str = "union", state_name: str = None, audit_category: str = "") -> str:
    """Dispatcher for tier-specific journalist prompts."""
    if tier == "state":
        return _get_journalist_prompt_state(state_name)
    elif tier == "local_body":
        return _get_journalist_prompt_local(state_name, audit_category)
    else:
        return _get_journalist_prompt_union()


def _get_journalist_prompt_union() -> str:
    """Journalist writeup for Union (Central Government) reports."""
    return """You are a senior investigative journalist at a major national newspaper (like The Hindu, Indian Express, or Times of India) writing about this CAG audit report on a Central Government ministry or department.

## Your Mission
Transform this government audit into a compelling news story that:
- Leads with the most dramatic yet accurate finding
- Makes complex Central Government issues accessible to the general public
- Serves the public interest by highlighting accountability gaps
- Could actually run on tomorrow's front page

## Required Sections

### 1. The Headlines (5-7 options)
Write potential news headlines that could run in major national papers:
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
- Include specific ₹ amounts throughout (typically ₹100s to ₹1000s of Crores)
- Use direct quotes/references from the report
- Explain what this means for ordinary citizens/taxpayers across India
- Include reactions/implications
- Build narrative tension

### 4. By The Numbers
Create a "fast facts" sidebar with 8-12 key statistics:
- Format: "₹X Crore - brief description"
- Most shocking/impactful numbers first
- Make numbers relatable: "₹12,000 Crore—enough to build 2,400 government schools"

### 5. The Context (200-250 words)
Background information:
- Why this ministry/sector matters to the nation
- Any historical context
- Previous audit findings if referenced
- Scale of operations involved

### 6. What Happens Next (150-200 words)
- What actions should the government take
- Timeline for expected responses
- Who will face questions (Parliamentary PAC, ministry officials)
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
- Make amounts relatable to national scale
- Be dramatic but NEVER exaggerate beyond what the data supports
- Write with controlled outrage appropriate for public interest journalism
- NO meta-commentary - write as if filing an actual story

## Report Data:
{input}

## Output:
Write as if you're filing for tomorrow's front page. ~2000-2200 words total.
Start directly with "# Headlines" followed by your story.
"""


def _get_journalist_prompt_state(state_name: str = None) -> str:
    """Journalist writeup for State Government reports."""
    state_display = state_name or "the State"
    return f"""You are a senior journalist at a major regional newspaper covering {state_display}. You're writing about this CAG audit report on a state government department or entity.

## Your Mission
Transform this state government audit into a compelling news story that:
- Leads with the finding most relevant to {state_display} residents
- Makes state government issues accessible to local readers
- Highlights accountability gaps in state administration
- Could run in the state edition of major regional dailies (Dainik Bhaskar, Amar Ujala, Eenadu, etc.)

## Required Sections

### 1. The Headlines (5-7 options)
Write potential news headlines for regional papers:
- One main headline (dramatic but 100% accurate)
- 4-6 alternative angles for different editorial choices
- Style examples:
  - "₹500 Crore Meant for {state_display} Roads Diverted: CAG Audit"
  - "State Health Department Failed to Spend ₹200 Crore on Hospitals: Audit"
  - "Power Distribution Losses Cost {state_display} ₹800 Crore Annually: CAG"

### 2. The Lead Paragraph (150 words)
Classic inverted pyramid:
- What's the biggest finding affecting {state_display}?
- How much state money is involved?
- Which department/officials are responsible?
- Why should {state_display} residents care?

### 3. The Full Story (800-1000 words)
Write as a complete news article:
- Lead with the biggest revelation
- Include specific ₹ amounts (typically ₹10s to ₹100s of Crores for state reports)
- Reference the specific state department/entity
- Explain what this means for state residents and taxpayers
- Connect to local services (state hospitals, roads, schools)
- Build narrative tension

### 4. By The Numbers
Create a "fast facts" sidebar with 8-12 key statistics:
- Format: "₹X Crore - brief description"
- Make numbers relatable to state scale: "₹500 Crore—the annual budget of 50 district hospitals"
- Compare to state budget allocations where possible

### 5. The Context (200-250 words)
Background information:
- Why this department matters to {state_display} residents
- State-specific context and history
- Previous state audit findings if referenced
- Scale of operations within the state

### 6. What Happens Next (150-200 words)
- What actions should the state government take
- Timeline for expected responses
- Who will face questions (State PAC, MLAs, department officials)
- What {state_display} residents can watch for

### 7. Quotable Findings
Extract 5-7 findings suitable for pull-quotes:
- Dramatic, specific, and attributable
- Include exact rupee amounts
- Could be used in local news coverage

## Style Guidelines
- Active voice throughout
- Short paragraphs (2-3 sentences maximum)
- Explain state-specific jargon
- Make amounts relatable to state scale
- Be dramatic but NEVER exaggerate
- Frame impact on state residents specifically
- NO meta-commentary - write as if filing an actual story

## Report Data:
{input}

## Output:
Write as if you're filing for the state edition. ~2000-2200 words total.
Start directly with "# Headlines" followed by your story.
"""


def _get_journalist_prompt_local(state_name: str = None, audit_category: str = "") -> str:
    """Journalist writeup for Local Body (PRI/ULB) reports."""
    state_display = state_name or "the State"

    atir_context = ""
    if audit_category == "atir":
        atir_context = """
**IMPORTANT:** This is an Annual Technical Inspection Report (ATIR) covering the smallest
units of government that directly serve citizens—village Gram Panchayats and city Municipal
Corporations. Findings here directly affect voters at the grassroots level.
"""

    return f"""You are a journalist writing about local governance in {state_display}. This CAG audit covers Panchayati Raj Institutions (PRIs) and Urban Local Bodies (ULBs)—the village and city governments closest to ordinary citizens.

## Your Mission
Transform this local body audit into a story that resonates with grassroots readers:
- Lead with findings that affect everyday village and city life
- Make local governance accountability accessible
- Show how audit findings affect roads, water, sanitation, welfare schemes in neighborhoods
- Frame as hyperlocal impact story—"your village", "your city"
{atir_context}

## Required Sections

### 1. The Headlines (5-7 options)
Write headlines that resonate with local readers:
- One main headline (dramatic but 100% accurate)
- 4-6 alternative angles
- Style examples:
  - "₹25 Crore for Village Roads Unused: CAG Finds 200 Gram Panchayats Never Spent Their Grants"
  - "Your Panchayat's Missing Audit: 60% of {state_display} GPs Haven't Been Audited in 3 Years"
  - "Why Your Ward's Drain Project Never Started: Municipal Audit Reveals the Answer"
  - "MGNREGA Wages Delayed for 6 Months in 150 Panchayats: CAG Report"

### 2. The Lead Paragraph (150 words)
- What's wrong with local governance in {state_display}?
- How many villages/cities are affected?
- What money meant for local services wasn't used properly?
- Why should local residents care?

### 3. The Full Story (800-1000 words)
Write as a story about local governance:
- Lead with the most relatable finding
- Explain what Gram Panchayats and Municipalities are supposed to do
- Show how failures affect daily life: roads, water, sanitation, streetlights, ration distribution
- Use amounts in Lakhs where appropriate (more relatable than Crores for local budgets)
- Include specific examples from the report
- Quote the audit findings directly

### 4. By The Numbers
8-12 statistics that local citizens can understand:
- "₹50 Lakh - average unspent funds per Gram Panchayat"
- "3 years - how long since some GPs were audited"
- "60% - Gram Panchayats that didn't hold required Gram Sabhas"
- "₹2 Crore - property tax that Municipal Corporation failed to collect"

### 5. What This Means For You (200-250 words)
- Connect findings to citizen services
- What should your Panchayat/Municipality be providing?
- What questions can you ask at the Gram Sabha or Ward Sabha?
- How to check if your local body spent its grants properly

### 6. The System Problem (150-200 words)
- Why does this keep happening?
- Staff shortages in local bodies
- Training and capacity gaps
- Fund flow and release delays
- What systemic changes are needed?

### 7. Quotable Findings
Extract 5-7 findings about local governance:
- Specific to villages/cities
- Include amounts in relatable terms
- Could be discussed at a Gram Sabha

## Style Guidelines
- Use "your village", "your city", "your Gram Panchayat", "your Municipal Corporation"
- Explain all abbreviations:
  - GP = Gram Panchayat (village council)
  - ZP = Zilla Parishad (district council)
  - MC = Municipal Corporation (city government)
  - BDO = Block Development Officer
  - SFC = State Finance Commission grants
- Use ₹ Lakhs for amounts under ₹1 Crore (more relatable)
- Connect to services people use: village roads, handpumps, streetlights, MGNREGA, ration cards
- Avoid blame; focus on systemic issues and what can be fixed
- NO meta-commentary - write as if filing an actual local story

## Report Data:
{input}

## Output:
Write for local readers who deal with these institutions daily. ~2000-2200 words total.
Start directly with "# Headlines" followed by your story.
"""


def _get_deep_dive_prompt(tier: str = "union", state_name: str = None) -> str:
    """Dispatcher for tier-specific deep dive prompts."""
    if tier == "state":
        return _get_deep_dive_prompt_state(state_name)
    elif tier == "local_body":
        return _get_deep_dive_prompt_local(state_name)
    else:
        return _get_deep_dive_prompt_union()


def _get_deep_dive_prompt_union() -> str:
    """Deep dive analysis for Union (Central Government) reports."""
    return """You are creating a comprehensive academic analysis of this CAG audit report on a Central Government entity for researchers, policy analysts, and serious students of governance.

## Target Audience
- Academic researchers studying Indian Central Government functioning
- Policy analysts at think tanks (CPR, ORF, PRS, NIPFP, etc.)
- PhD students in public administration, economics, or political science
- International organizations studying Supreme Audit Institutions
- Parliamentary research staff preparing briefings

## Required Sections

### 1. Audit Framework & Institutional Context (400-500 words)
- Legal basis: CAG DPC Act 1971, Constitution Article 151
- Type of audit (Performance/Compliance/Financial) and its significance
- Audit standards applied (SAI India standards, INTOSAI benchmarks)
- Institutional relationship between CAG, Parliamentary PAC/COPU, and audited ministry
- Historical context of CAG audits in this sector/ministry

### 2. Methodology Analysis (500-600 words)
- Scope and coverage of the audit (national/multi-state)
- Sampling methodology used
- Time period and rationale for selection
- Selection criteria for cases/units examined
- Data sources (ministry records, field visits, third-party data)
- Analytical methods employed
- Limitations acknowledged by CAG

### 3. Findings Analysis by Theme (1500-2000 words)
For EACH major thematic area:
- Key findings with exact paragraph/section references
- Methodology used for that specific examination
- Quantitative data and statistical patterns
- Cross-case patterns and variations across states/units
- Severity distribution (critical ≥₹100 Cr, high ≥₹10 Cr, medium ≥₹1 Cr)
- Causal analysis where provided

### 4. Quantitative Summary (400-500 words)
- Complete statistical breakdown of findings
- Cross-tabulations (severity × type, ministry/department × amount)
- Geographic distribution across states if applicable
- Temporal trends if historical comparisons made
- Statistical significance of samples

### 5. Systemic Issues Identified (400-500 words)
- Root causes identified by the audit
- Structural/institutional problems in Central Government
- Regulatory and policy gaps
- Information system weaknesses (e.g., MIS, PFMS integration)
- Capacity and resource constraints
- Centre-State coordination failures if relevant

### 6. Recommendations Analysis (400-500 words)
- Complete list of all recommendations
- Classification by type:
  - Policy-level changes (Cabinet/Ministry level)
  - Process improvements
  - System/IT changes
  - Capacity building
  - Legal/regulatory amendments
- Reference to GFR/CVC/DoPT guidelines where applicable
- Feasibility assessment based on past implementation
- Comparison with recommendations from previous audits

### 7. Research Implications (300-400 words)
- Questions for further academic research
- Data gaps that future studies could address
- Methodological contributions of this audit
- Comparative research possibilities (other countries, international benchmarks)
- Policy evaluation opportunities

### 8. Technical Appendix
- Complete list of major sections with page numbers
- Glossary of technical terms and abbreviations used
- List of Acts, Rules, and Regulations referenced
- Key Central Government entities and their roles
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


def _get_deep_dive_prompt_state(state_name: str = None) -> str:
    """Deep dive analysis for State Government reports."""
    state_display = state_name or "the State"
    return f"""You are creating a comprehensive academic analysis of this CAG audit report on {state_display} Government for researchers, policy analysts, and serious students of state-level governance.

## Target Audience
- Academic researchers studying Indian state governance and federalism
- Policy analysts at state-focused think tanks
- PhD students in public administration, economics, or political science
- Researchers doing comparative state studies
- State legislature research staff

## Required Sections

### 1. Audit Framework & Institutional Context (400-500 words)
- Legal basis: Constitution Article 151, State-specific provisions
- Role of AG {state_display} office
- Type of audit (Performance/Compliance/Financial) and its significance
- Audit standards applied
- Institutional relationship between CAG, State PAC, and audited department
- Historical context of state audits in this sector

### 2. Methodology Analysis (500-600 words)
- Scope and coverage within {state_display}
- Sampling methodology (districts, divisions, units selected)
- Time period and rationale for selection
- Selection criteria for cases/units examined
- Data sources (state records, field visits, district data)
- Analytical methods employed
- Limitations acknowledged

### 3. Findings Analysis by Theme (1500-2000 words)
For EACH major thematic area:
- Key findings with exact paragraph/section references
- Methodology used for that specific examination
- Quantitative data and statistical patterns
- Cross-district patterns and variations within {state_display}
- Severity distribution (critical ≥₹50 Cr, high ≥₹5 Cr, medium ≥₹0.5 Cr)
- Causal analysis where provided

### 4. Quantitative Summary (400-500 words)
- Complete statistical breakdown of findings
- Cross-tabulations (severity × type, department × amount)
- District-wise distribution if applicable
- Temporal trends if historical comparisons made
- Comparison to state budget allocations

### 5. Systemic Issues Identified (400-500 words)
- Root causes identified by the audit
- Structural/institutional problems in {state_display} administration
- State-specific regulatory and policy gaps
- State-level information system weaknesses
- Capacity constraints in state machinery
- State-Centre coordination issues if relevant

### 6. Recommendations Analysis (400-500 words)
- Complete list of all recommendations
- Classification by type:
  - State policy-level changes
  - Process improvements in state departments
  - State IT system changes
  - Capacity building for state officials
  - State legislative/regulatory amendments
- Reference to State Financial Rules where applicable
- Feasibility in {state_display} context
- Comparison with recommendations from previous state audits

### 7. Research Implications (300-400 words)
- Questions for state-level governance research
- Data gaps in {state_display} administration
- Comparative research possibilities with other states
- Policy evaluation opportunities
- Federalism and decentralization implications

### 8. Technical Appendix
- Complete list of major sections with page numbers
- Glossary of state-specific terms and abbreviations
- List of State Acts, Rules, and Regulations referenced
- Key {state_display} government entities and their roles
- Timeline of events if relevant

## Style Guidelines
- Academic tone throughout
- Use formal citation style: (Section 3.4.2, p. 45)
- Include verbatim quotes with exact references
- Present data in tabular format where appropriate
- Maintain analytical objectivity
- Place findings in comparative state context where possible

## Report Data:
{input}

## Output:
Write as a comprehensive research summary suitable for state governance research. ~3500-4000 words total.
Start directly with "# Deep Dive Analysis" followed by the content.
"""


def _get_deep_dive_prompt_local(state_name: str = None) -> str:
    """Deep dive analysis for Local Body (PRI/ULB) reports."""
    state_display = state_name or "the State"
    return f"""You are creating a comprehensive academic analysis of this CAG audit report on local bodies (PRIs and ULBs) in {state_display} for researchers studying decentralization, local governance, and grassroots democracy.

## Target Audience
- Academic researchers studying decentralization and local self-governance
- Policy analysts focused on Panchayati Raj and urban governance
- PhD students in rural development, urban studies, or public administration
- International researchers studying local government accountability
- State Institute of Rural Development (SIRD) faculty
- Ministry of Panchayati Raj / Urban Development research staff

## Required Sections

### 1. Audit Framework & Institutional Context (400-500 words)
- Legal basis: 73rd/74th Constitutional Amendments, CAG DPC Act Section 20(1)
- {state_display} Panchayat Act / Municipal Act provisions
- Type of audit (ATIR / Performance Audit) and its significance
- Institutional framework: Three-tier PRI structure, ULB categories
- Role of State AG, Director of Local Fund Audit (DLFA)
- Historical context of local body audits in {state_display}

### 2. Methodology Analysis (500-600 words)
- Scope: Number of GPs, PSs, ZPs, Municipalities covered
- Sampling methodology (how local bodies were selected)
- Time period and rationale
- Types of local bodies examined (rural vs urban, by size/category)
- Data sources (local body records, field visits, beneficiary verification)
- Analytical methods employed
- Coverage limitations acknowledged

### 3. Findings Analysis by Theme (1200-1500 words)
Analyze findings across key local governance themes:

**A. Financial Management**
- Own revenue collection (property tax, user charges)
- SFC/CFC grant utilization
- Fund flow and release delays
- Accounting and audit arrears

**B. Scheme Implementation**
- CSS/State scheme implementation (MGNREGA, housing, sanitation)
- Asset creation and maintenance
- Beneficiary selection and targeting

**C. Institutional Compliance**
- Gram Sabha/Ward Sabha meetings
- Standing committee functioning
- Staff positions and vacancies
- IT system compliance (PRIASoft, PFMS)

For each theme: findings with references, patterns across local bodies, severity distribution

### 4. Quantitative Summary (400-500 words)
- Statistical breakdown by type of local body
- District-wise distribution of findings
- Cross-tabulations (GP vs ULB, by grant type, by scheme)
- Aggregation of financial irregularities
- Compliance rates across sampled local bodies

### 5. Systemic Issues in Local Governance (400-500 words)
- Structural issues in {state_display}'s local body framework
- Devolution gaps (3Fs: Funds, Functions, Functionaries)
- Capacity constraints at grassroots level
- State-local coordination problems
- Information system and MIS weaknesses
- Audit coverage and accountability gaps

### 6. Recommendations Analysis (400-500 words)
- Complete list of all recommendations
- Classification by type:
  - State policy changes for local bodies
  - Process improvements at GP/ULB level
  - Capacity building for elected representatives
  - IT and accounting system improvements
  - Amendments to State Panchayat/Municipal Act
- Feasibility in local governance context
- Comparison with 2nd ARC recommendations on local governance

### 7. Research Implications (300-400 words)
- Questions for local governance research
- Decentralization theory implications
- Comparative research with other states' local bodies
- Democratic deepening and accountability at grassroots
- Data gaps in local body functioning
- Policy evaluation opportunities for 73rd/74th Amendment implementation

### 8. Technical Appendix
- Structure of PRIs/ULBs in {state_display}
- Glossary: GP, ZP, PS, MC, NP, NAC, BDO, DRDA, SFC, CFC, PRIASoft
- List of State Panchayat Act / Municipal Act provisions cited
- Finance Commission grant framework
- CSS schemes mentioned and their nodal ministries

## Style Guidelines
- Academic tone with local governance expertise
- Use formal citation style: (Section 3.4.2, p. 45)
- Explain PRI/ULB terminology for non-specialist readers
- Present data in tabular format where appropriate
- Connect to decentralization literature and 73rd/74th Amendment objectives
- Maintain analytical objectivity

## Report Data:
{input}

## Output:
Write as a comprehensive research summary for local governance scholars. ~3500-4000 words total.
Start directly with "# Deep Dive Analysis" followed by the content.
"""


def _get_simple_prompt(tier: str = "union", state_name: str = None, audit_category: str = "") -> str:
    """Dispatcher for tier-specific simple prompts."""
    if tier == "state":
        return _get_simple_prompt_state(state_name)
    elif tier == "local_body":
        return _get_simple_prompt_local(state_name, audit_category)
    else:
        return _get_simple_prompt_union()


def _get_simple_prompt_union() -> str:
    """Simple explainer for Union (Central Government) reports."""
    return """You are explaining this Central Government audit report to regular citizens who have no background in finance, accounting, or government procedures.

## Your Goal
Make this completely understandable to:
- A college student who doesn't study economics
- A small shop owner or farmer
- A retired person reading the newspaper
- Any Indian citizen who pays taxes but doesn't understand government jargon
- Someone who has 10 minutes to understand what happened

## Required Sections (Use Q&A Format with Simple Headers)

### What Is This Report About?
- Explain like you're telling a neighbor over tea
- NO jargon whatsoever (or explain it immediately in simple terms)
- What Central Government ministry or department was checked?
- What were the auditors (think of them as government accountants/inspectors) looking for?
- Why should ordinary Indians care?

### What Did They Find Wrong?
- Top 5-7 problems in plain, everyday language
- Use relatable analogies: "It's like if you gave money to a contractor to build your house, but they used cheaper materials and kept the difference..."
- Make amounts relatable at national scale:
  - "₹12,000 Crore—that's enough money to give ₹1,000 to 12 crore families"
  - "₹500 Crore—that could build 100 new hospitals"
  - "This is like losing ₹90 from every ₹100 collected"

### Why Should I Care?
- How does this directly affect regular Indians?
- What national services might be worse because of this?
- What happens to "your tax money" sent to Delhi?
- Are there safety, health, or economic implications?

### Who Is Responsible?
- Which Central ministry or department
- What were they supposed to do?
- What did they actually do (or not do)?
- Keep it factual, don't be preachy or political

### What Should Happen Now?
- What the Central Government should fix
- Simple action items anyone can understand
- How long these fixes might take
- What Parliament and citizens can watch for

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
  - Crore → (explain once that 1 crore = 100 lakhs = 10 million)
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


def _get_simple_prompt_state(state_name: str = None) -> str:
    """Simple explainer for State Government reports."""
    state_display = state_name or "your state"
    return f"""You are explaining this State Government audit report to regular citizens in {state_display} who have no background in finance, accounting, or government procedures.

## Your Goal
Make this completely understandable to:
- A college student in {state_display}
- A small shop owner or farmer in the state
- A retired person reading the local newspaper
- Anyone in {state_display} who pays taxes but doesn't understand government jargon
- Someone who has 10 minutes to understand what happened

## Required Sections (Use Q&A Format with Simple Headers)

### What Is This Report About?
- Explain like you're telling a neighbor over tea
- NO jargon whatsoever (or explain it immediately in simple terms)
- What {state_display} government department was checked?
- What were the auditors looking for?
- Why should residents of {state_display} care?

### What Did They Find Wrong?
- Top 5-7 problems in plain, everyday language
- Use relatable analogies from daily life
- Make amounts relatable at state scale:
  - "₹500 Crore—that's the annual budget for 50 government hospitals in {state_display}"
  - "₹50 Crore—that could pay salaries of 5,000 teachers for a year"
  - "This is like losing ₹50 from every ₹100 meant for state services"

### Why Should I Care?
- How does this directly affect people in {state_display}?
- What state services might be worse because of this? (hospitals, roads, schools)
- What happens to "your state taxes"?
- Are there local implications for your district?

### Who Is Responsible?
- Which state department or officials
- What were they supposed to do?
- What did they actually do (or not do)?
- Keep it factual, don't be preachy or political

### What Should Happen Now?
- What the {state_display} government should fix
- Simple action items anyone can understand
- How long these fixes might take
- What MLAs and citizens can watch for

### The Bottom Line (5-6 bullets)
- Most important takeaways in one sentence each
- Amounts in relatable terms
- What this means for {state_display}

## Style Guidelines
- Write for someone who is intelligent but knows nothing about government accounting
- Very short sentences (under 15-20 words)
- Use "you" and "your state taxes" and "your state's money"
- ZERO jargon without explanation
- Use everyday analogies from household, business, or daily life
- Connect to state-level services people use
- Be honest and clear, but not angry or preachy

## Report Data:
{input}

## Output:
Write in a friendly, clear, conversational tone. Use headers as questions people would ask.
Target ~1200-1500 words. Start directly with "# What Is This Report About?"
"""


def _get_simple_prompt_local(state_name: str = None, audit_category: str = "") -> str:
    """Simple explainer for Local Body (PRI/ULB) reports."""
    state_display = state_name or "your state"

    atir_context = ""
    if audit_category == "atir":
        atir_context = """
**IMPORTANT CONTEXT:**
This report is about the smallest government units that serve you directly:
- **Gram Panchayats** (village councils) - they manage village roads, water, sanitation
- **Municipal Corporations/Nagar Palikas** (city governments) - they manage city roads, drainage, streetlights
These are the governments closest to your daily life!
"""

    return f"""You are explaining this local government audit report to regular villagers and city residents in {state_display}. These readers interact with Gram Panchayats and Municipal Corporations in their daily lives.

## Your Goal
Make this completely understandable to:
- A farmer who attends Gram Sabha meetings
- A shopkeeper who pays municipal taxes
- A housewife who deals with the Panchayat for water or roads
- Auto drivers, daily wage workers, anyone who uses local services
- Someone who has 10 minutes to understand what happened

## Required Sections (Use Q&A Format with Simple Headers)

### What Is This Report About?
{atir_context}
- Explain like you're telling a neighbor over tea
- What local governments (Panchayats, Municipalities) were checked?
- What were the auditors looking for?
- Why should you care about your Gram Panchayat or Municipal Corporation?

### What Did They Find Wrong?
- Top 5 problems in plain, everyday language
- Use relatable analogies:
  - "It's like the Panchayat got money to build your village road, but the road was never built"
  - "The Municipality collected taxes but didn't fix the drains"
- Make amounts relatable at local scale:
  - "₹50 Lakh—that's the annual budget of 5 Gram Panchayats"
  - "₹5 Lakh—enough to build a village community hall"
  - "₹25 Crore—that could fix roads in 100 villages"

### Why Should I Care?
- How does this affect YOUR village or YOUR city ward?
- What local services are worse because of this?
  - Village roads not built
  - Handpumps not repaired
  - Streetlights not working
  - Drains overflowing
  - MGNREGA wages delayed
- This is YOUR money from government grants!

### Who Is Responsible?
- Your Sarpanch and Gram Panchayat members
- The Municipal Commissioner or Executive Officer
- The Block Development Officer (BDO)
- What were they supposed to do vs what they did?

### What Can YOU Do?
- Ask questions at the next Gram Sabha or Ward Sabha
- Check if your Panchayat's accounts are displayed publicly
- Ask the Sarpanch about SFC (State Finance Commission) grant utilization
- Right to Information (RTI) can get you answers

### What Should Happen Now?
- What the District Collector should order
- What your Panchayat needs to fix
- Training that local officials need
- How citizens can monitor progress

### The Bottom Line (5-6 bullets)
- Most important takeaways for your village/city
- Money that should have reached you but didn't
- What you can ask at the next Gram Sabha

## Style Guidelines
- Write for someone who is intelligent but may have limited formal education
- Very short sentences (under 12-15 words)
- Use "your village", "your Panchayat", "your ward", "your city"
- ZERO jargon without explanation:
  - GP = Gram Panchayat = your village council
  - ZP = Zilla Parishad = district council
  - BDO = Block Development Officer = the block-level government officer
  - SFC = State Finance Commission = grants from state government
  - Gram Sabha = village meeting where all adults can participate
- Use amounts in Lakhs (not Crores) when under ₹1 Crore—more relatable
- Connect to services people use daily: roads, water, toilets, streetlights, ration
- Be empowering, not angry—help people ask the right questions

## Report Data:
{input}

## Output:
Write in a friendly, clear tone that villagers and city residents can understand.
Target ~1200-1500 words. Start directly with "# What Is This Report About?"
"""


def _get_policy_prompt(tier: str = "union", state_name: str = None) -> str:
    """Dispatcher for tier-specific policy prompts."""
    if tier == "state":
        return _get_policy_prompt_state(state_name)
    elif tier == "local_body":
        return _get_policy_prompt_local(state_name)
    else:
        return _get_policy_prompt_union()


def _get_policy_prompt_union() -> str:
    """Policy brief for Union (Central Government) reports."""
    return """You are creating a Policy Brief for Central Government officials who need to prepare formal responses to this CAG audit and implement corrective actions.

## Target Audience
- Ministry officials preparing Action Taken Notes (ATNs) for PAC
- Joint Secretaries and Department heads implementing reforms
- Policy advisors drafting compliance responses
- Parliamentary PAC/COPU members reviewing audit findings
- Legal and compliance teams in ministries

## Required Sections

### 1. Policy & Regulatory Context (300-350 words)
- Relevant Central laws, rules, and regulations governing the audited area
- GFR 2017 provisions applicable
- CVC guidelines and DoPT rules relevant to findings
- Policy framework under which the ministry/PSU operates
- Recent policy changes or pending reforms

### 2. Compliance Gaps Identified (500-600 words)

**A. Regulatory Non-Compliance**
- Specific statutory provisions violated (cite Act/Rule/Section)
- GFR violations and financial irregularities
- Frequency and extent of violations
- Potential legal implications

**B. Process & Procedural Failures**
- Standard operating procedures not followed
- Documentation and record-keeping gaps
- Approval and authorization process issues
- Internal control weaknesses per CVC guidelines

**C. System & Monitoring Weaknesses**
- IT system deficiencies (PFMS, ministry MIS)
- Data integrity and reliability problems
- Monitoring mechanism failures
- Inter-ministry coordination issues

### 3. Financial Implications (300-350 words)
- Total revenue loss or potential recovery amount
- Breakdown by category of irregularity
- Recurring versus one-time financial impact
- Compound effects and cascading losses
- Recovery potential and timeframe

### 4. Prioritized Action Plan (600-700 words)

**IMMEDIATE ACTIONS (0-3 months)**
- Quick fixes and interim measures
- Circulars/Office Memoranda to be issued
- Cabinet/Secretary-level reviews to initiate
- Emergency compliance measures

**SHORT-TERM ACTIONS (3-12 months)**
- Process re-engineering requirements
- Training and capacity building needs
- System modifications (PFMS, MIS)
- Monitoring mechanism improvements

**MEDIUM-TERM ACTIONS (1-2 years)**
- Legislative or regulatory amendments
- Major IT system overhauls
- Structural and organizational reforms
- Inter-ministry coordination improvements

### 5. Implementation Framework (300-350 words)
- Responsible JS/Director-level officers for each action
- Ministry monitoring mechanisms and review frequency
- Reporting requirements to Secretary/Cabinet
- Success metrics and KPIs
- Escalation procedures to Cabinet Secretariat

### 6. Risk Assessment (200-250 words)
- Consequences if issues continue unaddressed
- PAC/COPU proceedings implications
- Potential court cases or CVC references
- Reputational and political risks
- Legal and regulatory exposure

### 7. Draft ATN Response Template
Provide an outline for the ministry's formal Action Taken Note:
- Para-wise response structure for PAC
- Points to be accepted with corrective action
- Points requiring factual clarification with evidence
- Points where action is already initiated with timeline
- Recoveries effected or in progress
- Systemic improvements implemented

## Style Guidelines
- Use Central Government bureaucratic terminology
- Include specific section/rule/para references from the audit
- Reference GFR, CVC, DoPT guidelines appropriately
- Format for easy tracking of action items
- Include realistic timelines considering government processes
- Be practical about implementation challenges in large ministries

## Report Data:
{input}

## Output:
Write in formal policy document style suitable for ministry circulation and PAC response. ~2200-2500 words total.
Start directly with "# Policy Brief" followed by the content.
"""


def _get_policy_prompt_state(state_name: str = None) -> str:
    """Policy brief for State Government reports."""
    state_display = state_name or "the State"
    return f"""You are creating a Policy Brief for {state_display} Government officials who need to prepare formal responses to this CAG audit and implement corrective actions.

## Target Audience
- Department Secretaries preparing responses for State PAC
- Heads of Departments implementing reforms
- Chief Secretary's office coordinating compliance
- State PAC members reviewing audit findings
- State legal and finance department teams

## Required Sections

### 1. Policy & Regulatory Context (300-350 words)
- Relevant State laws, rules, and regulations governing the audited area
- {state_display} Financial Rules and Treasury Code provisions
- State-specific policy framework
- AG {state_display} guidelines applicable
- Recent state policy changes or pending reforms

### 2. Compliance Gaps Identified (500-600 words)

**A. Regulatory Non-Compliance**
- Specific State Act/Rule/GO provisions violated
- State Financial Rules violations
- Frequency and extent of violations
- Potential legal implications under state laws

**B. Process & Procedural Failures**
- State SOPs not followed
- Documentation and record-keeping gaps
- Approval processes bypassed
- Internal control weaknesses

**C. System & Monitoring Weaknesses**
- State IT system deficiencies
- Treasury/IFMS integration problems
- Departmental MIS failures
- Inter-department coordination issues

### 3. Financial Implications (300-350 words)
- Total financial impact on state exchequer
- Breakdown by category of irregularity
- Impact on state budget allocations
- Recurring versus one-time financial impact
- Recovery potential and timeframe

### 4. Prioritized Action Plan (600-700 words)

**IMMEDIATE ACTIONS (0-3 months)**
- Government Orders (GOs) to be issued
- Department circulars and instructions
- Secretary-level reviews to initiate
- Emergency compliance measures

**SHORT-TERM ACTIONS (3-12 months)**
- Process re-engineering in departments
- Training for state officials
- State IT system modifications
- Monitoring mechanism improvements

**MEDIUM-TERM ACTIONS (1-2 years)**
- State legislative amendments
- Major system overhauls
- Departmental restructuring
- Inter-department coordination improvements

### 5. Implementation Framework (300-350 words)
- Responsible HoD/Secretary for each action
- Department monitoring mechanisms
- Reporting to Chief Secretary's office
- Success metrics and KPIs
- Escalation procedures within state hierarchy

### 6. Risk Assessment (200-250 words)
- Consequences if issues continue unaddressed
- State PAC proceedings implications
- State Assembly question implications
- Reputational risks for {state_display} government
- Legal exposure under state laws

### 7. Draft Response Template
Provide an outline for the department's formal response:
- Para-wise response structure for State PAC
- Points to be accepted with Government Order references
- Points requiring factual clarification
- Points where action is already initiated
- Recoveries effected or proceedings initiated
- Systemic improvements through GOs

## Style Guidelines
- Use {state_display} Government bureaucratic terminology
- Include specific section/rule/para references from the audit
- Reference State Financial Rules and Treasury Code
- Format for easy tracking of action items
- Include realistic timelines for state government processes
- Consider state-specific administrative constraints

## Report Data:
{input}

## Output:
Write in formal policy document style suitable for state government circulation. ~2200-2500 words total.
Start directly with "# Policy Brief" followed by the content.
"""


def _get_policy_prompt_local(state_name: str = None) -> str:
    """Policy brief for Local Body (PRI/ULB) reports."""
    state_display = state_name or "the State"
    return f"""You are creating a Policy Brief for officials responsible for local body oversight in {state_display}. This covers Panchayati Raj Institutions (PRIs) and Urban Local Bodies (ULBs).

## Target Audience
- Director of Panchayats / Commissioner of Municipal Administration
- District Collectors responsible for local body oversight
- State Panchayati Raj / Urban Development Department officials
- Block Development Officers and Municipal Commissioners
- State PAC members reviewing local body audits
- State Institute of Rural Development (SIRD) for training needs

## Required Sections

### 1. Policy & Regulatory Context (300-350 words)
- {state_display} Panchayat Act / Municipal Act provisions applicable
- 73rd/74th Constitutional Amendment compliance requirements
- State Finance Commission (SFC) grant conditions
- Central Finance Commission (CFC) fund utilization rules
- PRIASoft/PFMS compliance requirements
- State-specific rules for local bodies

### 2. Compliance Gaps Identified (500-600 words)

**A. Statutory Non-Compliance**
- Panchayat Act / Municipal Act violations
- Gram Sabha / Ward Sabha meeting requirements not met
- Standing committee functioning issues
- Election of statutory office bearers

**B. Financial Management Failures**
- Own revenue collection gaps (property tax, user charges)
- SFC/CFC grant utilization issues
- Accounting and audit arrears
- Fund diversion or misutilization

**C. Scheme Implementation Issues**
- CSS scheme implementation gaps (MGNREGA, housing, sanitation)
- Asset creation without proper records
- Beneficiary selection irregularities
- Maintenance of created assets

**D. Institutional Weaknesses**
- Staff vacancies at GP/ULB level
- Training gaps for elected representatives
- IT system compliance (PRIASoft, PFMS)
- Record-keeping deficiencies

### 3. Financial Implications (250-300 words)
- Total financial irregularities across local bodies
- Unspent grants and opportunity cost
- Revenue foregone due to non-collection
- Recovery potential from local bodies
- Impact on local service delivery

### 4. Prioritized Action Plan (500-600 words)

**IMMEDIATE ACTIONS (0-3 months)**
- District Collector circulars to local bodies
- Special Gram Sabha / Ward Sabha for audit findings
- Compliance drive for statutory meetings
- Emergency training for new provisions

**SHORT-TERM ACTIONS (3-12 months)**
- Capacity building for elected representatives
- PRIASoft/accounting system rollout
- Own revenue mobilization campaigns
- Block-level monitoring mechanism

**MEDIUM-TERM ACTIONS (1-2 years)**
- State Panchayat Act / Municipal Act amendments
- Staffing norms revision for local bodies
- IT system integration (PRIASoft-PFMS)
- Audit coverage improvement plan

### 5. Implementation Framework (250-300 words)
- Role of District Collector as nodal authority
- Block-level monitoring by BDO/Circle Officer
- State-level review by Director of Panchayats
- Monthly progress reporting mechanism
- Escalation from GP → Block → District → State

### 6. Risk Assessment (200-250 words)
- Consequences for local self-governance
- Impact on citizen services at grassroots
- State PAC scrutiny of local body audits
- Central scheme fund release implications
- 15th Finance Commission grant conditions at risk

### 7. Model Action Templates

**A. District Collector Order Template:**
- Findings requiring immediate local body action
- Timeline for compliance
- Penalty provisions for non-compliance

**B. Panchayat Resolution Format:**
- Acknowledgment of audit findings
- Action plan approved by Gram Sabha
- Responsible persons and timelines

**C. Training Needs Assessment:**
- Topics for elected representative training
- Financial management modules
- Scheme implementation guidelines

## Style Guidelines
- Use local governance terminology appropriately
- Reference State Panchayat/Municipal Act sections
- Include practical guidance for grassroots implementation
- Consider capacity constraints at GP/ULB level
- Be realistic about timelines given local body resources
- Focus on strengthening local self-governance, not just compliance

## Report Data:
{input}

## Output:
Write in formal policy document style suitable for state and district circulation. ~2200-2500 words total.
Start directly with "# Policy Brief" followed by the content.
"""
