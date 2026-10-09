"""
Phase 10a as one set of requests run in dependency order, across all reports.

Each request is sent as soon as its inputs exist:
- the overview (Pro) at once;
- the summary tree from the leaves up: a node is sent when all its summarised
  children are done (summary_tree.py);
- the five summary variants when the report's chapter summaries and its
  overview are both done, with both as input.

Nothing waits for a whole batch to finish, so Pro and Flash both stay busy and a
slow report does not hold up the others. Outputs keep the files the API, indexer
and loss accounting read (overview, summaries, hierarchical JSON).
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.core.json_files import write_json_atomic
from src.core.phase10_models import thinking_level

from .summary_tree import Node, SummaryTree, build_tree


def _short_id(text: str, prefix: str) -> str:
    from .batch_service import _short_id as short

    return short(text, prefix)


logger = logging.getLogger(__name__)

# Output tokens for a summary, thinking included
SUMMARY_MAX_TOKENS = 8192
VARIANT_CODES = {
    "executive": "ex",
    "journalist": "jo",
    "deep_dive": "dd",
    "simple": "si",
    "policy": "po",
}


@dataclass
class _Report:
    report_id: str
    data: dict
    tree: SummaryTree
    tier: str
    title: str
    pending: Dict[str, int] = field(default_factory=dict)
    summaries: Dict[str, Optional[str]] = field(default_factory=dict)
    inherited: set = field(default_factory=set)
    errors: List[dict] = field(default_factory=list)
    roots_left: int = 0
    overview: Optional[dict] = None
    overview_done: bool = False
    variants_started: bool = False
    variant_results: List[dict] = field(default_factory=list)


class Phase10aRun:
    def __init__(self, service, json_files: List[Path], job_timestamp: str):
        self.service = service
        self.json_files = [Path(p) for p in json_files]
        self.job_timestamp = job_timestamp
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._outstanding = 0
        self._pool: Optional[ThreadPoolExecutor] = None
        self.reports: Dict[str, _Report] = {}
        self.overview_results: List[dict] = []
        self.overview_ids: Dict[str, str] = {}
        self.calls = {"overview": 0, "summary_tree": 0, "variants": 0}

    # ── building ──────────────────────────────────────────────────────────

    def prepare(self) -> None:
        for path in self.json_files:
            data = self.service._read_chunks(path)
            meta = data.get("report_metadata", {})
            tree = build_tree(data)
            rep = _Report(
                report_id=meta["report_id"],
                data=data,
                tree=tree,
                tier=meta.get("government_body_type", "union"),
                title=meta.get("report_title", ""),
            )
            summarised = tree.summarised()
            for node in summarised:
                rep.pending[node.node_id] = len(tree.summarised_children(node))
            rep.roots_left = sum(1 for n in summarised if n.parent is None)
            self.reports[rep.report_id] = rep

    def node_prompt(self, rep: _Report, node: Node) -> str:
        from .prompts.hierarchical_summaries import build_node_summary_prompt

        children = []
        for child in rep.tree.summarised_children(node):
            summary = rep.summaries.get(child.node_id)
            if not summary:
                # A child whose summary failed: its opening text stands in for it
                summary = "(summary unavailable; opening text) " + child.text[:1500]
            children.append((child.title, summary))
        return build_node_summary_prompt(
            title=node.title,
            path=list(node.path),
            own_text=node.text,
            child_summaries=children,
            tier=rep.tier,
            report_title=rep.title,
            is_chapter=node.depth == 1,
        )

    def variant_requests(self, rep: _Report) -> List[dict]:
        from .grounding import build_source_text, source_numbers
        from .prompts.summary_variants import (
            VARIANTS,
            build_summary_input,
            get_summary_prompt,
        )

        chapters = [
            (rep.tree.nodes[n].title, rep.summaries.get(n))
            for n in rep.tree.roots
            if rep.summaries.get(n)
        ]
        summary_input = build_summary_input(
            rep.data, chapter_summaries=chapters, overview=rep.overview
        )
        self._grounding[rep.report_id] = source_numbers(
            build_source_text(rep.data, self.service._source_pdf_path(rep.data))
        )
        return [
            {
                "custom_id": _short_id(rep.report_id, f"sm_{VARIANT_CODES[v]}"),
                "variant": v,
                "prompt": get_summary_prompt(v, summary_input, rep.data),
                "model": self.service.models[v],
                "max_tokens": self.service.max_tokens[v],
            }
            for v in VARIANTS
        ]

    # ── running ───────────────────────────────────────────────────────────

    def _count(self, kind: str) -> None:
        with self._lock:
            self.calls[kind] += 1

    def _submit(self, fn, *args) -> None:
        with self._lock:
            self._outstanding += 1
        self._pool.submit(self._guarded, fn, *args)

    def _guarded(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception:  # a bug in one request must not hang the run
            logger.exception("Phase 10a request failed unexpectedly")
        finally:
            with self._idle:
                self._outstanding -= 1
                if self._outstanding == 0:
                    self._idle.notify_all()

    def _call(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        custom_id: str,
        tag: str,
        thinking=None,
    ) -> dict:
        """One request; a transient failure gets one more attempt after a pause."""
        from src.core.gemini_client import is_transient
        from src.core.gemini_limiter import GeminiDeadlineExceeded, get_limiter

        result = self.service._process_single_gemini(
            prompt, model, max_tokens, custom_id, tag, thinking
        )
        if (
            result["error"]
            and is_transient(result["error"])
            and self.service.retry_pause_s
        ):
            try:
                get_limiter().backoff(self.service.retry_pause_s, "phase10a")
            except GeminiDeadlineExceeded:
                return result
            result = self.service._process_single_gemini(
                prompt, model, max_tokens, custom_id, tag, thinking
            )
        return result

    def _run_overview(self, rep: _Report) -> None:
        from .prompts.overview_extraction import build_overview_prompt

        custom_id = _short_id(rep.report_id, "ov")
        self._count("overview")
        result = self._call(
            build_overview_prompt(rep.data),
            self.service.models["overview"],
            self.service.max_tokens["overview"],
            custom_id,
            "phase10a.overview",
        )
        parsed = None
        if not result["error"]:
            try:
                from .process_results import clean_json_response

                parsed = json.loads(clean_json_response(result["content"]))
            except (ValueError, TypeError):
                parsed = None
        with self._lock:
            self.overview_results.append(result)
            self.overview_ids[custom_id] = rep.report_id
            rep.overview = parsed
            rep.overview_done = True
            ready = self._variants_ready(rep)
        if ready:
            self._start_variants(rep)

    def _run_node(self, rep: _Report, node: Node) -> None:
        tree = rep.tree
        if not tree.needs_call(node):
            (child,) = tree.summarised_children(node)
            summary = rep.summaries.get(child.node_id)
            with self._lock:
                rep.summaries[node.node_id] = summary
                rep.inherited.add(node.node_id)
        else:
            role = "chapter_summary" if node.depth == 1 else "section_summary"
            custom_id = _short_id(f"{rep.report_id}_{node.node_id}", "hn")
            self._count("summary_tree")
            result = self._call(
                self.node_prompt(rep, node),
                getattr(self.service.model_config, role),
                SUMMARY_MAX_TOKENS,
                custom_id,
                "phase10a.hierarchical",
                thinking_level(role),
            )
            with self._lock:
                rep.summaries[node.node_id] = (
                    None if result["error"] else (result["content"] or "").strip()
                )
                if result["error"]:
                    rep.errors.append(
                        {
                            "parent_chunk_id": node.parent_chunk_id or node.node_id,
                            "title": node.title,
                            "hierarchy_level": 2 if node.depth == 1 else 1,
                            "depth": node.depth,
                            "error": str(result["error"])[:300],
                        }
                    )
        self._node_done(rep, node)

    def _node_done(self, rep: _Report, node: Node) -> None:
        next_node = None
        with self._lock:
            if node.parent is not None:
                rep.pending[node.parent] -= 1
                if rep.pending[node.parent] == 0:
                    next_node = rep.tree.nodes[node.parent]
            else:
                rep.roots_left -= 1
            ready = node.parent is None and self._variants_ready(rep)
        if next_node is not None:
            self._submit(self._run_node, rep, next_node)
        if ready:
            self._start_variants(rep)

    def _variants_ready(self, rep: _Report) -> bool:
        """Called with the lock held; True once, when both inputs are done."""
        if rep.variants_started or not rep.overview_done or rep.roots_left > 0:
            return False
        rep.variants_started = True
        return True

    def _start_variants(self, rep: _Report) -> None:
        for req in self.variant_requests(rep):
            self._submit(self._run_variant, rep, req)

    def _run_variant(self, rep: _Report, req: dict) -> None:
        self._count("variants")
        result = self._call(
            req["prompt"],
            req["model"],
            req["max_tokens"],
            req["custom_id"],
            "phase10a.summary",
        )
        with self._lock:
            rep.variant_results.append({**result, "variant": req["variant"]})

    def run(self, max_workers: int) -> None:
        self._grounding: Dict[str, set] = {}
        self.prepare()
        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="phase10a"
        ) as pool:
            self._pool = pool
            for rep in self.reports.values():
                self._submit(self._run_overview, rep)
                for node_id, count in list(rep.pending.items()):
                    if count == 0:
                        self._submit(self._run_node, rep, rep.tree.nodes[node_id])
                if rep.roots_left == 0:
                    with self._lock:
                        ready = self._variants_ready(rep)
                    if ready:
                        self._start_variants(rep)
            with self._idle:
                while self._outstanding:
                    self._idle.wait()
        self.save()

    # ── outputs ───────────────────────────────────────────────────────────

    def save(self) -> None:
        self.service._save_overview_results(self.overview_results, self.overview_ids)
        variant_results, variant_ids = [], {}
        for rep in self.reports.values():
            for r in rep.variant_results:
                variant_results.append(r)
                variant_ids[r["custom_id"]] = {
                    "report_id": rep.report_id,
                    "variant": r["variant"],
                }
        self.service._save_summary_results(
            variant_results, variant_ids, self._grounding
        )
        for rep in self.reports.values():
            self.save_tree(rep)

    def save_tree(self, rep: _Report) -> Path:
        chapters, sections = [], []
        for node in rep.tree.summarised():
            if node.part_of:
                continue  # parts feed their node's summary only
            summary = rep.summaries.get(node.node_id)
            if not summary:
                continue
            entry = {
                "parent_chunk_id": node.parent_chunk_id or node.node_id,
                "title": node.title,
                "summary": summary,
                "hierarchy_level": 2 if node.depth == 1 else 1,
                "depth": node.depth,
                "path": list(node.path),
                "inherited": node.node_id in rep.inherited,
                "tier": rep.tier,
            }
            (chapters if node.depth == 1 else sections).append(entry)
        path = self.service.get_hierarchical_output_path(rep.report_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            path,
            {
                "report_id": rep.report_id,
                "generated_at": datetime.now().isoformat(),
                "method": "bottom_up",
                "chapter_summaries": chapters,
                "section_summaries": sections,
                "errors": rep.errors or None,
                "stats": {
                    "chapter_count": len(chapters),
                    "section_count": len(sections),
                    "chapters_failed": sum(
                        1 for e in rep.errors if e["hierarchy_level"] == 2
                    ),
                    "sections_failed": sum(
                        1 for e in rep.errors if e["hierarchy_level"] == 1
                    ),
                },
            },
        )
        return path


def write_content_summaries(
    chunk_file: Path, hierarchical_file: Path, overview_file: Optional[Path] = None
) -> int:
    """
    Copy chapter and section summaries into their parent chunks' content_summary,
    where the indexer reads them, and fill an empty audit_period from the report's
    overview (Phase 9 runs before the overview exists). Returns the number of
    parents filled.
    """
    if not chunk_file.exists():
        return 0
    data = json.loads(chunk_file.read_text())
    changed = False
    filled = 0
    if hierarchical_file.exists():
        summaries = json.loads(hierarchical_file.read_text())
        by_parent = {
            e["parent_chunk_id"]: e["summary"]
            for e in (summaries.get("chapter_summaries") or [])
            + (summaries.get("section_summaries") or [])
            if e.get("summary")
        }
        for parent in data.get("parent_chunks") or []:
            summary = by_parent.get(parent.get("chunk_id"))
            if summary:
                parent["content_summary"] = summary
                filled += 1
        changed = filled > 0
    if overview_file is not None and overview_file.exists():
        from src.parsing_pipeline.modules.enrichment.temporal_extractor import (
            fill_audit_period_from_overview,
        )

        enrichment = data.get("semantic_enrichment") or {}
        coverage = enrichment.get("temporal_coverage")
        try:
            overview = json.loads(overview_file.read_text())
        except ValueError:
            overview = None
        if coverage is not None and fill_audit_period_from_overview(coverage, overview):
            for finding in enrichment.get("findings") or []:
                finding["audit_period"] = (
                    finding.get("audit_period") or coverage["audit_period"]
                )
            changed = True
    if changed:
        write_json_atomic(chunk_file, data)
    return filled
