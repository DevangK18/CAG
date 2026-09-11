"""
Batch Processing Service for Phase 10 - Gemini Native with Claude Fallback.

Key Features:
- Default to Gemini for GCP credit billing
- File-based job tracking (no database required)
- Organized folder structure for outputs
- Claude Batch API fallback available via USE_CLAUDE_BATCH=true

Phase 10a consists of three batch jobs:
1. Overview extraction (overview_batch) - Report-level metadata
2. Summary variants (summary_batch) - 5 styles: executive, journalist, deep_dive, simple, policy
3. Hierarchical summaries (hierarchical_batch) - RAPTOR chapter/section summaries for efficient RAG

Folder Structure:
    data/batch_jobs/
    ├── jobs/
    │   ├── job_YYYYMMDD_HHMMSS.json          # Job tracker
    │   └── job_YYYYMMDD_HHMMSS_mapping.json  # ID mapping
    ├── overviews/
    │   └── {report_id}_overview_llm.json
    ├── summaries/
    │   └── {report_id}_summaries.json
    └── hierarchical/                          # RAPTOR summaries
        └── {report_id}_hierarchical.json

Default: Gemini 3.5 Flash for GCP credit billing.
Set USE_CLAUDE_BATCH=true to use Anthropic Batch API instead.
"""

import os
import json
import time
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Literal, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Import trace emitter utilities
try:
    from src.parsing_pipeline.instrumentation import get_noop_emitter
except ImportError:
    # Fallback if instrumentation module not available
    def get_noop_emitter():
        class NoopEmitter:
            enabled = False
            def emit_decision(self, *args, **kwargs): pass
            def emit_io(self, *args, **kwargs): pass
            def emit_red_flag(self, *args, **kwargs): pass
            def emit_error(self, *args, **kwargs): pass
            def emit_sample(self, *args, **kwargs): pass
            def set_phase_status(self, *args, **kwargs): pass
        return NoopEmitter()

# Feature flag for batch processing mode
USE_CLAUDE_BATCH = os.getenv("USE_CLAUDE_BATCH", "false").lower() == "true"


def _short_id(report_id: str, prefix: str = "") -> str:
    """
    Create a short unique ID for batch custom_id (max 64 chars).
    Uses first 8 chars of MD5 hash + truncated report_id.
    """
    hash_part = hashlib.md5(report_id.encode()).hexdigest()[:8]
    max_report_len = 54 - len(prefix)
    truncated = (
        report_id[:max_report_len] if len(report_id) > max_report_len else report_id
    )

    if prefix:
        return f"{prefix}_{hash_part}_{truncated}"
    return f"{hash_part}_{truncated}"


