"""Phase 7: reading-order anchor assignment, sorted ranges, parent metadata, cleanup."""

from src.core.data_contracts import DocumentTask, ExtractedContent
from src.parsing_pipeline.modules.chunking_service import ChunkingService


def _item(text, page, y, ctype="paragraph"):
    return ExtractedContent(
        content_type=ctype, content=text, source_page_physical=page,
        source_bbox=[72.0, float(y), 520.0, float(y) + 14], model_used="t",
        layout_label="Section-header" if ctype == "header" else "Text",
    )


def _task(toc, items, positions=None, meta=None):
    task = DocumentTask(
        report_id="R", source_url="", local_pdf_path="",
        initial_metadata={"Title": "T", "Report No": "1 of 2025", **(meta or {})},
    )
    task.scaffold = {"toc": toc, "page_map": {}, "heading_positions": positions or {}}
    task.extracted_content = items
    return task


def _by_title(parents, children):
    titles = {p.chunk_id: p.toc_entry for p in parents}
    return {c.content[:12]: titles[c.parent_chunk_id] for c in children}


def test_heading_anchor_beats_y_copied_from_another_page():
    # HP_2019: "1.4 Financial profile" got the y of "3.4 Financial profile" (p.36)
    toc = [[2, "1.3 Audit coverage", 14], [2, "1.4 Financial profile", 15]]
    positions = {"15_1.4 Financial profile": 476.0}
    items = [
        _item("1.3 Audit coverage", 14, 100, "header"),
        _item("Coverage body text on the first page.", 14, 140),
        _item("Coverage continued at the top of p15.", 15, 80),
        _item("1.4 Financial profile", 15, 200, "header"),
        _item("Financial body text below the heading.", 15, 240),
    ]
    parents, children = ChunkingService().chunk_document(_task(toc, items, positions))
    owner = _by_title(parents, children)
    assert owner["Coverage con"] == "1.3 Audit coverage"
    assert owner["Financial bo"] == "1.4 Financial profile"
    assert owner["1.4 Financia"] == "1.4 Financial profile"


def test_anchor_found_one_page_after_toc_page():
    # Pre-fix union reports: the ToC page is one page off the real heading
    toc = [[2, "2.1 Planning", 30], [2, "2.2 Execution", 33]]
    items = [
        _item("2.1 Planning", 31, 100, "header"),
        _item("Planning text.", 31, 130),
        _item("More planning on p33.", 33, 100),
        _item("2.2 Execution", 34, 90, "header"),
        _item("Execution text.", 34, 130),
    ]
    parents, children = ChunkingService().chunk_document(_task(toc, items))
    owner = _by_title(parents, children)
    assert owner["More plannin"] == "2.1 Planning"
    assert owner["Execution te"] == "2.2 Execution"


def test_unsorted_toc_ranges_and_children_ranges():
    toc = [[1, "Chapter 2 Results", 20], [1, "Chapter 1 Profile", 5], [2, "1.1 Background", 6]]
    items = [
        _item("Chapter 1 Profile", 5, 80, "header"), _item("Profile intro text.", 5, 120),
        _item("1.1 Background", 6, 80, "header"), _item("Background text.", 9, 100),
        _item("Chapter 2 Results", 20, 80, "header"), _item("Results text.", 22, 100),
    ]
    parents, children = ChunkingService().chunk_document(_task(toc, items))
    ranges = {p.toc_entry: tuple(p.page_range_physical) for p in parents}
    assert [p.toc_entry for p in parents] == ["Chapter 1 Profile", "1.1 Background", "Chapter 2 Results"]
    assert ranges["1.1 Background"] == (6, 9)
    assert ranges["Chapter 1 Profile"] == (5, 9)  # covers its sub-section
    assert ranges["Chapter 2 Results"] == (20, 22)
    for c in children:
        p = next(p for p in parents if p.chunk_id == c.parent_chunk_id)
        assert p.page_range_physical[0] <= c.source_page_physical <= p.page_range_physical[1]


def test_parents_carry_tier_metadata_and_null_logical_pages():
    meta = {"government_body_type": "state", "state_name": "Odisha", "department": "SME",
            "audit_category": "performance", "report_subtype": "PRI_ULB"}
    items = [_item("1.1 Scope", 3, 80, "header"), _item("Scope text.", 3, 120)]
    parents, children = ChunkingService().chunk_document(_task([[2, "1.1 Scope", 3]], items, meta=meta))
    p = parents[0]
    assert (p.audit_category, p.department, p.report_subtype, p.state_name) == (
        "performance", "SME", "PRI_ULB", "Odisha")
    assert p.page_range_logical == (None, None)  # no printed number known: None, never physical+1
    assert children[0].source_page_logical is None
    assert children[0].department == "SME"


def test_empty_and_heading_only_leaves_are_removed():
    toc = [[1, "Chapter 1", 1], [2, "1.1 Empty", 2], [2, "Bold line", 3], [2, "1.2 Real", 3]]
    items = [
        _item("Chapter 1", 1, 80, "header"), _item("Chapter intro.", 1, 120),
        _item("Bold line", 3, 80, "header"),
        _item("1.2 Real", 3, 120, "header"), _item("Real text.", 3, 160),
    ]
    parents, children = ChunkingService().chunk_document(_task(toc, items))
    titles = [p.toc_entry for p in parents]
    assert titles == ["Chapter 1", "1.2 Real"]
    owner = _by_title(parents, children)
    assert owner["Bold line"] == "1.2 Real"


def test_front_matter_before_first_entry_gets_its_own_parent():
    toc = [[1, "Chapter 1 Profile", 5], [2, "1.1 Background", 6]]
    items = [
        _item("Report of the Comptroller and Auditor General", 0, 100),
        _item("Preface text on page two.", 1, 100),
        _item("Chapter 1 Profile", 5, 80, "header"), _item("Profile text.", 5, 120),
        _item("1.1 Background", 6, 80, "header"), _item("Background text.", 6, 120),
    ]
    parents, children = ChunkingService().chunk_document(_task(toc, items))
    owner = _by_title(parents, children)
    assert owner["Report of th"] == "Front matter" and owner["Preface text"] == "Front matter"
    front = next(p for p in parents if p.toc_entry == "Front matter")
    assert tuple(front.page_range_physical) == (0, 1)
    for c in children:
        p = next(p for p in parents if p.chunk_id == c.parent_chunk_id)
        assert p.page_range_physical[0] <= c.source_page_physical <= p.page_range_physical[1]
