"""
Prompt for extracting missing overview fields from CAG report JSON.

Extracts:
- audit_scope: Period, coverage, sample size, entities
- audit_objectives: List of objectives from report
- topics_covered: NEUTRAL topic names (not findings-focused)
- glossary_terms: Abbreviations and definitions
"""


def _get_government_level_label(government_body_type: str) -> str:
    """Convert government_body_type to human-readable label."""
    labels = {
        "union": "Union (Central Government)",
        "state": "State Government",
        "local_body": "Local Body (PRIs and ULBs)",
    }
    return labels.get(government_body_type, "Union (Central Government)")


def _get_department_display(meta: dict) -> str:
    """Get department/entity display value with fallbacks."""
    department = meta.get("department")
    if department:
        return department
    ministry = meta.get("ministry")
    if ministry:
        return ministry
    return "Multiple"


def build_overview_prompt(json_data: dict) -> str:
    """
    Build the overview extraction prompt.
    
    Uses:
    - TOC from parent_chunks (for structure)
    - Intro/Scope content from child_chunks (for details)
    """
    
    # Extract TOC
    toc_lines = []
    for chunk in json_data.get("parent_chunks", [])[:60]:
        indent = "  " * (chunk.get("toc_level", 1) - 1)
        page = chunk.get("page_range_physical", [0])[0]
        toc_lines.append(f"{indent}{chunk.get('toc_entry', 'N/A')} (p.{page})")
    toc_text = "\n".join(toc_lines)
    
    # Extract intro/scope/objectives content
    intro_content = _get_section_content(
        json_data,
        ["Introduction", "Scope", "Objective", "Methodology", "Chapter 1", "Audit Scope"]
    )
    
    # Extract glossary if present
    glossary_content = _get_section_content(
        json_data,
        ["Glossary", "Abbreviation", "Acronym", "Definition", "List of Abbreviations"]
    )
    
    # Extract preface/executive summary for additional context
    exec_content = _get_section_content(
        json_data,
        ["Executive Summary", "Preface", "Overview"]
    )
    
    meta = json_data.get("report_metadata", {})

    # Extract tier-aware fields with safe defaults
    government_body_type = meta.get("government_body_type", "union")
    state_name = meta.get("state_name")
    audit_category = meta.get("audit_category", "")

    # Build tier-aware context
    govt_level = _get_government_level_label(government_body_type)
    state_display = state_name if state_name else "Union (Central Government)"
    dept_display = _get_department_display(meta)

    # ATIR note for local body reports
    atir_note = ""
    if audit_category == "atir":
        atir_note = """
Note: ATIR reports cover Panchayati Raj Institutions (village-level governance)
and Urban Local Bodies (municipal governance). They assess institutional functioning,
financial management, and scheme implementation at the grassroots level.
"""

    return f'''You are extracting specific metadata from a CAG (Comptroller and Auditor General of India) audit report.

## CONTEXT
Report: {meta.get("report_title", "N/A")}
Type: {meta.get("report_type", "N/A")}
Government Level: {govt_level}
State: {state_display}
Department/Entity: {dept_display}
Year: {meta.get("report_year", "N/A")}
{atir_note}
## ALREADY EXTRACTED (do NOT repeat these - they exist in the JSON):
- Report metadata (title, ministry, year, type) ✓
- Table of Contents structure ✓
- Findings with severity and monetary amounts ✓
- Recommendations ✓
- Section classifications ✓
- Statistics (totals, breakdowns) ✓

## YOUR TASK: Extract these 5 fields

### 1. audit_scope
From the Scope of Audit / Introduction sections, extract:
```json
{{
  "period": {{
    "start": "YYYY-YY format (e.g., '2020-21')",
    "end": "YYYY-YY format (e.g., '2022-23')",
    "description": "e.g., '3 Financial Years' or 'April 2020 to March 2023'"
  }},
  "geographic_coverage": ["list of states/regions/units if mentioned, or ['All India'] if national scope"],
  "sample_size": {{
    "total": number or null if not specified,
    "description": "e.g., '8,470 cases from 15 Commissionerates' or null"
  }},
  "entities_covered": ["list of organizations/departments/units examined"]
}}
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
  {{
    "name": "neutral descriptive topic name",
    "sections": ["2.1", "2.2", "2.3"],
    "page_start": 18,
    "page_end": 35,
    "description": "brief one-line description of what this topic covers"
  }}
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
  {{
    "term": "full term name",
    "abbreviation": "ABC",
    "definition": "brief definition if provided in report, else null",
    "category": "organizational|technical|financial|legal|procedural"
  }}
]
```
Common CAG/Government terms to look for:
- AO (Assessing Officer), AY (Assessment Year), FY (Financial Year)
- CBDT, CIT, PCIT, TDS, GST, CGST, SGST, IGST
- CAG, PAC, FRBM, BE, RE, Actuals
- Ministry/Department-specific abbreviations
- State Government abbreviations: GoAP, GoHP, GoSK, GoUK, GoOD, GoMH, GoKL, GoAS, GoBR, GoCG, SPSE
- Local Body terms: PRI (Panchayati Raj Institutions), ULB (Urban Local Bodies), ZP (Zilla Parishad), GP (Gram Panchayat), PS (Panchayat Samiti), MC (Municipal Corporation), NP (Nagar Palika)
- Local audit terms: DLFA (Director Local Fund Audit), SFC (State Finance Commission), CFC (Central Finance Commission), PRIASoft, PFMS
- Any abbreviation that appears multiple times in the report

### 5. normalized_entities

Extract every distinct organizational, scheme, geographic, and governance entity mentioned in this report. For each entity:

```json
{{
  "canonical_form_in_report": "Full official name as it appears most authoritatively in this report",
  "entity_type": "ministry | department | psu | autonomous_body | scheme | state_government | local_body | regulatory_authority | organization | place",
  "aliases_seen": ["all variant spellings, abbreviations, and partial forms seen in this report"],
  "first_seen_page": physical_page_number,
  "tier_context": "union | state | local_body — which government tier this entity belongs to"
}}
```

Rules for normalized_entities:
- Extract 20-50 entities per report (this is a high-yield list, not exhaustive)
- ONE entry per logical entity. If "Ministry of Railways", "MoR", and "Min. of Railways" all appear, produce ONE entry with all three in aliases_seen
- Use the LONGEST/MOST OFFICIAL form as canonical_form_in_report (e.g., "National Highways Authority of India" not "NHAI")
- Always include the acronym in aliases_seen if both forms appear
- For state government entities, use "Government of [State]" as canonical (e.g., "Government of Mizoram")
- For local bodies, be specific: "Aizawl Municipal Corporation" not "AMC" as canonical, but include "AMC" in aliases
- entity_type uses the most specific applicable category
- tier_context: based on the report tier and the entity's level
  - Central ministries/PSUs/national schemes → "union"
  - State departments/State PSEs/state schemes → "state"
  - PRIs/ULBs/Village Councils/local schemes → "local_body"
- DO NOT include: generic terms ("the Ministry", "the State"), single-letter abbreviations, or vague entities ("various departments")
- DO include: specific named ministries, PSUs, schemes, autonomous bodies, named programmes, named regulators, geographic units (states, districts, specific project locations)

## INPUT DATA

### Table of Contents:
{toc_text[:8000]}

### Introduction / Scope / Objectives Content:
{intro_content[:12000]}

### Executive Summary / Preface (additional context):
{exec_content[:4000]}

### Glossary Section (if available):
{glossary_content[:4000]}

## OUTPUT FORMAT
Return ONLY a valid JSON object with these exact keys:
```json
{{
  "audit_scope": {{ ... }},
  "audit_objectives": [ ... ],
  "topics_covered": [ ... ],
  "glossary_terms": [ ... ],
  "normalized_entities": [ ... ]
}}
```

IMPORTANT:
- No markdown code blocks around the JSON
- No explanatory text before or after
- Just the raw JSON object
- Ensure all JSON is properly formatted and valid
'''


def _get_section_content(json_data: dict, keywords: list[str], max_chunks: int = 50) -> str:
    """Extract paragraph content from sections matching keywords."""
    matching = []
    
    for chunk in json_data.get("child_chunks", []):
        # Include paragraphs, text, and headers
        content_type = chunk.get("content_type", "")
        if content_type not in ["paragraph", "text", "header"]:
            continue
        
        # Check hierarchy for keyword matches
        hierarchy = chunk.get("hierarchy", {})
        hierarchy_str = " ".join(str(v) for v in hierarchy.values()).lower()
        
        # Also check toc_entry if available
        toc_entry = str(chunk.get("toc_entry", "")).lower()
        
        combined_text = hierarchy_str + " " + toc_entry
        
        if any(kw.lower() in combined_text for kw in keywords):
            content = chunk.get("content", "")
            if content and len(content) > 30:  # Skip tiny fragments
                page = chunk.get("source_page_physical", "?")
                matching.append(f"[Page {page}] {content}")
        
        if len(matching) >= max_chunks:
            break
    
    return "\n\n".join(matching)
