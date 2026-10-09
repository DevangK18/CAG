"""
Cross-Reference Resolver: Detects and resolves intra-document references.

Handles:
1. Paragraph references: "Para 3.2.1", "Paras 2.1.1, 2.1.2 and 2.3", "paragraphs 3.1 to 3.4"
2. Section references: "Section 2.1"
3. Chapter references: "Chapter III", "Chapter-3", "Chapters 5 and 6"
4. Table references: "Table 1.3", "Table-1", "Table No. 2"

Also home of the ReferenceIndex shared with the evidence linker, the annexure
linker and the executive-summary parser: one place that knows how a report
numbers its sections, chapters, tables and appendices.

References to another document ("Paragraph 4.4.1 of SSIF", "Chapter VI of GFR")
are not this report's paragraphs and are skipped. So is a heading or caption
naming its own table, appendix or chapter.

Does NOT handle semantic similarity linking (that's a Phase 4 embedding task).
"""

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

# ── identifiers ────────────────────────────────────────────────────────────

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50}


def roman_to_int(text: str) -> Optional[int]:
    """'iv' -> 4, 'XII' -> 12; None when not a Roman numeral of I, V, X and L."""
    s = (text or "").strip().lower()
    if not s or any(ch not in _ROMAN for ch in s):
        return None
    total = 0
    for i, ch in enumerate(s):
        value = _ROMAN[ch]
        if i + 1 < len(s) and _ROMAN[s[i + 1]] > value:
            total -= value
        else:
            total += value
    return total if total > 0 else None


def chapter_number(text: str) -> Optional[int]:
    """'III' -> 3, '3' -> 3, 'iii' -> 3."""
    s = (text or "").strip().rstrip(".")
    if s.isdigit():
        return int(s)
    return roman_to_int(s)


def normalize_appendix_id(raw: str) -> str:
    """
    'Appendix-3(i)' / '3 (i)' -> '3(i)'; 'Annexure IV' -> '4'; 'A' -> 'a'; '5.2.' -> '5.2'.

    Annexure and Appendix are the same thing; a Roman first part becomes Arabic so
    "Annexure II" and "Annexure 2" meet.
    """
    s = re.sub(
        r"^\W*(?:annexures?|appendix|appendices|annex)\b[\s\-–—:.]*(?:no\.?\s*)?",
        "",
        raw.strip(),
        flags=re.I,
    )
    s = re.sub(r"\s+", "", s).rstrip(".").lower()
    m = re.match(r"([a-z]+|\d+)(.*)$", s)
    if not m:
        return s
    head, rest = m.groups()
    number = roman_to_int(head) if re.fullmatch(r"[ivx]+", head) else None
    return f"{number if number is not None else head}{rest}"


def normalize_table_id(raw: str) -> str:
    """'6 (i)' -> '6(i)', '2.1.' -> '2.1'."""
    return re.sub(r"\s+", "", raw or "").rstrip(".").lower()


def expand_number_list(text: str) -> List[str]:
    """
    '2.1.1, 2.1.2, 2.2 and 2.3' -> four numbers; '3.1 to 3.4' -> 3.1, 3.2, 3.3, 3.4;
    '3.5.3 & 3.5.4.2' -> two numbers. Trailing dots are dropped.
    """
    numbers: List[str] = []
    for part in re.split(r"\s*(?:,|;|&|\band\b)\s*", text or ""):
        part = part.strip().rstrip(".")
        if not part:
            continue
        span = re.match(r"^(\d+(?:\.\d+)*)\s*(?:to|-|–)\s*(\d+(?:\.\d+)*)$", part)
        if span:
            start, end = span.group(1), span.group(2)
            a, b = start.split("."), end.split(".")
            if (
                len(a) == len(b)
                and a[:-1] == b[:-1]
                and int(a[-1]) < int(b[-1]) <= int(a[-1]) + 30
            ):
                prefix = ".".join(a[:-1])
                numbers.extend(
                    f"{prefix}.{i}" if prefix else str(i)
                    for i in range(int(a[-1]), int(b[-1]) + 1)
                )
            else:
                numbers.extend([start, end])
            continue
        if re.fullmatch(r"\d+(?:\.\d+)*", part):
            numbers.append(part)
    return list(dict.fromkeys(numbers))


