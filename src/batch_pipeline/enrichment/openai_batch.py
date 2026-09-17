"""
OpenAI Batch API client for high-volume, cost-efficient LLM calls.

Uses OpenAI's Batch API for finding extraction tasks that need many calls
but don't require deep reasoning.

Pricing (Batch API - 50% discount):
- GPT-4o-mini: $0.075/1M input, $0.30/1M output (batch pricing)
- GPT-4o: $1.25/1M input, $5.00/1M output (batch pricing)

Benefits:
- 50% cost reduction vs sync API
- No rate limits
- 24-hour completion window
- Perfect for Phase 2 finding extraction

Usage:
    service = OpenAIBatchService()
    batch_id = service.submit_batch(requests, task_type="finding_extraction")
    status = service.get_batch_status(batch_id)
    results = service.get_batch_results(batch_id)
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Literal

# OpenAI SDK
try:
    from openai import OpenAI
except ImportError:
    raise ImportError(
        "OpenAI package not installed. Install with: pip install openai"
    )

# Load environment variables
from dotenv import load_dotenv

load_dotenv()


class OpenAIBatchService:
    """
    Manages OpenAI Batch API operations for P2-1 enrichment.

    Supports three enrichment tasks:
    1. finding_extraction - Extract explicit audit findings
    2. implicit_finding - Detect implicit issues (variances, pending items)
    3. entity_extraction - Extract ministries, schemes, programs

    All responses use JSON mode for structured output.
    """

    def __init__(
        self,
        batch_jobs_dir: str = "data/batch_jobs/enrichment",
        model: str = "gpt-4o-mini",
    ):
        """
        Initialize OpenAI Batch service.

        Args:
            batch_jobs_dir: Directory for batch job tracking
            model: OpenAI model to use (default: gpt-4o-mini for cost efficiency)
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")

        self.client = OpenAI(api_key=api_key)
        self.batch_jobs_dir = Path(batch_jobs_dir)
        self.batch_jobs_dir.mkdir(parents=True, exist_ok=True)

        self.model = model

        # Max output tokens per task type
        self.max_tokens = {
            "finding_extraction": 1000,
            "implicit_finding": 800,
            "entity_extraction": 500,
        }

    def submit_batch(
        self,
        requests: List[Dict],
        task_type: Literal["finding_extraction", "implicit_finding", "entity_extraction"],
        job_timestamp: str = None,
    ) -> str:
        """
        Submit batch job to OpenAI.

        Args:
            requests: List of {custom_id, messages} dicts
            task_type: Type of enrichment task
            job_timestamp: Shared timestamp for job tracking (optional)

        Returns:
            batch_id for tracking

        Example request format:
            {
                "custom_id": "report123_chunk456",
                "messages": [{"role": "user", "content": "Extract findings from..."}]
            }
        """
        if task_type not in self.max_tokens:
            raise ValueError(
                f"Invalid task_type: {task_type}. Must be one of {list(self.max_tokens.keys())}"
            )

        # Create JSONL file for batch input
        ts = job_timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        input_file = self.batch_jobs_dir / f"openai_input_{task_type}_{ts}.jsonl"

        # Write batch requests in OpenAI's JSONL format
        with open(input_file, "w") as f:
            for req in requests:
                batch_request = {
                    "custom_id": req["custom_id"],
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.model,
                        "messages": req["messages"],
                        "max_tokens": self.max_tokens.get(task_type, 1000),
                        "temperature": 0.1,  # Low temp for consistency
                        "response_format": {"type": "json_object"},  # JSON mode
                    },
                }
                f.write(json.dumps(batch_request) + "\n")

        print(f"📝 Created batch input file: {input_file}")
        print(f"   Requests: {len(requests)}")

        # Upload file to OpenAI
        with open(input_file, "rb") as f:
            uploaded = self.client.files.create(file=f, purpose="batch")

        print(f"📤 Uploaded to OpenAI: {uploaded.id}")

        # Create batch job
        batch = self.client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={
                "task_type": task_type,
                "job_timestamp": ts,
                "request_count": str(len(requests)),
            },
        )

        print(f"✅ OpenAI batch submitted: {batch.id}")
        print(f"   Task: {task_type}")
        print(f"   Model: {self.model}")
        print(f"   Requests: {len(requests)}")
        print(f"   Completion window: 24 hours")

        # Save batch metadata
        metadata_file = self.batch_jobs_dir / f"openai_batch_{batch.id}.json"
        with open(metadata_file, "w") as f:
            json.dump(
                {
                    "batch_id": batch.id,
                    "task_type": task_type,
                    "model": self.model,
                    "request_count": len(requests),
                    "created_at": datetime.now().isoformat(),
                    "input_file": str(input_file),
                    "input_file_id": uploaded.id,
                    "status": "validating",
                },
                f,
                indent=2,
            )

        return batch.id

    def get_batch_status(self, batch_id: str) -> Dict:
        """
        Get current batch status.

        Returns:
            Dict with status, progress, completion info
        """
        batch = self.client.batches.retrieve(batch_id)

        return {
            "batch_id": batch.id,
            "status": batch.status,  # validating, in_progress, completed, failed, etc.
            "created_at": batch.created_at,
            "completed_at": batch.completed_at,
            "expires_at": batch.expires_at,
            "request_counts": {
                "total": batch.request_counts.total,
                "completed": batch.request_counts.completed,
                "failed": batch.request_counts.failed,
            },
            "is_complete": batch.status == "completed",
            "metadata": batch.metadata if hasattr(batch, "metadata") else {},
        }

    def get_batch_results(self, batch_id: str) -> List[Dict]:
        """
        Download results from completed batch.

        Returns:
            List of {custom_id, content, error} dicts

        Raises:
            ValueError: If batch not complete or no output file
        """
        batch = self.client.batches.retrieve(batch_id)

        if batch.status != "completed":
            raise ValueError(
                f"Batch not complete: {batch.status}. Cannot retrieve results yet."
            )

        if not batch.output_file_id:
            raise ValueError("No output file available for batch")

        print(f"📥 Downloading results for batch {batch_id}...")

        # Download output file
        content = self.client.files.content(batch.output_file_id)

        results = []
        for line_num, line in enumerate(content.text.strip().split("\n"), start=1):
            if not line:
                continue

            try:
                result = json.loads(line)
                custom_id = result.get("custom_id")

                item = {
                    "custom_id": custom_id,
                    "content": None,
                    "error": None,
                }

                # Check for errors
                if result.get("error"):
                    item["error"] = result["error"].get("message", str(result["error"]))

                # Extract content from successful response
                elif result.get("response", {}).get("body", {}).get("choices"):
                    choices = result["response"]["body"]["choices"]
                    if choices:
                        message = choices[0].get("message", {})
                        item["content"] = message.get("content")

                results.append(item)

            except json.JSONDecodeError as e:
                print(f"⚠️ Warning: Failed to parse line {line_num}: {e}")
                continue

        print(f"✅ Downloaded {len(results)} results")

        # Count successes and failures
        successes = sum(1 for r in results if r["content"] and not r["error"])
        failures = sum(1 for r in results if r["error"])

        print(f"   Successes: {successes}")
        print(f"   Failures: {failures}")

        return results

    def wait_for_batch(
        self, batch_id: str, poll_interval: int = 60, max_wait: int = 86400
    ) -> Dict:
        """
        Wait for a batch to complete, polling at specified interval.

        Args:
            batch_id: Batch ID to monitor
            poll_interval: Seconds between status checks (default: 60)
            max_wait: Maximum seconds to wait (default: 86400 = 24 hours)

        Returns:
            Final batch status dict

        Raises:
            TimeoutError: If max_wait exceeded
        """
        print(f"⏳ Waiting for batch {batch_id}...")
        start_time = time.time()

        while True:
            status = self.get_batch_status(batch_id)
            completed = status["request_counts"]["completed"]
            total = status["request_counts"]["total"]
            batch_status = status["status"]

            print(
                f"   Status: {batch_status} | Progress: {completed}/{total} | Elapsed: {int(time.time() - start_time)}s"
            )

            if status["is_complete"]:
                print(f"✅ Batch completed!")
                return status

            if batch_status in ["failed", "cancelled", "expired"]:
                print(f"❌ Batch ended with status: {batch_status}")
                return status

            if time.time() - start_time > max_wait:
                raise TimeoutError(
                    f"Batch did not complete within {max_wait} seconds"
                )

            time.sleep(poll_interval)

    def cancel_batch(self, batch_id: str) -> Dict:
        """
        Cancel a running batch.

        Returns:
            Updated batch status
        """
        batch = self.client.batches.cancel(batch_id)
        print(f"🛑 Batch cancelled: {batch_id}")
        return self.get_batch_status(batch_id)

    def list_batches(self, limit: int = 10) -> List[Dict]:
        """
        List recent batches.

        Args:
            limit: Maximum number of batches to return

        Returns:
            List of batch status dicts
        """
        batches = self.client.batches.list(limit=limit)
        return [self.get_batch_status(b.id) for b in batches.data]
