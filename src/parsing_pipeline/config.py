"""
Parsing Pipeline Configuration
===============================

Centralized configuration for all CAG parsing pipeline components.
All thresholds, model settings, and parameters are defined here.

Configuration is loaded from parsing_config.yaml at the repo root,
with environment variable overrides for operational control.

Design Philosophy:
- Group related settings by pipeline phase
- Document what each threshold controls
- Provide sensible defaults for immediate use
- Allow granular tuning without code changes
"""

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TriageConfig:
    """Phase 2: Document Triage - Classify PDFs as native_text or scanned."""

    sample_pages: int = 10
    """
    Number of pages to sample for text density calculation.

    Higher = more accurate classification but slower.
    Typical: 10-15 pages is sufficient for reliable classification.
    """

    text_threshold: int = 150
    """
    Minimum average non-whitespace characters per page to classify as native_text.

    Raising this threshold: More PDFs classified as scanned (more OCR processing).
    Lowering this threshold: Fewer PDFs classified as scanned (faster but may miss scanned docs).

    Default 150 chars/page works well for CAG reports.
    """


@dataclass
class OCRConfig:
    """Phase 3: OCR Processing - Convert scanned PDFs to searchable text."""

    language: str = "eng"
    """
    OCR language code(s). Use 'eng' for English, 'eng+hin' for English+Hindi.

    Note: Hindi support requires tesseract-lang-hin package installed.
    """

    timeout: int = 600
    """
    Maximum OCR processing time in seconds (10 minutes default).

    Large documents (200+ pages) may need higher timeout.
    """

    output_type: str = "pdfa"
    """
    OCRmyPDF output format. 'pdfa' creates PDF/A archival format.

    Options: 'pdfa', 'pdf', 'pdfa-1', 'pdfa-2', 'pdfa-3'
    """

    force_ocr: bool = True
    """
    Force OCR even if text layer exists (ensures clean OCR).
    """


@dataclass
class ScaffoldingConfig:
    """Phase 4: Document Scaffolding - TOC extraction and structure building."""

    embedded_toc_min_entries: int = 3
    """
    Minimum TOC entries required to accept an embedded TOC.

    Raising this: Stricter TOC validation, may reject valid but short TOCs.
    Lowering this: Accept shorter TOCs, risk of false positives.
    """

    toc_rejection_alert_threshold: float = 0.25
    """
    Alert if rejection rate exceeds this fraction (0.25 = 25%).

    Used for monitoring TOC extraction quality during processing.
    """

    min_toc_quality_score: int = 20
    """
    Minimum quality score (0-100) to accept a TOC.

    TOCs below this threshold are rejected and trigger fallback strategies.
    """

    bookmark_quality_threshold: float = 0.6
    """
    Minimum TOCQualityMetrics.score() * confidence to accept PDF bookmarks.

    Range 0-1 (multiplied by 100 internally). Default 0.6 = 60 points required.
    Catches garbage PDF-merger bookmarks that pass entry/level/coverage checks.
    """

    assembly_bookmark_patterns: List[str] = field(default_factory=lambda: [
        r"^\d{2}\s+\w+",     # "01 Cover", "05 Final_Report"
        r"^Part\s*\d+$",     # Just "Part 1"
        r"^Section\s*\d+$",  # Just "Section 1"
        r"^p\d+",            # "p001"
    ])
    """
    Regex patterns that indicate file-assembly/PDF-merger bookmarks.

    Matching bookmarks reduce confidence score. These are garbage bookmarks
    created by PDF tools when merging files, not real TOC entries.
    """

    cag_quality_patterns: List[str] = field(default_factory=lambda: [
        r"^Chapter\s+[IVX\d]+",
        r"^Annexure",
        r"^Executive\s+Summary",
        r"^Audit\s+(Objective|Finding|Scope)",
        r"^\d+\.\d+\s+[A-Z]",  # "2.3 Section Title"
    ])
    """
    Regex patterns that indicate high-quality CAG-specific bookmarks.

    Matching bookmarks boost confidence score. These patterns match
    standard CAG report structure.
    """


