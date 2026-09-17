"""
Chart Extractor Service for P2-2 Chart Data Extraction.

This module orchestrates the extraction of structured data from chart images
using Claude Vision via Anthropic Batch API. It identifies chart chunks,
submits them for vision analysis, and merges the extracted data back into
the processed JSON files.
"""

import os
import json
import base64
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from anthropic import Anthropic

from src.core.chart_contracts import (
    StructuredChart,
    ChartType,
    create_chart_from_dict,
    validate_chart_extraction
)
from src.batch_pipeline.batch_service import BatchService


class ChartExtractorService:
    """
    Orchestrates chart data extraction using Claude Vision via Anthropic Batch API.

    Usage:
        service = ChartExtractorService()

        # Submit chart extraction batch
        job_id = service.submit_chart_extraction_batch(json_files)

        # Check status
        status = service.get_chart_extraction_status(job_id)

        # Process results when complete
        service.process_chart_results(job_id)
    """

    def __init__(
        self,
        batch_jobs_dir: str = "data/batch_jobs",
        processed_dir: str = "data/processed",
        model: str = "claude-sonnet-5",
        max_tokens: int = 3000,
        confidence_threshold: float = 0.5,
    ):
        """
        Initialize ChartExtractorService.

        Args:
            batch_jobs_dir: Directory for batch job tracking
            processed_dir: Directory with processed report JSONs
            model: Claude model to use for vision analysis
            max_tokens: Max tokens per vision response
            confidence_threshold: Minimum confidence to accept extraction
        """
        self.batch_jobs_dir = Path(batch_jobs_dir)
        self.processed_dir = Path(processed_dir)
        self.chart_extraction_dir = self.batch_jobs_dir / "chart_extraction"
        self.chart_extraction_dir.mkdir(parents=True, exist_ok=True)

        self.model = model
        self.max_tokens = max_tokens
        self.confidence_threshold = confidence_threshold

        # Initialize Anthropic client
        self.client = Anthropic()

        # Initialize batch service for Anthropic Batch API
        self.batch_service = BatchService(
            batch_jobs_dir=str(self.batch_jobs_dir),
            processed_dir=str(self.processed_dir)
        )

    def submit_chart_extraction_batch(
        self,
        json_files: List[Path],
        skip_existing: bool = True,
        force_reextract: bool = False
    ) -> str:
        """
        Submit chart extraction batch job for multiple reports.

        Args:
            json_files: List of *_chunks.json file paths
            skip_existing: Skip charts that already have structured_data
            force_reextract: Re-extract even if structured_data exists

        Returns:
            job_id for tracking (format: chart_extraction_YYYYMMDD_HHMMSS)
        """
        job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        print(f"\n🔍 Identifying charts for extraction...")

        # Collect all chart extraction requests
        requests = []
        id_mapping = {}
        stats = {
            "total_reports": len(json_files),
            "total_charts": 0,
            "charts_to_extract": 0,
            "charts_skipped_existing": 0,
            "charts_skipped_missing_image": 0,
        }

        for json_path in json_files:
            with open(json_path) as f:
                data = json.load(f)

            report_id = data["report_metadata"]["report_id"]
            chunks = data.get("child_chunks", [])

            # Identify charts needing extraction
            chart_chunks = self._identify_charts_for_extraction(
                chunks,
                skip_existing=(skip_existing and not force_reextract)
            )

            stats["total_charts"] += len([
                c for c in chunks if c.get("content_type") == "chart_data_path"
            ])

            for chunk in chart_chunks:
                image_path = chunk.get("content")

                # Verify image exists
                if not image_path or not Path(image_path).exists():
                    stats["charts_skipped_missing_image"] += 1
                    print(f"⚠️  Chart image not found: {image_path}")
                    continue

                # Build vision request
                try:
                    vision_request = self._build_vision_request(chunk, image_path)
                except Exception as e:
                    print(f"❌ Error building vision request for {chunk.get('chunk_id')}: {e}")
                    continue

                custom_id = f"{report_id[:30]}_{chunk['chunk_id'][:25]}"
                id_mapping[custom_id] = {
                    "report_id": report_id,
                    "chunk_id": chunk["chunk_id"],
                    "image_path": image_path,
                    "json_file": str(json_path),
                }

                requests.append({
                    "custom_id": custom_id,
                    "params": vision_request
                })

                stats["charts_to_extract"] += 1

            if chart_chunks:
                skipped = len([
                    c for c in chunks
                    if c.get("content_type") == "chart_data_path"
                    and c.get("structured_data")
                ])
                stats["charts_skipped_existing"] += skipped

        if not requests:
            print("\n✅ No charts to extract (all already extracted or no charts found)")
            return None

        # Save ID mapping
        mapping_path = self.chart_extraction_dir / f"chart_extraction_{job_timestamp}_mapping.json"
        with open(mapping_path, "w") as f:
            json.dump(id_mapping, f, indent=2)

        print(f"\n📊 Chart Extraction Statistics:")
        print(f"   Total reports: {stats['total_reports']}")
        print(f"   Total charts: {stats['total_charts']}")
        print(f"   Charts to extract: {stats['charts_to_extract']}")
        print(f"   Charts skipped (existing): {stats['charts_skipped_existing']}")
        print(f"   Charts skipped (missing image): {stats['charts_skipped_missing_image']}")

        # Submit to Anthropic Batch API
        print(f"\n📤 Submitting {len(requests)} charts to Anthropic Batch API...")

        try:
            batch = self.client.messages.batches.create(requests=requests)
            batch_id = batch.id
        except Exception as e:
            print(f"❌ Error submitting batch: {e}")
            raise

        print(f"✅ Batch submitted: {batch_id}")

        # Create job tracker
        job_tracker = {
            "job_id": f"chart_extraction_{job_timestamp}",
            "job_timestamp": job_timestamp,
            "created_at": datetime.now().isoformat(),
            "status": "submitted",
            "batch_id": batch_id,
            "model": self.model,
            "request_count": len(requests),
            "reports_processed": [f.stem.replace("_chunks", "") for f in json_files],
            "mapping_file": str(mapping_path),
            "statistics": stats,
        }

        tracker_path = self.chart_extraction_dir / f"chart_extraction_{job_timestamp}.json"
        with open(tracker_path, "w") as f:
            json.dump(job_tracker, f, indent=2)

        print(f"\n✅ Chart extraction job created: {job_tracker['job_id']}")
        print(f"   Batch ID: {batch_id}")
        print(f"   Charts submitted: {len(requests)}")

        return job_tracker["job_id"]

    def get_chart_extraction_status(self, job_id: str) -> Dict:
        """
        Get status of chart extraction job.

        Args:
            job_id: Job ID returned from submit_chart_extraction_batch

        Returns:
            Job tracker dict with current status
        """
        tracker_path = self.chart_extraction_dir / f"{job_id}.json"

        if not tracker_path.exists():
            raise ValueError(f"Job not found: {job_id}")

        with open(tracker_path) as f:
            tracker = json.load(f)

        # Update batch status
        batch_id = tracker.get("batch_id")
        if batch_id:
            try:
                batch = self.client.messages.batches.retrieve(batch_id)

                tracker["batch_status"] = batch.processing_status
                tracker["request_counts"] = {
                    "total": batch.request_counts.processing + batch.request_counts.succeeded + batch.request_counts.errored + batch.request_counts.canceled + batch.request_counts.expired,
                    "processing": batch.request_counts.processing,
                    "succeeded": batch.request_counts.succeeded,
                    "errored": batch.request_counts.errored,
                    "canceled": batch.request_counts.canceled,
                    "expired": batch.request_counts.expired,
                }

                # Update overall status
                if batch.processing_status == "ended":
                    tracker["status"] = "ready_for_processing"
                elif batch.processing_status in ["in_progress", "finalizing"]:
                    tracker["status"] = "processing"

            except Exception as e:
                print(f"⚠️  Error fetching batch status: {e}")
                tracker["batch_status"] = "error"
                tracker["error"] = str(e)

        # Save updated tracker
        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)

        return tracker

    def process_chart_results(self, job_id: str) -> Dict:
        """
        Process completed chart extraction results and merge into JSONs.

        Args:
            job_id: Job ID to process

        Returns:
            Summary of processed results
        """
        tracker_path = self.chart_extraction_dir / f"{job_id}.json"

        with open(tracker_path) as f:
            tracker = json.load(f)

        batch_id = tracker.get("batch_id")
        if not batch_id:
            raise ValueError("No batch_id in tracker")

        # Check if batch is complete
        status = self.get_chart_extraction_status(job_id)
        if status.get("status") != "ready_for_processing":
            print(f"⚠️  Batch not ready: status = {status.get('batch_status')}")
            return {"error": "Batch not complete", "status": status.get("batch_status")}

        # Load ID mapping
        with open(tracker["mapping_file"]) as f:
            id_mapping = json.load(f)

        print(f"\n📥 Downloading results for batch {batch_id}...")

        # Retrieve batch results
        try:
            results_response = self.client.messages.batches.results(batch_id)
        except Exception as e:
            print(f"❌ Error downloading results: {e}")
            raise

        # Parse results
        all_results = []
        for line in results_response.text.strip().split("\n"):
            if not line:
                continue
            result = json.loads(line)
            all_results.append(result)

        print(f"✅ Downloaded {len(all_results)} results")

        # Group by report and process
        results_by_report = {}
        success_count = 0
        error_count = 0
        low_confidence_count = 0

        for result in all_results:
            custom_id = result.get("custom_id")
            mapping = id_mapping.get(custom_id, {})
            report_id = mapping.get("report_id")
            chunk_id = mapping.get("chunk_id")
            json_file = mapping.get("json_file")

            if not report_id or not chunk_id:
                print(f"⚠️  Skipping result with missing mapping: {custom_id}")
                continue

            # Parse result
            if result.get("result", {}).get("type") == "succeeded":
                try:
                    # Extract content from response
                    message = result["result"]["message"]
                    content_blocks = message.get("content", [])

                    # Find text block with JSON
                    chart_json = None
                    for block in content_blocks:
                        if block.get("type") == "text":
                            chart_json = block.get("text")
                            break

                    if not chart_json:
                        error_count += 1
                        print(f"❌ No content in result for {custom_id}")
                        continue

                    # Parse JSON response
                    chart_data = json.loads(chart_json)

                    # Create StructuredChart
                    chart = create_chart_from_dict(chart_data)

                    # Validate
                    warnings = validate_chart_extraction(chart)
                    if warnings:
                        print(f"⚠️  Validation warnings for {custom_id}:")
                        for w in warnings:
                            print(f"     - {w}")

                    # Check confidence
                    if chart.confidence < self.confidence_threshold:
                        low_confidence_count += 1
                        print(f"⚠️  Low confidence ({chart.confidence:.2f}) for {custom_id}")

                    # Group by report
                    if report_id not in results_by_report:
                        results_by_report[report_id] = []

                    results_by_report[report_id].append({
                        "chunk_id": chunk_id,
                        "json_file": json_file,
                        "chart_data": chart.to_dict(),
                        "success": True,
                        "error": None,
                    })

                    success_count += 1

                except Exception as e:
                    error_count += 1
                    print(f"❌ Error parsing result for {custom_id}: {e}")
                    if report_id not in results_by_report:
                        results_by_report[report_id] = []
                    results_by_report[report_id].append({
                        "chunk_id": chunk_id,
                        "json_file": json_file,
                        "chart_data": None,
                        "success": False,
                        "error": str(e),
                    })

            else:
                # Error result
                error_type = result.get("result", {}).get("type", "unknown")
                error_msg = result.get("result", {}).get("error", {}).get("message", "Unknown error")
                error_count += 1
                print(f"❌ Batch API error for {custom_id}: {error_type} - {error_msg}")

                if report_id not in results_by_report:
                    results_by_report[report_id] = []
                results_by_report[report_id].append({
                    "chunk_id": chunk_id,
                    "json_file": json_file,
                    "chart_data": None,
                    "success": False,
                    "error": f"{error_type}: {error_msg}",
                })

        # Update JSON files with extracted chart data
        print(f"\n📝 Updating processed JSON files...")

        reports_updated = 0
        chunks_updated = 0

        for report_id, results in results_by_report.items():
            # Group by JSON file
            files_to_update = {}
            for r in results:
                json_file = r["json_file"]
                if json_file not in files_to_update:
                    files_to_update[json_file] = []
                files_to_update[json_file].append(r)

            # Update each JSON file
            for json_file, file_results in files_to_update.items():
                try:
                    updated = self._update_json_with_chart_data(json_file, file_results)
                    if updated:
                        reports_updated += 1
                        chunks_updated += len([r for r in file_results if r["success"]])
                except Exception as e:
                    print(f"❌ Error updating {json_file}: {e}")

        # Save per-report results for reference
        for report_id, results in results_by_report.items():
            output_path = self.chart_extraction_dir / f"{report_id}_charts.json"
            chart_doc = {
                "report_id": report_id,
                "processed_at": datetime.now().isoformat(),
                "results": results,
                "success_count": sum(1 for r in results if r["success"]),
                "error_count": sum(1 for r in results if not r["success"]),
            }
            with open(output_path, "w") as f:
                json.dump(chart_doc, f, indent=2, ensure_ascii=False)

        # Update tracker
        summary = {
            "success": success_count,
            "errors": error_count,
            "low_confidence": low_confidence_count,
            "reports_updated": reports_updated,
            "chunks_updated": chunks_updated,
        }

        tracker["status"] = "completed"
        tracker["completed_at"] = datetime.now().isoformat()
        tracker["summary"] = summary

        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)

        print(f"\n✅ Chart extraction complete!")
        print(f"   Successful: {success_count}")
        print(f"   Errors: {error_count}")
        print(f"   Low confidence: {low_confidence_count}")
        print(f"   Reports updated: {reports_updated}")
        print(f"   Chunks updated: {chunks_updated}")

        return summary

    # ========== Helper Methods ==========

    def _identify_charts_for_extraction(
        self,
        chunks: List[Dict],
        skip_existing: bool = True
    ) -> List[Dict]:
        """
        Identify chart chunks that need extraction.

        Args:
            chunks: List of ChildChunk dicts
            skip_existing: Skip charts with existing structured_data

        Returns:
            List of chart chunks to process
        """
        chart_chunks = []

        for chunk in chunks:
            if chunk.get("content_type") != "chart_data_path":
                continue

            # Skip if structured_data already exists
            if skip_existing and chunk.get("structured_data"):
                continue

            chart_chunks.append(chunk)

        return chart_chunks

    def _build_vision_request(self, chunk: Dict, image_path: str) -> Dict:
        """
        Build vision request for Anthropic Batch API.

        Args:
            chunk: ChildChunk dict with chart metadata
            image_path: Path to chart image file

        Returns:
            Request params dict for Anthropic API
        """
        # Encode image as base64
        image_base64 = self._encode_image_base64(image_path)

        # Build context from chunk
        context_text = self._get_chart_context(chunk)

        # Import prompt builder (will create next)
        from src.batch_pipeline.prompts.chart_extraction import build_chart_prompt

        # Build prompt
        prompt = build_chart_prompt(chunk, context_text)

        # Build Anthropic request
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        }

    def _encode_image_base64(self, image_path: str) -> str:
        """
        Encode image as base64 string.

        Args:
            image_path: Path to image file

        Returns:
            Base64 encoded string
        """
        with open(image_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def _get_chart_context(self, chunk: Dict) -> str:
        """
        Build context text from chunk metadata.

        Args:
            chunk: ChildChunk dict

        Returns:
            Context string for prompt
        """
        lines = []

        # Add hierarchy
        hierarchy = chunk.get("hierarchy", {})
        if hierarchy:
            hierarchy_str = " > ".join(
                f"{k}: {v}" for k, v in hierarchy.items() if v
            )
            lines.append(f"Section: {hierarchy_str}")

        # Add page
        page = chunk.get("source_page_physical")
        if page is not None:
            lines.append(f"Page: {page + 1}")

        # Add any adjacent text content
        content = chunk.get("content", "")
        if content and content.strip():
            lines.append(f"Adjacent text: {content[:500]}")  # Limit to 500 chars

        return "\n".join(lines)

    def _update_json_with_chart_data(
        self,
        json_file: str,
        results: List[Dict]
    ) -> bool:
        """
        Update JSON file with extracted chart data.

        Args:
            json_file: Path to JSON file
            results: List of chart extraction results

        Returns:
            True if updated successfully
        """
        try:
            # Load JSON
            with open(json_file) as f:
                data = json.load(f)

            # Update each chunk
            updated_count = 0
            for result in results:
                if not result["success"]:
                    continue

                chunk_id = result["chunk_id"]
                chart_data = result["chart_data"]

                # Find chunk and update
                for chunk in data.get("child_chunks", []):
                    if chunk.get("chunk_id") == chunk_id:
                        chunk["structured_data"] = chart_data
                        updated_count += 1
                        break

            if updated_count > 0:
                # Save updated JSON
                with open(json_file, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                print(f"✅ Updated {updated_count} charts in {Path(json_file).name}")
                return True
            else:
                print(f"⚠️  No chunks updated in {Path(json_file).name}")
                return False

        except Exception as e:
            print(f"❌ Error updating {json_file}: {e}")
            return False