# ── reference patterns ─────────────────────────────────────────────────────

_NUM = r"\d{1,2}(?:\.\d{1,3})+\.?"
_NUM_LIST = rf"{_NUM}(?:\s*(?:,|&|\band\b|\bto\b)\s*{_NUM})*"
_CHAPTER_ID = r"(?:[IVX]+|\d{1,2})\b"
_TABLE_ID = r"\d{1,2}(?:\.\d{1,3})*(?:\s*\((?:[ivx]+|[a-z])\))?"
_APPENDIX_ID = r"(?:[IVX]+\b|[A-Z](?![A-Za-z])|\d{1,3}(?:\.\d{1,3})*)(?:\s*\((?:[ivx]+|[a-z]|\d{1,2})\))?"

REFERENCE_REGEXES: Dict[str, re.Pattern] = {
    # "Para 3.2.1", "Paras 2.1.1, 2.1.2 and 2.3", "paragraphs 3.1 to 3.4"
    "para": re.compile(rf"\b(?i:para(?:graph)?s?)\b\.?\s*(?i:no\.?\s*)?({_NUM_LIST})"),
    "section": re.compile(rf"\b(?i:sections?)\s+({_NUM_LIST})"),
    "chapter": re.compile(
        rf"\b(?i:chapters?)\b[\s\-–—:.]*({_CHAPTER_ID}(?:\s*(?:,|&|\band\b|\bto\b)\s*{_CHAPTER_ID})*)"
    ),
    # Case-sensitive keyword: "time table 2019" is not a table reference
    "table": re.compile(
        rf"\b(?:Tables?|TABLES?)\b[\s\-–—:.]*(?:No\.?\s*)?({_TABLE_ID})(?!\d|-\d)"
    ),
    "appendix": re.compile(
        rf"\b(?i:annexures?|appendix|appendices|annex)\b[\s\-–—:.]*(?:No\.?\s*)?"
        rf"({_APPENDIX_ID}(?:\s*(?:,|&|\band\b|\bto\b)\s*{_APPENDIX_ID})*)"
    ),
}

# "... of the Act", "of SSIF", "of PWD Manual": another document's paragraph or chapter.
# "of this Report", "of Chapter 3" stay ours.
_OF_OTHER_DOC = re.compile(
    r"^\s*,?\s*(?:of|under|in)\s+"
    r"(?!(?i:(?:this|the\s+present|the)\s+(?:audit\s+)?(?:report|chapter)\b|chapters?\b|paras?\b|paragraphs?\b))"
    r"(?:the\s+)?(?:[A-Z]|\w+\s+(?:Act|Rules?|Manual|Code|Guidelines?|Framework|Policy|Order))"
)
# An ATIR's own paragraphs are cited as "Para x.y of this Report"; a previous report
# ("of the Report No. 5 of 2020", "of Audit Report 2019") is another document.
_OF_EARLIER_REPORT = re.compile(
    r"^\s*,?\s*of\s+(?:the\s+)?(?:audit\s+)?report\s+(?:no|for|of|\d)", re.I
)
# "NEP 2020 (Paragraph 6.9)", "the Act (Section 2.1)": named just before
_AFTER_OTHER_DOC = re.compile(
    r"(?:\b[A-Z]{2,}\s+(?:19|20)\d{2}|\b(?:Act|Rules|Manual|Guidelines|Policy|Code|Framework|Order))\s*,?\s*\(?\s*$"
)


@dataclass
class Reference:
    kind: str  # para, section, chapter, table, appendix
    target: str  # one identifier ("3.2.1", "3", "6(i)", "appendix id")
    text: str  # the whole matched text
    start: int
    end: int