@dataclass
class LayoutAnalysisConfig:
    """Phase 5: Layout Analysis - AI-powered block detection via Docling."""

    confidence_threshold: float = 0.65
    """
    Minimum confidence score to accept a layout block.

    Raising this: Fewer false positives, may miss valid blocks.
    Lowering this: More blocks detected, increased noise.

    0.65 is a balanced default for CAG reports.
    """

    table_min_non_empty_cells: int = 3
    """
    Minimum non-empty cells to accept a Docling TableFormer extraction.

    Quality gate to reject garbage tables (e.g., OCR artifacts, formatting noise).
    """

    accelerator_device: str = "cpu"
    """
    Docling accelerator device: 'cpu', 'mps', or 'cuda'.

    GPU acceleration (mps/cuda) is 5x faster but requires compatible hardware.
    """

    tableformer_mode: str = "ACCURATE"
    """
    Docling TableFormer mode: 'FAST' or 'ACCURATE'.

    ACCURATE mode: Better quality for scanned PDFs, ~2x slower.
    FAST mode: Faster processing, may miss complex table structures.
    """


@dataclass
class TOCReconciliationConfig:
    """Phase 5.5: TOC Reconciliation - Fuse heuristic TOC with Docling headers."""

    similarity_threshold: float = 0.65
    """
    Minimum string similarity (0-1) for title matching between Phase 4 and Docling.

    Raising this: Stricter matching, fewer false matches.
    Lowering this: More lenient matching, risk of incorrect merges.
    """

    min_docling_headers: int = 3
    """
    Minimum Docling section headers required to enable reconciliation.

    If Docling detects fewer headers, reconciliation is skipped.
    """

    section_header_confidence_threshold: float = 0.60
    """
    Minimum confidence for Docling Section-header blocks.

    Lower than general layout confidence (0.65) because section headers
    are harder to detect with high confidence.
    """

    quality_high_threshold: int = 70
    """
    Quality score threshold for "high quality" TOC tier.

    High quality TOCs are supplemented, not replaced, by Docling.
    """

    quality_medium_threshold: int = 40
    """
    Quality score threshold for "medium quality" TOC tier.

    Medium quality TOCs are merged equally with Docling headers.
    TOCs below this threshold prefer Docling as primary source.
    """


@dataclass
class LLMValidationConfig:
    """Phase 5.7: LLM TOC Validation - Last resort validation via Google Gemini."""

    enabled: bool = True
    """
    Enable LLM validation for low-quality TOCs.

    Set to False to skip LLM validation (saves API costs, ~$0.005-0.01 per report).
    """

    model: str = "gemini-3.6-flash"
    """
    Gemini model for TOC validation. Flash is cost-efficient (~$0.015/report).

    Options: 'gemini-3.6-flash', 'gemini-2.5-flash', 'gemini-2.5-pro'
    """

    max_input_chars: int = 8000
    """
    Maximum characters of document text to send to LLM.

    Balances context vs API cost. 8000 chars covers first ~15 pages.
    """

    quality_threshold: int = 50
    """
    Only validate TOCs with quality score below this threshold.

    Higher threshold: More reports validated (higher API costs).
    Lower threshold: Fewer reports validated (only tail cases).
    """

    max_pages_to_extract: int = 15
    """
    Maximum number of PDF pages to extract text from for LLM validation.
    """


