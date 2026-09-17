"""
Data contracts for the CAG RAG Pipeline.

Defines Pydantic models for all pipeline stages:
- Phase 1-3: Extraction and chunking
- Phase 5: Semantic enrichment (Findings, Recommendations, etc.)

PHASE 5 ADDITIONS:
- Finding: Extracted audit finding with monetary values
- Recommendation: Extracted action items
- MonetaryValue: Structured currency representation
- SectionClassification: Semantic section tagging
- SemanticEnrichment: Complete enrichment output
"""

from typing import List, Optional, Literal, Dict, Tuple, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field


# ==================== TOC QUALITY METRICS ====================


# Source types for TOC extraction - tracks which method produced the TOC
TOCSource = Literal[
    "bookmarks",          # PDF embedded bookmarks
    "toc_table",          # Parsed from printed TOC table
    "heuristic",          # Font-based heading detection
    "combined",           # Multiple sources merged
    "docling_reconciled", # Phase 5.5 reconciliation with Docling
    "llm_validated",      # Phase 5.7 LLM validation
    "none",               # No TOC extracted
]


@dataclass
class TOCQualityMetrics:
    """
    Quality metrics for a TOC extraction.

    Used by Phase 4 (Scaffolding) to score bookmark quality and decide
    whether to use embedded TOC or fall back to heuristic generation.

    The score() method returns 0-100 based on structural quality and
    confidence adjustments (assembly pattern penalties, CAG pattern bonuses).
    """

    source: str  # TOCSource literal value
    entry_count: int
    level_count: int  # Number of unique hierarchy levels
    has_chapters: bool
    has_sections: bool
    page_coverage: float  # Fraction of document pages covered (0-1)
    confidence: float  # Confidence adjustment factor (0-1)

    def score(self) -> float:
        """
        Calculate overall quality score (0-100).

        Scoring breakdown:
        - Entry count: 0-30 points (2 points per entry, max 30)
        - Level depth: 0-25 points (8 points per level, max 25)
        - Has chapters: 15 points
        - Has sections: 15 points
        - Page coverage: 0-15 points (proportional to coverage)

        Final score is multiplied by confidence factor.
        """
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


# ==================== PHASE 1-3: EXTRACTION MODELS ====================


class ExtractedContent(BaseModel):
    """Structured representation of a single piece of extracted content."""

    content_type: Literal[
        "paragraph",
        "table_markdown",
        "image_caption",
        "chart_data_path",
        "list",
        "header",
        "footnote",  # P4-1: Footnote capture
    ] = Field(..., description="The semantic type of the extracted content.")

    content: str = Field(..., description="The extracted data itself.")

    source_page_physical: int = Field(
        ..., description="The 0-indexed physical page number."
    )

    source_bbox: List[float] = Field(
        ..., description="The [x0, y0, x1, y1] bounding box."
    )

    model_used: str = Field(..., description="Identifier for the model/method used.")

    layout_label: str = Field(..., description="Original DocLayNet label.")

    layout_confidence: Optional[float] = Field(
        None, description="Layout confidence score."
    )

    # P0-1 ADDITION: Structured table data
    structured_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Structured representation for tables. Contains StructuredTable dict."
    )

    # V2 ADDITION: Extraction provenance
    extraction_method: Optional[str] = Field(
        default=None,
        description="V2: Extraction tier - 'pdfplumber-lines_strict', 'pdfplumber-text_fallback', "
                    "'docling-tableformer', 'gemini-2.5-flash', 'image-crop-for-gemini'"
    )
    extraction_confidence: Optional[float] = Field(
        default=None,
        description="V2: Extraction confidence score 0.0-1.0 from the extractor"
    )


