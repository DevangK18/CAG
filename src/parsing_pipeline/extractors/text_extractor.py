"""
TextExtractor: Precision text extraction using PyMuPDF bounding box clipping.
Handles all textual content types: paragraphs, headers, lists, footnotes, etc.
"""

import logging

import fitz  # PyMuPDF
from typing import Dict, List, Optional, Tuple
import re

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.extractors.text_repair import (
    CONTROL_CHAR_RE,
    build_vocabulary,
    is_garbled,
    is_letter_spaced,
    is_reversed,
    is_rupee_font,
    is_shifted_span,
    repair_font_shift,
    repair_rupee_backtick,
    repair_shifted_block,
    respace_letter_spaced,
    reverse_words,
    shifted_fonts,
    unshift,
)
from src.parsing_pipeline.modules.ocr_normalizer import get_ocr_normalizer


logger = logging.getLogger(__name__)

# Footnote reference marker written into the text: "₹ 1.14 crore[^36]"
FOOTNOTE_MARKER_RE = re.compile(r"\[\^(\d+)\]")
_SUPERSCRIPT_FLAG = 1
# "10,000 m2", "Cu.m3", "sq.ft2": a raised 2 or 3 after a unit is an exponent
_EXPONENT_UNIT_RE = re.compile(
    r"(?:^|[\d\s.])(?:sq\.?)?(?:[kcm]?m|ft)\.?$", re.IGNORECASE
)
# "10^15": a raised number after a bare 10 is a power, not a footnote
_POWER_BASE_RE = re.compile(r"(?:^|[^\d,.])10$")

# Text a reader cannot see is not extracted: glyphs painted over by a later opaque
# white fill (an edit pasted over the old paragraph, which then read twice:
# "Hon'bleHon'ble", 2025_35, GJ) and glyphs set below 2 pt (Word's hidden reference
# numbers after BR's footnote markers: "Corporations44" + "7")
MIN_VISIBLE_SIZE = 2.0
_WHITE = 0.95
# Origins of a covered glyph and its rawdict char agree to rounding
_ORIGIN_TOLERANCE = 0.05
# Words on the same line: top or bottom within this distance (as PyMuPDF's sort)
_LINE_TOLERANCE = 3


def covered_glyphs(page) -> Dict[str, List[Tuple[float, float]]]:
    """Origins of the glyphs painted over by a later opaque white fill, by character."""
    try:
        fills = [
            (d["seqno"], fitz.Rect(d["rect"]))
            for d in page.get_drawings()
            if d.get("fill")
            and min(d["fill"]) >= _WHITE
            and (d.get("fill_opacity") is None or d["fill_opacity"] >= 0.99)
        ]
        if not fills:
            return {}
        spans = page.get_texttrace()
    except Exception:
        return {}
    covered: Dict[str, List[Tuple[float, float]]] = {}
    for span in spans:
        later = [rect for seq, rect in fills if seq > span["seqno"]]
        if not later:
            continue
        for unicode, _, origin, bbox in span["chars"]:
            char = chr(unicode)
            if char.isspace():
                continue
            cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
            if any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in later):
                covered.setdefault(char, []).append(tuple(origin))
    return covered


def _take(origins: Optional[list], origin) -> bool:
    """Remove and report a covered origin matching this glyph's origin."""
    for i, (x, y) in enumerate(origins or ()):
        if (
            abs(x - origin[0]) <= _ORIGIN_TOLERANCE
            and abs(y - origin[1]) <= _ORIGIN_TOLERANCE
        ):
            del origins[i]
            return True
    return False


