"""
Prompt for extracting entities from CAG report chunks.

Extracts structured information about:
- Government entities (ministries, departments, directorates)
- Organizations (PSUs, autonomous bodies, state governments)
- Schemes and programs
- Laws and regulations referenced
- Geographic entities (states, districts)
"""

ENTITY_EXTRACTION_PROMPT = """You are analyzing a CAG audit report chunk to extract structured entity information.

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
{{
  "entities": {{
    "ministries": ["Ministry of Railways"],
    "departments": ["Department of Posts"],
    "directorates": [],
    "psus": ["National Highways Authority of India"],
    "autonomous_bodies": [],
    "state_governments": ["Government of Uttar Pradesh"],
    "schemes": ["Pradhan Mantri Gram Sadak Yojana"],
    "laws_regulations": ["General Financial Rules 2017"],
    "geographic": ["Uttar Pradesh", "Bihar"]
  }}
}}

If no entities found in a category, use empty list [].
"""


def build_entity_prompt(chunk: dict) -> str:
    """
    Build the entity extraction prompt for a chunk.

    Args:
        chunk: ChildChunk dict with content

    Returns:
        Formatted prompt string
    """
    return ENTITY_EXTRACTION_PROMPT.format(
        chunk_content=chunk.get("content", "")
    )
