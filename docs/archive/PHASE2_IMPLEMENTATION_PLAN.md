# CAG Pipeline Enhancement: Phase 2 Implementation Plan

## Advanced Understanding & Analytics (P2+)

**Version:** 1.0  
**Scope:** LLM-augmented enrichment, vision extraction, analytics  
**Timeline:** 8-10 weeks  
**Prerequisites:** Phase 1 completion (P0 + P1 tasks)

---

## Executive Summary

Phase 2 adds LLM-powered capabilities to the pipeline, building on Phase 1's algorithmic foundation. All LLM calls use the **batch processing infrastructure** established in Phase 10, ensuring cost efficiency and scalability.

### Tasks Overview

| Task | Priority | Effort | Description | LLM Provider |
|------|----------|--------|-------------|--------------|
| **P2-1** | High | 3-4 weeks | LLM-Augmented Enrichment | OpenAI (volume) + Anthropic Batch (complex) |
| **P2-2** | High | 2-3 weeks | Chart Data Extraction | Claude Vision (batch) |
| **P2-3** | Medium | 2 weeks | Query-Ready JSON Schema | N/A (schema design) |
| **P2-4** | Low | 2 weeks | Visualization Service | N/A (API only) |

### Cost Model

| Task | Volume per Report | Provider | Est. Cost/Report |
|------|-------------------|----------|------------------|
| P2-1 Finding Extraction | 10-50 chunks | OpenAI GPT-4o-mini | ~$0.02-0.10 |
| P2-1 Implicit Finding | 5-20 chunks | OpenAI GPT-4o-mini | ~$0.01-0.05 |
| P2-1 Complex Analysis | 1-3 calls | Anthropic Batch (Sonnet) | ~$0.10-0.30 |
| P2-2 Chart Extraction | 2-10 charts | Claude Vision (batch) | ~$0.20-0.50 |
| **Total per report** | | | **~$0.35-1.00** |

---

## Task P2-1: LLM-Augmented Enrichment

**Priority:** P2 (High)  
**Effort:** 3-4 weeks  
**Dependencies:** Phase 1 completion

### Objective

Use LLM for deep semantic enrichment that goes beyond regex patterns:
1. Finding extraction with full context
2. Implicit finding detection
3. Evidence linking suggestions
4. Entity relationship extraction

### Architecture: Dual-Provider Batch System

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         P2-1 LLM Enrichment Flow                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ChunkingService Output                                                     │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────────┐                                                        │
│  │ EnrichmentRouter │ ──► Decides which chunks need LLM                     │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           ├──────────────────┬──────────────────┐                           │
│           ▼                  ▼                  ▼                           │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                 │
│  │ HIGH VOLUME    │  │ COMPLEX        │  │ SKIP           │                 │
│  │ (10-50 chunks) │  │ (1-3 calls)    │  │ (No LLM needed)│                 │
│  └───────┬────────┘  └───────┬────────┘  └────────────────┘                 │
│          │                   │                                              │
│          ▼                   ▼                                              │
│  ┌────────────────┐  ┌────────────────┐                                     │
│  │ OpenAI Batch   │  │ Anthropic Batch│                                     │
│  │ (GPT-4o-mini)  │  │ (Sonnet)       │                                     │
│  │ Free tier!     │  │ 50% discount   │                                     │
│  └───────┬────────┘  └───────┬────────┘                                     │
│          │                   │                                              │
│          └─────────┬─────────┘                                              │
│                    ▼                                                        │
│           ┌────────────────┐                                                │
│           │ Result Merger  │                                                │
│           └───────┬────────┘                                                │
│                   ▼                                                         │
│           SemanticEnrichment                                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Folder Structure

