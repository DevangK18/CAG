"""PART-A/B banners next to a chapter, and long chapter titles (contents)."""

from src.parsing_pipeline.modules.printed_toc_parser import fold_part_rows
from src.parsing_pipeline.modules.toc_quality import is_garbage_title


def test_part_rows_beside_a_chapter_are_folded():
    toc = [[1, "Overview", 9], [1, "PART-A PANCHAYATI RAJ INSTITUTIONS", 13],
           [1, "CHAPTER-1 PROFILE OF PRIs", 13], [2, "1.1 Background", 13],
           [1, "PART-B URBAN LOCAL BODIES", 35], [1, "CHAPTER-3 PROFILE OF ULBs", 35]]
    assert [e[1] for e in fold_part_rows(toc)] == [
        "Overview", "CHAPTER-1 PROFILE OF PRIs", "1.1 Background", "CHAPTER-3 PROFILE OF ULBs"]


def test_part_row_without_a_chapter_is_kept():
    toc = [[1, "PART-A Introduction", 3], [2, "A.1 Scope", 3]]
    assert fold_part_rows(toc) == toc


def test_long_chapter_title_is_a_heading():
    title = ("CHAPTER I An Overview of the Functioning, Accountability Mechanism and Financial "
             "Reporting Issues of Panchayati Raj Institutions")
    assert not is_garbage_title(title)