class ParentChunk(BaseModel):
    """Parent chunk for hierarchical retrieval (section-level context)."""

    chunk_id: str = Field(..., description="Unique identifier for parent chunk")
    report_id: str = Field(..., description="Source report identifier")
    hierarchy: Dict[str, str] = Field(
        ...,
        description="Hierarchy path (e.g., {'level_1': 'Chapter III', 'level_2': '3.1.2'})",
    )
    page_range_physical: Tuple[int, int] = Field(
        ..., description="Physical page range (0-indexed, inclusive)"
    )
    page_range_logical: Tuple[str, str] = Field(
        ..., description="Logical page range as printed in document"
    )
    toc_entry: str = Field(..., description="Original ToC title")
    toc_level: int = Field(..., description="Depth in ToC (1=Chapter, 2=Section, etc.)")
    content_summary: Optional[str] = Field(
        None, description="Optional LLM-generated summary (Phase 2+)"
    )

    # P0-2 ADDITION: Y-coordinate for accurate child assignment
    start_y_position: Optional[float] = Field(
        None,
        description="Y-coordinate of section heading on first page (for multi-section pages)"
    )

    # Multi-tier expansion fields
    government_body_type: Literal["union", "state", "local_body"] = Field(
        default="union",
        description="Type of government body: union, state, or local_body"
    )
    state_name: Optional[str] = Field(
        default=None,
        description="State name for State/Local Body reports (e.g., 'Odisha', 'Maharashtra'); null for Union"
    )
    department: Optional[str] = Field(
        default=None,
        description="State/Local Body department (equivalent to Union ministry); null for Union"
    )
    audit_category: Literal["compliance", "performance", "financial", "revenue", "commercial", "atir"] = Field(
        default="compliance",
        description="Audit category type"
    )
    report_subtype: Optional[Literal["PSE", "Revenue", "PRI_ULB"]] = Field(
        default=None,
        description="Report subtype: PSE (Public Sector Enterprises), Revenue, PRI_ULB (Panchayati Raj/Urban Local Bodies)"
    )


class ChildChunk(BaseModel):
    """Child chunk with full extraction metadata and parent linking."""

    chunk_id: str = Field(..., description="Unique identifier for child chunk")
    parent_chunk_id: str = Field(..., description="Link to parent chunk")
    content_type: Literal[
        "paragraph",
        "table_markdown",
        "image_caption",
        "chart_data_path",
        "list",
        "header",
        "footnote",  # P4-1: Footnote capture
    ] = Field(..., description="Type of content")
    content: str = Field(..., description="The actual extracted content")

    # Source location
    source_page_physical: int = Field(..., description="0-indexed page number")
    source_page_logical: Optional[str] = Field(
        None, description="Page number as printed (e.g., '25', 'iv')"
    )
    source_bbox: List[float] = Field(..., description="[x0, y0, x1, y1] coordinates")

    # Extraction metadata
    model_used: str = Field(..., description="Extraction model identifier")
    layout_label: str = Field(..., description="Original DocLayNet label")
    layout_confidence: Optional[float] = Field(None, description="Layout confidence")

    # Report metadata
    report_id: str = Field(..., description="Source report identifier")
    report_title: str = Field(..., description="Report title")
    report_no: str = Field(..., description="Report number")
    source_filename: str = Field(..., description="Source PDF filename")
    hierarchy: Dict[str, str] = Field(
        ..., description="Inherited hierarchy from parent"
    )

    # P0-1 ADDITION: Structured table data
    structured_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Structured representation inherited from ExtractedContent."
    )

    # P3-3: Temporal metadata
    temporal_references: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Extracted temporal references: [{type, start_year, end_year, raw_text}]"
    )

    # P3-4: Composite extraction confidence
    extraction_confidence: Optional[float] = Field(
        default=None,
        description="Composite confidence (0-1) combining layout, TOC, and enrichment quality"
    )

    # V2 ADDITION: Extraction provenance
    extraction_method: Optional[str] = Field(
        default=None,
        description="V2: Which extraction tier produced this chunk"
    )

    # P4-6: Visual subtype classification
    visual_subtype: Optional[str] = Field(
        default=None,
        description="P4-6: Subtype for image_caption chunks: 'chart', 'map', 'flowchart', 'diagram', 'photo', 'data_visualization', 'unknown'"
    )

    # Multi-tier expansion fields
    government_body_type: Literal["union", "state", "local_body"] = Field(
        default="union",
        description="Type of government body: union, state, or local_body"
    )
    state_name: Optional[str] = Field(
        default=None,
        description="State name for State/Local Body reports (e.g., 'Odisha', 'Maharashtra'); null for Union"
    )
    department: Optional[str] = Field(
        default=None,
        description="State/Local Body department (equivalent to Union ministry); null for Union"
    )
    audit_category: Literal["compliance", "performance", "financial", "revenue", "commercial", "atir"] = Field(
        default="compliance",
        description="Audit category type"
    )
    report_subtype: Optional[Literal["PSE", "Revenue", "PRI_ULB"]] = Field(
        default=None,
        description="Report subtype: PSE (Public Sector Enterprises), Revenue, PRI_ULB (Panchayati Raj/Urban Local Bodies)"
    )