```
services/
└── batch_pipeline/
    ├── __init__.py
    ├── batch_service.py           # Existing (Phase 10)
    ├── phase10_service.py         # Existing (Phase 10)
    │
    ├── enrichment/                # NEW: P2-1 Enrichment
    │   ├── __init__.py
    │   ├── enrichment_service.py  # Main orchestrator
    │   ├── enrichment_router.py   # Decides LLM routing
    │   ├── openai_batch.py        # OpenAI batch client
    │   └── result_merger.py       # Combines results
    │
    ├── prompts/
    │   ├── overview_extraction.py # Existing (Phase 10)
    │   ├── summary_variants.py    # Existing (Phase 10)
    │   ├── finding_extraction.py  # NEW: P2-1
    │   ├── implicit_finding.py    # NEW: P2-1
    │   └── entity_extraction.py   # NEW: P2-1
    │
    ├── submit_jobs.py             # MODIFY: Add enrichment option
    ├── check_status.py            # MODIFY: Track enrichment jobs
    └── process_results.py         # MODIFY: Process enrichment results

data/
└── batch_jobs/
    ├── jobs/                      # Job tracking
    ├── overviews/                 # Phase 10 outputs
    ├── summaries/                 # Phase 10 outputs
    └── enrichment/                # NEW: P2-1 outputs
        ├── {report_id}_findings_llm.json
        ├── {report_id}_implicit.json
        └── {report_id}_entities.json
```

### Implementation

#### 1. Enrichment Router

```python
# services/batch_pipeline/enrichment/enrichment_router.py

from dataclasses import dataclass
from typing import List, Literal
from enum import Enum

class EnrichmentTask(str, Enum):
    FINDING_EXTRACTION = "finding_extraction"
    IMPLICIT_FINDING = "implicit_finding"
    ENTITY_EXTRACTION = "entity_extraction"
    COMPLEX_ANALYSIS = "complex_analysis"

@dataclass
class RoutingDecision:
    """Routing decision for a chunk."""
    chunk_id: str
    task: EnrichmentTask
    provider: Literal["openai", "anthropic", "skip"]
    priority: int  # 1=high, 2=medium, 3=low
    reason: str

class EnrichmentRouter:
    """
    Decides which chunks need LLM enrichment and routes to appropriate provider.
    
    Routing Logic:
    - High volume, simple tasks → OpenAI (free tier)
    - Complex reasoning tasks → Anthropic Batch (Sonnet)
    - Already extracted/low value → Skip
    """
    
    # Patterns that indicate chunk might contain findings
    FINDING_SIGNALS = [
        r"audit\s+(?:revealed|observed|found)",
        r"(?:loss|damage|wastage)\s+of",
        r"₹\s*[\d.,]+\s*(?:crore|lakh)",
        r"(?:non-?compliance|violation|deviation)",
        r"(?:irregular|unauthorized|excess)",
    ]
    
    # Patterns for implicit findings
    IMPLICIT_SIGNALS = [
        r"(?:variance|difference|gap)\s+of",
        r"(?:shortfall|excess)\s+against",
        r"(?:pending|outstanding)\s+(?:since|for)",
        r"(?:no|lack\s+of)\s+(?:records?|documentation)",
    ]
    
    # Patterns for complex analysis needs
    COMPLEX_SIGNALS = [
        r"(?:systematic|systemic)\s+(?:issue|failure)",
        r"(?:multiple|several)\s+(?:instances|cases)",
        r"(?:policy|procedural)\s+(?:implications|recommendations)",
    ]
    
    def __init__(self, report_type: str = "general"):
        self.report_type = report_type
        self._compile_patterns()
    
    def route_chunks(
        self,
        chunks: List[dict],
        existing_findings: List[dict]
    ) -> List[RoutingDecision]:
        """
        Analyze chunks and decide routing.
        
        Args:
            chunks: List of ChildChunk dicts
            existing_findings: Findings already extracted by Phase 1
            
        Returns:
            List of routing decisions
        """
        decisions = []
        existing_chunk_ids = {f.get("source_chunk_id") for f in existing_findings}
        
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            content = chunk.get("content", "")
            content_type = chunk.get("content_type")
            
            # Skip tables (already structured in Phase 1)
            if content_type == "table_markdown":
                decisions.append(RoutingDecision(
                    chunk_id=chunk_id,
                    task=EnrichmentTask.FINDING_EXTRACTION,
                    provider="skip",
                    priority=3,
                    reason="Table already structured"
                ))
                continue
            
            # Skip if already has finding
            if chunk_id in existing_chunk_ids:
                decisions.append(RoutingDecision(
                    chunk_id=chunk_id,
                    task=EnrichmentTask.FINDING_EXTRACTION,
                    provider="skip",
                    priority=3,
                    reason="Finding already extracted"
                ))
                continue
            
            # Check for finding signals
            finding_score = self._score_patterns(content, self.FINDING_SIGNALS)
            implicit_score = self._score_patterns(content, self.IMPLICIT_SIGNALS)
            complex_score = self._score_patterns(content, self.COMPLEX_SIGNALS)
            
            # Route based on scores
            if complex_score > 0.5:
                # Complex analysis → Anthropic
                decisions.append(RoutingDecision(
                    chunk_id=chunk_id,
                    task=EnrichmentTask.COMPLEX_ANALYSIS,
                    provider="anthropic",
                    priority=1,
                    reason=f"Complex signals detected (score={complex_score:.2f})"
                ))
            elif finding_score > 0.3:
                # Finding extraction → OpenAI
                decisions.append(RoutingDecision(
                    chunk_id=chunk_id,
                    task=EnrichmentTask.FINDING_EXTRACTION,
                    provider="openai",
                    priority=1,
                    reason=f"Finding signals detected (score={finding_score:.2f})"
                ))
            elif implicit_score > 0.3:
                # Implicit finding → OpenAI
                decisions.append(RoutingDecision(
                    chunk_id=chunk_id,
                    task=EnrichmentTask.IMPLICIT_FINDING,
                    provider="openai",
                    priority=2,
                    reason=f"Implicit signals detected (score={implicit_score:.2f})"
                ))
            else:
                # Low value → Skip
                decisions.append(RoutingDecision(
                    chunk_id=chunk_id,
                    task=EnrichmentTask.FINDING_EXTRACTION,
                    provider="skip",
                    priority=3,
                    reason="No enrichment signals"
                ))
        
        return decisions
    
    def _score_patterns(self, text: str, patterns: List[str]) -> float:
        """Score text against pattern list."""
        import re
        matches = sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))
        return matches / len(patterns) if patterns else 0.0
```

