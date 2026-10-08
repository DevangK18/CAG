"""
The tree Phase 10a summarises bottom-up.

Every parent chunk with real text is a node, whatever its depth; its place in the
tree comes from its hierarchy path (level_1 > level_2 > ...). A chapter or section
that has no parent chunk of its own becomes a node without text, so its children
still roll up into it. Then:

- a node is summarised from its own text plus its children's summaries;
- a node whose own text is short is folded into its parent's text instead of
  getting a call of its own (its text is still behind a summary);
- a node whose text is too long for one call is split, at chunk boundaries, into
  parts that are summarised first;
- a node with no own text and a single summarised child takes that child's
  summary (no call);
- duplicate, heading-only and garbage parents are not sent.

coverage() measures how much of the report's text is behind some summary.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

TEXT_TYPES = ("paragraph", "list", "table_markdown")
# Own text below this is folded into the parent's text
MIN_OWN_CHARS = 300
# Own text above this is split into parts
MAX_PART_CHARS = 24000

_ALPHA = re.compile(r"[A-Za-z]")
_SPACE = re.compile(r"\s+")


@dataclass
class Node:
    node_id: str
    title: str
    depth: int  # 1 = chapter
    path: Tuple[str, ...]
    parent_chunk_id: Optional[
        str
    ]  # None for a node with no parent chunk, and for parts
    own_text: str = ""
    folded_text: str = ""  # short children's text folded in
    parent: Optional[str] = None
    children: List[str] = field(default_factory=list)
    skip: Optional[str] = None  # duplicate, heading_only, garbage, folded
    part_of: Optional[str] = None
    pages: Tuple[int, int] = (0, 0)

    @property
    def text(self) -> str:
        return "\n\n".join(t for t in (self.own_text, self.folded_text) if t)


@dataclass
class SummaryTree:
    report_id: str
    nodes: Dict[str, Node]
    roots: List[str]  # chapters, in reading order
    chunk_chars: int  # characters of TEXT_TYPES content in the report

    def summarised(self) -> List[Node]:
        """Nodes that get a summary (call or inherited), children before parents."""
        out: List[Node] = []

        def visit(node_id: str) -> None:
            node = self.nodes[node_id]
            for child in node.children:
                visit(child)
            if node.skip is None and self.has_input(node):
                out.append(node)

        for root in self.roots:
            visit(root)
        return out

    def has_input(self, node: Node) -> bool:
        return bool(node.text) or any(self._kept(c) for c in node.children)

    def _kept(self, node_id: str) -> bool:
        node = self.nodes[node_id]
        return node.skip is None and self.has_input(node)

    def summarised_children(self, node: Node) -> List[Node]:
        return [self.nodes[c] for c in node.children if self._kept(c)]

    def needs_call(self, node: Node) -> bool:
        """False when the node can take its single child's summary as its own."""
        return bool(node.text) or len(self.summarised_children(node)) != 1


def _hierarchy_path(chunk: dict) -> Tuple[str, ...]:
    hierarchy = chunk.get("hierarchy") or {}
    levels = sorted(
        (int(k.split("_")[1]), v)
        for k, v in hierarchy.items()
        if k.startswith("level_") and v
    )
    return tuple(str(v).strip() for _, v in levels)


def _chars(text: str) -> int:
    """Characters that are not whitespace (joins and separators do not count)."""
    return len(_SPACE.sub("", text or ""))


def _is_garbage(title: str, text: str) -> bool:
    """A garbage title over little text, or prose (tables aside, which are numbers) with few letters."""
    from src.parsing_pipeline.modules.toc_quality import is_garbage_title

    if title and is_garbage_title(title) and len(text) < MIN_OWN_CHARS:
        return True
    prose = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("|")
    )
    prose = _SPACE.sub("", prose)
    return len(prose) >= 50 and len(_ALPHA.findall(prose)) / len(prose) < 0.3