def _split_ids(kind: str, raw: str) -> List[str]:
    if kind in ("para", "section"):
        return expand_number_list(raw)
    parts = [p.strip() for p in re.split(r"\s*(?:,|&|\band\b)\s*", raw) if p.strip()]
    ids: List[str] = []
    for part in parts:
        span = re.match(r"^(.+?)\s*\bto\b\s*(.+)$", part)
        if span and kind == "chapter":
            a, b = chapter_number(span.group(1)), chapter_number(span.group(2))
            if a and b and a < b <= a + 15:
                ids.extend(str(i) for i in range(a, b + 1))
                continue
        if span and re.fullmatch(r"[\d.\s]+to[\d.\s]+", part):
            ids.extend(expand_number_list(part))
            continue
        ids.extend([span.group(1), span.group(2)] if span else [part])
    if kind == "chapter":
        return [str(n) for n in (chapter_number(i) for i in ids) if n]
    if kind == "table":
        return [normalize_table_id(i) for i in ids]
    return [normalize_appendix_id(i) for i in ids]


def find_references(
    text: str, kinds: Iterable[str] = REFERENCE_REGEXES.keys()
) -> List[Reference]:
    """Every reference to a part of this report in text, lists expanded, other documents left out."""
    found: List[Reference] = []
    for kind in kinds:
        for m in REFERENCE_REGEXES[kind].finditer(text or ""):
            after = text[m.end() : m.end() + 80]
            before = text[max(0, m.start() - 40) : m.start()]
            if kind != "appendix" and (
                _OF_OTHER_DOC.match(after)
                or _OF_EARLIER_REPORT.match(after)
                or _AFTER_OTHER_DOC.search(before)
            ):
                continue
            for target in _split_ids(kind, m.group(1)):
                found.append(
                    Reference(kind, target, m.group(0).strip(), m.start(), m.end())
                )
    found.sort(key=lambda r: (r.start, r.kind))
    return found


def is_title_match(chunk: Dict, ref: Reference) -> bool:
    """
    The reference names the chunk itself: a heading or caption ("Table 3.2: ...",
    "Annexure III (Refer Para 5.1.3.1)", "Chapter II: Management of ..."), not a
    pointer to somewhere else.
    """
    content = chunk.get("content") or ""
    lead = len(content) - len(content.lstrip(" \t\n(|*#"))
    if ref.start > lead:
        return False
    if chunk.get("content_type") in ("header", "caption", "table_markdown"):
        return True
    return bool(re.match(r"\s*[:\-–—|]", content[ref.end : ref.end + 4]))


def is_contents_listing(chunk: Dict) -> bool:
    """A table of contents, list of appendices or tables: rows naming sections, not references."""
    if chunk.get("content_type") != "table_markdown":
        return False
    head = (chunk.get("content") or "")[:300]
    return bool(
        re.search(r"\|\s*(?:page|pages|page\s+no\.?|page\s+number)\s*\|", head, re.I)
    )


# ── the index ───────────────────────────────────────────────────────────────