#### 2. OpenAI Batch Client

```python
# services/batch_pipeline/enrichment/openai_batch.py

"""
OpenAI Batch API client for high-volume, low-cost LLM calls.

Uses OpenAI's Batch API (50% discount) for finding extraction tasks.
Ideal for tasks that need many calls but don't require deep reasoning.

Pricing (Batch API - 50% off):
- GPT-4o-mini: $0.075/1M input, $0.30/1M output
- GPT-4o: $1.25/1M input, $5.00/1M output
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from openai import OpenAI

class OpenAIBatchService:
    """
    Manages OpenAI Batch API operations for P2-1 enrichment.
    
    Usage:
        service = OpenAIBatchService()
        batch_id = service.submit_batch(requests, task_type="finding_extraction")
        status = service.get_batch_status(batch_id)
        results = service.get_batch_results(batch_id)
    """
    
    def __init__(
        self,
        batch_jobs_dir: str = "data/batch_jobs/enrichment",
        model: str = "gpt-4o-mini"
    ):
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
        self.batch_jobs_dir = Path(batch_jobs_dir)
        self.batch_jobs_dir.mkdir(parents=True, exist_ok=True)
        
        self.model = model
        self.max_tokens = {
            "finding_extraction": 1000,
            "implicit_finding": 800,
            "entity_extraction": 500,
        }
    
    def submit_batch(
        self,
        requests: List[Dict],
        task_type: str,
        job_timestamp: str = None
    ) -> str:
        """
        Submit batch job to OpenAI.
        
        Args:
            requests: List of {custom_id, messages} dicts
            task_type: Type of enrichment task
            job_timestamp: Shared timestamp for job tracking
            
        Returns:
            batch_id for tracking
        """
        # Create JSONL file for batch input
        ts = job_timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        input_file = self.batch_jobs_dir / f"openai_input_{task_type}_{ts}.jsonl"
        
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
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"}
                    }
                }
                f.write(json.dumps(batch_request) + "\n")
        
        # Upload file
        with open(input_file, "rb") as f:
            uploaded = self.client.files.create(file=f, purpose="batch")
        
        # Create batch
        batch = self.client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={
                "task_type": task_type,
                "job_timestamp": ts,
                "request_count": str(len(requests))
            }
        )
        
        print(f"✅ OpenAI batch submitted: {batch.id}")
        print(f"   Task: {task_type}")
        print(f"   Requests: {len(requests)}")
        
        return batch.id
    
    def get_batch_status(self, batch_id: str) -> Dict:
        """Get current batch status."""
        batch = self.client.batches.retrieve(batch_id)
        
        return {
            "batch_id": batch.id,
            "status": batch.status,
            "created_at": batch.created_at,
            "completed_at": batch.completed_at,
            "request_counts": {
                "total": batch.request_counts.total,
                "completed": batch.request_counts.completed,
                "failed": batch.request_counts.failed,
            },
            "is_complete": batch.status == "completed",
        }
    
    def get_batch_results(self, batch_id: str) -> List[Dict]:
        """Download results from completed batch."""
        batch = self.client.batches.retrieve(batch_id)
        
        if batch.status != "completed":
            raise ValueError(f"Batch not complete: {batch.status}")
        
        if not batch.output_file_id:
            raise ValueError("No output file available")
        
        # Download output file
        content = self.client.files.content(batch.output_file_id)
        
        results = []
        for line in content.text.strip().split("\n"):
            if not line:
                continue
            
            result = json.loads(line)
            custom_id = result.get("custom_id")
            
            item = {
                "custom_id": custom_id,
                "content": None,
                "error": None,
            }
            
            if result.get("error"):
                item["error"] = result["error"]["message"]
            elif result.get("response", {}).get("body", {}).get("choices"):
                choices = result["response"]["body"]["choices"]
                if choices:
                    item["content"] = choices[0]["message"]["content"]
            
            results.append(item)
        
        return results
```

