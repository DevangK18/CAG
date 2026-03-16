"""
Intelligent TOC Service: Multi-layer TOC extraction and enrichment.

This service orchestrates multiple layers of TOC detection:
1. PDF Bookmarks (quick check with quality scoring)
2. TOC Table Parser (parse printed TOC from document content)
3. Section Header Detection (existing heuristic approach)
4. Hierarchy Enrichment (create deeper levels from numbered sections)

The goal is to produce a rich, multi-level TOC for any CAG report,
regardless of whether it has good PDF bookmarks or a printed TOC table.
"""

import re
import fitz  # PyMuPDF
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from pathlib import Path
import logging

from .toc_table_parser import TOCTableParser, TOCEntry
from .hierarchy_enricher import HierarchyEnricher

logger = logging.getLogger(__name__)


@dataclass
class TOCQualityMetrics:
    """Quality metrics for a TOC extraction."""
    source: str  # "bookmarks", "toc_table", "heuristic", "combined"
    entry_count: int
    level_count: int  # Number of unique levels
    has_chapters: bool
    has_sections: bool
    page_coverage: float  # % of document pages covered
    confidence: float  # 0-1
    
    def score(self) -> float:
        """Calculate overall quality score."""
        score = 0.0
        
        # Entry count (0-30 points)
        score += min(30, self.entry_count * 2)
        
        # Level depth (0-25 points)
        score += min(25, self.level_count * 8)
        
        # Has chapters (15 points)
        if self.has_chapters:
            score += 15
        
        # Has sections (15 points)
        if self.has_sections:
            score += 15
        
        # Page coverage (0-15 points)
        score += self.page_coverage * 15
        
        return min(100, score) * self.confidence