def _serialize_datetime(obj):
    """Convert datetime objects to ISO format strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _ensure_serializable(data):
    """Recursively ensure all values in a dict are JSON serializable."""
    if isinstance(data, dict):
        return {k: _ensure_serializable(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_ensure_serializable(item) for item in data]
    elif isinstance(data, datetime):
        return data.isoformat()
    else:
        return data


class BatchService:
    """
    Manages batch processing operations for Phase 10.

    Default: Uses Gemini for GCP credit billing.
    Fallback: Set USE_CLAUDE_BATCH=true to use Anthropic Batch API.

    Usage:
        service = BatchService()
        batch_id = service.submit_overview_batch(json_files)
        # ... wait for completion ...
        status = service.get_batch_status(batch_id)
        results = service.get_batch_results(batch_id)
    """

    def __init__(
        self,
        batch_jobs_dir: str = "data/batch_jobs",
        processed_dir: str = "data/processed",
        trace_emitter=None,
    ):
        """
        Initialize BatchService with optional trace instrumentation.

        Args:
            batch_jobs_dir: Directory for batch job tracking files
            processed_dir: Directory with processed report JSONs
            trace_emitter: Optional TraceEmitter for Phase 10a instrumentation.
                          If None, uses noop emitter (no overhead).
        """
        self.use_claude = USE_CLAUDE_BATCH
        self._trace_emitter = trace_emitter or get_noop_emitter()

        # Initialize clients based on mode
        if self.use_claude:
            import anthropic
            self.client = anthropic.Anthropic()
            self._gemini_client = None
            logger.info("BatchService initialized with Claude Batch API")
        else:
            from google import genai
            self._gemini_client = genai.Client()
            self.client = None  # No Anthropic client needed
            logger.info("BatchService initialized with Gemini (GCP billing)")

        # Trace: Emit client mode selection decision
        self._trace_emitter.emit_decision(
            "10a",
            "batch_client_mode",
            "claude" if self.use_claude else "gemini",
            ["claude", "gemini"],
            f"USE_CLAUDE_BATCH={USE_CLAUDE_BATCH}",
        )

        # Base directories
        self.batch_jobs_dir = Path(batch_jobs_dir)
        self.processed_dir = Path(processed_dir)

        # Organized subdirectories within batch_jobs
        self.jobs_dir = self.batch_jobs_dir / "jobs"
        self.overviews_dir = self.batch_jobs_dir / "overviews"
        self.summaries_dir = self.batch_jobs_dir / "summaries"

        # Create all directories
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.overviews_dir.mkdir(parents=True, exist_ok=True)
        self.summaries_dir.mkdir(parents=True, exist_ok=True)

        # Model configuration
        if self.use_claude:
            # Claude models with Extended Thinking
            self.models = {
                "overview": "claude-sonnet-5",
                "executive": "claude-sonnet-5",
                "journalist": "claude-opus-5",
                "deep_dive": "claude-opus-5",
                "simple": "claude-sonnet-5",
                "policy": "claude-sonnet-5",
            }
        else:
            # Gemini models for GCP credit billing
            self.models = {
                "overview": "gemini-3.5-flash",
                "executive": "gemini-3.5-flash",
                "journalist": "gemini-3.5-flash",  # Use Flash for cost efficiency
                "deep_dive": "gemini-3.5-flash",
                "simple": "gemini-3.5-flash-lite",
                "policy": "gemini-3.5-flash",
            }

        # Max output tokens
        self.max_tokens = {
            "overview": 18000,
            "executive": 16000,
            "journalist": 20000,
            "deep_dive": 24000,
            "simple": 12000,
            "policy": 16000,
        }

        # Extended Thinking budget tokens (Claude only)
        self.thinking_budgets = {
            "overview": 5000,
            "executive": 8000,
            "journalist": 12000,
            "deep_dive": 16000,
            "simple": 6000,
            "policy": 10000,
        }

        # Concurrent processing settings (Gemini mode)
        self.max_workers = 5  # Parallel API calls for Gemini

        # Current job timestamp (set when creating job tracker)
        self._current_job_timestamp = None

    def _get_mapping_path(self, job_timestamp: str = None) -> Path:
        """Get the ID mapping file path for a specific job."""
        ts = job_timestamp or self._current_job_timestamp
        if ts:
            return self.jobs_dir / f"job_{ts}_mapping.json"
        # Fallback to find most recent mapping
        mapping_files = sorted(self.jobs_dir.glob("job_*_mapping.json"), reverse=True)
        return mapping_files[0] if mapping_files else self.jobs_dir / "id_mapping.json"

    def _save_id_mapping(self, mapping: dict, job_timestamp: str = None):
        """Save custom_id to report_id mapping for a specific job."""
        mapping_path = self._get_mapping_path(job_timestamp)

        existing = {}
        if mapping_path.exists():
            with open(mapping_path) as f:
                existing = json.load(f)
        existing.update(mapping)

        with open(mapping_path, "w") as f:
            json.dump(existing, f, indent=2)

        return mapping_path

    def _load_id_mapping(self, job_timestamp: str = None) -> dict:
        """Load custom_id to report_id mapping for a specific job."""
        mapping_path = self._get_mapping_path(job_timestamp)
        if mapping_path.exists():
            with open(mapping_path) as f:
                return json.load(f)

        # Fallback: find closest matching timestamp (handles slight timing differences)
        if job_timestamp:
            prefix = job_timestamp[:8]  # YYYYMMDD part
            candidates = sorted(self.jobs_dir.glob(f"job_{prefix}*_mapping.json"), reverse=True)
            if candidates:
                with open(candidates[0]) as f:
                    return json.load(f)

        return {}

    # ═══════════════════════════════════════════════════════════════════════
    # GEMINI PROCESSING HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _process_single_gemini(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        custom_id: str,
    ) -> dict:
        """Process a single request with Gemini."""
        from google.genai import types

        try:
            response = self._gemini_client.models.generate_content(
                model=model,
                contents=[types.Part.from_text(text=prompt)],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=max_tokens,
                ),
            )
            return {
                "custom_id": custom_id,
                "content": response.text,
                "error": None,
            }
        except Exception as e:
            logger.error(f"Gemini request failed for {custom_id}: {e}")
            return {
                "custom_id": custom_id,
                "content": None,
                "error": str(e),
            }

    def _process_batch_gemini(
        self,
        requests: list[dict],
        description: str = "batch",
    ) -> list[dict]:
        """Process multiple requests concurrently with Gemini."""
        results = []
        emitter = self._trace_emitter

        print(f"🚀 Processing {len(requests)} {description} requests with Gemini...")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._process_single_gemini,
                    req["prompt"],
                    req["model"],
                    req["max_tokens"],
                    req["custom_id"],
                ): req["custom_id"]
                for req in requests
            }

            completed = 0
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                completed += 1
                if completed % 10 == 0 or completed == len(requests):
                    print(f"   Progress: {completed}/{len(requests)}")

        success = sum(1 for r in results if r["error"] is None)
        failed = len(results) - success
        print(f"✅ {description} complete: {success}/{len(results)} succeeded")

        # Trace: Emit batch processing summary
        emitter.emit_io(
            "10a",
            {"requests": len(requests), "batch_type": description},
            {"success": success, "failed": failed},
        )

        # Red flag for high failure rate
        if failed > 0 and len(results) > 0:
            failure_rate = failed / len(results)
            if failure_rate > 0.1:  # More than 10% failures
                emitter.emit_red_flag(
                    "10a",
                    f"High {description} batch failure rate ({failure_rate*100:.1f}%)",
                    {"failed": failed, "total": len(results)},
                )

        return results

    # ═══════════════════════════════════════════════════════════════════════
    # BATCH SUBMISSION
    # ═══════════════════════════════════════════════════════════════════════

    def submit_overview_batch(
        self, json_files: list[Path], job_timestamp: str = None
    ) -> str:
        """
        Submit batch job for overview extraction (missing fields only).

        Args:
            json_files: List of *_chunks.json file paths
            job_timestamp: Optional timestamp to associate with this batch

        Returns:
            batch_id for tracking (or "gemini_sync" for Gemini mode)
        """
        # Auto-generate timestamp if none provided and none exists
        if not job_timestamp and not self._current_job_timestamp:
            self._current_job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            print(f"⚠️  No job timestamp set — auto-generated: {self._current_job_timestamp}")

        from .prompts.overview_extraction import build_overview_prompt

        requests = []
        id_mapping = {}

        for json_path in json_files:
            with open(json_path) as f:
                data = json.load(f)

            report_id = data["report_metadata"]["report_id"]
            prompt = build_overview_prompt(data)

            # Create short custom_id (max 64 chars)
            custom_id = _short_id(report_id, "ov")
            id_mapping[custom_id] = report_id

            if self.use_claude:
                requests.append(
                    {
                        "custom_id": custom_id,
                        "params": {
                            "model": self.models["overview"],
                            "max_tokens": self.max_tokens["overview"],
                            "thinking": {
                                "type": "adaptive",
                            },
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    }
                )
            else:
                # Gemini request format
                requests.append({
                    "custom_id": custom_id,
                    "prompt": prompt,
                    "model": self.models["overview"],
                    "max_tokens": self.max_tokens["overview"],
                })

        # Save ID mapping
        self._save_id_mapping(id_mapping, job_timestamp)

        # Trace: Emit overview batch submission
        emitter = self._trace_emitter
        emitter.emit_io(
            "10a",
            {"json_files": len(json_files)},
            {"overview_requests": len(requests), "model": self.models["overview"]},
        )

        if self.use_claude:
            # Submit batch using messages.batches API (SDK v0.77.0+)
            batch = self.client.messages.batches.create(requests=requests)
            print(f"✅ Overview batch submitted: {batch.id}")
            print(f"   Reports: {len(requests)}")

            emitter.emit_decision(
                "10a",
                "overview_batch_submission",
                "submitted",
                ["submitted", "failed"],
                f"Claude batch {batch.id}",
            )
            return batch.id
        else:
            # Process synchronously with Gemini
            results = self._process_batch_gemini(requests, "overview")
            # Save results immediately
            self._save_overview_results(results, id_mapping)

            success = sum(1 for r in results if r["error"] is None)
            emitter.emit_decision(
                "10a",
                "overview_batch_submission",
                "completed" if success == len(results) else "partial",
                ["completed", "partial", "failed"],
                f"Gemini sync: {success}/{len(results)} succeeded",
            )
            return f"gemini_sync_{self._current_job_timestamp}"

    def _save_overview_results(self, results: list[dict], id_mapping: dict):
        """Save Gemini overview results to files."""
        for result in results:
            custom_id = result["custom_id"]
            report_id = id_mapping.get(custom_id, custom_id)

            if result["error"]:
                logger.error(f"Overview failed for {report_id}: {result['error']}")
                continue

            output_path = self.get_overview_output_path(report_id)
            try:
                # Parse JSON response
                content = result["content"]
                # Try to extract JSON from the response
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)
                with open(output_path, "w") as f:
                    json.dump(parsed, f, indent=2)
                logger.info(f"Saved overview: {output_path}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse overview JSON for {report_id}: {e}")
                # Save raw content for debugging
                with open(output_path.with_suffix(".txt"), "w") as f:
                    f.write(result["content"])

    def submit_summary_batch(
        self, json_files: list[Path], job_timestamp: str = None
    ) -> str:
        """
        Submit batch job for all 5 summary variants.

        Args:
            json_files: List of *_chunks.json file paths
            job_timestamp: Optional timestamp to associate with this batch

        Returns:
            batch_id for tracking (or "gemini_sync" for Gemini mode)
        """
        # Auto-generate timestamp if none provided and none exists
        if not job_timestamp and not self._current_job_timestamp:
            self._current_job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            print(f"⚠️  No job timestamp set — auto-generated: {self._current_job_timestamp}")

        from .prompts.summary_variants import (
            build_summary_input,
            get_summary_prompt,
            VARIANTS,
        )

        requests = []
        id_mapping = {}

        for json_path in json_files:
            with open(json_path) as f:
                data = json.load(f)

            report_id = data["report_metadata"]["report_id"]
            summary_input = build_summary_input(data)

            for variant in VARIANTS:
                prompt = get_summary_prompt(variant, summary_input, data)

                # Create short custom_id with variant prefix (max 64 chars)
                variant_codes = {
                    "executive": "ex",
                    "journalist": "jo",
                    "deep_dive": "dd",
                    "simple": "si",
                    "policy": "po",
                }
                prefix = f"sm_{variant_codes[variant]}"
                custom_id = _short_id(report_id, prefix)
                id_mapping[custom_id] = {"report_id": report_id, "variant": variant}

                if self.use_claude:
                    requests.append(
                        {
                            "custom_id": custom_id,
                            "params": {
                                "model": self.models[variant],
                                "max_tokens": self.max_tokens[variant],
                                "thinking": {
                                    "type": "adaptive",
                                },
                                "messages": [{"role": "user", "content": prompt}],
                            },
                        }
                    )
                else:
                    # Gemini request format
                    requests.append({
                        "custom_id": custom_id,
                        "prompt": prompt,
                        "model": self.models[variant],
                        "max_tokens": self.max_tokens[variant],
                        "variant": variant,
                    })

        # Save ID mapping
        self._save_id_mapping(id_mapping, job_timestamp)

        # Trace: Emit summary batch submission
        emitter = self._trace_emitter
        emitter.emit_io(
            "10a",
            {"json_files": len(json_files), "variants": 5},
            {"summary_requests": len(requests)},
        )

        if self.use_claude:
            # Submit batch using messages.batches API (SDK v0.77.0+)
            batch = self.client.messages.batches.create(requests=requests)
            print(f"✅ Summary batch submitted: {batch.id}")
            print(f"   Reports: {len(json_files)}")
            print(f"   Total requests: {len(requests)} ({len(json_files)} × 5 variants)")

            emitter.emit_decision(
                "10a",
                "summary_batch_submission",
                "submitted",
                ["submitted", "failed"],
                f"Claude batch {batch.id} ({len(requests)} requests)",
            )
            return batch.id
        else:
            # Process synchronously with Gemini
            results = self._process_batch_gemini(requests, "summary")
            # Save results
            self._save_summary_results(results, id_mapping)

            success = sum(1 for r in results if r["error"] is None)
            emitter.emit_decision(
                "10a",
                "summary_batch_submission",
                "completed" if success == len(results) else "partial",
                ["completed", "partial", "failed"],
                f"Gemini sync: {success}/{len(results)} succeeded",
            )
            return f"gemini_sync_{self._current_job_timestamp}"

    def _save_summary_results(self, results: list[dict], id_mapping: dict):
        """Save Gemini summary results to files, grouped by report."""
        from collections import defaultdict

        # Group by report_id
        by_report = defaultdict(dict)

        for result in results:
            custom_id = result["custom_id"]
            mapping = id_mapping.get(custom_id, {})

            if isinstance(mapping, dict):
                report_id = mapping.get("report_id", custom_id)
                variant = mapping.get("variant", "unknown")
            else:
                report_id = mapping
                variant = "unknown"

            if result["error"]:
                logger.error(f"Summary {variant} failed for {report_id}: {result['error']}")
                continue

            by_report[report_id][variant] = result["content"]

        # Save per-report summary files
        for report_id, summaries in by_report.items():
            output_path = self.get_summary_output_path(report_id)
            with open(output_path, "w") as f:
                json.dump({
                    "report_id": report_id,
                    "generated_at": datetime.now().isoformat(),
                    "model": "gemini-3.5-flash",
                    "summaries": summaries,
                }, f, indent=2)
            logger.info(f"Saved summaries: {output_path}")

    # ═══════════════════════════════════════════════════════════════════════
    # BATCH STATUS & RESULTS
    # ═══════════════════════════════════════════════════════════════════════

    def get_batch_status(self, batch_id: str) -> dict:
        """Get current status of a batch job."""
        # Handle Gemini sync mode (already completed)
        if batch_id.startswith("gemini_sync"):
            return {
                "batch_id": batch_id,
                "status": "ended",
                "created_at": batch_id.split("_")[-1] if "_" in batch_id else None,
                "ended_at": datetime.now().isoformat(),
                "expires_at": None,
                "request_counts": {
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                },
                "is_complete": True,
            }

        if not self.client:
            raise ValueError("Claude client not available - using Gemini mode")

        batch = self.client.messages.batches.retrieve(batch_id)

        # Handle different SDK versions for request_counts
        request_counts = batch.request_counts

        if hasattr(request_counts, "total"):
            total = request_counts.total
            completed = request_counts.completed
            failed = request_counts.failed
        elif hasattr(request_counts, "processing"):
            # New SDK structure: processing, succeeded, errored, canceled, expired
            succeeded = getattr(request_counts, "succeeded", 0)
            errored = getattr(request_counts, "errored", 0)
            canceled = getattr(request_counts, "canceled", 0)
            expired = getattr(request_counts, "expired", 0)
            processing = getattr(request_counts, "processing", 0)

            completed = succeeded
            failed = errored + canceled + expired
            total = processing + succeeded + errored + canceled + expired
        else:
            try:
                rc_dict = (
                    request_counts.model_dump()
                    if hasattr(request_counts, "model_dump")
                    else vars(request_counts)
                )
                total = rc_dict.get(
                    "total",
                    rc_dict.get("processing", 0)
                    + rc_dict.get("succeeded", 0)
                    + rc_dict.get("errored", 0),
                )
                completed = rc_dict.get("completed", rc_dict.get("succeeded", 0))
                failed = rc_dict.get("failed", rc_dict.get("errored", 0))
            except:
                total = 0
                completed = 0
                failed = 0

        # Convert datetime objects to strings
        created_at = batch.created_at
        ended_at = batch.ended_at
        expires_at = batch.expires_at

        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        if isinstance(ended_at, datetime):
            ended_at = ended_at.isoformat()
        if isinstance(expires_at, datetime):
            expires_at = expires_at.isoformat()

        return {
            "batch_id": batch.id,
            "status": batch.processing_status,
            "created_at": created_at,
            "ended_at": ended_at,
            "expires_at": expires_at,
            "request_counts": {
                "total": total,
                "completed": completed,
                "failed": failed,
            },
            "is_complete": batch.processing_status == "ended",
        }

    def get_batch_results(self, batch_id: str, job_timestamp: str = None) -> list[dict]:
        """
        Download results from a completed batch.

        Returns:
            List of {custom_id, report_id, variant, content, thinking, error} dicts
        """
        results = []
        id_mapping = self._load_id_mapping(job_timestamp)

        for result in self.client.messages.batches.results(batch_id):
            custom_id = result.custom_id

            # Resolve report_id from mapping
            mapped = id_mapping.get(custom_id, custom_id)
            if isinstance(mapped, dict):
                report_id = mapped.get("report_id", custom_id)
                variant = mapped.get("variant")
            else:
                report_id = mapped
                variant = None

            item = {
                "custom_id": custom_id,
                "report_id": report_id,
                "variant": variant,
                "content": None,
                "thinking": None,
                "error": None,
            }

            if result.result.type == "errored":
                error_obj = result.result.error
                if hasattr(error_obj, "message"):
                    item["error"] = error_obj.message
                else:
                    item["error"] = str(error_obj)
            elif result.result.type == "succeeded":
                message = result.result.message
                for block in message.content:
                    if block.type == "thinking":
                        item["thinking"] = block.thinking
                    elif block.type == "text":
                        item["content"] = block.text
            elif result.result.type == "canceled":
                item["error"] = "Request was canceled"
            elif result.result.type == "expired":
                item["error"] = "Request expired"

            results.append(item)

        return results

    # ═══════════════════════════════════════════════════════════════════════
    # JOB TRACKING (File-based)
    # ═══════════════════════════════════════════════════════════════════════

    def create_job_tracker(
        self,
        overview_batch_id: str,
        summary_batch_id: str,
        report_ids: list[str],
        hierarchical_batch_id: str = None,
    ) -> Path:
        """
        Create a job tracking file for monitoring progress.

        Phase 10a consists of three batch jobs:
        1. Overview extraction (overview_batch)
        2. Summary variants (summary_batch)
        3. Hierarchical summaries (hierarchical_batch) - RAPTOR chapter/section summaries

        Args:
            overview_batch_id: Batch ID for overview extraction
            summary_batch_id: Batch ID for summary variants
            report_ids: List of report IDs being processed
            hierarchical_batch_id: Optional batch ID for hierarchical summaries

        Returns:
            Path to tracking file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_job_timestamp = timestamp

        tracker = {
            "job_id": f"phase10_{timestamp}",
            "job_timestamp": timestamp,
            "created_at": datetime.now().isoformat(),
            "status": "submitted",
            "overview_batch": {
                "batch_id": overview_batch_id,
                "status": "processing",
                "completed_at": None,
            },
            "summary_batch": {
                "batch_id": summary_batch_id,
                "status": "processing",
                "completed_at": None,
            },
            # Phase 10a Part 3: RAPTOR hierarchical summaries
            "hierarchical_batch": {
                "batch_id": hierarchical_batch_id or "N/A",
                "status": "processing" if hierarchical_batch_id else "skipped",
                "completed_at": None,
            },
            "reports": {
                rid: {
                    "overview_extracted": False,
                    "summaries_generated": [],
                    "hierarchical_generated": False,  # Track hierarchical completion
                }
                for rid in report_ids
            },
            "output_paths": {
                "job_tracker": f"jobs/job_{timestamp}.json",
                "id_mapping": f"jobs/job_{timestamp}_mapping.json",
                "overviews_dir": "overviews/",
                "summaries_dir": "summaries/",
                "hierarchical_dir": "hierarchical/",  # Added for RAPTOR outputs
            },
            "completed_at": None,
        }

        tracker_path = self.jobs_dir / f"job_{timestamp}.json"
        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)

        print(f"📋 Job tracker created: {tracker_path}")
        return tracker_path

    def submit_phase_10a_batches(
        self,
        json_files: list[Path],
        include_hierarchical: bool = True,
    ) -> tuple[str, str, str | None, Path]:
        """
        Submit all Phase 10a batch jobs together.

        Phase 10a consists of:
        1. Overview extraction
        2. Summary variants (5 types)
        3. Hierarchical summaries (RAPTOR chapter/section) - optional

        Args:
            json_files: List of *_chunks.json file paths
            include_hierarchical: Whether to include RAPTOR hierarchical summaries

        Returns:
            Tuple of (overview_batch_id, summary_batch_id, hierarchical_batch_id, tracker_path)
        """
        # Generate job timestamp
        job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_job_timestamp = job_timestamp

        # Extract report IDs
        report_ids = []
        for json_path in json_files:
            with open(json_path) as f:
                data = json.load(f)
            report_ids.append(data["report_metadata"]["report_id"])

        print(f"📦 Submitting Phase 10a batches for {len(report_ids)} reports...")
        print(f"   Job timestamp: {job_timestamp}")

        # Submit overview batch
        overview_batch_id = self.submit_overview_batch(json_files, job_timestamp)

        # Submit summary batch
        summary_batch_id = self.submit_summary_batch(json_files, job_timestamp)

        # Submit hierarchical batch (optional)
        hierarchical_batch_id = None
        if include_hierarchical:
            hierarchical_batch_id = self.submit_hierarchical_batch(json_files, job_timestamp)

        # Create unified job tracker
        tracker_path = self.create_job_tracker(
            overview_batch_id=overview_batch_id,
            summary_batch_id=summary_batch_id,
            report_ids=report_ids,
            hierarchical_batch_id=hierarchical_batch_id,
        )

        print(f"\n✅ Phase 10a batches submitted successfully!")
        print(f"   Overview batch: {overview_batch_id}")
        print(f"   Summary batch: {summary_batch_id}")
        if hierarchical_batch_id:
            print(f"   Hierarchical batch: {hierarchical_batch_id}")
        print(f"   Tracker: {tracker_path}")

        # Trace: Emit Phase 10a completion summary
        emitter = self._trace_emitter
        emitter.emit_io(
            "10a",
            {"reports": len(report_ids), "include_hierarchical": include_hierarchical},
            {
                "overview_batch_id": overview_batch_id,
                "summary_batch_id": summary_batch_id,
                "hierarchical_batch_id": hierarchical_batch_id,
                "tracker_path": str(tracker_path),
            },
        )
        emitter.set_phase_status("10a", "submitted")

        return overview_batch_id, summary_batch_id, hierarchical_batch_id, tracker_path

    def get_latest_job(self) -> Path | None:
        """Get the most recent job tracking file."""
        job_files = sorted(self.jobs_dir.glob("job_*.json"), reverse=True)
        # Filter out mapping files
        job_files = [f for f in job_files if not f.name.endswith("_mapping.json")]
        return job_files[0] if job_files else None

    def update_job_status(self, tracker_path: Path) -> dict:
        """
        Update job tracker with current batch statuses.

        Returns:
            Updated tracker dict
        """
        with open(tracker_path) as f:
            tracker = json.load(f)

        # Set current job timestamp for ID mapping lookups
        self._current_job_timestamp = tracker.get("job_timestamp")

        # Check overview batch
        if tracker["overview_batch"]["batch_id"] != "N/A":
            overview_status = self.get_batch_status(
                tracker["overview_batch"]["batch_id"]
            )
            tracker["overview_batch"]["status"] = overview_status["status"]
            if overview_status["is_complete"]:
                # Ensure ended_at is a string, not datetime
                ended_at = overview_status["ended_at"]
                if isinstance(ended_at, datetime):
                    ended_at = ended_at.isoformat()
                tracker["overview_batch"]["completed_at"] = ended_at

        # Check summary batch
        if tracker["summary_batch"]["batch_id"] != "N/A":
            summary_status = self.get_batch_status(tracker["summary_batch"]["batch_id"])
            tracker["summary_batch"]["status"] = summary_status["status"]
            if summary_status["is_complete"]:
                # Ensure ended_at is a string, not datetime
                ended_at = summary_status["ended_at"]
                if isinstance(ended_at, datetime):
                    ended_at = ended_at.isoformat()
                tracker["summary_batch"]["completed_at"] = ended_at

        # Check hierarchical batch (Phase 10a Part 3: RAPTOR summaries)
        if "hierarchical_batch" in tracker and tracker["hierarchical_batch"]["batch_id"] != "N/A":
            hierarchical_status = self.get_batch_status(tracker["hierarchical_batch"]["batch_id"])
            tracker["hierarchical_batch"]["status"] = hierarchical_status["status"]
            if hierarchical_status["is_complete"]:
                ended_at = hierarchical_status["ended_at"]
                if isinstance(ended_at, datetime):
                    ended_at = ended_at.isoformat()
                tracker["hierarchical_batch"]["completed_at"] = ended_at

        # Update overall status
        overview_done = (
            tracker["overview_batch"]["batch_id"] == "N/A"
            or tracker["overview_batch"]["status"] == "ended"
        )
        summary_done = (
            tracker["summary_batch"]["batch_id"] == "N/A"
            or tracker["summary_batch"]["status"] == "ended"
        )
        hierarchical_done = (
            "hierarchical_batch" not in tracker
            or tracker["hierarchical_batch"]["batch_id"] == "N/A"
            or tracker["hierarchical_batch"]["status"] in ("ended", "skipped")
        )

        if overview_done and summary_done and hierarchical_done:
            tracker["status"] = "ready_for_processing"
        elif tracker["status"] == "submitted":
            tracker["status"] = "processing"

        # Ensure everything is serializable before saving
        tracker = _ensure_serializable(tracker)

        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)

        return tracker

    def wait_for_batch(self, batch_id: str, poll_interval: int = 60) -> dict:
        """
        Wait for a batch to complete, polling at specified interval.
        """
        print(f"⏳ Waiting for batch {batch_id}...")

        while True:
            status = self.get_batch_status(batch_id)
            completed = status["request_counts"]["completed"]
            total = status["request_counts"]["total"]

            print(f"   Status: {status['status']} | Progress: {completed}/{total}")

            if status["is_complete"]:
                print(f"✅ Batch completed!")
                return status

            time.sleep(poll_interval)

    # ═══════════════════════════════════════════════════════════════════════
    # OUTPUT PATH HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def get_overview_output_path(self, report_id: str) -> Path:
        """Get the path for storing LLM-extracted overview."""
        return self.overviews_dir / f"{report_id}_overview_llm.json"

    def get_summary_output_path(self, report_id: str) -> Path:
        """Get the path for storing generated summaries."""
        return self.summaries_dir / f"{report_id}_summaries.json"

    def find_chunks_path(self, report_id: str) -> Path | None:
        """
        Find the chunks.json file for a report, searching tier subdirectories.

        Searches in order: state/, local_body/, union/, then flat processed_dir.
        """
        tiers = ["state", "local_body", "union"]

        # Try tier subdirectories first
        for tier in tiers:
            tier_path = self.processed_dir / tier / f"{report_id}_chunks.json"
            if tier_path.exists():
                return tier_path

        # Fall back to flat structure (legacy)
        flat_path = self.processed_dir / f"{report_id}_chunks.json"
        if flat_path.exists():
            return flat_path

        return None

    def get_tier_from_chunks(self, chunks_path: Path) -> str | None:
        """Extract tier from chunks file path or metadata."""
        # Check if path contains tier directory
        path_str = str(chunks_path)
        if "/state/" in path_str:
            return "state"
        elif "/local_body/" in path_str:
            return "local_body"
        elif "/union/" in path_str:
            return "union"

        # Fall back to reading metadata from file
        try:
            with open(chunks_path) as f:
                data = json.load(f)
            return data.get("report_metadata", {}).get("government_body_type", "union")
        except:
            return None

    def get_final_overview_path(self, report_id: str, tier: str = None) -> Path:
        """
        Get the path for final merged overview (in processed dir).

        Args:
            report_id: The report identifier
            tier: Optional tier (state/local_body/union). If not provided,
                  will search for existing chunks file to determine tier.
        """
        if tier:
            return self.processed_dir / tier / f"{report_id}_overview.json"

        # Try to find the chunks file to determine tier
        chunks_path = self.find_chunks_path(report_id)
        if chunks_path:
            detected_tier = self.get_tier_from_chunks(chunks_path)
            if detected_tier:
                return self.processed_dir / detected_tier / f"{report_id}_overview.json"

        # Fall back to flat structure
        return self.processed_dir / f"{report_id}_overview.json"

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 10a PART 3: RAPTOR HIERARCHICAL SUMMARIES
    # Generates chapter-level (L2) and section-level (L1) summaries
    # for efficient high-level query answering
    # ═══════════════════════════════════════════════════════════════════════

    def submit_hierarchical_batch(
        self,
        json_files: list[Path],
        job_timestamp: str = None,
    ) -> str:
        """
        Submit batch job for RAPTOR hierarchical summaries (Phase 10c).

        Generates:
        - Chapter summaries (L2): ~23 per report average
        - Section summaries (L1): ~50 per report average

        Uses Claude Haiku for cost efficiency (~$0.10/report additional).

        Args:
            json_files: List of *_chunks.json file paths
            job_timestamp: Optional timestamp to associate with this batch

        Returns:
            batch_id for tracking
        """
        from .prompts.hierarchical_summaries import (
            build_chapter_summary_prompt,
            build_section_summary_prompt,
        )

        # Auto-generate timestamp if none provided and none exists
        if not job_timestamp and not self._current_job_timestamp:
            self._current_job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            print(f"⚠️  No job timestamp set — auto-generated: {self._current_job_timestamp}")

        # Hierarchical model config
        if self.use_claude:
            hierarchical_models = {
                "chapter_summary": "claude-haiku-4-5-20251001",
                "section_summary": "claude-haiku-4-5-20251001",
            }
        else:
            # Gemini models for GCP credit billing
            hierarchical_models = {
                "chapter_summary": "gemini-3.5-flash-lite",
                "section_summary": "gemini-3.5-flash-lite",
            }
        hierarchical_max_tokens = {
            "chapter_summary": 500,   # 3-5 sentences
            "section_summary": 200,   # 1-2 sentences
        }

        # Create hierarchical output directory
        self.hierarchical_dir = self.batch_jobs_dir / "hierarchical"
        self.hierarchical_dir.mkdir(parents=True, exist_ok=True)

        requests = []
        id_mapping = {}

        chapter_count = 0
        section_count = 0

        for json_path in json_files:
            with open(json_path) as f:
                data = json.load(f)

            report_id = data["report_metadata"]["report_id"]
            tier = data["report_metadata"].get("government_body_type", "union")
            report_title = data["report_metadata"].get("report_title", "")
            parents = data.get("parent_chunks", [])
            children = data.get("child_chunks", [])

            # Build content map: parent_id -> concatenated child content
            parent_content = self._build_parent_content_map(parents, children)

            # Generate chapter summary requests (L2)
            chapters = [p for p in parents if self._is_chapter(p)]
            for chapter in chapters:
                chunk_id = chapter.get("chunk_id")
                title = chapter.get("toc_entry", "Unknown Chapter")
                content = parent_content.get(chunk_id, "")

                if len(content) < 100:  # Skip empty chapters
                    continue

                custom_id = _short_id(f"{report_id}_ch_{chunk_id}", "h2")
                id_mapping[custom_id] = {
                    "report_id": report_id,
                    "level": 2,
                    "parent_chunk_id": chunk_id,
                    "title": title,
                    "tier": tier,
                }

                prompt = build_chapter_summary_prompt(
                    chapter_title=title,
                    chapter_content=content,
                    tier=tier,
                    report_title=report_title,
                )

                requests.append({
                    "custom_id": custom_id,
                    "params": {
                        "model": hierarchical_models["chapter_summary"],
                        "max_tokens": hierarchical_max_tokens["chapter_summary"],
                        "messages": [{"role": "user", "content": prompt}],
                    },
                })
                chapter_count += 1

            # Generate section summary requests (L1)
            sections = [p for p in parents if self._is_section(p)]
            for section in sections:
                chunk_id = section.get("chunk_id")
                title = section.get("toc_entry", "Unknown Section")
                content = parent_content.get(chunk_id, "")

                if len(content) < 50:  # Skip empty sections
                    continue

                # Find parent chapter title for context
                hierarchy = section.get("hierarchy", {})
                chapter_title = hierarchy.get("level_1", "")

                custom_id = _short_id(f"{report_id}_sec_{chunk_id}", "h1")
                id_mapping[custom_id] = {
                    "report_id": report_id,
                    "level": 1,
                    "parent_chunk_id": chunk_id,
                    "title": title,
                    "tier": tier,
                }

                prompt = build_section_summary_prompt(
                    section_title=title,
                    section_content=content,
                    tier=tier,
                    chapter_title=chapter_title,
                )

                requests.append({
                    "custom_id": custom_id,
                    "params": {
                        "model": hierarchical_models["section_summary"],
                        "max_tokens": hierarchical_max_tokens["section_summary"],
                        "messages": [{"role": "user", "content": prompt}],
                    },
                })
                section_count += 1

        if not requests:
            print("⚠️  No hierarchical summaries to generate")
            # Trace: Emit skipped status
            emitter = self._trace_emitter
            emitter.emit_decision(
                "10a",
                "hierarchical_batch_submission",
                "skipped",
                ["submitted", "skipped", "failed"],
                "No hierarchical summaries to generate",
            )
            return "N/A"

        # Save ID mapping
        self._save_id_mapping(id_mapping, job_timestamp)

        # Trace: Emit hierarchical batch submission info
        emitter = self._trace_emitter
        emitter.emit_io(
            "10a",
            {"json_files": len(json_files)},
            {
                "chapter_summaries": chapter_count,
                "section_summaries": section_count,
                "total_requests": len(requests),
            },
        )

        # Submit batch using messages.batches API
        batch = self.client.messages.batches.create(requests=requests)

        print(f"✅ Hierarchical batch submitted: {batch.id}")
        print(f"   Reports: {len(json_files)}")
        print(f"   Chapter summaries (L2): {chapter_count}")
        print(f"   Section summaries (L1): {section_count}")
        print(f"   Total requests: {len(requests)}")

        emitter.emit_decision(
            "10a",
            "hierarchical_batch_submission",
            "submitted",
            ["submitted", "skipped", "failed"],
            f"Claude batch {batch.id}",
        )

        return batch.id

    def process_hierarchical_results(
        self,
        batch_id: str,
        job_timestamp: str = None,
    ) -> dict:
        """
        Process hierarchical batch results and save to JSON files.

        Creates per-report JSON files in data/batch_jobs/hierarchical/
        with chapter and section summaries.

        Args:
            batch_id: The batch ID to process
            job_timestamp: Optional job timestamp for ID mapping

        Returns:
            Dict with processing stats
        """
        from collections import defaultdict

        results = self.get_batch_results(batch_id, job_timestamp)
        id_mapping = self._load_id_mapping(job_timestamp)

        # Group by report_id
        by_report = defaultdict(lambda: {"chapters": [], "sections": []})

        success_count = 0
        error_count = 0

        for result in results:
            custom_id = result.get("custom_id")
            mapping = id_mapping.get(custom_id, {})

            if result.get("error"):
                print(f"⚠️  Hierarchical summary failed: {custom_id} - {result['error']}")
                error_count += 1
                continue

            report_id = mapping.get("report_id", result.get("report_id"))
            level = mapping.get("level", 0)

            summary_entry = {
                "parent_chunk_id": mapping.get("parent_chunk_id"),
                "title": mapping.get("title"),
                "summary": result.get("content", ""),
                "hierarchy_level": level,
                "tier": mapping.get("tier", "union"),
            }

            if level == 2:
                by_report[report_id]["chapters"].append(summary_entry)
            elif level == 1:
                by_report[report_id]["sections"].append(summary_entry)

            success_count += 1

        # Ensure hierarchical directory exists
        self.hierarchical_dir = self.batch_jobs_dir / "hierarchical"
        self.hierarchical_dir.mkdir(parents=True, exist_ok=True)

        # Save per-report JSON files
        for report_id, summaries in by_report.items():
            output_path = self.hierarchical_dir / f"{report_id}_hierarchical.json"
            with open(output_path, "w") as f:
                json.dump({
                    "report_id": report_id,
                    "generated_at": datetime.now().isoformat(),
                    "chapter_summaries": summaries["chapters"],
                    "section_summaries": summaries["sections"],
                    "stats": {
                        "chapter_count": len(summaries["chapters"]),
                        "section_count": len(summaries["sections"]),
                    }
                }, f, indent=2)

            print(f"✅ Saved: {output_path}")
            print(f"   Chapters: {len(summaries['chapters'])}, Sections: {len(summaries['sections'])}")

        return {
            "reports_processed": len(by_report),
            "success_count": success_count,
            "error_count": error_count,
        }

    def _is_chapter(self, parent: dict) -> bool:
        """Check if parent is a chapter (L1 in hierarchy)."""
        h = parent.get("hierarchy", {})
        # Chapter: has level_1 but no level_2
        return bool(h.get("level_1")) and not h.get("level_2")

    def _is_section(self, parent: dict) -> bool:
        """Check if parent is a section (L2 in hierarchy)."""
        h = parent.get("hierarchy", {})
        # Section: has level_2 but no level_3
        return bool(h.get("level_2")) and not h.get("level_3")

    def _build_parent_content_map(
        self,
        parents: list,
        children: list,
    ) -> dict[str, str]:
        """Build map of parent_chunk_id -> concatenated child content."""
        content_map = {}
        for child in children:
            parent_id = child.get("parent_chunk_id")
            if parent_id:
                if parent_id not in content_map:
                    content_map[parent_id] = ""
                content_map[parent_id] += child.get("content", "") + "\n\n"
        return content_map

    def get_hierarchical_output_path(self, report_id: str) -> Path:
        """Get the path for storing hierarchical summaries."""
        self.hierarchical_dir = self.batch_jobs_dir / "hierarchical"
        return self.hierarchical_dir / f"{report_id}_hierarchical.json"