#### 3. Main Enrichment Service

```python
# services/batch_pipeline/enrichment/enrichment_service.py

"""
P2-1 LLM-Augmented Enrichment Service.

Orchestrates the enrichment workflow:
1. Route chunks to appropriate LLM provider
2. Submit batches to OpenAI (high-volume) and Anthropic (complex)
3. Process results and merge with existing enrichment
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from .enrichment_router import EnrichmentRouter, EnrichmentTask, RoutingDecision
from .openai_batch import OpenAIBatchService
from ..batch_service import BatchService as AnthropicBatchService
from ..prompts.finding_extraction import build_finding_prompt
from ..prompts.implicit_finding import build_implicit_prompt


class EnrichmentService:
    """
    Main orchestrator for P2-1 LLM enrichment.
    
    Usage:
        service = EnrichmentService()
        
        # Submit enrichment jobs
        job_id = service.submit_enrichment_batch(json_files)
        
        # Check status
        status = service.get_enrichment_status(job_id)
        
        # Process results
        service.process_enrichment_results(job_id)
    """
    
    def __init__(
        self,
        batch_jobs_dir: str = "data/batch_jobs",
        processed_dir: str = "data/processed",
        use_openai_for_volume: bool = True,
    ):
        self.batch_jobs_dir = Path(batch_jobs_dir)
        self.processed_dir = Path(processed_dir)
        self.enrichment_dir = self.batch_jobs_dir / "enrichment"
        self.enrichment_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize providers
        self.openai_service = OpenAIBatchService(
            batch_jobs_dir=str(self.enrichment_dir)
        ) if use_openai_for_volume else None
        
        self.anthropic_service = AnthropicBatchService(
            batch_jobs_dir=str(self.batch_jobs_dir),
            processed_dir=str(self.processed_dir)
        )
        
        self.router = EnrichmentRouter()
    
    def submit_enrichment_batch(
        self,
        json_files: List[Path],
        skip_already_enriched: bool = True
    ) -> str:
        """
        Submit enrichment batch jobs for multiple reports.
        
        Args:
            json_files: List of *_chunks.json file paths
            skip_already_enriched: Skip chunks with existing findings
            
        Returns:
            job_id for tracking
        """
        job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Collect all routing decisions
        openai_requests = []
        anthropic_requests = []
        id_mapping = {}
        
        for json_path in json_files:
            with open(json_path) as f:
                data = json.load(f)
            
            report_id = data["report_metadata"]["report_id"]
            chunks = data.get("child_chunks", [])
            existing_findings = data.get("semantic_enrichment", {}).get("findings", [])
            
            # Get routing decisions
            decisions = self.router.route_chunks(chunks, existing_findings)
            
            for decision in decisions:
                if decision.provider == "skip":
                    continue
                
                chunk = next(
                    (c for c in chunks if c["chunk_id"] == decision.chunk_id),
                    None
                )
                if not chunk:
                    continue
                
                custom_id = f"{report_id[:30]}_{decision.chunk_id[:20]}"
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
                else:
                    prompt = build_finding_prompt(chunk)  # Default
                
                request = {
                    "custom_id": custom_id,
                    "messages": [{"role": "user", "content": prompt}]
                }
                
                if decision.provider == "openai":
                    openai_requests.append(request)
                else:
                    anthropic_requests.append(request)
        
        # Save ID mapping
        mapping_path = self.enrichment_dir / f"enrichment_{job_timestamp}_mapping.json"
        with open(mapping_path, "w") as f:
            json.dump(id_mapping, f, indent=2)
        
        # Submit batches
        openai_batch_id = None
        anthropic_batch_id = None
        
        if openai_requests and self.openai_service:
            print(f"\n📤 Submitting {len(openai_requests)} requests to OpenAI...")
            openai_batch_id = self.openai_service.submit_batch(
                openai_requests,
                task_type="finding_extraction",
                job_timestamp=job_timestamp
            )
        
        if anthropic_requests:
            print(f"\n📤 Submitting {len(anthropic_requests)} requests to Anthropic...")
            # Use Anthropic batch service
            anthropic_batch_id = self._submit_anthropic_enrichment(
                anthropic_requests,
                job_timestamp
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
            "reports_processed": [f.stem.replace("_chunks", "") for f in json_files],
            "mapping_file": str(mapping_path),
        }
        
        tracker_path = self.enrichment_dir / f"enrichment_{job_timestamp}.json"
        with open(tracker_path, "w") as f:
            json.dump(job_tracker, f, indent=2)
        
        print(f"\n✅ Enrichment job created: {job_tracker['job_id']}")
        print(f"   OpenAI requests: {len(openai_requests)}")
        print(f"   Anthropic requests: {len(anthropic_requests)}")
        
        return job_tracker["job_id"]
    
    def _submit_anthropic_enrichment(
        self,
        requests: List[Dict],
        job_timestamp: str
    ) -> str:
        """Submit complex analysis requests to Anthropic batch."""
        from anthropic import Anthropic
        
        client = Anthropic()
        
        batch_requests = []
        for req in requests:
            batch_requests.append({
                "custom_id": req["custom_id"],
                "params": {
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 2000,
                    "messages": req["messages"],
                }
            })
        
        batch = client.messages.batches.create(requests=batch_requests)
        return batch.id
    
    def get_enrichment_status(self, job_id: str) -> Dict:
        """Get status of enrichment job."""
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
            tracker["anthropic_batch"]["progress"] = anthropic_status["request_counts"]
        
        # Update overall status
        openai_done = (
            not tracker["openai_batch"]["batch_id"] or 
            tracker["openai_batch"]["status"] == "completed"
        )
        anthropic_done = (
            not tracker["anthropic_batch"]["batch_id"] or
            tracker["anthropic_batch"]["status"] == "ended"
        )
        
        if openai_done and anthropic_done:
            tracker["status"] = "ready_for_processing"
        
        # Save updated tracker
        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)
        
        return tracker
    
    def process_enrichment_results(self, job_id: str) -> Dict:
        """
        Process completed enrichment results and merge into chunks.
        
        Returns:
            Summary of processed results
        """
        tracker_path = self.enrichment_dir / f"{job_id}.json"
        
        with open(tracker_path) as f:
            tracker = json.load(f)
        
        # Load ID mapping
        with open(tracker["mapping_file"]) as f:
            id_mapping = json.load(f)
        
        # Collect all results
        all_results = []
        
        # Get OpenAI results
        if tracker["openai_batch"]["batch_id"]:
            openai_results = self.openai_service.get_batch_results(
                tracker["openai_batch"]["batch_id"]
            )
            for r in openai_results:
                r["provider"] = "openai"
            all_results.extend(openai_results)
        
        # Get Anthropic results
        if tracker["anthropic_batch"]["batch_id"]:
            anthropic_results = self.anthropic_service.get_batch_results(
                tracker["anthropic_batch"]["batch_id"]
            )
            for r in anthropic_results:
                r["provider"] = "anthropic"
            all_results.extend(anthropic_results)
        
        # Group by report
        results_by_report = {}
        for result in all_results:
            mapping = id_mapping.get(result["custom_id"], {})
            report_id = mapping.get("report_id")
            
            if report_id not in results_by_report:
                results_by_report[report_id] = []
            
            results_by_report[report_id].append({
                "chunk_id": mapping.get("chunk_id"),
                "task": mapping.get("task"),
                "content": result.get("content"),
                "error": result.get("error"),
                "provider": result.get("provider"),
            })
        
        # Save per-report results
        summary = {"success": 0, "failed": 0, "reports": []}
        
        for report_id, results in results_by_report.items():
            output_path = self.enrichment_dir / f"{report_id}_enrichment.json"
            
            enrichment_doc = {
                "report_id": report_id,
                "processed_at": datetime.now().isoformat(),
                "results": results,
                "success_count": sum(1 for r in results if not r["error"]),
                "error_count": sum(1 for r in results if r["error"]),
            }
            
            with open(output_path, "w") as f:
                json.dump(enrichment_doc, f, indent=2, ensure_ascii=False)
            
            summary["reports"].append({
                "report_id": report_id,
                "success": enrichment_doc["success_count"],
                "errors": enrichment_doc["error_count"],
            })
            summary["success"] += enrichment_doc["success_count"]
            summary["failed"] += enrichment_doc["error_count"]
        
        # Update tracker
        tracker["status"] = "completed"
        tracker["completed_at"] = datetime.now().isoformat()
        tracker["summary"] = summary
        
        with open(tracker_path, "w") as f:
            json.dump(tracker, f, indent=2)
        
        return summary
```

