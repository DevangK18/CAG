"""
Anthropic Batch API service with Extended Thinking support.

Key Features:
- 50% cost reduction via Batch API
- Extended Thinking for higher quality outputs
- File-based job tracking (no database required)
- Async submit, process later workflow
- Organized folder structure for outputs

Folder Structure:
    data/batch_jobs/
    ├── jobs/
    │   ├── job_YYYYMMDD_HHMMSS.json
    │   └── job_YYYYMMDD_HHMMSS_mapping.json
    ├── overviews/
    │   └── {report_id}_overview_llm.json
    └── summaries/
        └── {report_id}_summaries.json

Compatible with anthropic SDK v0.77.0+
"""

import anthropic
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Literal

# Load environment variables
from dotenv import load_dotenv

load_dotenv()


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
    Manages Claude Batch API operations for Phase 10.

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
    ):
        self.client = anthropic.Anthropic()

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
        self.models = {
            "overview": "claude-sonnet-4-20250514",
            "executive": "claude-sonnet-4-20250514",
            "journalist": "claude-opus-4-20250514",
            "deep_dive": "claude-opus-4-20250514",
            "simple": "claude-sonnet-4-20250514",
            "policy": "claude-sonnet-4-20250514",
        }

        # Max output tokens - MUST be greater than thinking.budget_tokens
        self.max_tokens = {
            "overview": 18000,  # Phase 12: increased for normalized_entities field
            "executive": 16000,
            "journalist": 20000,
            "deep_dive": 24000,  # Fixed: must be > thinking_budget (16000)
            "simple": 12000,
            "policy": 16000,
        }

        # Extended Thinking budget tokens
        self.thinking_budgets = {
            "overview": 5000,
            "executive": 8000,
            "journalist": 12000,
            "deep_dive": 16000,
            "simple": 6000,
            "policy": 10000,
        }

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
        return {}

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
            batch_id for tracking
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

            requests.append(
                {
                    "custom_id": custom_id,
                    "params": {
                        "model": self.models["overview"],
                        "max_tokens": self.max_tokens["overview"],
                        "thinking": {
                            "type": "enabled",
                            "budget_tokens": self.thinking_budgets["overview"],
                        },
                        "messages": [{"role": "user", "content": prompt}],
                    },
                }
            )

        # Save ID mapping
        self._save_id_mapping(id_mapping, job_timestamp)

        # Submit batch using messages.batches API (SDK v0.77.0+)
        batch = self.client.messages.batches.create(requests=requests)

        print(f"✅ Overview batch submitted: {batch.id}")
        print(f"   Reports: {len(requests)}")

        return batch.id

    def submit_summary_batch(
        self, json_files: list[Path], job_timestamp: str = None
    ) -> str:
        """
        Submit batch job for all 5 summary variants.

        Args:
            json_files: List of *_chunks.json file paths
            job_timestamp: Optional timestamp to associate with this batch

        Returns:
            batch_id for tracking
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

                requests.append(
                    {
                        "custom_id": custom_id,
                        "params": {
                            "model": self.models[variant],
                            "max_tokens": self.max_tokens[variant],
                            "thinking": {
                                "type": "enabled",
                                "budget_tokens": self.thinking_budgets[variant],
                            },
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    }
                )

        # Save ID mapping
        self._save_id_mapping(id_mapping, job_timestamp)

        # Submit batch using messages.batches API (SDK v0.77.0+)
        batch = self.client.messages.batches.create(requests=requests)

        print(f"✅ Summary batch submitted: {batch.id}")
        print(f"   Reports: {len(json_files)}")
        print(f"   Total requests: {len(requests)} ({len(json_files)} × 5 variants)")

        return batch.id

    # ═══════════════════════════════════════════════════════════════════════
    # BATCH STATUS & RESULTS
    # ═══════════════════════════════════════════════════════════════════════

    def get_batch_status(self, batch_id: str) -> dict:
        """Get current status of a batch job."""
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
        self, overview_batch_id: str, summary_batch_id: str, report_ids: list[str]
    ) -> Path:
        """
        Create a job tracking file for monitoring progress.

        Returns:
            Path to tracking file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_job_timestamp = timestamp

        tracker = {
            "job_id": f"phase10_{timestamp}",
            "job_timestamp": timestamp,
            "created_at": datetime.now().isoformat(),  # Convert to string
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
            "reports": {
                rid: {
                    "overview_extracted": False,
                    "summaries_generated": [],
                }
                for rid in report_ids
            },
            "output_paths": {
                "job_tracker": f"jobs/job_{timestamp}.json",
                "id_mapping": f"jobs/job_{timestamp}_mapping.json",
                "overviews_dir": "overviews/",
                "summaries_dir": "summaries/",
            },
            "completed_at": None,
        }

        tracker_path = self.jobs_dir / f"job_{timestamp}.json"
        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)

        print(f"📋 Job tracker created: {tracker_path}")
        return tracker_path

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

        # Update overall status
        overview_done = (
            tracker["overview_batch"]["batch_id"] == "N/A"
            or tracker["overview_batch"]["status"] == "ended"
        )
        summary_done = (
            tracker["summary_batch"]["batch_id"] == "N/A"
            or tracker["summary_batch"]["status"] == "ended"
        )

        if overview_done and summary_done:
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