# ==================== PHASE 5: SEMANTIC ENRICHMENT MODELS ====================


class FindingTypeEnum(str, Enum):
    """Classification of audit finding types."""

    IRREGULAR_EXPENDITURE = "irregular_expenditure"
    LOSS_OF_REVENUE = "loss_of_revenue"
    WASTEFUL_EXPENDITURE = "wasteful_expenditure"
    NON_COMPLIANCE = "non_compliance"
    SYSTEM_DEFICIENCY = "system_deficiency"
    PERFORMANCE_SHORTFALL = "performance_shortfall"
    FRAUD_MISAPPROPRIATION = "fraud_misappropriation"
    PROCEDURAL_LAPSE = "procedural_lapse"
    OTHER = "other"


class SeverityEnum(str, Enum):
    """Severity classification based on monetary value and impact."""

    CRITICAL = "critical"  # > ₹100 crore or systemic issues
    HIGH = "high"  # ₹10-100 crore or significant impact
    MEDIUM = "medium"  # ₹1-10 crore or moderate impact
    LOW = "low"  # < ₹1 crore or minor issues


class SectionTypeEnum(str, Enum):
    """Semantic classification of document sections."""

    EXECUTIVE_SUMMARY = "executive_summary"
    INTRODUCTION = "introduction"
    AUDIT_OBJECTIVES = "audit_objectives"
    AUDIT_SCOPE = "audit_scope"
    AUDIT_METHODOLOGY = "audit_methodology"
    AUDIT_CRITERIA = "audit_criteria"
    FINDINGS = "findings"
    RECOMMENDATIONS = "recommendations"
    CONCLUSION = "conclusion"
    ANNEXURE = "annexure"
    GLOSSARY = "glossary"
    ACKNOWLEDGEMENT = "acknowledgement"
    PREFACE = "preface"
    # P0-09: Expanded taxonomy for State/Local Body performance audits
    FINANCIAL_MANAGEMENT = "financial_management"
    EMPLOYMENT = "employment"
    EXECUTION = "execution"
    PLANNING = "planning"
    CAPACITY_BUILDING = "capacity_building"
    GRIEVANCE_REDRESSAL = "grievance_redressal"
    IMPACT = "impact"
    MONITORING_EVALUATION = "monitoring_evaluation"
    COMPLIANCE_REVIEW = "compliance_review"
    PERFORMANCE_AUDIT = "performance_audit"
    INFRASTRUCTURE = "infrastructure"
    SERVICE_DELIVERY = "service_delivery"
    REGULATORY = "regulatory"
    ENVIRONMENT = "environment"
    OTHER = "other"


class MonetaryValue(BaseModel):
    """Structured representation of monetary amounts."""

    raw_text: str = Field(..., description="Original text: '₹847.71 crore'")
    amount: float = Field(..., description="Numeric value: 847.71")
    unit: str = Field(..., description="Unit: 'crore', 'lakh', 'thousand'")
    normalized_inr: int = Field(..., description="Normalized to INR (paise)")