@dataclass
class ContentExtractionConfig:
    """Phase 6: Content Extraction - Extract text, tables, and images from layout blocks."""

    # pdfplumber table extraction settings
    pdfplumber_snap_tolerance: int = 5
    """
    pdfplumber snap tolerance for line detection (pixels).

    Higher = more lenient line matching, risk of merging separate table cells.
    Lower = stricter line matching, may miss faint table borders.
    """

    pdfplumber_join_tolerance: int = 5
    """
    pdfplumber join tolerance for merging close lines (pixels).

    Higher = merge more lines, risk of over-joining.
    Lower = keep lines separate, may split continuous borders.
    """

    # Table quality thresholds
    table_min_confidence: float = 0.2
    """
    Minimum confidence score to accept a pdfplumber table extraction.

    Very low threshold (0.2) allows fallback to Tier 3 (Gemini) for poor extractions.
    """

    table_fill_ratio_threshold: float = 0.3
    """
    Minimum fraction of non-empty cells to accept a table.

    Rejects tables with >70% empty cells as likely noise.
    """

    table_min_non_empty_cells: int = 3
    """
    Minimum non-empty cells required to accept a table.

    Rejects tiny or degenerate tables (e.g., single-cell artifacts).
    """

    # Confidence scoring factors
    table_empty_ratio_penalty_threshold: float = 0.5
    """
    Penalize confidence score if empty cell ratio exceeds this threshold.
    """

    table_column_consistency_threshold: float = 0.7
    """
    Penalize confidence if column count consistency falls below this ratio.

    Measures how many rows have the mode column count.
    """

    table_numeric_ratio_threshold: float = 0.1
    """
    Penalize confidence if numeric cell ratio falls below this threshold.

    CAG tables are heavily numeric; low ratio suggests extraction failure.
    """


@dataclass
class ChunkingConfig:
    """Phase 7: Hierarchical Chunking - Build parent-child chunk relationships."""

    multi_page_table_column_similarity_threshold: float = 0.8
    """
    Minimum Jaccard similarity for column structure to merge multi-page tables.

    Raising this: Stricter matching, fewer false merges.
    Lowering this: More lenient matching, risk of merging unrelated tables.
    """

    max_parent_chunk_pages: int = 100
    """
    Maximum page range for a single parent chunk.

    Prevents pathological cases where single section spans entire document.
    """


@dataclass
class SemanticEnrichmentConfig:
    """Phase 9: Semantic Enrichment - Extract findings, recommendations, entities."""

    # Tier-specific severity thresholds for findings (in crore)
    severity_thresholds: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "union": {"critical": 100, "high": 10, "medium": 1, "low": 0},
        "state": {"critical": 50, "high": 5, "medium": 0.5, "low": 0},
        "local_body": {"critical": 10, "high": 1, "medium": 0.10, "low": 0},
    })
    """
    Tier-specific monetary thresholds for finding severity classification.

    Union reports: Larger amounts (₹100 crore = critical)
    State reports: Medium amounts (₹50 crore = critical)
    Local Body reports: Smaller amounts (₹10 crore = critical)

    Adjusting these changes which findings are flagged as high-priority.
    """

    finding_confidence_threshold: float = 0.5
    """
    Minimum confidence score to classify a chunk as an audit finding.

    Based on semantic pattern matching. Raising this reduces false positives.
    P3: Raised from 0.4 to 0.5 - lower confidence findings go to LLM validation.
    """

    min_monetary_value_for_high_severity: int = 1_00_000_00  # ₹1 lakh in paise
    """
    Minimum monetary value to consider for high severity classification.

    Prevents tiny amounts from being flagged as critical.
    """


@dataclass
class InstrumentationConfig:
    """Trace instrumentation configuration for pipeline observability."""

    enabled: bool = False
    """
    Master switch for trace instrumentation.

    When False (default), all TraceEmitter methods are no-ops with zero overhead.
    When True, emits per-report markdown trace files documenting every decision,
    fallback, and input/output for debugging and analysis.
    """

    output_dir: str = "logs/traces"
    """
    Directory for trace markdown files.

    Each report generates a file: {report_id}_trace_{date}.md
    """

    sample_count: int = 5
    """
    Maximum number of samples to collect per category (e.g., accepted/rejected TOC entries).

    Keeps trace files manageable while providing representative examples.
    """

    incremental_flush: bool = False
    """
    Flush events to disk after each phase for crash protection.

    When True, writes a partial trace file ({report_id}_partial.md) incrementally.
    Useful for debugging crashes mid-pipeline.
    """