def visible_words(textpage, covered: Dict[str, list]) -> Optional[list]:
    """
    The textpage's words without hidden glyphs, as extractWORDS tuples; None when no
    glyph is hidden. A word keeps its own box unless glyphs were taken from it.
    """
    raw = textpage.extractRAWDICT()
    words = textpage.extractWORDS()
    blocks = {b.get("number"): b for b in raw.get("blocks", []) if b.get("type") == 0}
    pending = {char: list(origins) for char, origins in covered.items()}
    split_lines: dict = {}
    out, dropped = [], False
    for w in words:
        block = blocks.get(w[5])
        if block is None or w[6] >= len(block["lines"]):
            out.append(w)
            continue
        key = (w[5], w[6])
        if key not in split_lines:
            parts, current = [], []
            for span in block["lines"][w[6]]["spans"]:
                tiny = span["size"] < MIN_VISIBLE_SIZE
                for ch in span["chars"]:
                    if ch["c"].isspace():
                        if current:
                            parts.append(current)
                        current = []
                    else:
                        current.append((ch, tiny))
            if current:
                parts.append(current)
            split_lines[key] = parts
        parts = split_lines[key]
        if w[7] >= len(parts) or "".join(c["c"] for c, _ in parts[w[7]]) != w[4]:
            out.append(w)
            continue
        kept = [
            c
            for c, tiny in parts[w[7]]
            if not (tiny or _take(pending.get(c["c"]), c["origin"]))
        ]
        if len(kept) == len(parts[w[7]]):
            out.append(w)
            continue
        dropped = True
        if kept:
            box = fitz.Rect()
            for c in kept:
                box |= fitz.Rect(c["bbox"])
            out.append((*box, "".join(c["c"] for c in kept), *w[5:]))
    return out if dropped else None


def sorted_text(words: list, tolerance: float = _LINE_TOLERANCE) -> str:
    """
    Plain text of words in reading order, laid out as PyMuPDF's
    get_text("text", sort=True) lays out a page's words.
    """
    if not words:
        return ""
    words = sorted(words, key=lambda w: (w[3], w[0]))
    ordered, line = [], [words[0]]
    lrect = fitz.Rect(words[0][:4])
    for w in words[1:]:
        rect = fitz.Rect(w[:4])
        if abs(rect.y0 - lrect.y0) <= tolerance or abs(rect.y1 - lrect.y1) <= tolerance:
            line.append(w)
            lrect |= rect
        else:
            ordered.extend(sorted(line, key=lambda w: w[0]))
            line, lrect = [w], rect
    ordered.extend(sorted(line, key=lambda w: w[0]))

    boxes = [(fitz.Rect(w[:4]), w[4]) for w in ordered]
    total = fitz.Rect()
    for rect, _ in boxes:
        total |= rect

    def line_text(items) -> str:
        items.sort(key=lambda item: item[0].x0)
        text, x1 = "", total.x0
        for rect, word in items:
            gap = max(
                int(round((rect.x0 - x1) / (rect.width or 1) * len(word))),
                0 if (x1 == total.x0 or rect.x0 <= x1) else 1,
            )
            text += " " * gap + word
            x1 = rect.x1
        return text

    lines, current = [], [boxes[0]]
    lrect = boxes[0][0]
    for rect, word in boxes[1:]:
        if abs(lrect.y0 - rect.y0) <= tolerance or abs(lrect.y1 - rect.y1) <= tolerance:
            current.append((rect, word))
            lrect |= rect
        else:
            lines.append((lrect, line_text(current)))
            current, lrect = [(rect, word)], rect
    lines.append((lrect, line_text(current)))
    lines.sort(key=lambda item: item[0].y1)
    text, y1 = lines[0][1], lines[0][0].y1
    for rect, ltext in lines[1:]:
        distance = min(int(round((rect.y0 - y1) / (rect.height or 1))), 5)
        text += "\n" * (distance + 1) + ltext
        y1 = rect.y1
    return text


def coded_words(textpage, fonts: set) -> list:
    """
    The textpage's words with the shifted fonts' glyphs decoded. Decoding comes
    first: the shifted space, digits and punctuation sit below U+0020, and PyMuPDF's
    word list drops them ("Report No. 7 of 2023" read "Report No of").
    """
    words = []
    for block in textpage.extractRAWDICT().get("blocks", []):
        if block.get("type") != 0:
            continue
        for line_no, line in enumerate(block["lines"]):
            chars, word_no = [], 0
            line_chars = [
                (ch, unshift(ch["c"]) if is_shifted_span(span, fonts) else ch["c"])
                for span in line["spans"]
                for ch in span["chars"]
            ]
            for item in line_chars + [None]:
                if item is not None and not item[1].isspace():
                    chars.append(item)
                    continue
                if chars:
                    box = fitz.Rect()
                    for ch, _ in chars:
                        box |= fitz.Rect(ch["bbox"])
                    text = "".join(c for _, c in chars)
                    words.append((*box, text, block["number"], line_no, word_no))
                    chars, word_no = [], word_no + 1
    return words