class Finding(BaseModel):
    """Extracted CAG audit finding."""

    finding_id: str = Field(..., description="Unique finding identifier")
    report_id: str = Field(..., description="Source report identifier")
    text: str = Field(..., description="Full finding text")
    summary: str = Field(..., description="First 200 chars or first sentence")
    finding_type: str = Field(..., description="FindingType enum value")
    severity: str = Field(..., description="Severity enum value")
    monetary_values: List[Dict] = Field(
        default_factory=list, description="List of MonetaryValue dicts"
    )
    total_amount_inr: int = Field(
        default=0, description="Sum of all monetary values (in paise)"
    )
    # P0-01: Single monetary value fields (max amount from monetary_values)
    monetary_value: Optional[int] = Field(
        default=None, description="P0-01: Max single monetary amount (in paise)"
    )
    monetary_value_crore: Optional[float] = Field(
        default=None, description="P0-01: Max single monetary amount (in crore, derived from monetary_value)"
    )
    # P1-2: Enhanced semantic pattern matching fields
    confidence: float = Field(
        default=0.0, description="P1-2: Confidence score (0.0-1.0) from pattern matching"
    )
    pattern_types: List[str] = Field(
        default_factory=list, description="P1-2: Matched pattern types (e.g., 'audit_revealed', 'variance_issue')"
    )
    # P1-3: Evidence linking field
    evidence_links: List[Dict] = Field(
        default_factory=list, description="P1-3: Links to supporting evidence (tables, paragraphs, etc.)"
    )
    chapter: Optional[str] = Field(None, description="Chapter heading")
    section: Optional[str] = Field(
        None,
        description="Section heading from parent chunk's toc_entry. Also accessible as source_section property."
    )
    page: int = Field(default=0, description="Source page number")
    source_chunk_id: str = Field(default="", description="Source chunk ID")
    entities_mentioned: List[str] = Field(
        default_factory=list, description="Schemes, programs, etc."
    )

    # M2 fix: Alias for section field for clarity (source_section is more descriptive)
    @property
    def source_section(self) -> Optional[str]:
        """Alias for section field - returns the source section from parent chunk's TOC entry."""
        return self.section

    # P3-3: Temporal context for the finding
    audit_period: Optional[Dict[str, int]] = Field(
        default=None,
        description="{'start_year': 2019, 'end_year': 2023} - period the finding covers"
    )
    reference_years: List[int] = Field(
        default_factory=list,
        description="All years explicitly mentioned in the finding text"
    )

    # R3: Cross-finding deduplication fields
    is_duplicate: bool = Field(
        default=False,
        description="R3: True if this finding duplicates another (same amount on nearby pages)"
    )
    dedup_group_id: Optional[str] = Field(
        default=None,
        description="R3: Group identifier for duplicate findings (e.g., 'dedup_10000000000')"
    )

    # R4: Executive summary section flagging
    is_executive_summary: bool = Field(
        default=False,
        description="R4: True if finding is from executive summary/overview section"
    )

    # R5: Monetary context classification
    monetary_context: Optional[str] = Field(
        default=None,
        description="R5: Context of primary monetary value (finding_impact, budget_allocation, etc.)"
    )


class Recommendation(BaseModel):
    """Extracted CAG recommendation."""

    recommendation_id: str = Field(..., description="Unique recommendation identifier")
    report_id: str = Field(..., description="Source report identifier")
    text: str = Field(..., description="Full recommendation text")
    summary: str = Field(..., description="First 200 chars")
    target_entity: Optional[str] = Field(
        None, description="'Ministry of Railways', etc."
    )
    action_required: Optional[str] = Field(
        None, description="Extracted action verb phrase"
    )
    chapter: Optional[str] = Field(None, description="Chapter heading")
    section: Optional[str] = Field(None, description="Section heading")
    page: int = Field(default=0, description="Source page number")
    source_chunk_id: str = Field(default="", description="Source chunk ID")
    related_finding_ids: List[str] = Field(
        default_factory=list, description="Linked findings"
    )
    status: str = Field(
        default="pending", description="pending, accepted, implemented, rejected"
    )
    ministry_response: Optional[str] = Field(None, description="Ministry's response")

    # P4-3: Extraction metadata
    extraction_strategy: str = Field(
        default="verb",
        description="P4-3: 'structural' (from dedicated section), 'numbered' (Recommendation No. X), or 'verb' (should/may)"
    )
    rec_number: Optional[str] = Field(
        None,
        description="P4-3: Explicit recommendation number if found (e.g., 'Recommendation No. 18')"
    )
    paragraph_citations: List[str] = Field(
        default_factory=list,
        description="P4-3: Paragraph references from exec summary (e.g., ['3.1', '3.2'])"
    )


class SectionClassification(BaseModel):
    """Section type classification result."""

    chunk_id: str = Field(..., description="Parent chunk ID")
    section_title: str = Field(..., description="Section title from TOC")
    section_type: str = Field(..., description="SectionType enum value")
    confidence: float = Field(..., description="Classification confidence 0.0-1.0")
    # P1-C: Flag for low-confidence extractions needing LLM validation
    is_low_confidence: bool = Field(
        default=False,
        description="True if confidence below threshold, candidate for LLM validation"
    )


