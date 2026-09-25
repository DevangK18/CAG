"""
Text repair for PDF extraction artifacts found in CAG reports.

1. Reversed text: some pages/tables come out with every word's characters reversed
   ("tnemtrapeD fo eunever"). Detected by whole-word scoring against reversed and
   forward vocabularies; substring matching flagged "tonne" and "profit" as reversed.

2. Font-shifted text: some embedded fonts map glyphs 29 code points below their
   Unicode value ("5HSRUW RI WKH &RPSWUROOHU" = "Report of the Comptroller").
   Repaired by adding 29 back, applied per line only when the result reads as English.
"""

import re
from typing import List

# Reversed forms of frequent English/CAG words; rare or non-existent forwards.
# Don't add words that are valid both ways (saw/was, ton/not, no/on).
REVERSED_WORDS = {
    "eht", "dna", "rof", "htiw", "morf", "evah", "siht", "taht", "erew", "neeb",
    "elbaliava", "tegdub", "tnemucod", "troper", "tidua", "hkal", "erorc",
    "tnemnrevog", "tnemtraped", "yrtsinim", "detroper", "devresbo", "dehsilbup",
    "stneduts", "loohcs", "noitacude", "srehcaet", "gniniart", "seiticapac",
    "margorp", "semmargorp", "tcirtsid", "gnidneps", "deviecer", "detubirtsid",
    "noitatnemelp", "tnemeganam", "erutidnepxe", "secruoser", "seitivitca",
    "stifeneb", "serudecorp", "stnuocca", "ecnanif", "sdnuf", "tneiciffe",
    "fo", "ot", "ni", "si", "yb", "hcihw", "gnirud", "rednu", "osla", "latot",
}

# Forward forms plus common stopwords: real English is full of these, so they veto
# reversal even when a reversed pattern happens to match.
FORWARD_WORDS = {w[::-1] for w in REVERSED_WORDS} | {
    "of", "to", "in", "is", "was", "by", "on", "as", "at", "an", "be",
    "which", "are", "not", "per", "total", "during", "under", "also",
}

_WORD_RE = re.compile(r"[A-Za-z]+")


def is_reversed(text: str) -> bool:
    """True if the text reads as word-reversed English."""
    if not text or len(text) < 20:
        return False

    tokens = [t.lower() for t in _WORD_RE.findall(text)]
    if not tokens:
        return False

    reversed_hits = sum(1 for t in tokens if t in REVERSED_WORDS)
    forward_hits = sum(1 for t in tokens if t in FORWARD_WORDS)

    if reversed_hits >= 2 and reversed_hits > forward_hits:
        return True
    if reversed_hits == 1 and forward_hits == 0 and len(text) >= 30:
        return True

    # Reversed proper nouns: "gnarabaN" (Nabarang) has a lowercase->uppercase transition
    words = text.split()
    reversed_caps = re.findall(r"[a-z][A-Z]", text)
    return len(words) > 3 and len(reversed_caps) / len(words) > 0.3 and forward_hits * 5 < len(tokens)


def reverse_words(text: str) -> str:
    """Reverse each word's characters, keeping line breaks, word order and edge punctuation."""
    lines = []
    for line in text.split("\n"):
        words = []
        for word in line.split():
            leading = trailing = ""
            while word and not word[0].isalnum():
                leading += word[0]
                word = word[1:]
            while word and not word[-1].isalnum():
                trailing = word[-1] + trailing
                word = word[:-1]
            words.append(leading + word[::-1] + trailing)
        lines.append(" ".join(words))
    return "\n".join(lines)


# ==================== FONT SHIFT ====================

FONT_SHIFT = 29

# Words that identify English once a shifted line is decoded
_KNOWN_WORDS = {
    "the", "and", "of", "to", "in", "for", "with", "was", "were", "on", "by", "is",
    "from", "that", "have", "been", "as", "at", "an", "be", "which", "are", "not",
    "report", "chapter", "audit", "auditor", "comptroller", "general", "india",
    "government", "ministry", "national", "authority", "project", "projects",
    "annexure", "table", "figure", "chart", "para", "paragraph", "crore", "lakh",
    "deputy", "principal", "director", "dated", "new", "delhi", "countersigned",
}
_SHIFT_SIGNATURE = re.compile(r"[$&%#()*+,\-./0-9:;<=>?@\[\\\]]")


def _shift_char(c: str) -> str:
    code = ord(c)
    if c.isspace() or not (3 <= code <= 93):
        return c
    return chr(code + FONT_SHIFT)


def unshift(text: str) -> str:
    """Decode text from a font whose glyphs are mapped 29 code points low."""
    return "".join(_shift_char(c) for c in text)


def _known_count(text: str) -> int:
    return sum(1 for t in re.findall(r"[a-z]+", text.lower()) if t in _KNOWN_WORDS)