#### 4. Prompt Templates

```python
# services/batch_pipeline/prompts/finding_extraction.py

"""
Prompt for extracting audit findings from CAG report chunks.

Used by: OpenAI Batch (high volume) and Anthropic Batch (complex)
"""

FINDING_EXTRACTION_PROMPT = """You are analyzing a chunk from a CAG (Comptroller and Auditor General of India) audit report.

TASK: Extract all audit findings from this text.

For each finding, provide:
1. finding_type: One of [irregular_expenditure, loss_of_revenue, wasteful_expenditure, non_compliance, system_deficiency, performance_shortfall, fraud_misappropriation, procedural_lapse, other]
2. summary: One sentence summary (max 150 chars)
3. monetary_amount: Amount in crore (null if not mentioned)
4. currency_unit: "crore" or "lakh" (null if not mentioned)
5. severity: One of [critical, high, medium, low] based on:
   - critical: >₹100 crore or systemic fraud
   - high: ₹10-100 crore or significant non-compliance
   - medium: ₹1-10 crore or moderate issues
   - low: <₹1 crore or minor procedural lapses
6. entities: List of ministries, departments, schemes mentioned
7. evidence_refs: Any table/para references (e.g., "Table 3.1", "Para 4.2.3")

TEXT:
{chunk_content}

HIERARCHY CONTEXT:
{hierarchy}

Respond with JSON:
{{"findings": [...]}}

If no findings, return {{"findings": []}}
"""

def build_finding_prompt(chunk: dict) -> str:
    """Build the finding extraction prompt for a chunk."""
    hierarchy = chunk.get("hierarchy", {})
    hierarchy_str = " > ".join(
        f"{k}: {v}" for k, v in hierarchy.items() if v
    )
    
    return FINDING_EXTRACTION_PROMPT.format(
        chunk_content=chunk.get("content", ""),
        hierarchy=hierarchy_str or "N/A"
    )
```

