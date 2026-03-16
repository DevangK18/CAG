"""
P2-1 LLM-Augmented Enrichment Service.

Main orchestrator for Phase 2 enrichment workflow:
1. Route chunks to appropriate LLM provider (OpenAI vs Anthropic)
2. Submit batch jobs to both providers
3. Track job status
4. Process and merge results

Architecture:
- OpenAI Batch API: High volume, simple extraction (GPT-4o-mini)
- Anthropic Batch API: Complex analysis requiring deep reasoning (Sonnet)
- File-based tracking: No database required

Usage:
    service = EnrichmentService()

    # Submit enrichment jobs
    job_id = service.submit_enrichment_batch(json_files)

    # Check status
    status = service.get_enrichment_status(job_id)

    # Process results when complete
    results = service.process_enrichment_results(job_id)
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from .enrichment_router import EnrichmentRouter, EnrichmentTask, RoutingDecision
from .openai_batch import OpenAIBatchService
from ..batch_service import BatchService as AnthropicBatchService
from ..prompts.finding_extraction import build_finding_prompt
from ..prompts.implicit_finding import build_implicit_prompt
from ..prompts.entity_extraction import build_entity_prompt


class EnrichmentService:
    """
    Main orchestrator for P2-1 LLM enrichment.

    Coordinates dual-provider batch processing:
    - Routes chunks based on complexity and value
    - Submits to OpenAI (volume) and Anthropic (complexity)
    - Tracks jobs and processes results
    - Merges with Phase 1 extractions
    """

    def __init__(
        self,
        batch_jobs_dir: str = "data/batch_jobs",
        processed_dir: str = "data/processed",
        use_openai_for_volume: bool = True,
    ):
        """
        Initialize enrichment service.

        Args:
            batch_jobs_dir: Base directory for batch job tracking
            processed_dir: Directory with processed report JSONs
            use_openai_for_volume: If False, route all to Anthropic
        """
        self.batch_jobs_dir = Path(batch_jobs_dir)
        self.processed_dir = Path(processed_dir)
        self.enrichment_dir = self.batch_jobs_dir / "enrichment"
        self.enrichment_dir.mkdir(parents=True, exist_ok=True)

        # Initialize services
        self.openai_service = (
            OpenAIBatchService(batch_jobs_dir=str(self.enrichment_dir))
            if use_openai_for_volume
            else None
        )

        self.anthropic_service = AnthropicBatchService(
            batch_jobs_dir=str(self.batch_jobs_dir),
            processed_dir=str(self.processed_dir),
        )

        self.router = EnrichmentRouter()

        print("✅ EnrichmentService initialized")
        print(f"   OpenAI enabled: {use_openai_for_volume}")
        print(f"   Enrichment dir: {self.enrichment_dir}")

    def submit_enrichment_batch(
        self,
        json_files: List[Path],
        skip_already_enriched: bool = True,
        report_type: str = "general",
    ) -> str:
        """
        Submit enrichment batch jobs for multiple reports.

        Workflow:
        1. Load chunks from each report JSON
        2. Route chunks to OpenAI or Anthropic based on complexity
        3. Submit batch jobs to both providers
        4. Create job tracker for status monitoring

        Args:
            json_files: List of *_chunks.json file paths
            skip_already_enriched: Skip chunks with existing findings
            report_type: Report type for routing (compliance/performance/financial)

        Returns:
            job_id for tracking (format: enrichment_YYYYMMDD_HHMMSS)
        """
        job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        print(f"\n{'='*70}")
        print(f"PHASE 2 - P2-1: LLM-AUGMENTED ENRICHMENT")
        print(f"{'='*70}")
        print(f"Job ID: enrichment_{job_timestamp}")
        print(f"Reports: {len(json_files)}")
        print(f"Report type: {report_type}")
        print(f"Skip enriched: {skip_already_enriched}")
        print(f"{'='*70}\n")

        # Update router with report type
        self.router = EnrichmentRouter(report_type=report_type)

        # Collect all routing decisions
        openai_requests = []
        anthropic_requests = []
        id_mapping = {}
        all_routing_stats = []

        for json_path in json_files:
            print(f"\n📄 Processing: {json_path.name}")

            with open(json_path) as f:
                data = json.load(f)

            report_id = data["report_metadata"]["report_id"]
            chunks = data.get("child_chunks", [])
            existing_findings = (
                data.get("semantic_enrichment", {}).get("findings", [])
            )

            print(f"   Report ID: {report_id}")
            print(f"   Total chunks: {len(chunks)}")
            print(f"   Existing findings: {len(existing_findings)}")

            # Get routing decisions
            decisions = self.router.route_chunks(chunks, existing_findings)

            # Get statistics
            stats = self.router.get_routing_statistics(decisions)
            all_routing_stats.append({"report_id": report_id, "stats": stats})

            print(f"   Routing decisions:")
            print(f"      Skip: {stats['by_provider']['skip']}")
            print(f"      OpenAI: {stats['by_provider']['openai']}")
            print(f"      Anthropic: {stats['by_provider']['anthropic']}")

            # Build requests for each provider
            for decision in decisions:
                if decision.provider == "skip":
                    continue

                # Find the chunk
                chunk = next(
                    (c for c in chunks if c["chunk_id"] == decision.chunk_id), None
                )
                if not chunk:
                    continue

                # Create custom_id for tracking (max 64 chars)
                custom_id = f"{report_id[:30]}_{decision.chunk_id[:20]}"

                # Save mapping
                id_mapping[custom_id] = {
                    "report_id": report_id,
                    "chunk_id": decision.chunk_id,
                    "task": decision.task.value,
                }

                # Build appropriate prompt
                if decision.task == EnrichmentTask.FINDING_EXTRACTION:
                    prompt = build_finding_prompt(chunk)
                elif decision.task == EnrichmentTask.IMPLICIT_FINDING:
                    prompt = build_implicit_prompt(chunk)
                elif decision.task == EnrichmentTask.ENTITY_EXTRACTION:
                    prompt = build_entity_prompt(chunk)
                elif decision.task == EnrichmentTask.COMPLEX_ANALYSIS:
                    # Complex analysis uses finding extraction with extended thinking
                    prompt = build_finding_prompt(chunk)
                else:
                    prompt = build_finding_prompt(chunk)  # Default

                request = {
                    "custom_id": custom_id,
                    "messages": [{"role": "user", "content": prompt}],
                }

                # Route to appropriate provider
                if decision.provider == "openai":
                    openai_requests.append(request)
                elif decision.provider == "anthropic":
                    anthropic_requests.append(request)

        # Save ID mapping
        mapping_path = self.enrichment_dir / f"enrichment_{job_timestamp}_mapping.json"
        with open(mapping_path, "w") as f:
            json.dump(id_mapping, f, indent=2)

        print(f"\n💾 Saved ID mapping: {mapping_path}")

        # Submit batches
        openai_batch_id = None
        anthropic_batch_id = None

        if openai_requests and self.openai_service:
            print(f"\n📤 Submitting {len(openai_requests)} requests to OpenAI...")
            openai_batch_id = self.openai_service.submit_batch(
                openai_requests,
                task_type="finding_extraction",
                job_timestamp=job_timestamp,
            )

        if anthropic_requests:
            print(
                f"\n📤 Submitting {len(anthropic_requests)} requests to Anthropic..."
            )
            anthropic_batch_id = self._submit_anthropic_enrichment(
                anthropic_requests, job_timestamp
            )

        # Create job tracker
        job_tracker = {
            "job_id": f"enrichment_{job_timestamp}",
            "job_timestamp": job_timestamp,
            "created_at": datetime.now().isoformat(),
            "status": "submitted",
            "openai_batch": {
                "batch_id": openai_batch_id,
                "status": "processing" if openai_batch_id else "skipped",
                "request_count": len(openai_requests),
            },
            "anthropic_batch": {
                "batch_id": anthropic_batch_id,
                "status": "processing" if anthropic_batch_id else "skipped",
                "request_count": len(anthropic_requests),
            },
            "reports_processed": [
                f.stem.replace("_chunks", "") for f in json_files
            ],
            "routing_statistics": all_routing_stats,
            "mapping_file": str(mapping_path),
            "completed_at": None,
        }

        tracker_path = self.enrichment_dir / f"enrichment_{job_timestamp}.json"
        with open(tracker_path, "w") as f:
            json.dump(job_tracker, f, indent=2)

        print(f"\n✅ Enrichment job created: {job_tracker['job_id']}")
        print(f"   Tracker: {tracker_path}")
        print(f"   OpenAI requests: {len(openai_requests)}")
        print(f"   Anthropic requests: {len(anthropic_requests)}")
        print(f"\n{'='*70}")

        return job_tracker["job_id"]

    def _submit_anthropic_enrichment(
        self, requests: List[Dict], job_timestamp: str
    ) -> str:
        """Submit complex analysis requests to Anthropic batch API."""
        from anthropic import Anthropic

        client = Anthropic()

        batch_requests = []
        for req in requests:
            batch_requests.append(
                {
                    "custom_id": req["custom_id"],
                    "params": {
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 2000,
                        "messages": req["messages"],
                    },
                }
            )

        batch = client.messages.batches.create(requests=batch_requests)

        print(f"   Anthropic batch ID: {batch.id}")
        return batch.id

    def get_enrichment_status(self, job_id: str) -> Dict:
        """
        Get current status of enrichment job.

        Updates tracker file with latest batch statuses.

        Args:
            job_id: Job ID from submit_enrichment_batch()

        Returns:
            Updated tracker dict with current status
        """
        tracker_path = self.enrichment_dir / f"{job_id}.json"

        if not tracker_path.exists():
            raise ValueError(f"Job not found: {job_id}")

        with open(tracker_path) as f:
            tracker = json.load(f)

        # Update OpenAI status
        if tracker["openai_batch"]["batch_id"]:
            openai_status = self.openai_service.get_batch_status(
                tracker["openai_batch"]["batch_id"]
            )
            tracker["openai_batch"]["status"] = openai_status["status"]
            tracker["openai_batch"]["progress"] = openai_status["request_counts"]

        # Update Anthropic status
        if tracker["anthropic_batch"]["batch_id"]:
            anthropic_status = self.anthropic_service.get_batch_status(
                tracker["anthropic_batch"]["batch_id"]
            )
            tracker["anthropic_batch"]["status"] = anthropic_status["status"]
            tracker["anthropic_batch"]["progress"] = anthropic_status[
                "request_counts"
            ]

        # Update overall status
        openai_done = (
            not tracker["openai_batch"]["batch_id"]
            or tracker["openai_batch"]["status"] == "completed"
        )
        anthropic_done = (
            not tracker["anthropic_batch"]["batch_id"]
            or tracker["anthropic_batch"]["status"] == "ended"
        )

        if openai_done and anthropic_done:
            tracker["status"] = "ready_for_processing"
        elif tracker["status"] == "submitted":
            tracker["status"] = "processing"

        # Save updated tracker
        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)

        return tracker

    def process_enrichment_results(self, job_id: str) -> Dict:
        """
        Process completed enrichment results and save per-report.

        Downloads results from both providers, merges, and saves
        per-report enrichment JSON files.

        Args:
            job_id: Job ID from submit_enrichment_batch()

        Returns:
            Summary dict with success/failure counts
        """
        tracker_path = self.enrichment_dir / f"{job_id}.json"

        with open(tracker_path) as f:
            tracker = json.load(f)

        # Check if ready
        if tracker["status"] != "ready_for_processing":
            raise ValueError(
                f"Job not ready for processing. Status: {tracker['status']}"
            )

        print(f"\n{'='*70}")
        print(f"PROCESSING ENRICHMENT RESULTS: {job_id}")
        print(f"{'='*70}\n")

        # Load ID mapping
        with open(tracker["mapping_file"]) as f:
            id_mapping = json.load(f)

        # Collect all results
        all_results = []

        # Get OpenAI results
        if tracker["openai_batch"]["batch_id"]:
            print(f"📥 Downloading OpenAI results...")
            openai_results = self.openai_service.get_batch_results(
                tracker["openai_batch"]["batch_id"]
            )
            for r in openai_results:
                r["provider"] = "openai"
            all_results.extend(openai_results)
            print(f"   Retrieved: {len(openai_results)} results")

        # Get Anthropic results
        if tracker["anthropic_batch"]["batch_id"]:
            print(f"📥 Downloading Anthropic results...")
            anthropic_results = self.anthropic_service.get_batch_results(
                tracker["anthropic_batch"]["batch_id"]
            )
            for r in anthropic_results:
                r["provider"] = "anthropic"
            all_results.extend(anthropic_results)
            print(f"   Retrieved: {len(anthropic_results)} results")

        # Group by report
        results_by_report = {}
        for result in all_results:
            mapping = id_mapping.get(result["custom_id"], {})
            report_id = mapping.get("report_id")

            if not report_id:
                continue

            if report_id not in results_by_report:
                results_by_report[report_id] = []

            results_by_report[report_id].append(
                {
                    "chunk_id": mapping.get("chunk_id"),
                    "task": mapping.get("task"),
                    "content": result.get("content"),
                    "error": result.get("error"),
                    "provider": result.get("provider"),
                }
            )

        # Save per-report results
        summary = {"success": 0, "failed": 0, "reports": []}

        for report_id, results in results_by_report.items():
            output_path = self.enrichment_dir / f"{report_id}_enrichment.json"

            enrichment_doc = {
                "report_id": report_id,
                "job_id": job_id,
                "processed_at": datetime.now().isoformat(),
                "results": results,
                "success_count": sum(1 for r in results if not r["error"]),
                "error_count": sum(1 for r in results if r["error"]),
            }

            with open(output_path, "w") as f:
                json.dump(enrichment_doc, f, indent=2, ensure_ascii=False)

            print(f"\n📄 {report_id}")
            print(f"   Success: {enrichment_doc['success_count']}")
            print(f"   Errors: {enrichment_doc['error_count']}")
            print(f"   Saved: {output_path}")

            summary["reports"].append(
                {
                    "report_id": report_id,
                    "success": enrichment_doc["success_count"],
                    "errors": enrichment_doc["error_count"],
                    "output_file": str(output_path),
                }
            )
            summary["success"] += enrichment_doc["success_count"]
            summary["failed"] += enrichment_doc["error_count"]

        # Update tracker
        tracker["status"] = "completed"
        tracker["completed_at"] = datetime.now().isoformat()
        tracker["summary"] = summary

        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)

        print(f"\n{'='*70}")
        print(f"✅ ENRICHMENT COMPLETE")
        print(f"   Total successes: {summary['success']}")
        print(f"   Total errors: {summary['failed']}")
        print(f"   Reports: {len(summary['reports'])}")
        print(f"{'='*70}\n")

        return summary