def build_tree(
    data: dict, max_part_chars: int = MAX_PART_CHARS, min_own_chars: int = MIN_OWN_CHARS
) -> SummaryTree:
    report_id = data.get("report_metadata", {}).get("report_id", "")
    parents = data.get("parent_chunks") or []
    children = data.get("child_chunks") or []

    texts: Dict[str, List[str]] = {}
    pieces: Dict[str, List[str]] = {}
    chunk_chars = 0
    for c in children:
        if c.get("content_type") not in TEXT_TYPES:
            continue
        content = (c.get("content") or "").strip()
        if not content:
            continue
        chunk_chars += _chars(content)
        pid = c.get("parent_chunk_id")
        if pid:
            pieces.setdefault(pid, []).append(content)
    for pid, parts in pieces.items():
        texts[pid] = parts

    nodes: Dict[str, Node] = {}
    by_path: Dict[Tuple[str, ...], str] = {}
    roots: List[str] = []
    seen_text: Dict[str, str] = {}

    def ensure(path: Tuple[str, ...]) -> str:
        """The node for a path, creating text-less ancestors as needed."""
        if path in by_path:
            return by_path[path]
        node_id = (
            f"{report_id}::path::"
            + hashlib.sha1(" > ".join(path).encode()).hexdigest()[:12]
        )
        node = Node(
            node_id=node_id,
            title=path[-1],
            depth=len(path),
            path=path,
            parent_chunk_id=None,
        )
        nodes[node_id] = node
        by_path[path] = node_id
        attach(node)
        return node_id

    def attach(node: Node) -> None:
        if node.depth == 1:
            roots.append(node.node_id)
            return
        parent_id = ensure(node.path[:-1])
        node.parent = parent_id
        nodes[parent_id].children.append(node.node_id)

    for p in parents:
        pid = p.get("chunk_id")
        path = _hierarchy_path(p)
        if not pid or not path:
            continue
        own = "\n\n".join(texts.get(pid, []))
        pages = tuple((p.get("page_range_physical") or [0, 0])[:2]) or (0, 0)
        title = p.get("toc_entry") or path[-1]
        if path in by_path and nodes[by_path[path]].parent_chunk_id is None:
            # A text-less placeholder made for this path: the parent chunk takes its place
            node = nodes[by_path[path]]
            node.parent_chunk_id = pid
            node.own_text = own
            node.title = title
            node.pages = pages if len(pages) == 2 else (pages[0], pages[0])
        else:
            node = Node(
                node_id=pid,
                title=title,
                depth=len(path),
                path=path,
                parent_chunk_id=pid,
                own_text=own,
                pages=pages if len(pages) == 2 else (pages[0], pages[0]),
            )
            nodes[pid] = node
            if path not in by_path:
                by_path[path] = pid
            attach(node)
        digest = (
            hashlib.sha1(re.sub(r"\s+", " ", own).strip().lower().encode()).hexdigest()
            if own
            else None
        )
        if digest and digest in seen_text:
            node.skip = "duplicate"
        elif digest:
            seen_text[digest] = node.node_id
        if node.skip is None and own and _is_garbage(title, own):
            node.skip = "garbage"

    tree = SummaryTree(
        report_id=report_id, nodes=nodes, roots=roots, chunk_chars=chunk_chars
    )

    # Fold short leaves into their parent's text; heading-only leaves are skipped
    def fold(node_id: str) -> None:
        node = nodes[node_id]
        for child in list(node.children):
            fold(child)
        if node.skip or node.depth == 1 or node.parent is None:
            return
        kept_children = tree.summarised_children(node)
        if not node.own_text.strip() and not kept_children and not node.folded_text:
            node.skip = "heading_only"
        elif len(node.text) < min_own_chars and not kept_children:
            parent = nodes[node.parent]
            parent.folded_text = "\n\n".join(
                t for t in (parent.folded_text, node.text) if t
            )
            node.skip = "folded"

    for root in roots:
        fold(root)

    # Split long text into parts, summarised before the node itself
    for node in list(nodes.values()):
        if node.skip or len(node.text) <= max_part_chars:
            continue
        paragraphs = node.text.split("\n\n")
        parts, current = [], ""
        for para in paragraphs:
            if current and len(current) + len(para) > max_part_chars:
                parts.append(current)
                current = ""
            current = f"{current}\n\n{para}" if current else para
        if current:
            parts.append(current)
        node.own_text, node.folded_text = "", ""
        for i, part in enumerate(parts, 1):
            part_id = f"{node.node_id}#part{i}"
            nodes[part_id] = Node(
                node_id=part_id,
                title=f"{node.title} (part {i} of {len(parts)})",
                depth=node.depth + 1,
                path=node.path + (f"part {i}",),
                parent_chunk_id=None,
                own_text=part,
                parent=node.node_id,
                part_of=node.node_id,
                pages=node.pages,
            )
            node.children.insert(i - 1, part_id)
    return tree


def coverage(tree: SummaryTree) -> Dict[str, object]:
    """
    Share of the report's text that is input to some summary, per chapter and overall.

    Each piece of text sits in exactly one node (folded text in the node it was folded
    into, a split node's text in its parts); it is behind a summary when that node
    gets one.
    """
    behind: Dict[str, int] = {}
    total: Dict[str, int] = {}
    summarised = {n.node_id for n in tree.summarised()}

    def chapter_of(node: Node) -> str:
        while node.parent is not None:
            node = tree.nodes[node.parent]
        return node.node_id

    for node in tree.nodes.values():
        if node.skip == "folded":
            continue
        chars = _chars(node.own_text) + _chars(node.folded_text)
        chapter = chapter_of(node)
        total[chapter] = total.get(chapter, 0) + chars
        if node.node_id in summarised:
            behind[chapter] = behind.get(chapter, 0) + chars

    shares = {
        tree.nodes[c].title: round(behind.get(c, 0) / total[c], 3)
        for c in total
        if total[c] > 0
    }
    ordered = sorted(shares.values())
    return {
        "chapter_share": shares,
        "median_chapter_share": ordered[len(ordered) // 2] if ordered else None,
        "text_behind_no_summary": round(1 - sum(behind.values()) / tree.chunk_chars, 3)
        if tree.chunk_chars
        else None,
        "summaries": len(summarised),
        "calls": sum(1 for n in tree.summarised() if tree.needs_call(n)),
    }