```python
# services/batch_pipeline/prompts/implicit_finding.py

"""
Prompt for detecting implicit/hidden findings in CAG report chunks.

These are issues not explicitly labeled as "findings" but represent audit concerns.
"""

IMPLICIT_FINDING_PROMPT = """You are analyzing a CAG audit report chunk for IMPLICIT audit issues.

These are problems NOT explicitly labeled as "findings" but represent audit concerns:
- Budget variances without explanation
- Targets not met without explicit finding label
- Procedural gaps mentioned in passing
- Pending issues noted casually
- Performance shortfalls in tables

TASK: Identify any implicit audit issues in this text.

For each implicit issue:
1. issue_type: Category [variance, target_miss, procedural_gap, pending_issue, performance_gap, unexplained_difference, other]
2. description: What the issue is (max 200 chars)
3. monetary_impact: Amount in crore if mentioned (null otherwise)
4. confidence: Your confidence this represents a real audit concern (0.0-1.0)
5. supporting_text: The exact text that indicates this issue (max 100 chars)

TEXT:
{chunk_content}

Respond with JSON:
{{"implicit_issues": [...]}}

Only include issues with confidence >= 0.6. If none found, return {{"implicit_issues": []}}
"""

def build_implicit_prompt(chunk: dict) -> str:
    """Build the implicit finding prompt for a chunk."""
    return IMPLICIT_FINDING_PROMPT.format(
        chunk_content=chunk.get("content", "")
    )
```