@dataclass
class ParsingPipelineConfig:
    """Root configuration aggregating all phase-specific configs."""

    triage: TriageConfig = field(default_factory=TriageConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    scaffolding: ScaffoldingConfig = field(default_factory=ScaffoldingConfig)
    layout: LayoutAnalysisConfig = field(default_factory=LayoutAnalysisConfig)
    toc_reconciliation: TOCReconciliationConfig = field(default_factory=TOCReconciliationConfig)
    llm_validation: LLMValidationConfig = field(default_factory=LLMValidationConfig)
    content_extraction: ContentExtractionConfig = field(default_factory=ContentExtractionConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    semantic_enrichment: SemanticEnrichmentConfig = field(default_factory=SemanticEnrichmentConfig)
    instrumentation: InstrumentationConfig = field(default_factory=InstrumentationConfig)

    @classmethod
    def from_yaml(cls, yaml_path: Optional[str] = None) -> "ParsingPipelineConfig":
        """
        Load configuration from YAML file with environment variable overrides.

        Args:
            yaml_path: Path to parsing_config.yaml (default: repo root)

        Returns:
            ParsingPipelineConfig instance
        """
        if yaml_path is None:
            # Default: parsing_config.yaml at repo root
            repo_root = Path(__file__).parent.parent.parent
            yaml_path = str(repo_root / "parsing_config.yaml")

        config = cls()

        # Load from YAML if exists
        yaml_file = Path(yaml_path)
        if yaml_file.exists():
            with open(yaml_file, 'r') as f:
                yaml_data = yaml.safe_load(f) or {}

            # Apply YAML overrides
            config = cls._apply_yaml_overrides(config, yaml_data)

        # Apply environment variable overrides
        config = cls._apply_env_overrides(config)

        return config

    @classmethod
    def _apply_yaml_overrides(cls, config: "ParsingPipelineConfig", yaml_data: Dict) -> "ParsingPipelineConfig":
        """Apply YAML configuration overrides to default config."""
        for phase_name, phase_config in yaml_data.items():
            if hasattr(config, phase_name) and isinstance(phase_config, dict):
                phase_obj = getattr(config, phase_name)
                for key, value in phase_config.items():
                    if hasattr(phase_obj, key):
                        setattr(phase_obj, key, value)
        return config

    @classmethod
    def _apply_env_overrides(cls, config: "ParsingPipelineConfig") -> "ParsingPipelineConfig":
        """
        Apply environment variable overrides.

        Format: PARSING_{PHASE}_{SETTING}
        Example: PARSING_TRIAGE_TEXT_THRESHOLD=200
        """
        for phase_name in dir(config):
            if phase_name.startswith('_'):
                continue
            phase_obj = getattr(config, phase_name)
            if not hasattr(phase_obj, '__dataclass_fields__'):
                continue

            for field_name in phase_obj.__dataclass_fields__:
                env_key = f"PARSING_{phase_name.upper()}_{field_name.upper()}"
                env_value = os.getenv(env_key)

                if env_value is not None:
                    # Type conversion
                    current_value = getattr(phase_obj, field_name)
                    if isinstance(current_value, bool):
                        new_value = env_value.lower() in ('true', '1', 'yes')
                    elif isinstance(current_value, int):
                        new_value = int(env_value)
                    elif isinstance(current_value, float):
                        new_value = float(env_value)
                    else:
                        new_value = env_value

                    setattr(phase_obj, field_name, new_value)

        return config


# Global singleton instance
_global_config: Optional[ParsingPipelineConfig] = None


def get_config() -> ParsingPipelineConfig:
    """
    Get the global parsing pipeline configuration.

    Lazily loads from parsing_config.yaml on first call.
    Subsequent calls return the cached instance.

    Returns:
        ParsingPipelineConfig instance
    """
    global _global_config
    if _global_config is None:
        _global_config = ParsingPipelineConfig.from_yaml()
    return _global_config


def reset_config():
    """Reset global config (useful for testing)."""
    global _global_config
    _global_config = None