def _is_shifted_line(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    if len(line.strip()) < 3 or not letters:
        return False
    # Shifted lines have almost no lowercase: 'a'-'z' decode from 'D'-']'
    if sum(c.islower() for c in letters) > 0.2 * len(letters):
        return False
    decoded = unshift(line)
    before, after = _known_count(line), _known_count(decoded)
    # Decoded line must read as words, not symbol soup from a table row or code list
    decoded_words = re.findall(r"[a-z]{2,}", decoded.lower())
    if not decoded_words or after / len(decoded_words) < 0.2:
        return False
    # Digits decode to letters ("21" -> "ON"), so require a longer known word too
    if not any(len(w) >= 3 and w in _KNOWN_WORDS for w in decoded_words):
        return False
    if after >= 2 and after > 2 * before:
        return True
    # Short headings: "&KDSWHU $ZDUGRI3URMHFWV" -> "Chapter AwardofProjects"
    return after >= 1 and before == 0 and len(_SHIFT_SIGNATURE.findall(line)) >= 1


def repair_font_shift(text: str) -> str:
    """Decode any font-shifted lines in the text; other lines are returned unchanged."""
    if not text:
        return text
    lines = text.split("\n")
    changed = False
    for i, line in enumerate(lines):
        if _is_shifted_line(line):
            lines[i] = unshift(line)
            changed = True
    return "\n".join(lines) if changed else text


def repair_cells(cells: List[str]) -> List[str]:
    """Apply font-shift repair to each cell (cells come from one table row)."""
    return [repair_font_shift(c) for c in cells]


_CID_RE = re.compile(r"\(cid:(\d+)\)")


def decode_cid_shift(text: str) -> str:
    """
    pdfplumber cannot map glyphs of the same shifted fonts and emits "(cid:54)(cid:17)";
    the glyph id is the character code minus 29 ("(cid:54)" = "S").
    """
    return _CID_RE.sub(lambda m: chr(int(m.group(1)) + FONT_SHIFT), text)


def has_cid_shift(text: str) -> bool:
    """True if the text is mostly shifted-font glyph ids that decode to English."""
    return len(_CID_RE.findall(text)) >= 3 and _known_count(decode_cid_shift(text)) >= 1


# ==================== LETTER-SPACED TEXT ====================

import math
from collections import Counter

_TOKEN_RE = re.compile(r"[A-Za-z]+|[^A-Za-z\s]+")


_SHORT_WORDS = {
    "a", "i", "an", "as", "at", "be", "by", "do", "if", "in", "is", "it", "no", "of",
    "on", "or", "so", "to", "up", "us", "we",
}


def is_letter_spaced(text: str) -> bool:
    """True if most words are split into 1-2 letter pieces ("M o nit ori n g a n d")."""
    tokens = re.findall(r"[A-Za-z]+", text)
    if len(tokens) < 5:
        return False
    # Prose, not codes/units ("e4170dae-05b8-...", "Km 83.200", "3.45 Cu.m /MWh")
    visible = [c for c in text if not c.isspace()]
    if sum(c.isalpha() for c in visible) < 0.7 * len(visible):
        return False
    # Fragments, not real short words or upper-case abbreviations ("of", "EC", "a)")
    fragments = [t for t in tokens if len(t) <= 2 and t.lower() not in _SHORT_WORDS and not t.isupper()]
    return len(fragments) / len(tokens) > 0.35


def build_vocabulary(text: str) -> Counter:
    """Word frequencies from normally spaced text (a report's other pages)."""
    return Counter(w.lower() for w in re.findall(r"[A-Za-z]+", text))


def _segment(pieces: List[str], vocab: Counter, total: int) -> List[str]:
    """
    Join letter pieces into words. Real word breaks are always at one of the existing
    spaces, so only joins of whole pieces are considered (unigram DP over pieces).
    """
    n = len(pieces)
    best = [0.0] + [-math.inf] * n
    back = [0] * (n + 1)
    for end in range(1, n + 1):
        for start in range(max(0, end - 12), end):
            word = "".join(pieces[start:end]).lower()
            count = vocab.get(word, 0)
            # Unknown words cost per letter only: a flat penalty made one long unknown
            # word ("pastandongoing") cheaper than several ("past and ongoing")
            cost = math.log(count / total) if count else -3.0 * len(word)
            if best[start] + cost > best[end]:
                best[end], back[end] = best[start] + cost, start
    words, end = [], n
    while end > 0:
        words.append("".join(pieces[back[end]:end]))
        end = back[end]
    return words[::-1]


def respace_letter_spaced(text: str, vocab: Counter) -> str:
    """
    Rejoin text whose PDF text layer has spaces between letters. Spaces carry no word
    information there, so letter runs are re-split using the report's own vocabulary.
    """
    if not vocab or not is_letter_spaced(text):
        return text
    total = sum(vocab.values())
    lines = []
    for line in text.split("\n"):
        pieces, run = [], []
        for token in line.split():
            # Letters stay as joinable pieces; punctuation/digits end a run
            for part in _TOKEN_RE.findall(token):
                if part[0].isalpha():
                    run.append(part)
                else:
                    if run:
                        pieces.extend(_segment(run, vocab, total))
                        run = []
                    pieces.append(part)
        if run:
            pieces.extend(_segment(run, vocab, total))
        # Attach punctuation to the preceding word; rejoin split numbers ("2 0 2 2", "7. 1")
        joined = " ".join(pieces)
        joined = re.sub(r"(?<=\d)[ ](?=\d)|(?<=\d\.)[ ](?=\d)", "", joined)
        lines.append(re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\(\s+", "(", joined)))
    return "\n".join(lines)