#### 5. CLI Integration

```python
# Update services/batch_pipeline/submit_jobs.py

# Add new argument
parser.add_argument(
    "--enrichment",
    action="store_true",
    help="Submit P2-1 LLM enrichment batch (finding extraction)"
)

# In main():
if args.enrichment:
    from .enrichment.enrichment_service import EnrichmentService
    
    enrichment_service = EnrichmentService()
    job_id = enrichment_service.submit_enrichment_batch(json_files)
    
    print(f"\n📋 Enrichment Job: {job_id}")
    print("\nNext steps:")
    print("  1. Check status:")
    print("     poetry run python -m services.batch_pipeline.check_status --enrichment")
    print("")
    print("  2. When complete, process results:")
    print("     poetry run python -m services.batch_pipeline.process_results --enrichment")
```

---

## Task P2-2: Chart Data Extraction

**Priority:** P2 (High)  
**Effort:** 2-3 weeks  
**Dependencies:** P2-1

### Objective

Extract structured data from charts/graphs using Claude Vision via batch API.

### Architecture

```
Visual Asset Extractor (existing)
         │
         ▼
    Chart Images
         │
         ▼
┌────────────────────┐
│ Claude Vision Batch │
│ (claude-sonnet)    │
└─────────┬──────────┘
          ▼
    ChartData JSON
    {
      chart_type: "bar",
      title: "Budget vs Actual",
      data_series: [...],
      axes: {...}
    }
```

### Implementation Notes

- Use Anthropic Batch API with vision capability
- Extract: chart type, title, axis labels, data points, legends
- Cost: ~$0.02-0.05 per chart (batch pricing)

---

## Task P2-3: Query-Ready JSON Schema

**Priority:** P2 (Medium)  
**Effort:** 2 weeks  
**Dependencies:** P2-1, P2-2

### Objective

Design unified JSON schema for all extracted data to enable direct querying.

### Schema Highlights

```json
{
  "report_id": "...",
  "queryable_tables": {
    "table_001": {
      "columns": ["State", "FY2021-22", "FY2022-23"],
      "column_types": ["entity", "currency", "currency"],
      "rows": [...],
      "aggregations": {
        "FY2022-23": {"sum": 12345.67, "avg": 123.45}
      }
    }
  },
  "queryable_findings": {
    "by_severity": {...},
    "by_type": {...},
    "by_ministry": {...},
    "total_monetary_impact": 847.71
  },
  "queryable_entities": {
    "ministries": [...],
    "schemes": [...],
    "states": [...]
  }
}
```

---

## Task P2-4: Visualization Service

**Priority:** P3 (Low)  
**Effort:** 2 weeks  
**Dependencies:** P2-3

### Objective

API endpoints for generating visualizations from extracted data.

### Endpoints

```
GET /api/reports/{report_id}/visualize/findings-by-severity
GET /api/reports/{report_id}/visualize/monetary-impact-timeline
GET /api/reports/{report_id}/visualize/table/{table_id}
```

