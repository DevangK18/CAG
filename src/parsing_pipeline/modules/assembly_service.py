"""
AssemblyService: Final JSON assembly with metadata enrichment.
Serializes hierarchical chunks to Phase 2-ready JSON format.

UPDATED: Added report_year extraction for RAG pipeline compatibility.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from src.core.data_contracts import DocumentTask, ParentChunk, ChildChunk


class AssemblyService:
    """
    Final pipeline stage: enriches chunks with metadata and serializes to JSON.

    Responsibilities:
    1. Merge chunking output with DocumentTask metadata
    2. Resolve logical page numbers from page_map
    3. Build complete hierarchy objects
    4. Serialize to Phase 2-ready JSON format
    5. Write output files and maintain corpus manifest

    UPDATED: Now extracts report_year as integer for RAG filtering.
    """

    def __init__(self, output_dir: str = "data/processed"):
        """
        Initialize the assembly service.

        Args:
            output_dir: Directory for output JSON files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Manifest file tracks all assembled documents
        self.manifest_path = self.output_dir / "manifest.json"
        self.manifest = self._load_or_create_manifest()

        print(f"AssemblyService initialized. Output: {self.output_dir}")

    def _load_or_create_manifest(self) -> Dict[str, Any]:
        """Load existing manifest or create new one."""
        if self.manifest_path.exists():
            with open(self.manifest_path, "r") as f:
                return json.load(f)
        else:
            return {
                "corpus_version": "1.0",
                "generation_timestamp": datetime.utcnow().isoformat(),
                "total_reports": 0,
                "total_parent_chunks": 0,
                "total_child_chunks": 0,
                "reports": [],
            }

    def _extract_report_year(self, task: DocumentTask) -> Optional[int]:
        """
        Extract report year as integer from available metadata.

        Tries multiple sources in order:
        1. publication_date (Date field): "2023-08-10" → 2023
        2. report_id: "2023_07_Performance_Audit_..." → 2023
        3. Report No: "15 of 2023" → 2023

        Args:
            task: DocumentTask with metadata

        Returns:
            Integer year or None if extraction fails
        """
        metadata = task.initial_metadata or {}

        # Method 1: Parse from publication_date (most reliable)
        date_str = metadata.get("Date", "")
        if date_str and date_str != "Unknown":
            # Try YYYY-MM-DD format
            match = re.match(r"^(\d{4})-\d{2}-\d{2}", str(date_str))
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    pass

            # Try other date formats
            try:
                # Handle various date formats
                for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                    try:
                        dt = datetime.strptime(str(date_str)[:10], fmt)
                        return dt.year
                    except ValueError:
                        continue
            except Exception:
                pass

        # Method 2: Parse from report_id (e.g., "2023_07_Performance_Audit_...")
        if task.report_id:
            match = re.match(r"^(\d{4})_", task.report_id)
            if match:
                try:
                    year = int(match.group(1))
                    # Validate it's a reasonable year
                    if 2000 <= year <= 2100:
                        return year
                except ValueError:
                    pass

        # Method 3: Parse from Report No (e.g., "15 of 2023")
        report_no = metadata.get("Report No", "")
        if report_no and report_no != "Unknown":
            # Try "X of YYYY" format
            match = re.search(r"of\s+(\d{4})", str(report_no))
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    pass

            # Try "YYYY/X" or "YYYY_X" format
            match = re.match(r"^(\d{4})[/_]", str(report_no))
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    pass

        return None

    def assemble_document(
        self,
        task: DocumentTask,
        parent_chunks: List[ParentChunk],
        child_chunks: List[ChildChunk],
    ) -> str:
        """
        Main entry point: assemble final JSON output for a document.

        Args:
            task: Fully processed DocumentTask
            parent_chunks: List of parent chunks
            child_chunks: List of child chunks

        Returns:
            Path to output JSON file
        """
        print(f"Assembling document: {task.report_id}")

        # Extract report_year once for use in metadata
        report_year = self._extract_report_year(task)
        if report_year:
            print(f"  Extracted report_year: {report_year}")
        else:
            print(f"  Warning: Could not extract report_year")

        # Build complete output structure
        assembled_data = {
            "report_metadata": self._build_report_metadata(task, report_year),
            "parent_chunks": self._serialize_parent_chunks(parent_chunks),
            "child_chunks": self._serialize_child_chunks(
                child_chunks, task, report_year
            ),
            "processing_stats": self._build_processing_stats(
                task, parent_chunks, child_chunks
            ),
        }

        # P3-2: Replace generic image captions with contextual ones
        from src.parsing_pipeline.modules.enrichment.contextual_caption_service import ContextualCaptionService
        caption_service = ContextualCaptionService()
        total_images, replaced = caption_service.replace_generic_captions(
            assembled_data["child_chunks"],
            assembled_data["parent_chunks"],
        )
        if replaced > 0:
            print(f"  P3-2: Replaced {replaced}/{total_images} generic image captions")

        # P3-3: Annotate chunks with temporal references
        from src.parsing_pipeline.modules.enrichment.temporal_extractor import TemporalExtractor
        temporal_extractor = TemporalExtractor()
        temporal_count = 0
        for chunk_dict in assembled_data["child_chunks"]:
            if chunk_dict.get("content_type") == "paragraph":
                temporal_refs = temporal_extractor.annotate_chunk_temporal(chunk_dict)
                if temporal_refs:
                    chunk_dict["temporal_references"] = temporal_refs
                    temporal_count += 1
        if temporal_count > 0:
            print(f"  P3-3: Annotated {temporal_count} chunks with temporal references")

        # P3-4: Compute extraction confidence for all chunks
        toc_quality = 75.0  # Default if not available
        if task.scaffold and isinstance(task.scaffold, dict):
            toc_quality = task.scaffold.get("toc_quality_score", 75.0)

        for chunk in assembled_data["child_chunks"]:
            chunk["extraction_confidence"] = self._compute_chunk_confidence(
                chunk, assembled_data["parent_chunks"], toc_quality
            )
        print(f"  P3-4: Computed extraction confidence for {len(assembled_data['child_chunks'])} chunks")

        # P4-1: Build footnote index
        footnote_index = self._build_footnote_index(assembled_data["child_chunks"])
        assembled_data["footnote_index"] = footnote_index
        if footnote_index:
            print(f"  P4-1: Indexed {len(footnote_index)} footnotes")

        # P4-5: Build visual asset registry
        visual_asset_registry = self._build_visual_asset_registry(
            assembled_data["child_chunks"],
            assembled_data["parent_chunks"],
        )
        assembled_data["visual_asset_registry"] = visual_asset_registry
        print(
            f"  P4-5: Visual assets: {visual_asset_registry['total_tables']} tables, "
            f"{visual_asset_registry['total_figures']} figures"
        )

        # Write to JSON file in tier-specific subdirectory
        government_body_type = task.initial_metadata.get("government_body_type", "union")
        tier_dir = self.output_dir / government_body_type
        tier_dir.mkdir(parents=True, exist_ok=True)
        output_path = tier_dir / f"{task.report_id}_chunks.json"
        self._write_json(assembled_data, output_path)

        # Update manifest
        self._update_manifest(task.report_id, parent_chunks, child_chunks, output_path)

        print(f"Assembly complete: {output_path}")
        return str(output_path)

    def _build_report_metadata(
        self, task: DocumentTask, report_year: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract and structure report-level metadata.

        Args:
            task: DocumentTask with initial_metadata
            report_year: Pre-extracted report year (integer)

        Returns:
            Report metadata dict
        """
        metadata = task.initial_metadata or {}

        return {
            "report_id": task.report_id,
            "report_title": metadata.get("Title", "Unknown"),
            "report_no": metadata.get("Report No", "Unknown"),
            "report_year": report_year,  # NEW: Integer year for RAG filtering
            "ministry": metadata.get("Department", "Unknown"),
            "sector": metadata.get("Sector", "Unknown"),
            "publication_date": metadata.get("Date", "Unknown"),
            "report_type": metadata.get("Report Type", "Unknown"),
            # Multi-tier expansion fields (Phase A)
            "government_body_type": metadata.get("government_body_type", "union"),
            "state_name": metadata.get("state_name"),
            "department": metadata.get("department"),
            "audit_category": metadata.get("audit_category", "compliance"),
            "report_subtype": metadata.get("report_subtype"),
            # Processing metadata
            "source_url": task.source_url,
            "source_filename": Path(task.local_pdf_path).name
            if task.local_pdf_path
            else "unknown.pdf",
            "classification": task.classification,
            "processing_status": task.processing_status,
        }

    def _serialize_parent_chunks(
        self, parent_chunks: List[ParentChunk]
    ) -> List[Dict[str, Any]]:
        """
        Convert parent chunks to JSON-serializable dicts.

        Args:
            parent_chunks: List of ParentChunk objects

        Returns:
            List of dictionaries
        """
        return [chunk.dict() for chunk in parent_chunks]

    def _serialize_child_chunks(
        self,
        child_chunks: List[ChildChunk],
        task: DocumentTask,
        report_year: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Convert child chunks to enriched JSON-serializable dicts.

        Args:
            child_chunks: List of ChildChunk objects
            task: DocumentTask for additional metadata
            report_year: Pre-extracted report year (integer)

        Returns:
            List of enriched dictionaries
        """
        enriched_chunks = []

        for child in child_chunks:
            # Convert to dict and restructure for Phase 2 format
            chunk_dict = {
                "chunk_id": child.chunk_id,
                "parent_chunk_id": child.parent_chunk_id,
                "content_type": child.content_type,
                "content": child.content,
                # NEW: Top-level fields for easy RAG indexing
                "report_id": child.report_id,
                "report_year": report_year,  # NEW: Integer year
                "report_title": child.report_title,
                "report_no": child.report_no,
                "hierarchy": child.hierarchy,
                "source_page_physical": child.source_page_physical,
                "source_page_logical": child.source_page_logical,
                # Multi-tier metadata (Phase A expansion) - propagates to Qdrant payloads
                "government_body_type": child.government_body_type,
                "state_name": child.state_name,
                "audit_category": child.audit_category,
                # Nested metadata (preserved for backward compatibility)
                "metadata": {
                    "source": {
                        "filename": child.source_filename,
                        "report_id": child.report_id,
                        "report_title": child.report_title,
                        "report_no": child.report_no,
                        "report_year": report_year,  # NEW: Also in nested for consistency
                        "report_type": task.initial_metadata.get(
                            "Report Type", "Unknown"
                        ),
                        "ministry": task.initial_metadata.get("Department", "Unknown"),
                        "sector": task.initial_metadata.get("Sector", "Unknown"),
                        "publication_date": task.initial_metadata.get(
                            "Date", "Unknown"
                        ),
                        # Multi-tier metadata (Phase A expansion)
                        "government_body_type": child.government_body_type,
                        "state_name": child.state_name,
                        "audit_category": child.audit_category,
                    },
                    "location": {
                        "page_physical": child.source_page_physical,
                        "page_logical": child.source_page_logical,
                        "bbox": child.source_bbox,
                    },
                    "hierarchy": child.hierarchy,
                    "extraction": {
                        "model_used": child.model_used,
                        "layout_label": child.layout_label,
                        "layout_confidence": child.layout_confidence,
                        "extraction_timestamp": datetime.utcnow().isoformat(),
                    },
                },
            }

            # P0-1: Include structured table data for queryable tables
            if child.structured_data is not None:
                chunk_dict["structured_data"] = child.structured_data

            enriched_chunks.append(chunk_dict)

        return enriched_chunks

    def _compute_chunk_confidence(
        self,
        child: Dict,
        parent_chunks: List[Dict],
        toc_quality_score: float,
    ) -> float:
        """
        Compute composite confidence for a child chunk.

        Factors:
        1. Layout confidence (from Docling): weight 0.4
        2. TOC quality (document-level): weight 0.3
        3. Content quality heuristic: weight 0.3

        Returns: float 0.0-1.0
        """
        # Factor 1: Layout confidence
        layout_conf = child.get("metadata", {}).get("extraction", {}).get(
            "layout_confidence", None
        )
        if layout_conf is None:
            layout_score = 0.5  # Unknown = neutral
        else:
            layout_score = min(1.0, layout_conf)

        # Factor 2: TOC quality (normalized to 0-1)
        toc_score = min(1.0, toc_quality_score / 100.0)

        # Factor 3: Content quality heuristic
        content = child.get("content", "")
        content_score = 1.0

        # Penalize very short content
        if len(content.strip()) < 20:
            content_score *= 0.5

        # Penalize high ratio of numbers to words (likely table fragment)
        words = re.findall(r'[a-zA-Z]{2,}', content)
        numbers = re.findall(r'\d+', content)
        if numbers and len(numbers) > len(words) * 2:
            content_score *= 0.7

        # Penalize image captions that are still generic
        if child.get("content_type") == "image_caption":
            if any(ind in content.lower() for ind in ["the image shows", "black background"]):
                content_score *= 0.3

        # Penalize orphan-like assignment (parent has very wide page range)
        parent_id = child.get("parent_chunk_id")
        if parent_id:
            parent = next((p for p in parent_chunks if p.get("chunk_id") == parent_id), None)
            if parent:
                page_range = parent.get("page_range_physical", [0, 0])
                if isinstance(page_range, (list, tuple)) and len(page_range) == 2:
                    span = page_range[1] - page_range[0]
                    if span > 50:  # Parent covers 50+ pages = likely poor assignment
                        content_score *= 0.6

        # Weighted composite
        composite = (
            layout_score * 0.4
            + toc_score * 0.3
            + content_score * 0.3
        )

        return round(composite, 3)

    def _build_processing_stats(
        self,
        task: DocumentTask,
        parent_chunks: List[ParentChunk],
        child_chunks: List[ChildChunk],
    ) -> Dict[str, Any]:
        """
        Build processing statistics for the document.

        Args:
            task: DocumentTask
            parent_chunks: List of parent chunks
            child_chunks: List of child chunks

        Returns:
            Statistics dictionary
        """
        # Count content types
        content_type_counts = {}
        for child in child_chunks:
            ctype = child.content_type
            content_type_counts[ctype] = content_type_counts.get(ctype, 0) + 1

        # Calculate page coverage
        if child_chunks:
            pages_covered = set(child.source_page_physical for child in child_chunks)
            min_page = min(pages_covered)
            max_page = max(pages_covered)
        else:
            pages_covered = set()
            min_page = 0
            max_page = 0

        return {
            "total_parent_chunks": len(parent_chunks),
            "total_child_chunks": len(child_chunks),
            "content_type_distribution": content_type_counts,
            "page_coverage": {
                "pages_with_content": len(pages_covered),
                "page_range": [min_page, max_page],
            },
            "processing_status": task.processing_status,
            "errors_encountered": len(task.error_log),
            "assembly_timestamp": datetime.utcnow().isoformat(),
        }

    def _build_footnote_index(self, child_chunks: List[Dict]) -> List[Dict[str, Any]]:
        """
        P4-1: Build a flat index of all footnotes for easy lookup.

        Extracts footnote chunks from child_chunks and creates a structured index
        separate from main content flow, facilitating frontend footnote display.

        Args:
            child_chunks: Serialized child chunk dictionaries

        Returns:
            List of footnote index entries with metadata
        """
        footnotes = []

        for chunk in child_chunks:
            if chunk.get("content_type") != "footnote":
                continue

            # Extract footnote number from content
            # Format: "[Footnote 7] Content..." or "[Footnote] Content..."
            footnote_num = self._extract_footnote_number(chunk.get("content", ""))

            footnotes.append({
                "footnote_number": footnote_num,
                "content": chunk["content"],
                "page_physical": chunk.get("source_page_physical"),
                "page_logical": chunk.get("source_page_logical"),
                "chunk_id": chunk.get("chunk_id"),
                "parent_section": chunk.get("hierarchy", {}),
            })

        return footnotes

    def _extract_footnote_number(self, content: str) -> Optional[str]:
        """
        Extract footnote number from footnote content.

        Args:
            content: Footnote content (e.g., "[Footnote 7] Text...")

        Returns:
            Footnote number as string, or None if not found
        """
        match = re.match(r'^\[Footnote\s+(\d+)\]', content)
        if match:
            return match.group(1)
        return None

    def _build_visual_asset_registry(
        self,
        child_chunks: List[Dict],
        parent_chunks: List[Dict],
    ) -> Dict[str, Any]:
        """
        P4-5: Build a flat registry of all tables, figures, and charts
        for frontend navigation.

        Args:
            child_chunks: Serialized child chunk dictionaries
            parent_chunks: Serialized parent chunk dictionaries

        Returns:
            {
                "tables": [{table_id, caption, page, section, chunk_id, row_count, col_count, ...}],
                "figures": [{figure_id, caption, page, section, chunk_id, ...}],
                "total_tables": N,
                "total_figures": M,
            }
        """
        tables = []
        figures = []

        # Build parent lookup
        parent_lookup = {p.get("chunk_id"): p for p in parent_chunks}

        for chunk in child_chunks:
            content_type = chunk.get("content_type", "")
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id", "")
            page = chunk.get("source_page_physical", 0)
            page_logical = chunk.get("source_page_logical")
            bbox = chunk.get("metadata", {}).get("location", {}).get("bbox", [])
            hierarchy = chunk.get("hierarchy", {})
            parent_id = chunk.get("parent_chunk_id")

            # Parent section context
            parent = parent_lookup.get(parent_id, {})
            parent_section = parent.get("toc_entry", "")

            if content_type == "table_markdown":
                # Extract table number and caption from content or context
                table_num, table_caption = self._extract_table_identity(content, hierarchy)

                # Count rows/cols from markdown
                lines = [l for l in content.split('\n') if l.strip().startswith('|')]
                row_count = max(0, len(lines) - 1)  # Exclude header separator
                col_count = len(lines[0].split('|')) - 2 if lines else 0  # Exclude edge pipes

                # Check for structured data
                structured = chunk.get("structured_data")

                tables.append({
                    "table_id": table_num or f"table_p{page}_{len(tables)+1}",
                    "caption": table_caption or f"Table on page {page + 1}",
                    "page_physical": page,
                    "page_logical": page_logical,
                    "bbox": bbox,
                    "parent_section": parent_section,
                    "hierarchy": hierarchy,
                    "chunk_id": chunk_id,
                    "row_count": row_count,
                    "col_count": col_count,
                    "has_structured_data": structured is not None,
                })

            elif content_type == "image_caption":
                # Extract figure number
                fig_match = re.match(
                    r'(?:Figure|Fig\.?|Chart|Graph|Diagram|Map)\s*([\d.]+)',
                    content, re.IGNORECASE
                )
                fig_num = f"fig_{fig_match.group(1)}" if fig_match else None

                # P4-6: Classify visual subtype
                visual_subtype = self._classify_visual_subtype(content, hierarchy)

                figures.append({
                    "figure_id": fig_num or f"fig_p{page}_{len(figures)+1}",
                    "caption": content[:200],
                    "page_physical": page,
                    "page_logical": page_logical,
                    "bbox": bbox,
                    "parent_section": parent_section,
                    "hierarchy": hierarchy,
                    "chunk_id": chunk_id,
                    "visual_subtype": visual_subtype,  # P4-6
                })

        return {
            "tables": tables,
            "figures": figures,
            "total_tables": len(tables),
            "total_figures": len(figures),
        }

    def _extract_table_identity(
        self, content: str, hierarchy: Dict
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        P4-5: Extract table number and caption from table content or context.

        Args:
            content: Table markdown content
            hierarchy: Chunk hierarchy dict

        Returns:
            (table_number, table_caption) tuple
        """
        # Check first line for "Table X.X: Caption"
        first_line = content.split('\n')[0] if content else ""

        table_match = re.match(
            r'(?:\*\*)?(?:Table)\s*([\d.]+)\s*[:\-–]?\s*(.+?)(?:\*\*)?$',
            first_line, re.IGNORECASE
        )
        if table_match:
            return f"table_{table_match.group(1)}", table_match.group(2).strip()

        # Check hierarchy for table references
        for val in hierarchy.values():
            table_match = re.match(
                r'(?:Table)\s*([\d.]+)\s*[:\-–]?\s*(.+)',
                str(val), re.IGNORECASE
            )
            if table_match:
                return f"table_{table_match.group(1)}", table_match.group(2).strip()

        return None, None

    def _classify_visual_subtype(self, caption: str, hierarchy: Dict) -> str:
        """
        P4-6: Classify visual element subtype based on caption and context.

        Args:
            caption: Image caption text
            hierarchy: Chunk hierarchy dict

        Returns:
            Subtype: "chart", "map", "flowchart", "diagram", "photo", "data_visualization", "unknown"
        """
        VISUAL_SUBTYPE_KEYWORDS = {
            "chart": ["chart", "graph", "trend", "bar chart", "pie chart", "line graph", "histogram"],
            "map": ["map", "geographical", "district-wise", "state-wise map", "location"],
            "flowchart": ["flow chart", "flowchart", "process flow", "workflow", "decision tree"],
            "diagram": ["diagram", "schematic", "structure", "organization", "org chart"],
            "photo": ["photograph", "photo", "image of", "construction site", "physical verification"],
        }

        context = (caption + " " + " ".join(str(v) for v in hierarchy.values())).lower()

        for subtype, keywords in VISUAL_SUBTYPE_KEYWORDS.items():
            if any(kw in context for kw in keywords):
                return subtype

        return "unknown"

    def _write_json(self, data: Dict[str, Any], output_path: Path) -> None:
        """
        Write JSON data to file with proper formatting.
        """

        def json_serial(obj):
            """JSON serializer for objects not serializable by default json code"""
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            if hasattr(obj, "item"):  # Handle numpy types if any
                return obj.item()
            return str(obj)  # Fallback to string

        with open(output_path, "w", encoding="utf-8") as f:
            # FIX: Added default=json_serial to handle Pandas Timestamps
            json.dump(data, f, indent=2, ensure_ascii=False, default=json_serial)

    def _update_manifest(
        self,
        report_id: str,
        parent_chunks: List[ParentChunk],
        child_chunks: List[ChildChunk],
        output_path: Path,
    ) -> None:
        """
        Update corpus-level manifest with document stats.

        Args:
            report_id: Report identifier
            parent_chunks: List of parent chunks
            child_chunks: List of child chunks
            output_path: Path to output file
        """
        # Check if report already exists in manifest
        existing_reports = [
            r for r in self.manifest["reports"] if r["report_id"] == report_id
        ]

        if existing_reports:
            # Update existing entry
            for report in self.manifest["reports"]:
                if report["report_id"] == report_id:
                    report.update(
                        {
                            "status": "completed",
                            "parent_chunks": len(parent_chunks),
                            "child_chunks": len(child_chunks),
                            "output_file": output_path.name,
                            "last_updated": datetime.utcnow().isoformat(),
                        }
                    )
        else:
            # Add new entry
            self.manifest["reports"].append(
                {
                    "report_id": report_id,
                    "status": "completed",
                    "parent_chunks": len(parent_chunks),
                    "child_chunks": len(child_chunks),
                    "output_file": output_path.name,
                    "last_updated": datetime.utcnow().isoformat(),
                }
            )

        # Update totals
        self.manifest["total_reports"] = len(self.manifest["reports"])
        self.manifest["total_parent_chunks"] = sum(
            r["parent_chunks"] for r in self.manifest["reports"]
        )
        self.manifest["total_child_chunks"] = sum(
            r["child_chunks"] for r in self.manifest["reports"]
        )
        self.manifest["last_updated"] = datetime.utcnow().isoformat()

        # Save manifest
        self._write_json(self.manifest, self.manifest_path)

    def get_corpus_stats(self) -> Dict[str, Any]:
        """
        Get current corpus statistics from manifest.

        Returns:
            Dictionary with corpus-level statistics
        """
        return {
            "total_reports": self.manifest["total_reports"],
            "total_parent_chunks": self.manifest["total_parent_chunks"],
            "total_child_chunks": self.manifest["total_child_chunks"],
            "reports_completed": len(
                [r for r in self.manifest["reports"] if r["status"] == "completed"]
            ),
        }