class IntelligentTOCService:
    """
    Multi-layer TOC extraction and enrichment service.
    
    Layers:
    1. PDF Bookmarks - Fast, use if quality > threshold
    2. TOC Table Parser - Parse printed TOC from pages 3-10
    3. Heuristic Detection - Font-based heading detection
    4. Hierarchy Enrichment - Add depth by detecting numbered sections
    """
    
    # Quality thresholds
    BOOKMARK_QUALITY_THRESHOLD = 0.6
    TOC_TABLE_CONFIDENCE_THRESHOLD = 0.5
    HEURISTIC_MIN_ENTRIES = 3
    
    # File-assembly bookmark patterns (low quality)
    ASSEMBLY_PATTERNS = [
        r"^\d{2}\s+\w+",  # "01 Cover", "05 Final_Report"
        r"^Part\s*\d+$",  # Just "Part 1"
        r"^Section\s*\d+$",  # Just "Section 1"
        r"^p\d+",  # "p001"
    ]
    
    # High-quality CAG patterns
    CAG_PATTERNS = [
        r"^Chapter\s+[IVX\d]+",
        r"^Annexure",
        r"^Executive\s+Summary",
        r"^Audit\s+(Objective|Finding|Scope)",
        r"^\d+\.\d+\s+[A-Z]",
    ]
    
    def __init__(
        self,
        bookmark_quality_threshold: float = 0.6,
        toc_table_confidence_threshold: float = 0.5,
        enable_enrichment: bool = True,
    ):
        """
        Initialize Intelligent TOC Service.
        
        Args:
            bookmark_quality_threshold: Min quality to use bookmarks
            toc_table_confidence_threshold: Min confidence for TOC table
            enable_enrichment: Whether to run hierarchy enrichment
        """
        self.bookmark_quality_threshold = bookmark_quality_threshold
        self.toc_table_confidence_threshold = toc_table_confidence_threshold
        self.enable_enrichment = enable_enrichment
        
        # Initialize sub-services
        self.toc_table_parser = TOCTableParser()
        self.hierarchy_enricher = HierarchyEnricher()
        
        # Compile patterns
        self._assembly_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.ASSEMBLY_PATTERNS
        ]
        self._cag_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.CAG_PATTERNS
        ]
    
    def extract_toc(
        self,
        pdf_path: str,
        child_chunks: Optional[List[Dict]] = None,
        report_id: str = "unknown",
    ) -> Tuple[List[List], TOCQualityMetrics]:
        """
        Extract best possible TOC using multi-layer approach.
        
        Args:
            pdf_path: Path to PDF file
            child_chunks: Extracted content chunks (for Layer 2)
            report_id: Report identifier
            
        Returns:
            Tuple of (TOC list, quality metrics)
        """
        logger.info(f"[{report_id}] Starting intelligent TOC extraction")
        
        doc = None
        try:
            doc = fitz.Document(pdf_path)
            total_pages = len(doc)
            
            # Layer 1: Try PDF bookmarks
            bookmark_toc, bookmark_metrics = self._extract_bookmarks(doc, total_pages, report_id)
            
            if bookmark_metrics.score() >= self.bookmark_quality_threshold * 100:
                logger.info(f"[{report_id}] Using PDF bookmarks (score: {bookmark_metrics.score():.1f})")
                return bookmark_toc, bookmark_metrics
            
            # Layer 2: Try TOC table parsing
            if child_chunks:
                table_toc, table_metrics = self._extract_toc_table(
                    child_chunks, total_pages, report_id
                )
                
                if table_metrics.score() > bookmark_metrics.score():
                    logger.info(f"[{report_id}] Using TOC table (score: {table_metrics.score():.1f})")
                    return table_toc, table_metrics
            
            # Layer 3: Use heuristic detection (existing approach)
            # This would call the existing _generate_heuristic_toc from scaffolding_service
            # For now, we fall back to bookmarks if they exist
            
            if bookmark_toc:
                logger.info(f"[{report_id}] Falling back to bookmarks (score: {bookmark_metrics.score():.1f})")
                return bookmark_toc, bookmark_metrics
            
            # No TOC found
            logger.warning(f"[{report_id}] No TOC extracted")
            return [], TOCQualityMetrics(
                source="none",
                entry_count=0,
                level_count=0,
                has_chapters=False,
                has_sections=False,
                page_coverage=0.0,
                confidence=0.0,
            )
            
        finally:
            if doc:
                doc.close()
    
    def enrich_hierarchy(
        self,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        report_id: str = "unknown",
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Enrich TOC hierarchy by detecting sub-sections.
        
        This is Layer 4 - run after initial TOC extraction and assembly.
        
        Args:
            parent_chunks: Existing parent chunks from assembly
            child_chunks: Child content chunks
            report_id: Report identifier
            
        Returns:
            Tuple of (enriched_parents, updated_children)
        """
        if not self.enable_enrichment:
            return parent_chunks, child_chunks
        
        return self.hierarchy_enricher.enrich_hierarchy(
            parent_chunks, child_chunks, report_id
        )
    
    def _extract_bookmarks(
        self,
        doc: fitz.Document,
        total_pages: int,
        report_id: str,
    ) -> Tuple[List[List], TOCQualityMetrics]:
        """
        Layer 1: Extract and score PDF bookmarks.
        """
        try:
            toc = doc.get_toc(simple=True)
        except Exception as e:
            logger.warning(f"[{report_id}] Failed to extract bookmarks: {e}")
            toc = []
        
        if not toc:
            return [], TOCQualityMetrics(
                source="bookmarks",
                entry_count=0,
                level_count=0,
                has_chapters=False,
                has_sections=False,
                page_coverage=0.0,
                confidence=0.0,
            )
        
        # Calculate quality metrics
        metrics = self._calculate_toc_metrics(toc, total_pages, "bookmarks")
        
        # Apply quality penalties
        confidence = 1.0
        
        # Penalty for file-assembly patterns
        assembly_count = sum(
            1 for entry in toc
            if any(p.match(entry[1]) for p in self._assembly_patterns)
        )
        if assembly_count > 0:
            confidence -= (assembly_count / len(toc)) * 0.5
        
        # Bonus for CAG-specific patterns
        cag_count = sum(
            1 for entry in toc
            if any(p.match(entry[1]) for p in self._cag_patterns)
        )
        if cag_count > 0:
            confidence += min(0.2, cag_count * 0.05)
        
        # Penalty for very few entries
        if len(toc) < 5:
            confidence -= 0.3
        
        metrics.confidence = max(0.1, min(1.0, confidence))
        
        return toc, metrics
    
    def _extract_toc_table(
        self,
        child_chunks: List[Dict],
        total_pages: int,
        report_id: str,
    ) -> Tuple[List[List], TOCQualityMetrics]:
        """
        Layer 2: Parse TOC from document content.
        """
        entries, confidence = self.toc_table_parser.parse_from_chunks(
            child_chunks, report_id
        )
        
        if not entries:
            return [], TOCQualityMetrics(
                source="toc_table",
                entry_count=0,
                level_count=0,
                has_chapters=False,
                has_sections=False,
                page_coverage=0.0,
                confidence=0.0,
            )
        
        # Convert to standard format
        toc = self.toc_table_parser.convert_to_toc_format(entries)
        
        # Calculate metrics
        metrics = self._calculate_toc_metrics(toc, total_pages, "toc_table")
        metrics.confidence = confidence
        
        return toc, metrics
    
    def _calculate_toc_metrics(
        self,
        toc: List[List],
        total_pages: int,
        source: str,
    ) -> TOCQualityMetrics:
        """Calculate quality metrics for a TOC."""
        if not toc:
            return TOCQualityMetrics(
                source=source,
                entry_count=0,
                level_count=0,
                has_chapters=False,
                has_sections=False,
                page_coverage=0.0,
                confidence=0.0,
            )
        
        # Count entries and levels
        levels = set(entry[0] for entry in toc)
        
        # Check for chapters
        has_chapters = any(
            "chapter" in entry[1].lower()
            for entry in toc
        )
        
        # Check for numbered sections
        has_sections = any(
            re.match(r"^\d+\.\d+", entry[1])
            for entry in toc
        )
        
        # Calculate page coverage
        pages_covered = set()
        for entry in toc:
            if len(entry) >= 3 and isinstance(entry[2], int) and entry[2] > 0:
                pages_covered.add(entry[2])
        
        page_coverage = len(pages_covered) / total_pages if total_pages > 0 else 0
        
        return TOCQualityMetrics(
            source=source,
            entry_count=len(toc),
            level_count=len(levels),
            has_chapters=has_chapters,
            has_sections=has_sections,
            page_coverage=page_coverage,
            confidence=1.0,  # Will be adjusted by caller
        )
    
    def clean_toc_entry(self, title: str) -> str:
        """Clean a TOC entry title."""
        # Remove trailing page numbers
        title = re.sub(r'\s+\d+\s*$', '', title)
        
        # Remove dot leaders
        title = re.sub(r'\.{3,}', '', title)
        
        # Clean extra whitespace
        title = ' '.join(title.split())
        
        return title.strip()


class IntegratedScaffoldingService:
    """
    Drop-in replacement for ScaffoldingService that uses intelligent TOC.
    
    This class wraps the IntelligentTOCService and provides the same
    interface as the original ScaffoldingService.
    """
    
    def __init__(
        self,
        embed_toc_min_entries: int = 3,
        enable_enrichment: bool = True,
    ):
        """Initialize integrated scaffolding service."""
        self.embed_toc_min_entries = embed_toc_min_entries
        self.intelligent_toc = IntelligentTOCService(
            enable_enrichment=enable_enrichment,
        )
    
    def build_scaffold(
        self,
        task,  # DocumentTask
        child_chunks: Optional[List[Dict]] = None,
    ):
        """
        Build document scaffold with intelligent TOC extraction.
        
        Args:
            task: DocumentTask with PDF path
            child_chunks: Optional content chunks for Layer 2
            
        Returns:
            Updated DocumentTask with scaffold
        """
        pdf_path = self._get_pdf_path(task)
        if not pdf_path:
            task.error_log.append("No valid PDF path found")
            task.processing_status = "failed_scaffold"
            return task
        
        # Initialize scaffold
        task.scaffold = {"toc": [], "page_map": {}}
        
        try:
            # Extract TOC using intelligent multi-layer approach
            toc, metrics = self.intelligent_toc.extract_toc(
                pdf_path,
                child_chunks=child_chunks,
                report_id=task.report_id,
            )
            
            task.scaffold["toc"] = toc
            task.error_log.append(
                f"Intelligent TOC extracted: {metrics.entry_count} entries, "
                f"source={metrics.source}, score={metrics.score():.1f}"
            )
            
            # Build page mappings
            task = self._build_page_mappings(task, pdf_path)
            
            # Set status
            if toc:
                task.processing_status = "scaffold_complete"
            else:
                task.processing_status = "scaffold_partial"
                task.error_log.append("No TOC entries extracted")
            
        except Exception as e:
            task.error_log.append(f"Scaffolding failed: {str(e)}")
            task.processing_status = "failed_scaffold"
        
        return task
    
    def _get_pdf_path(self, task) -> Optional[str]:
        """Get PDF path from task."""
        if task.ocred_pdf_path and Path(task.ocred_pdf_path).exists():
            return task.ocred_pdf_path
        elif task.local_pdf_path and Path(task.local_pdf_path).exists():
            return task.local_pdf_path
        return None
    
    def _build_page_mappings(self, task, pdf_path: str):
        """Build physical to logical page mappings."""
        try:
            doc = fitz.Document(pdf_path)
            page_map = {}
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                label = page.get_label()
                page_map[page_num] = label if label else str(page_num + 1)
            
            doc.close()
            task.scaffold["page_map"] = page_map
            
        except Exception as e:
            task.error_log.append(f"Page mapping failed: {str(e)}")
        
        return task


# Convenience functions for pipeline integration

def extract_intelligent_toc(
    pdf_path: str,
    child_chunks: Optional[List[Dict]] = None,
    report_id: str = "unknown",
) -> Tuple[List[List], Dict]:
    """
    Extract TOC using intelligent multi-layer approach.
    
    Args:
        pdf_path: Path to PDF file
        child_chunks: Content chunks for TOC table parsing
        report_id: Report identifier
        
    Returns:
        Tuple of (TOC list, metrics dict)
    """
    service = IntelligentTOCService()
    toc, metrics = service.extract_toc(pdf_path, child_chunks, report_id)
    
    return toc, {
        "source": metrics.source,
        "entry_count": metrics.entry_count,
        "level_count": metrics.level_count,
        "score": metrics.score(),
        "confidence": metrics.confidence,
    }


def enrich_hierarchy(
    parent_chunks: List[Dict],
    child_chunks: List[Dict],
    report_id: str = "unknown",
) -> Tuple[List[Dict], List[Dict]]:
    """
    Enrich flat hierarchy with detected sub-sections.
    
    Args:
        parent_chunks: Existing parent chunks
        child_chunks: Child content chunks
        report_id: Report identifier
        
    Returns:
        Tuple of (enriched_parents, updated_children)
    """
    enricher = HierarchyEnricher()
    return enricher.enrich_hierarchy(parent_chunks, child_chunks, report_id)