---

## Timeline

```
Weeks 1-4: P2-1 LLM-Augmented Enrichment
    ├── enrichment_router.py
    ├── openai_batch.py
    ├── enrichment_service.py
    ├── Prompts (finding, implicit, entity)
    ├── CLI integration
    └── Testing with sample reports

Weeks 4-6: P2-2 Chart Data Extraction
    ├── chart_extractor.py (vision batch)
    ├── Chart type classification
    ├── Data point extraction
    └── Integration tests

Weeks 6-8: P2-3 Query-Ready JSON Schema
    ├── Schema design
    ├── Migration scripts
    ├── Query interface
    └── Documentation

Weeks 8-10: P2-4 Visualization Service
    ├── API endpoints
    ├── Chart generation
    └── Frontend integration
```

---

## Cost Summary

### Per Report (Estimated)

| Component | Provider | Est. Tokens | Cost |
|-----------|----------|-------------|------|
| P2-1 Finding Extraction | OpenAI GPT-4o-mini | ~20K in, ~5K out | $0.003 |
| P2-1 Implicit Finding | OpenAI GPT-4o-mini | ~15K in, ~3K out | $0.002 |
| P2-1 Complex Analysis | Anthropic Sonnet Batch | ~10K in, ~2K out | $0.06 |
| P2-2 Chart Extraction | Claude Vision Batch | ~5 images | $0.15 |
| **Total** | | | **~$0.22** |

### Full Corpus (100 reports)

| Phase | Cost |
|-------|------|
| Phase 10 (existing) | ~$100 |
| Phase 2 P2-1 + P2-2 | ~$22 |
| **Total** | **~$122** |

---

## Success Metrics

| Metric | Target | Validation |
|--------|--------|------------|
| Finding extraction recall | >90% | Manual validation on 10 reports |
| Implicit finding precision | >70% | Manual validation |
| Chart data accuracy | >85% | Compare to manual extraction |
| Processing time | <5 min/report | Batch completion time |
| Cost per report | <$0.50 | Monitor API costs |

---

## File Summary

### New Files

| File | Task | Description |
|------|------|-------------|
| `services/batch_pipeline/enrichment/__init__.py` | P2-1 | Package init |
| `services/batch_pipeline/enrichment/enrichment_service.py` | P2-1 | Main orchestrator |
| `services/batch_pipeline/enrichment/enrichment_router.py` | P2-1 | Chunk routing logic |
| `services/batch_pipeline/enrichment/openai_batch.py` | P2-1 | OpenAI batch client |
| `services/batch_pipeline/enrichment/result_merger.py` | P2-1 | Result combination |
| `services/batch_pipeline/prompts/finding_extraction.py` | P2-1 | Finding prompt |
| `services/batch_pipeline/prompts/implicit_finding.py` | P2-1 | Implicit finding prompt |
| `services/batch_pipeline/prompts/entity_extraction.py` | P2-1 | Entity prompt |
| `services/batch_pipeline/chart_extractor.py` | P2-2 | Chart vision extraction |

### Modified Files

| File | Task | Changes |
|------|------|---------|
| `services/batch_pipeline/submit_jobs.py` | P2-1 | Add --enrichment flag |
| `services/batch_pipeline/check_status.py` | P2-1 | Track enrichment jobs |
| `services/batch_pipeline/process_results.py` | P2-1 | Process enrichment results |

---

## Migration Path

After Phase 2 completion, the full pipeline workflow becomes:

```bash
# Full pipeline for new reports
poetry run python -m services.parsing_pipeline.main manifest.xlsx

# This now runs:
# Phases 1-9: Parsing, extraction, chunking
# Phase 10: Overview + Summary (Anthropic Batch)
# Phase 11: P2-1 Enrichment (OpenAI + Anthropic Batch)
# Phase 12: P2-2 Chart Extraction (Claude Vision Batch)

# For existing reports, run phases separately:
poetry run python -m services.batch_pipeline.submit_jobs           # Phase 10
poetry run python -m services.batch_pipeline.submit_jobs --enrichment  # Phase 11
```