def _line_superscripts(line: dict) -> List[bool]:
    """Per character of a rawdict line: is it a raised, small digit?"""
    chars = [(span, c) for span in line["spans"] for c in span["chars"]]
    sizes = sorted(span["size"] for span, c in chars if not c["c"].isspace())
    if not sizes:
        return [False] * len(chars)
    median = sizes[len(sizes) // 2]
    baselines = sorted(
        c["origin"][1] for span, c in chars if span["size"] >= 0.8 * median
    )
    baseline = baselines[len(baselines) // 2] if baselines else None
    flags = []
    for span, c in chars:
        raised = span["flags"] & _SUPERSCRIPT_FLAG or (
            span["size"] < 0.8 * median
            and baseline is not None
            and c["origin"][1] < baseline - 0.15 * median
        )
        flags.append(bool(raised) and c["c"].isdigit())
    return flags


def _fix_word(
    chars: List[dict], fonts: List[str], sup: List[bool], first_in_line: bool
) -> str:
    """Rebuild one word with footnote markers and the rupee sign."""
    out = ""
    i, n = 0, len(chars)
    while i < n:
        if not sup[i]:
            c = chars[i]["c"]
            out += "₹" if c == "`" and is_rupee_font(fonts[i]) else c
            i += 1
            continue
        j = i
        while j < n and (sup[j] or (chars[j]["c"] == "," and j + 1 < n and sup[j + 1])):
            j += 1
        run = "".join(c["c"] for c in chars[i:j])
        numbers = re.findall(r"\d+", run)
        if i == 0 and first_in_line:
            # The number in front of a footnote's own text stays plain: "36 The ..."
            out += run + (" " if j < n else "")
        elif out and _EXPONENT_UNIT_RE.search(out) and set(numbers) <= {"2", "3"}:
            out += run
        elif _POWER_BASE_RE.search(out):
            out += "^" + run
        elif all(len(num) <= 3 for num in numbers):
            out += "".join(f"[^{num}]" for num in numbers)
        else:
            out += run
        i = j
    return out


def word_fixes(raw: dict, words: list) -> dict:
    """
    {word: repaired word} for the words of a textpage whose superscripts or rupee
    glyphs need repair. A word whose occurrences would be repaired differently is
    left alone, since the plain text gives no position to tell them apart.
    """
    blocks = {b.get("number"): b for b in raw.get("blocks", []) if b.get("type") == 0}
    line_words: dict = {}
    choices: dict = {}
    for w in words:
        block = blocks.get(w[5])
        if block is None or w[6] >= len(block["lines"]):
            continue
        key = (w[5], w[6])
        if key not in line_words:
            line = block["lines"][key[1]]
            sup = _line_superscripts(line)
            items = [
                (c, span["font"], s)
                for (span, c), s in zip(
                    ((span, c) for span in line["spans"] for c in span["chars"]), sup
                )
            ]
            split, current = [], []
            for item in items:
                if item[0]["c"].isspace():
                    if current:
                        split.append(current)
                    current = []
                else:
                    current.append(item)
            if current:
                split.append(current)
            line_words[key] = split
        split = line_words[key]
        if w[7] >= len(split):
            continue
        parts = split[w[7]]
        if "".join(p[0]["c"] for p in parts) != w[4]:
            continue
        if not any(p[2] for p in parts) and not any(
            p[0]["c"] == "`" and is_rupee_font(p[1]) for p in parts
        ):
            choices.setdefault(w[4], set()).add(w[4])
            continue
        fixed = _fix_word(
            [p[0] for p in parts],
            [p[1] for p in parts],
            [p[2] for p in parts],
            w[7] == 0,
        )
        choices.setdefault(w[4], set()).add(fixed)
    return {
        word: fixed.pop()
        for word, fixed in choices.items()
        if len(fixed) == 1 and next(iter(fixed)) != word
    }


class TextExtractor:
    """
    Extracts precise textual content from PDF bounding boxes using PyMuPDF's clip parameter.
    Handles text normalization and content type classification.
    """

    def __init__(self):
        """Initialize with text processing patterns."""
        self._vocab_cache = {}
        self._hidden_cache: dict = {}
        logger.info("TextExtractor initialized with PyMuPDF text extraction.")

    def _vocabulary(self, pdf_path: str):
        """Word frequencies of the report's normally spaced pages (for re-spacing)."""
        if pdf_path not in self._vocab_cache:
            with fitz.open(pdf_path) as doc:
                pages = [page.get_text("text") for page in doc]
            self._vocab_cache = {
                pdf_path: build_vocabulary(
                    " ".join(t for t in pages if not is_letter_spaced(t))
                )
            }
        return self._vocab_cache[pdf_path]

    def _normalize_text(self, text: str) -> str:
        """
        Normalize extracted text: ligatures, hyphenation, whitespace, artifacts.

        Args:
            text: Raw text extracted from PDF.

        Returns:
            Cleaned and normalized text.
        """

        if not text:
            return ""

        # Step 1: Ligature replacement
        ligature_map = {
            "ﬀ": "ff",
            "ﬁ": "fi",
            "ﬂ": "fl",
            "ﬃ": "ffi",
            "ﬄ": "ffl",
            "Ɵ": "ti",  # Common OCR artifact
            "ﬆ": "st",
            "œ": "oe",
            "æ": "ae",
            "Œ": "OE",
            "Æ": "AE",
        }

        for ligature, replacement in ligature_map.items():
            text = text.replace(ligature, replacement)

        # Step 2: Unicode normalization for special characters
        special_chars = {
            "\u200b": "",  # Zero-width space
            "\u00ad": "",  # Soft hyphen
            "\ufeff": "",  # BOM
            "\u00a0": " ",  # Non-breaking space
            "–": "-",  # En dash
            "—": "-",  # Em dash
            "\u201c": '"',  # Left double quote
            "\u201d": '"',  # Right double quote
            "\u2018": "'",  # Left single quote
            "\u2019": "'",  # Right single quote
            "…": "...",  # Ellipsis
            "′": "'",  # Prime
            "″": '"',  # Double prime
        }

        for char, replacement in special_chars.items():
            text = text.replace(char, replacement)

        # Rupee sign drawn with the backtick glyph ("` 23.89 crore")
        text = repair_rupee_backtick(text)

        # Step 3: Rejoin hyphenated words at line breaks. A hyphen before a digit or a
        # capital is real ("2018-\n19", "Inter-\nState"); after a space it is a dash.
        text = re.sub(r"(?<=\S)-[ \t]*\n\s*(?=[\dA-Z])", "-", text)
        text = re.sub(r"(?<=\s)-[ \t]*\n\s*", "- ", text)
        text = re.sub(r"-[ \t]*\n\s*", "", text)  # Soft hyphenation: join the word

        # Step 4: Normalize whitespace
        text = re.sub(r"\s+", " ", text)

        # Step 5: Clean up common OCR artifacts
        text = re.sub(r"\s+([.,;:!?])", r"\1", text)  # Remove space before punctuation

        return text.strip()

    def _classify_content_type(self, layout_label: str, text: str) -> str:
        """
        Map DocLayNet layout labels to internal content type classifications.

        Args:
            layout_label: Original DocLayNet label from LayoutAnalysisService.
            text: The normalized text content.

        Returns:
            Internal content type: 'paragraph', 'header', or 'list'.
        """
        # Direct mappings based on label
        if "header" in layout_label.lower() or "title" in layout_label.lower():
            return "header"

        if "list" in layout_label.lower() or "list-item" in layout_label.lower():
            return "list"

        if "footnote" in layout_label.lower():
            return "paragraph"  # Footnotes treated as regular paragraphs

        # Default for all other text elements
        return "paragraph"

    def _get_page_rotation(self, page) -> int:
        """
        P1-11: Get effective page rotation (0, 90, 180, 270).

        Args:
            page: PyMuPDF page object.

        Returns:
            Rotation angle normalized to 0, 90, 180, or 270.
        """
        return page.rotation % 360

    def _extract_text_with_rotation_handling(
        self, page, clip_rect: fitz.Rect, sort: bool = True
    ) -> str:
        """
        Extract text from a clip region, handling rotated pages.

        Docling reports boxes in the displayed (rotated) page space, while PyMuPDF
        clips in unrotated space. Mapping the clip through the derotation matrix
        gives correct text and reading order for 90/180/270 pages; the previous
        span-reversal approach cut words at column edges ("ple Sig cur inte").

        Args:
            page: PyMuPDF page object.
            clip_rect: Clipping rectangle in displayed page coordinates.
            sort: Whether to sort text by position.

        Returns:
            Extracted text.
        """
        if self._get_page_rotation(page):
            clip_rect = fitz.Rect(clip_rect) * page.derotation_matrix
        else:
            # Landscape annexures typeset sideways on a /Rotate 0 page
            sideways = self._extract_sideways_text(page, clip_rect)
            if sideways is not None:
                return sideways
        text = self._visible_text(page, clip_rect)
        if text is None:
            text = page.get_text("text", clip=clip_rect, sort=sort)
        return self._apply_span_fixes(page, clip_rect, text)

    def _hidden(self, page) -> Tuple[Dict[str, list], list, set, list]:
        """
        Per page: covered glyphs by character, the origins of all hidden glyphs, the
        shifted fonts and the boxes of their spans.
        """
        key = (page.parent.name, page.number)
        if key not in self._hidden_cache:
            covered = covered_glyphs(page)
            points = [o for origins in covered.values() for o in origins]
            fonts, coded = set(), []
            try:
                layout = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT).extractRAWDICT()
                fonts = shifted_fonts(layout)
                for block in layout["blocks"]:
                    for line in block.get("lines", []):
                        for span in line["spans"]:
                            if span["size"] < MIN_VISIBLE_SIZE and any(
                                not c["c"].isspace() for c in span["chars"]
                            ):
                                points.append(tuple(span["origin"]))
                            if is_shifted_span(span, fonts):
                                coded.append(fitz.Rect(span["bbox"]))
            except Exception:
                pass
            # One page at a time: blocks arrive page by page
            self._hidden_cache = {key: (covered, points, fonts, coded)}
        return self._hidden_cache[key]

    def _visible_text(self, page, clip_rect: fitz.Rect) -> Optional[str]:
        """
        The clip's text without hidden glyphs and with shifted fonts decoded; None
        when the clip has neither (the plain extraction is then used).
        """
        try:
            covered, points, fonts, coded = self._hidden(page)
        except Exception:
            return None
        area = fitz.Rect(clip_rect) + (-2, -2, 2, 2)
        hidden = any(area.contains(fitz.Point(p)) for p in points)
        shifted = any(area.intersects(rect) for rect in coded)
        if not (hidden or shifted):
            return None
        try:
            textpage = page.get_textpage(clip=clip_rect, flags=fitz.TEXTFLAGS_TEXT)
            if shifted:
                return sorted_text(coded_words(textpage, fonts))
            words = visible_words(textpage, covered)
        except Exception:
            return None
        return None if words is None else sorted_text(words)

    def _extract_sideways_text(self, page, clip_rect: fitz.Rect) -> Optional[str]:
        """
        Text in reading order when most of the clip is drawn vertically or upside
        down, else None.

        Sorting top-to-bottom reversed the word order of lines that read
        bottom-to-top ("2022 March ended year the for"). Words are grouped into
        lines by their x position and read along the line's direction.
        """
        try:
            textpage = page.get_textpage(clip=clip_rect, flags=fitz.TEXTFLAGS_TEXT)
            layout = textpage.extractDICT()
        except Exception:
            return None
        if not isinstance(layout, dict):
            return None
        counts = {"up": 0, "down": 0, "flipped": 0, "other": 0}
        flipped = []
        for block in layout.get("blocks", []):
            for line in block.get("lines", []):
                dx, dy = line["dir"]
                n = sum(len(span["text"].strip()) for span in line["spans"])
                if abs(dx) < 0.2 and dy < -0.8:
                    counts["up"] += n
                elif abs(dx) < 0.2 and dy > 0.8:
                    counts["down"] += n
                elif dx < -0.8:
                    counts["flipped"] += n
                    flipped.extend(span["text"] for span in line["spans"])
                else:
                    counts["other"] += n
        total = sum(counts.values())
        direction = max(("up", "down", "flipped"), key=counts.get)
        if not total or counts[direction] <= 0.5 * total:
            return None
        if direction == "flipped":
            # Upside-down text on an upright page: an OCR layer read from a scan lying
            # upside down (RJ chapter dividers: "A1-.1aJdBq3" for "Chapter-IV") is
            # noise; upside-down text that reads as words is read along its lines
            vocab = self._vocabulary(page.parent.name) if page.parent.name else {}
            if is_garbled(" ".join(flipped), vocab):
                return ""

        words = textpage.extractWORDS()
        # Only the rupee repair: superscript tests assume horizontal baselines
        fixes = word_fixes(textpage.extractRAWDICT(), [w for w in words if "`" in w[4]])
        words = [(*w[:4], fixes.get(w[4], w[4]), *w[5:]) for w in words]
        if direction == "up":
            # Bottom-to-top lines: the first line is leftmost, words run upwards
            words.sort(key=lambda w: w[0])
            line_x, along = (lambda w: w[0]), (lambda w: -w[3])
        elif direction == "flipped":
            # Right-to-left lines: the first line is lowest, words run leftwards
            words.sort(key=lambda w: -w[3])
            line_x, along = (lambda w: w[3]), (lambda w: -w[2])
        else:
            # Top-to-bottom lines: the first line is rightmost, words run downwards
            words.sort(key=lambda w: -w[2])
            line_x, along = (lambda w: w[2]), (lambda w: w[1])
        lines: List[list] = []
        for w in words:
            if lines and abs(line_x(w) - line_x(lines[-1][0])) <= 3:
                lines[-1].append(w)
            else:
                lines.append([w])
        return "\n".join(
            " ".join(w[4] for w in sorted(line, key=along)) for line in lines
        )

    def _apply_span_fixes(self, page, clip_rect: fitz.Rect, text: str) -> str:
        """
        Repair words using what the plain text loses: span flags, sizes and fonts.

        A superscript number after text becomes a footnote marker ("crore36" ->
        "crore[^36]"); a backtick in a Rupee font becomes "₹". Only the changed words
        are replaced, so text without either comes out exactly as before.
        """
        if not text or not text.strip():
            return text
        try:
            textpage = page.get_textpage(clip=clip_rect, flags=fitz.TEXTFLAGS_TEXT)
            raw = textpage.extractRAWDICT()
            words = textpage.extractWORDS()
        except Exception:
            return text
        if not isinstance(raw, dict) or not isinstance(words, list):
            return text
        fixes = word_fixes(raw, words)
        if not fixes:
            return text
        return re.sub(r"\S+", lambda m: fixes.get(m.group(0), m.group(0)), text)

    def _detect_reversed_content(self, text: str) -> bool:
        """D9-FIX: Detect word-reversed text (see text_repair.is_reversed)."""
        return is_reversed(text)

    def _reverse_text_content(self, text: str) -> str:
        """C2 fix: Reverse each word back, preserving lines and punctuation."""
        return reverse_words(text)

    def _extract_text_from_bbox(
        self, pdf_path: str, page_num: int, bbox: List[float]
    ) -> tuple:
        """
        Extract text precisely from within a bounding box using PyMuPDF's clip parameter.

        Args:
            pdf_path: Path to the PDF document.
            page_num: Zero-indexed page number.
            bbox: [x0, y0, x1, y1] coordinates in PDF space.

        Returns:
            Tuple of (extracted_text, rotation_angle).

        Raises:
            ValueError: If PDF access fails or bounding box is invalid.
        """
        if len(bbox) != 4:
            raise ValueError(
                f"Bounding box must have 4 coordinates, got {len(bbox)}: {bbox}"
            )

        doc = fitz.open(pdf_path)

        try:
            page = doc.load_page(page_num)

            # Create clipping rectangle from bounding box
            clip_rect = fitz.Rect(bbox)

            # P1-11: Get page rotation
            rotation = self._get_page_rotation(page)

            # P1-11: Use rotation-aware text extraction
            text = self._extract_text_with_rotation_handling(page, clip_rect, sort=True)

            return text, rotation

        except Exception as e:
            doc.close()
            raise ValueError(f"Failed to extract text from PDF: {str(e)}") from e
        finally:
            doc.close()

    def extract(
        self, pdf_path: str, page_num: int, bbox: List[float], **kwargs
    ) -> Optional[ExtractedContent]:
        """Main extraction method for textual content."""
        try:
            # Extract raw text from bounding box (P1-11: returns tuple with rotation)
            raw_text, rotation = self._extract_text_from_bbox(pdf_path, page_num, bbox)

            # Shifted-font digits and punctuation sit below U+0020 and would be lost
            # as whitespace: decode them first
            raw_text = CONTROL_CHAR_RE.sub(" ", repair_shifted_block(raw_text))

            # Normalize text (hyphenation, whitespace)
            normalized_text = self._normalize_text(raw_text)

            # Decode lines set in fonts whose glyphs are shifted 29 code points low
            normalized_text = repair_font_shift(normalized_text)

            # P2-17: Apply OCR header normalization (fixes Roman numeral corruptions)
            normalized_text = get_ocr_normalizer().normalize_headers(normalized_text)

            # C2 + M3 fix: Detect and recover reversed text content
            # This handles cases where:
            # 1. Page has reversed characters without rotation metadata (rotation == 0)
            # 2. Rotation handling didn't fully fix the text (rotated pages)
            # Apply detection as a final fallback for all pages
            content_was_reversed = False
            if self._detect_reversed_content(normalized_text):
                logger.debug(
                    f"C2/M3: Detected reversed content on page {page_num} (rotation={rotation}), applying correction"
                )
                normalized_text = self._reverse_text_content(normalized_text)
                content_was_reversed = True

            # Rejoin text whose PDF text layer has spaces between letters
            if is_letter_spaced(normalized_text):
                normalized_text = respace_letter_spaced(
                    normalized_text, self._vocabulary(pdf_path)
                )

            # Skip if no meaningful text was extracted
            if not normalized_text or normalized_text.isspace():
                return None

            # Classify content type based on layout label
            layout_label = kwargs.get("label", "Text")
            content_type = self._classify_content_type(layout_label, normalized_text)

            # P1-11: Log rotation for debugging if non-zero
            if rotation != 0:
                logger.debug(
                    f"P1-11: Extracted text from rotated page {page_num} (rotation={rotation})"
                )

            # Create ExtractedContent object
            # P1-11: Include rotation in structured_data if non-zero
            # C2: Include content_reversed flag if text was reversed
            # Footnote markers the text refers to, for linking to the footnotes
            markers = list(dict.fromkeys(FOOTNOTE_MARKER_RE.findall(normalized_text)))
            structured_data = None
            if rotation != 0 or content_was_reversed or markers:
                structured_data = {}
                if rotation != 0:
                    structured_data["page_rotation"] = rotation
                if content_was_reversed:
                    structured_data["content_reversed"] = True
                if markers:
                    structured_data["footnote_markers"] = markers

            return ExtractedContent(
                content_type=content_type,
                content=normalized_text,
                source_page_physical=page_num,
                source_bbox=bbox,
                model_used="PyMuPDF-clip",
                layout_label=layout_label,
                layout_confidence=kwargs.get("confidence"),
                structured_data=structured_data,
                # C3 fix: Add extraction_method for provenance tracking
                extraction_method="pymupdf-text",
            )

        except Exception as e:
            logger.error(f"Text extraction failed on page {page_num}: {e}")
            import traceback

            traceback.print_exc()
            return None