class SemanticEnrichmentStats(BaseModel):
    """Statistics from semantic enrichment."""

    report_info: Dict[str, str] = Field(..., description="Report metadata")
    findings: Dict[str, Any] = Field(..., description="Finding statistics")
    recommendations: Dict[str, Any] = Field(
        ..., description="Recommendation statistics"
    )
    sections: Dict[str, Any] = Field(..., description="Section statistics")


class SemanticEnrichment(BaseModel):
    """Complete semantic enrichment output for a report."""

    report_id: str = Field(..., description="Report identifier")
    findings: List[Dict] = Field(default_factory=list, description="Extracted findings")
    recommendations: List[Dict] = Field(
        default_factory=list, description="Extracted recommendations"
    )
    section_classifications: List[Dict] = Field(
        default_factory=list, description="Section type tags"
    )
    statistics: Dict[str, Any] = Field(
        default_factory=dict, description="Aggregate statistics"
    )
    entities: Dict[str, List[str]] = Field(
        default_factory=dict, description="Extracted entities"
    )

    # P3-5: Annexure-finding links
    annexure_links: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Links from findings/paragraphs to annexure sections"
    )

    # P3-6: Cross-chunk references
    cross_references: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Resolved cross-chunk references (para refs, section refs, table refs)"
    )

    # P3-3: Document-level temporal metadata
    temporal_coverage: Optional[Dict[str, Any]] = Field(
        default=None,
        description="{'audit_period': {start, end}, 'reference_years': [...], 'previous_audit_refs': [...]}"
    )

    # P4-2: Box element detection
    box_elements: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="P4-2: Detected Box X.X illustrative elements"
    )

    # P4-4: Executive summary structured index
    executive_summary_index: Optional[Dict[str, Any]] = Field(
        default=None,
        description="P4-4: Structured index from exec summary with paragraph citations"
    )


# ==================== P1-14c: VISUAL ASSET REGISTRY ====================


class VisualAssetRegistry(BaseModel):
    """
    P1-14c: Registry tracking all extracted visual assets.

    Used for:
    - Counting tables/figures per report
    - Tracking extraction methods used (pdfplumber, docling, gemini)
    - Grouping visual assets by section for downstream processing
    """

    total_tables: int = Field(
        default=0,
        description="Total number of table chunks in the report"
    )
    total_figures: int = Field(
        default=0,
        description="Total number of figure/chart chunks in the report"
    )
    tables_by_section: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Map of parent_chunk_id -> list of table chunk_ids"
    )
    figures_by_section: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Map of parent_chunk_id -> list of figure chunk_ids"
    )
    extraction_stats: Dict[str, int] = Field(
        default_factory=dict,
        description="Counts by extraction method: {'pdfplumber-lines_strict': 42, 'docling-tableformer': 15}"
    )


# ==================== PIPELINE TASK MODEL ====================


class DocumentTask(BaseModel):
    """Main pipeline task tracking document through all stages."""

    # Initial state from ManifestIngestionService
    report_id: str  # A unique ID, e.g., sanitized report number
    source_url: str
    local_pdf_path: str
    initial_metadata: dict  # All columns from the Excel file

    # Added by TriageService
    classification: Optional[Literal["native_text", "scanned"]] = None

    # Updated by OCRService if run
    ocred_pdf_path: Optional[str] = None

    # Added by ScaffoldingService
    scaffold: Optional[dict] = None  # Contains 'toc' and 'page_map'

    # Added by LayoutAnalysisService
    layout: Optional[Dict[int, List[Dict]]] = None  # page_num -> list of layout blocks

    # Added by ContentExtractionService
    extracted_content: Optional[List[ExtractedContent]] = None

    # Added by ChunkingService
    parent_chunks: Optional[List[ParentChunk]] = None
    child_chunks: Optional[List[ChildChunk]] = None
    # M2-FIX: DLQ entries from multi-page table handler
    dlq_entries: Optional[List[Dict[str, Any]]] = None

    # Added by AssemblyService
    assembled_output_path: Optional[str] = None

    # PHASE 5: Added by SemanticEnrichmentService
    semantic_enrichment: Optional[SemanticEnrichment] = None
    enrichment_stats: Optional[Dict[str, Any]] = (
        None  # Stats for corpus-level aggregation
    )

    # Pipeline metadata
    processing_status: str = "pending"
    error_log: List[str] = []