_SECTION_TITLE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3})*)\.?(?=\s|$|[A-Za-z(])")
_CHAPTER_TITLE = re.compile(r"^\W*chapter\b[\s\-–—:.]*([ivx]+|\d{1,2})\b", re.I)
_TABLE_TITLE = re.compile(
    rf"^\W*(?:Table|TABLE)[\s\-–—:.]*(?:No\.?\s*)?({_TABLE_ID})(?!\d)"
)
_APPENDIX_TITLE = re.compile(
    rf"^\W*(?i:annexures?|appendix|annex)\b[\s\-–—:.]*(?:No\.?\s*)?({_APPENDIX_ID})"
)
_APPENDIX_REGION = re.compile(r"\b(?:annexures?|appendix|appendices|annex)\b", re.I)
_EXEC_REGION = re.compile(
    r"executive\s+summary|^\W*overview\W*$|^\W*highlights?\W*$", re.I
)


def _first_page(parent: Dict) -> int:
    pages = parent.get("page_range_physical") or [0]
    return pages[0] if pages else 0


def parents_from_children(child_chunks: List[Dict]) -> List[Dict]:
    """Parent stubs (id, title, level, hierarchy, first page) for callers that only have children."""
    parents: Dict[str, Dict] = {}
    for child in child_chunks:
        pid = child.get("parent_chunk_id")
        if not pid or pid in parents:
            continue
        hierarchy = child.get("hierarchy") or {}
        values = [v for v in hierarchy.values() if isinstance(v, str)]
        parents[pid] = {
            "chunk_id": pid,
            "toc_entry": values[-1] if values else "",
            "toc_level": len(values) or 1,
            "hierarchy": hierarchy,
            "page_range_physical": [child.get("source_page_physical", 0)],
        }
    return list(parents.values())


class ReferenceIndex:
    """
    Where each section, chapter, table and appendix of one report lives.

    - sections: "3.2.1" -> parent (or a numbered heading inside a parent);
      a deeper number falls back to its nearest indexed ancestor.
    - chapters: 3 -> the level-1 parent titled "Chapter III" / "Chapter-3".
    - tables: "3.2" -> the table chunk (its number from Phase 6/8, or a caption
      at most two chunks before it).
    - appendices: "2.1" -> the appendix parent, or the heading chunk that starts
      it when all appendices sit under one "Annexures" parent.
    """

    def __init__(self, parent_chunks: List[Dict], child_chunks: List[Dict]):
        self.sections: Dict[str, Dict] = {}
        self.chapters: Dict[str, Dict] = {}
        self.tables: Dict[str, Dict] = {}
        self.appendices: Dict[str, Dict] = {}
        # chunk_id of a caption or heading -> the table or appendix key it names
        self.caption_of: Dict[str, Tuple[str, str]] = {}
        self.parent_of: Dict[str, str] = {
            c.get("chunk_id"): c.get("parent_chunk_id") for c in child_chunks
        }
        self._index_parents(parent_chunks)
        self._index_children(parent_chunks, child_chunks)

    @staticmethod
    def _target(chunk: Dict, chunk_type: str, title: str, page: int) -> Dict:
        return {
            "chunk_id": chunk.get("chunk_id"),
            "chunk_type": chunk_type,
            "title": title[:80],
            "page": page,
        }

    def _index_parents(self, parent_chunks: List[Dict]) -> None:
        for parent in parent_chunks:
            title = (parent.get("toc_entry") or "").strip()
            level_1 = (parent.get("hierarchy") or {}).get("level_1") or title
            in_exec = bool(_EXEC_REGION.search(level_1))
            target = self._target(parent, "parent", title, _first_page(parent))
            m = _APPENDIX_TITLE.match(title)
            if m:
                self.appendices.setdefault(normalize_appendix_id(m.group(1)), target)
                continue
            m = _CHAPTER_TITLE.match(title)
            if m and chapter_number(m.group(1)):
                self.chapters.setdefault(str(chapter_number(m.group(1))), target)
                continue
            m = _SECTION_TITLE.match(title)
            if m and int(m.group(1).split(".")[0]) <= 50:
                key = m.group(1)
                held = self.sections.get(key)
                # A section's own number wins over an executive-summary heading that copies it
                if held is None or (held.get("_exec") and not in_exec):
                    self.sections[key] = {**target, "_exec": in_exec}
                if "." not in key and (parent.get("toc_level") or 1) == 1:
                    self.chapters.setdefault(key, target)

    def _index_children(
        self, parent_chunks: List[Dict], child_chunks: List[Dict]
    ) -> None:
        appendix_parents = {
            p.get("chunk_id")
            for p in parent_chunks
            if _APPENDIX_REGION.search(p.get("toc_entry") or "")
            or _APPENDIX_REGION.search((p.get("hierarchy") or {}).get("level_1") or "")
        }
        for i, child in enumerate(child_chunks):
            content = (child.get("content") or "").strip()
            ctype = child.get("content_type")
            page = child.get("source_page_physical", 0)
            cid = child.get("chunk_id")
            if ctype == "table_markdown":
                sd = child.get("structured_data") or {}
                number = sd.get("table_number")
                caption_id = None
                if not number:
                    m = _TABLE_TITLE.match(content)
                    number = m.group(1) if m else None
                if not number:
                    # Caption just before the table: at most two chunks back, same or previous page
                    for back in child_chunks[max(0, i - 2) : i][::-1]:
                        if back.get("source_page_physical", 0) not in (page, page - 1):
                            continue
                        m = _TABLE_TITLE.match((back.get("content") or "").strip())
                        if m and back.get("content_type") != "table_markdown":
                            number, caption_id = m.group(1), back.get("chunk_id")
                            break
                if number:
                    key = normalize_table_id(str(number))
                    if key not in self.tables:
                        self.tables[key] = self._target(child, "child", content, page)
                        self.caption_of[cid] = ("table", key)
                        if caption_id:
                            self.caption_of[caption_id] = ("table", key)
            elif ctype in ("caption", "header", "paragraph"):
                m = _TABLE_TITLE.match(content)
                if m and re.match(r"\s*[:\-–—.]", content[m.end() : m.end() + 3]):
                    self.caption_of.setdefault(
                        cid, ("table", normalize_table_id(m.group(1)))
                    )
            if ctype in ("header", "paragraph", "caption", "table_markdown") and (
                child.get("parent_chunk_id") in appendix_parents
            ):
                # An appendix heading starts the chunk, or a row of a table running on from the last one
                lines = (
                    [content]
                    if ctype != "table_markdown"
                    else [
                        line.strip().strip("|").strip() for line in content.splitlines()
                    ]
                )
                for line in lines:
                    m = _APPENDIX_TITLE.match(line)
                    if m:
                        key = normalize_appendix_id(m.group(1))
                        self.caption_of.setdefault(cid, ("appendix", key))
                        self.appendices.setdefault(
                            key, self._target(child, "child", line, page)
                        )
                        break
            if ctype == "header":
                m = _SECTION_TITLE.match(content)
                if m and "." in m.group(1) and int(m.group(1).split(".")[0]) <= 50:
                    self.sections.setdefault(
                        m.group(1),
                        {**self._target(child, "child", content, page), "_exec": False},
                    )
        # Tables named only by a caption (an image table, or a caption the table chunk lost)
        for cid, (kind, key) in self.caption_of.items():
            if kind == "table" and key not in self.tables:
                chunk = next(
                    (c for c in child_chunks if c.get("chunk_id") == cid), None
                )
                if chunk:
                    self.tables[key] = self._target(
                        chunk,
                        "child",
                        chunk.get("content") or "",
                        chunk.get("source_page_physical", 0),
                    )

    # ── lookups: (target, how) or (None, None) ──────────────────────────────

    def resolve_section(self, number: str) -> Tuple[Optional[Dict], Optional[str]]:
        number = (number or "").rstrip(".")
        if number in self.sections:
            return self.sections[number], "exact"
        parts = number.split(".")
        while len(parts) > 2:
            parts = parts[:-1]
            if ".".join(parts) in self.sections:
                return self.sections[".".join(parts)], "ancestor"
        return None, None

    def resolve_chapter(self, number: str) -> Tuple[Optional[Dict], Optional[str]]:
        n = chapter_number(number)
        target = self.chapters.get(str(n)) if n else None
        return (target, "exact") if target else (None, None)

    def resolve_table(self, key: str) -> Tuple[Optional[Dict], Optional[str]]:
        key = normalize_table_id(key)
        if key in self.tables:
            return self.tables[key], "exact"
        base = re.sub(r"\(.*\)$", "", key)
        if base != key and base in self.tables:
            return self.tables[base], "ancestor"
        return None, None

    def resolve_appendix(self, key: str) -> Tuple[Optional[Dict], Optional[str]]:
        if key in self.appendices:
            return self.appendices[key], "exact"
        base = re.sub(r"\(.*\)$", "", key)
        if base != key and base in self.appendices:
            return self.appendices[base], "ancestor"
        # "Appendix 15" when only 15(i) and 15(ii) exist: only a single candidate resolves
        prefixed = [k for k in self.appendices if k.startswith(key + "(")]
        if len(prefixed) == 1:
            return self.appendices[prefixed[0]], "prefix"
        return None, None

    def resolve(self, ref: Reference) -> Tuple[Optional[Dict], Optional[str]]:
        if ref.kind in ("para", "section"):
            return self.resolve_section(ref.target)
        if ref.kind == "chapter":
            return self.resolve_chapter(ref.target)
        if ref.kind == "table":
            return self.resolve_table(ref.target)
        return self.resolve_appendix(ref.target)

    def names_itself(self, chunk: Dict, ref: Reference) -> bool:
        """The chunk is the caption or heading of the very table or appendix it mentions."""
        named = self.caption_of.get(chunk.get("chunk_id"))
        return bool(named) and named == (
            "table"
            if ref.kind == "table"
            else "appendix"
            if ref.kind == "appendix"
            else "",
            ref.target if ref.kind == "appendix" else normalize_table_id(ref.target),
        )


class CrossReferenceResolver:
    KINDS = ("para", "section", "chapter", "table")

    def _build_section_index(
        self, parent_chunks: List[Dict], child_chunks: List[Dict]
    ) -> Dict[str, Dict]:
        """
        Flat lookup kept for callers of the old API: "3.2.1", "chapter_3", "table_1.3".
        """
        index = ReferenceIndex(parent_chunks, child_chunks)
        flat: Dict[str, Dict] = {}
        for key, target in index.sections.items():
            flat[key] = {k: v for k, v in target.items() if not k.startswith("_")}
        for key, target in index.chapters.items():
            flat[f"chapter_{key}"] = target
        for key, target in index.tables.items():
            flat[f"table_{key}"] = target
        return flat

    def resolve_references(
        self,
        child_chunks: List[Dict],
        parent_chunks: List[Dict],
        index: Optional[ReferenceIndex] = None,
    ) -> List[Dict]:
        """
        Scan all chunks for cross-references and resolve them.

        Returns one entry per (chunk, type, target):
        [{
            "source_chunk_id": "...",
            "source_page": 47,
            "reference_type": "para" | "section" | "chapter" | "table",
            "reference_target": "3.2.1",
            "reference_text": "Paras 3.2.1 and 3.2.2",
            "resolved_chunk_id": "..." or None,
            "resolved_chunk_type": "parent" | "child" or None,
            "resolved_page": 12 or None,
            "resolved": True | False,
            "resolved_by": "exact" | "ancestor" | None,
        }]
        """
        index = index or ReferenceIndex(parent_chunks, child_chunks)
        references = []
        captions_seen = set()

        for chunk in child_chunks:
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id", "")
            if not content or is_contents_listing(chunk):
                continue
            # A table running over several pages repeats its caption on each part; the
            # caption's references were counted on the first part
            repeated_caption = 0
            if chunk.get("content_type") == "table_markdown":
                first_line = content.split("\n", 1)[0].strip()
                if first_line in captions_seen:
                    repeated_caption = len(first_line)
                captions_seen.add(first_line)
            seen = set()
            for ref in find_references(content, self.KINDS):
                if ref.end <= repeated_caption:
                    continue
                if is_title_match(chunk, ref) or index.names_itself(chunk, ref):
                    continue
                key = (ref.kind, ref.target)
                if key in seen:
                    continue
                seen.add(key)
                resolved, how = index.resolve(ref)
                # Don't create self-references
                if (
                    resolved
                    and resolved["chunk_id"] in (chunk_id, chunk.get("parent_chunk_id"))
                    and (how == "exact")
                ):
                    continue
                references.append(
                    {
                        "source_chunk_id": chunk_id,
                        "source_page": chunk.get("source_page_physical", 0),
                        "reference_type": ref.kind,
                        "reference_target": ref.target,
                        "reference_text": ref.text[:60],
                        "resolved_chunk_id": resolved["chunk_id"] if resolved else None,
                        "resolved_chunk_type": resolved["chunk_type"]
                        if resolved
                        else None,
                        "resolved_page": resolved.get("page") if resolved else None,
                        "resolved": resolved is not None,
                        "resolved_by": how,
                    }
                )

        return references
