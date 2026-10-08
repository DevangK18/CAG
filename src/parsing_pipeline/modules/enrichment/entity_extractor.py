"""
EntityExtractor: Extracts named entities (schemes, ministries, organizations)
from CAG audit report text.

P3-1: Uses case-sensitive matching (NO IGNORECASE) because capitalization
matters for proper entity detection.

P1-10: Enhanced filtering for:
- Stuttered/doubled text (tokenizer artifacts)
- Place names (state names)
- Job titles (Block Education Officer, etc.)
- Document section references (Chapter 3 of..., etc.)
"""

import re
from typing import List, Dict, Optional, Set

from src.parsing_pipeline.modules.manifest_ingestion_service import STATE_CODES


class EntityExtractor:
    """
    Extracts named entities from audit report chunks.

    Features:
    - Scheme/program extraction with acronym handling
    - Ministry/department detection
    - Organization extraction (PSUs, boards, PRIs, ULBs)
    - Verb/preposition rejection to filter sentence fragments
    - Substring deduplication
    """

    # A capital letter, Latin accents included ("Āyushman Bhārat")
    _UP = "A-ZÀ-ÖØ-Þ\u0100-\u017f"

    # P3-1: Entity patterns - NO IGNORECASE, capitalization matters
    ENTITY_PATTERNS = {
        "schemes": [
            # A run of capitalised words (joined by of/for/and/the/in/to) ending in
            # Scheme/Yojana/...: "Pradhan Mantri Awas Yojana", not "There are seven ... Scheme"
            r"(?<![\w'’])((?!(?:The|This|These|That|Under|In|As|It|An|All|Audit|Its|Such|Each)\b)"
            rf"[{_UP}][\w'’&-]*(?:\s+(?:(?:of|for|and|the|in|to|&)\s+)?[{_UP}][\w'’&-]*){{0,6}}"
            r"\s+(?:Scheme|Programme|Program|Mission|Yojana|Abhiyan|Abhiyaan))\b",
        ],
        "ministries": [
            # Match Ministry/Department of <Capitalized Words>
            # Stop before "and Ministry/Department" (separate entity)
            # Allow internal "and" for names like "Micro, Small & Medium Enterprises"
            r"(Ministry\s+of\s+[A-Z][a-z\w]*(?:(?:,\s*|\s+&\s+|\s+)[A-Z](?!inistry|epartment)[a-z\w]*){0,5})",
            r"(Department\s+of\s+[A-Z][a-z\w]*(?:(?:,\s*|\s+&\s+|\s+)[A-Z](?!inistry|epartment)[a-z\w]*){0,5})",
        ],
        "organizations": [
            r"((?:Indian\s+)?Railways?)",
            # Common CAG acronyms
            r"(INCOIS|ISRO|DRDO|CPWD|PWD|NHAI|ONGC|BHEL|SAIL|HAL|AAI|FCI)",
            # State PSEs
            r"(\w+\s+(?:Tourism|Power|Finance|Mining|Transport|Industrial)\s+Corporation)",
            # State boards
            r"(\w+\s+(?:Electricity|Pollution\s+Control|Revenue)\s+(?:Board|Commission))",
            # State government abbreviations
            r"\b(Go(?:AP|HP|SK|UK|OD|MH|KL|AS|BR|CG))\b",
            # PRIs (Panchayati Raj Institutions)
            r"(Gram\s+Panchayats?)",
            r"(Zilla\s+Panchayats?)",
            r"(Zila\s+Parishads?)",
            r"(Panchayat\s+Samitis?)",
            r"(Block\s+Panchayats?)",
            # ULBs (Urban Local Bodies)
            r"(Municipal\s+Corporations?)",
            r"(Municipal\s+Councils?)",
            r"(Nagar\s+Panchayats?)",
            r"(Nagar\s+Palikas?)",
            r"(Nagar\s+Nigams?)",
            # Local positions (treated as organizations)
            r"(Block\s+Development\s+Officers?)",
            r"(District\s+Programme\s+Coordinators?)",
            r"(Adhyakshas?)",
            r"(Sarpanchs?)",
            # Finance Commission
            r"(\d+th\s+(?:Central|State)\s+Finance\s+Commission)",
            # Require 2+ capitalized words before suffix, max 60 chars
            r"((?:[A-Z][a-z]+\s+){1,5}(?:Corporation|Authority|Board|Commission|Council))",
        ],
    }

    # "Gross Enrolment Ratio (GER)": an acronym and what it stands for, kept apart
    # from schemes (most such definitions are not schemes)
    ACRONYM_PATTERN = re.compile(
        r"(?<![\w'’])((?!(?:The|This|These|In|Under|As|An|Audit|Its)\b)[A-Z][\w'’&-]*"
        r"(?:\s+(?:(?:of|for|and|the|in|to|with|on|&)\s+)?[A-Z][\w'’&-]*){0,8})"
        r"\s*\(\s*([A-Z][A-Za-z&]{1,9})\s*\)"
    )
    _CONNECTORS = {"of", "for", "and", "the", "in", "to", "with", "on", "&"}
    _GOI_SUFFIX = re.compile(
        r"\s*,?\s*\(?(?:GoI|GOI|Government\s+of\s+India|Govt\.?\s+of\s+India)\)?$"
    )

    # P3-1: Verb stems and prepositions that indicate captured sentence fragments
    ENTITY_REJECT_VERBS = {
        "was",
        "were",
        "is",
        "are",
        "has",
        "had",
        "have",
        "been",
        "said",
        "noted",
        "observed",
        "stated",
        "found",
        "reported",
        "recommended",
        "suggested",
        "directed",
        "instructed",
        "mentioned",
        "indicated",
        "revealed",
        "submitted",
        "failed",
        "did",
        "does",
        "could",
        "should",
        "would",
        "the",
        "that",
        "this",
        "which",
        "where",
        "when",
        "under",
        "over",
        "during",
        "after",
        "before",
        "from",  # Prepositions
    }

    # Scheme rejection patterns (filter out false positives)
    SCHEME_REJECT_PATTERNS = [
        r"^As\s+per\s+",
        r"^Audit\s+(?:noticed|observed|conducted|of\s+Scheme)",
        r"^In\s+(?:respect\s+of|the|STO|Municipal)",
        r"^It\s+was\s+",
        r"^A\s+total\s+of\s+\d+",
        r"^A\s+has\s+",
        r"^An\s+Audit",
        r"^(?:Section|Rule|Clause)\s+\d+",
        r"DLFA\s+also",
        r"Local\s+Fund\s+Accounts\s+Audit",
    ]

    # P1-10: State names for place-name rejection (lowercase for comparison)
    STATE_NAMES_LOWER = {name.lower() for name in STATE_CODES.keys()}

    # P1-10: Job title patterns to reject
    JOB_TITLE_PATTERNS = [
        re.compile(
            r"^(?:Block|District|State)\s+(?:Education|Development|Programme)\s+Officer",
            re.I,
        ),
        re.compile(r"^(?:Chartered\s+)?Accountant$", re.I),
        re.compile(r"^Block\s+Resource\s+(?:Person|Coordinator)", re.I),
        re.compile(r"^Executive\s+Engineer$", re.I),
        re.compile(r"^District\s+Collector$", re.I),
        re.compile(r"^Chief\s+(?:Engineer|Executive)\s+Officer$", re.I),
        re.compile(
            r"^(?:Assistant|Deputy|Joint)\s+(?:Commissioner|Director|Secretary)$", re.I
        ),
    ]

    # P1-10: Document section patterns to reject
    DOCUMENT_SECTION_PATTERNS = [
        re.compile(r"^Chapter\s+\d+\s+of\b", re.I),
        re.compile(r"^Annual\s+(?:Report|Technical\s+Inspection)", re.I),
        re.compile(r"^Paragraph\s+[\d.]+", re.I),
        re.compile(r"^Annexure\s+[A-Za-z\d]+\s+of\b", re.I),
        re.compile(r"^Appendix\s+[A-Za-z\d]+\s+to\b", re.I),
    ]

    def __init__(self):
        """Initialize with compiled regex patterns."""
        # P3-1: NO IGNORECASE - capitalization matters for entities
        self._entity_patterns = {
            entity_type: [re.compile(p) for p in patterns]
            for entity_type, patterns in self.ENTITY_PATTERNS.items()
        }

        # Compile scheme rejection patterns
        self._scheme_reject_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.SCHEME_REJECT_PATTERNS
        ]

        # alias (lowercase) -> canonical name, per entity type, from enrichment_patterns.yaml
        self._aliases: Dict[str, Dict[str, str]] = {}
        try:
            from src.parsing_pipeline.modules.enrichment.pattern_loader import (
                get_pattern_loader,
            )

            for entity_type, mapping in (
                get_pattern_loader().get_entity_aliases() or {}
            ).items():
                lookup = self._aliases.setdefault(entity_type, {})
                for canonical, aliases in (mapping or {}).items():
                    lookup[canonical.lower()] = canonical
                    for alias in aliases or []:
                        lookup[str(alias).lower()] = canonical
        except Exception:
            self._aliases = {}

    def extract_entities(self, child_chunks: List[Dict]) -> Dict[str, List[str]]:
        """
        Extract named entities from all child chunks.

        Args:
            child_chunks: List of child chunk dicts

        Returns:
            Dict mapping entity type to sorted list of unique entities, plus
            "acronyms": ["Gross Enrolment Ratio (GER)", ...]
        """
        entities: Dict[str, Set[str]] = {
            entity_type: set() for entity_type in self.ENTITY_PATTERNS.keys()
        }

        for chunk in child_chunks:
            content = chunk.get("content", "")

            for entity_type, patterns in self._entity_patterns.items():
                for pattern in patterns:
                    matches = pattern.findall(content)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]

                        # Apply scheme rejection filter
                        if entity_type == "schemes":
                            if any(
                                rej.search(match)
                                for rej in self._scheme_reject_patterns
                            ):
                                continue

                        # Aliases first: "FCI" is too short to pass the cleaner on its own
                        cleaned = self._clean_entity(
                            self._canonical(entity_type, " ".join(match.split()))
                        )
                        if cleaned:
                            entities[entity_type].add(cleaned)

        # Deduplicate by substring (keep longer form)
        for entity_type in entities:
            entities[entity_type] = self._deduplicate_by_substring(
                entities[entity_type]
            )

        # Convert sets to sorted lists
        result = {k: sorted(list(v)) for k, v in entities.items()}
        result["acronyms"] = sorted(
            f"{expansion} ({acronym})"
            for acronym, expansion in self.extract_acronyms(child_chunks).items()
        )
        return result

    def extract_acronyms(self, child_chunks: List[Dict]) -> Dict[str, str]:
        """{"GER": "Gross Enrolment Ratio"}: acronyms the report defines, the first definition kept."""
        found: Dict[str, str] = {}
        for chunk in child_chunks:
            for m in self.ACRONYM_PATTERN.finditer(chunk.get("content", "") or ""):
                acronym = m.group(2)
                if acronym in found:
                    continue
                expansion = self._expansion_for(m.group(1).split(), acronym)
                if expansion:
                    found[acronym] = expansion
        return found

    def _expansion_for(self, words: List[str], acronym: str) -> Optional[str]:
        """The shortest tail of words whose initials spell the acronym's capitals."""
        letters = [c for c in acronym if c.isupper()]
        for start in range(len(words) - 1, -1, -1):
            tail = words[start:]
            if tail[0].lower() in self._CONNECTORS:
                continue
            initials = [w[0].upper() for w in tail if w.lower() not in self._CONNECTORS]
            if initials == letters:
                return " ".join(tail)
            if len(initials) > len(letters):
                break
        return None

    def _canonical(self, entity_type: str, entity: str) -> str:
        """Alias -> canonical name; "Ministry of Education, GoI" -> "Ministry of Education"."""
        if entity_type == "ministries":
            entity = self._GOI_SUFFIX.sub("", entity).strip() or entity
        return self._aliases.get(entity_type, {}).get(entity.lower(), entity)

    def extract_entities_from_text(self, text: str) -> List[str]:
        """
        Extract entities from a single text block.

        Args:
            text: Text to extract entities from

        Returns:
            List of unique entities (max 10)
        """
        entities = []

        for entity_type, patterns in self._entity_patterns.items():
            for pattern in patterns:
                matches = pattern.findall(text)
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0]

                    # Apply scheme rejection filter
                    if entity_type == "schemes":
                        if any(
                            rej.search(match) for rej in self._scheme_reject_patterns
                        ):
                            continue

                    cleaned = self._clean_entity(
                        self._canonical(entity_type, " ".join(match.split()))
                    )
                    if cleaned:
                        entities.append(cleaned)

        # Max 10 entities per finding, the first ones found: a set's order changes
        # from one process to the next, which changed the list between runs
        return list(dict.fromkeys(entities))[:10]

    def _clean_entity(self, raw: str) -> Optional[str]:
        """
        P3-1: Post-process a raw entity match. Returns None if garbage.
        P1-10: Enhanced filtering for stuttered text, place names, job titles,
               and document section references.

        Filters out:
        - Sentence fragments (starts with verbs/articles/prepositions)
        - Too short (<4 chars) or too long (>60 chars)
        - Lowercase starts
        - Too many words (>8 = likely sentence fragment)
        - Contains sentence-ending punctuation mid-string
        - P1-10: Stuttered/doubled text (tokenizer artifacts)
        - P1-10: State names (place-name rejection)
        - P1-10: Job titles (Block Education Officer, etc.)
        - P1-10: Document section references (Chapter 3 of..., etc.)

        Args:
            raw: Raw entity string extracted by regex

        Returns:
            Cleaned entity string or None if it should be rejected
        """
        cleaned = " ".join(raw.split()).strip()

        # Length bounds
        if len(cleaned) < 4 or len(cleaned) > 60:
            return None

        # Must start with uppercase
        if not cleaned[0].isupper():
            return None

        # Reject if first word is a common verb/article/preposition
        first_word = cleaned.split()[0].lower()
        if first_word in self.ENTITY_REJECT_VERBS:
            return None

        # Reject if >8 words (likely a sentence fragment)
        # Allow up to 8 for names like "Ministry of Micro, Small & Medium Enterprises"
        if len(cleaned.split()) > 8:
            return None

        # Reject if contains sentence-ending punctuation mid-string
        if re.search(r"[.!?]\s+[A-Z]", cleaned):
            return None

        # P1-10: Detect stuttered/doubled text pattern (tokenizer artifact)
        # "DirectDirect BenefitBenefit TransferTransfer" → reject
        if re.search(r"\b(\w{3,})\1\b", cleaned, re.IGNORECASE):
            return None

        # P1-10: Reject standalone state names (but allow "Maharashtra Employment Scheme")
        # Only reject if the entity is EXACTLY a state name
        if cleaned.lower() in self.STATE_NAMES_LOWER:
            return None

        # P1-10: Reject job titles
        if any(p.match(cleaned) for p in self.JOB_TITLE_PATTERNS):
            return None

        # P1-10: Reject document section references
        if any(p.match(cleaned) for p in self.DOCUMENT_SECTION_PATTERNS):
            return None

        return cleaned

    def _deduplicate_by_substring(self, entities: Set[str]) -> Set[str]:
        """
        P3-1: Deduplicate by substring.

        If "National Highways Authority" and "National Highways Authority of India"
        both exist, keep the longer one.

        Args:
            entities: Set of entity strings

        Returns:
            Deduplicated set
        """
        deduped = set()
        sorted_ents = sorted(entities, key=lambda e: (-len(e), e))
        for ent in sorted_ents:
            # Whole words only: "RD" is not part of "RDD"
            inside = re.compile(r"(?<!\w)" + re.escape(ent.lower()) + r"(?!\w)")
            if not any(inside.search(existing.lower()) for existing in deduped):
                deduped.add(ent)
        return deduped
