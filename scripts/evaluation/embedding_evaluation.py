#!/usr/bin/env python3
"""
Embedding Strategy Evaluation Script
=====================================

Compares embedding strategies for CAG audit report chunks:
1. OpenAI text-embedding-3-large (current)
2. Voyage context-4 (contextual embeddings)

Metrics:
- MRR (Mean Reciprocal Rank)
- Recall@k (k=1,3,5,10)
- Precision@k
- Hit Rate

Usage:
    python scripts/embedding_evaluation.py --sample-size 200
    python scripts/embedding_evaluation.py --voyage-key <key> --full
"""

import os
import sys
import re
import json
import hashlib
import argparse
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
import numpy as np
from tqdm import tqdm

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class EvalChunk:
    """Chunk prepared for evaluation."""
    chunk_id: str
    content: str
    content_type: str
    hierarchy: Dict[str, str]
    report_id: str
    report_title: str
    page: int
    parent_content: Optional[str] = None  # For contextual embedding

    def get_hierarchy_prefix(self) -> str:
        """Generate hierarchy breadcrumb."""
        parts = []
        for key in ['level_1', 'level_2', 'level_3']:
            if key in self.hierarchy and self.hierarchy[key]:
                # Clean up numbered prefixes like "5_Executive summary"
                val = self.hierarchy[key]
                if '_' in val and val.split('_')[0].isdigit():
                    val = val.split('_', 1)[1]
                parts.append(val)
        return ' > '.join(parts) if parts else ''


@dataclass
class EvalQuery:
    """Evaluation query with known relevant chunks."""
    query_id: str
    query_text: str
    query_type: str  # factual, list, aggregation, etc.
    relevant_chunk_ids: List[str]
    report_id: Optional[str] = None  # If query is report-specific


@dataclass
class RetrievalResult:
    """Single retrieval result."""
    chunk_id: str
    score: float
    rank: int


@dataclass
class EvalMetrics:
    """Evaluation metrics for a strategy."""
    mrr: float
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    recall_at_10: float
    precision_at_1: float
    precision_at_5: float
    hit_rate: float
    avg_latency_ms: float
    total_queries: int


# ============================================================================
# Chunk Loading
# ============================================================================

def load_chunks_from_reports(
    processed_dir: Path,
    max_reports: int = 5,
    max_chunks_per_report: int = 100
) -> Tuple[List[EvalChunk], Dict[str, Dict]]:
    """Load chunks from processed report JSON files."""

    chunks = []
    parent_map = {}  # chunk_id -> parent chunk data

    # Find all chunk files
    chunk_files = list(processed_dir.glob("**/*_chunks.json"))
    logger.info(f"Found {len(chunk_files)} chunk files")

    # Select diverse reports (mix of union, state, local_body)
    selected_files = []
    for tier in ['union', 'state', 'local_body']:
        tier_files = [f for f in chunk_files if f"/{tier}/" in str(f)]
        selected_files.extend(tier_files[:max_reports // 3 + 1])

    selected_files = selected_files[:max_reports]
    logger.info(f"Selected {len(selected_files)} reports for evaluation")

    for chunk_file in tqdm(selected_files, desc="Loading chunks"):
        try:
            with open(chunk_file) as f:
                data = json.load(f)

            report_meta = data.get('report_metadata', {})
            report_id = report_meta.get('report_id', chunk_file.stem)
            report_title = report_meta.get('report_title', '')

            # Build parent map
            for parent in data.get('parent_chunks', []):
                parent_map[parent['chunk_id']] = parent

            # Load child chunks (paragraphs and tables with meaningful content)
            child_chunks = data.get('child_chunks', [])

            count = 0
            for child in child_chunks:
                content = child.get('content', '')
                content_type = child.get('content_type', '')

                # Filter: only paragraphs and tables with sufficient content
                if content_type not in ('paragraph', 'table_markdown'):
                    continue
                if len(content) < 100:  # Skip very short chunks
                    continue

                # Get parent content for contextual embedding
                parent_id = child.get('parent_chunk_id')
                parent_content = None
                if parent_id and parent_id in parent_map:
                    parent = parent_map[parent_id]
                    parent_content = parent.get('toc_entry', '')

                eval_chunk = EvalChunk(
                    chunk_id=child['chunk_id'],
                    content=content,
                    content_type=content_type,
                    hierarchy=child.get('hierarchy', {}),
                    report_id=report_id,
                    report_title=report_title,
                    page=child.get('source_page_physical', 0),
                    parent_content=parent_content
                )

                chunks.append(eval_chunk)
                count += 1

                if count >= max_chunks_per_report:
                    break

        except Exception as e:
            logger.warning(f"Error loading {chunk_file}: {e}")

    logger.info(f"Loaded {len(chunks)} chunks from {len(selected_files)} reports")
    return chunks, parent_map


# ============================================================================
# Evaluation Query Generation
# ============================================================================

def generate_eval_queries(chunks: List[EvalChunk]) -> List[EvalQuery]:
    """
    Generate evaluation queries with known relevant chunks.

    Uses content-based query generation:
    1. Extract key phrases from chunks
    2. Create queries that should retrieve those chunks
    3. Mark the source chunk as relevant
    """

    queries = []

    # Group chunks by report for diversity
    chunks_by_report = defaultdict(list)
    for chunk in chunks:
        chunks_by_report[chunk.report_id].append(chunk)

    query_id = 0

    for report_id, report_chunks in chunks_by_report.items():
        # Sample chunks for query generation
        sample_chunks = report_chunks[:20]  # Top 20 chunks per report

        for chunk in sample_chunks:
            content = chunk.content

            # Skip if content is too short or just a table
            if len(content) < 150:
                continue

            # Extract query-worthy phrases
            generated_queries = extract_queries_from_content(chunk, query_id)
            queries.extend(generated_queries)
            query_id += len(generated_queries)

    logger.info(f"Generated {len(queries)} evaluation queries")
    return queries


def extract_queries_from_content(chunk: EvalChunk, start_id: int) -> List[EvalQuery]:
    """Extract natural queries from chunk content."""
    import re

    queries = []
    content = chunk.content

    # Pattern 1: Monetary findings (most important for CAG)
    money_patterns = [
        r'(?:loss|revenue|expenditure|amount|payment)\s+of\s+(?:₹|Rs\.?)\s*([\d,\.]+)\s*(crore|lakh)',
        r'(?:₹|Rs\.?)\s*([\d,\.]+)\s*(crore|lakh)\s+(?:was|were|remained)',
    ]

    for pattern in money_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            # Create a factual query about the monetary amount
            query = EvalQuery(
                query_id=f"q_{start_id}",
                query_text=f"What audit finding involved monetary irregularity in {chunk.hierarchy.get('level_1', 'this section')}?",
                query_type="factual",
                relevant_chunk_ids=[chunk.chunk_id],
                report_id=chunk.report_id
            )
            queries.append(query)
            start_id += 1
            break

    # Pattern 2: Compliance/Rule violations
    rule_patterns = [
        r'violation of (Rule|Section|Article|Clause)\s+[\d\w\(\)]+',
        r'non-compliance with',
        r'contrary to (guidelines|rules|provisions)',
    ]

    for pattern in rule_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            query = EvalQuery(
                query_id=f"q_{start_id}",
                query_text=f"What compliance violations were found?",
                query_type="list",
                relevant_chunk_ids=[chunk.chunk_id],
                report_id=chunk.report_id
            )
            queries.append(query)
            start_id += 1
            break

    # Pattern 3: Recommendations
    rec_patterns = [
        r'(?:recommend|suggested|advised)\s+that',
        r'should\s+(?:ensure|take|initiate|strengthen)',
    ]

    for pattern in rec_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            # Use hierarchy for context
            section = chunk.hierarchy.get('level_2', chunk.hierarchy.get('level_1', ''))
            query = EvalQuery(
                query_id=f"q_{start_id}",
                query_text=f"What recommendations were made regarding {section}?",
                query_type="list",
                relevant_chunk_ids=[chunk.chunk_id],
                report_id=chunk.report_id
            )
            queries.append(query)
            start_id += 1
            break

    # Pattern 4: Scheme/Program names (domain-specific)
    scheme_patterns = [
        r'(MGNREGA|PMAY|PMJAY|NSAP|NREGA|Swachh Bharat|PM-KISAN)',
        r'(?:under the|implementation of)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4}\s+(?:Scheme|Programme|Yojana|Mission))',
    ]

    for pattern in scheme_patterns:
        match = re.search(pattern, content)
        if match:
            scheme = match.group(1) if match.lastindex else match.group(0)
            query = EvalQuery(
                query_id=f"q_{start_id}",
                query_text=f"What issues were found in {scheme}?",
                query_type="explanation",
                relevant_chunk_ids=[chunk.chunk_id],
                report_id=chunk.report_id
            )
            queries.append(query)
            start_id += 1
            break

    # Pattern 5: Generic content-based query (fallback)
    if not queries and len(content) > 300:
        # Use first sentence as basis
        first_sentence = content.split('.')[0][:200]
        if len(first_sentence) > 50:
            query = EvalQuery(
                query_id=f"q_{start_id}",
                query_text=f"What does the audit report say about: {first_sentence[:100]}...?",
                query_type="factual",
                relevant_chunk_ids=[chunk.chunk_id],
                report_id=chunk.report_id
            )
            queries.append(query)

    return queries


# ============================================================================
# Cross-Reference Query Generation (for Late Chunking A/B Test)
# ============================================================================


def generate_cross_reference_queries(chunks: List[EvalChunk]) -> List[EvalQuery]:
    """
    Generate queries that specifically test cross-reference resolution.

    These queries target scenarios where late chunking would provide benefit:
    - Anaphoric references ("the above", "as mentioned")
    - Thematic continuity across chunks
    - Entity coreference resolution
    """
    queries = []

    # Group chunks by report
    chunks_by_report = defaultdict(list)
    for chunk in chunks:
        chunks_by_report[chunk.report_id].append(chunk)

    query_id = 0

    for report_id, report_chunks in chunks_by_report.items():
        # Sort by page for sequential analysis
        sorted_chunks = sorted(report_chunks, key=lambda c: c.page)

        for i, chunk in enumerate(sorted_chunks[1:], 1):
            prev_chunk = sorted_chunks[i - 1]

            # Type 1: Anaphoric reference (look for backward references)
            if _has_backward_reference(chunk.content):
                referent = _extract_referent(chunk.content)
                if referent:
                    queries.append(EvalQuery(
                        query_id=f"xref_{query_id}",
                        query_text=f"What does '{referent}' refer to in the audit report?",
                        query_type="cross_reference",
                        relevant_chunk_ids=[chunk.chunk_id, prev_chunk.chunk_id],
                        report_id=report_id
                    ))
                    query_id += 1

            # Type 2: Continuation pattern (same topic across chunks)
            if _is_continuation(chunk.content, prev_chunk.content):
                topic = _extract_topic(chunk.content, prev_chunk.content)
                if topic:
                    queries.append(EvalQuery(
                        query_id=f"xref_{query_id}",
                        query_text=f"Explain the full context of {topic}",
                        query_type="thematic_continuity",
                        relevant_chunk_ids=[chunk.chunk_id, prev_chunk.chunk_id],
                        report_id=report_id
                    ))
                    query_id += 1

            # Type 3: Entity coreference (same entity mentioned in consecutive chunks)
            shared_entities = _find_shared_entities(chunk.content, prev_chunk.content)
            if shared_entities:
                entity = shared_entities[0]
                queries.append(EvalQuery(
                    query_id=f"xref_{query_id}",
                    query_text=f"What issues were found regarding {entity}?",
                    query_type="entity_coreference",
                    relevant_chunk_ids=[chunk.chunk_id, prev_chunk.chunk_id],
                    report_id=report_id
                ))
                query_id += 1

    logger.info(f"Generated {len(queries)} cross-reference queries")
    return queries


def _has_backward_reference(text: str) -> bool:
    """Check if text contains backward references like 'the above', 'as mentioned'."""
    patterns = [
        r'\b(the above|above mentioned|aforesaid|said)\b',
        r'\b(as mentioned|as stated|as discussed)\b',
        r'\b(this department|this ministry|the ministry)\b',
        r'\b(the same|these|those)\s+(observations?|findings?|irregularit)',
    ]
    return any(re.search(p, text, re.I) for p in patterns)


def _extract_referent(text: str) -> Optional[str]:
    """Extract the referent phrase from backward reference."""
    patterns = [
        (r'(the above|above mentioned|aforesaid)\s+(\w+(?:\s+\w+)?)', 2),
        (r'(as mentioned|as stated)\s+(?:in|above|earlier)', 0),
        (r'(this|the)\s+(department|ministry|scheme|project)', 0),
    ]

    for pattern, group in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            if group > 0:
                return match.group(group)
            return match.group(0)

    return "the above mentioned"  # Default fallback


def _is_continuation(current: str, prev: str) -> bool:
    """Check if current chunk continues the topic from previous chunk."""
    # Look for continuation markers
    continuation_markers = [
        r'^(further|moreover|additionally|also|in addition)',
        r'^(the|this)\s+(audit|examination|review)\s+(also|further)',
        r'^(it was|we)\s+(also|further)\s+(observed|noted|found)',
    ]

    for marker in continuation_markers:
        if re.match(marker, current.strip(), re.I):
            return True

    return False


def _extract_topic(current: str, prev: str) -> Optional[str]:
    """Extract shared topic between chunks."""
    # Look for scheme/project names
    scheme_pattern = r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Scheme|Programme|Project|Mission|Yojana))'

    current_schemes = set(re.findall(scheme_pattern, current))
    prev_schemes = set(re.findall(scheme_pattern, prev))

    shared = current_schemes & prev_schemes
    if shared:
        return list(shared)[0]

    # Look for department names
    dept_pattern = r'(Ministry of\s+[A-Z][a-z]+(?:\s+[A-Za-z]+)*|Department of\s+[A-Z][a-z]+(?:\s+[A-Za-z]+)*)'

    current_depts = set(re.findall(dept_pattern, current))
    prev_depts = set(re.findall(dept_pattern, prev))

    shared = current_depts & prev_depts
    if shared:
        return list(shared)[0]

    return None


def _find_shared_entities(current: str, prev: str) -> List[str]:
    """Find entities mentioned in both chunks."""
    # Look for acronyms (likely entity names)
    acronym_pattern = r'\b([A-Z]{2,6})\b'

    current_acronyms = set(re.findall(acronym_pattern, current))
    prev_acronyms = set(re.findall(acronym_pattern, prev))

    # Filter out common non-entity acronyms
    non_entities = {'CAG', 'PAC', 'Rs', 'Cr', 'FY', 'AG', 'GOI', 'GOK', 'NER', 'PSU', 'PSE'}
    shared = (current_acronyms & prev_acronyms) - non_entities

    return list(shared)


# ============================================================================
# Embedding Services
# ============================================================================

class OpenAIEmbedder:
    """Current embedding strategy using OpenAI."""

    def __init__(self, api_key: str, dimensions: int = 1536):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = "text-embedding-3-large"
        self.dimensions = dimensions
        self.name = f"OpenAI ({self.model}, {dimensions}d)"

    def prepare_text(self, chunk: EvalChunk, include_hierarchy: bool = True) -> str:
        """Prepare text for embedding (current strategy)."""
        parts = []

        if include_hierarchy:
            prefix = chunk.get_hierarchy_prefix()
            if prefix:
                parts.append(f"[{prefix}]")

        parts.append(chunk.content)

        return '\n\n'.join(parts)

    def embed_batch(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        """Embed texts in batches."""
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.client.embeddings.create(
                input=batch,
                model=self.model,
                dimensions=self.dimensions
            )
            embeddings = [e.embedding for e in response.data]
            all_embeddings.extend(embeddings)

        return all_embeddings

    def embed_chunks(self, chunks: List[EvalChunk]) -> Dict[str, List[float]]:
        """Embed all chunks, return chunk_id -> embedding mapping."""
        texts = [self.prepare_text(c) for c in chunks]
        embeddings = self.embed_batch(texts)
        return {chunk.chunk_id: emb for chunk, emb in zip(chunks, embeddings)}

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query."""
        response = self.client.embeddings.create(
            input=[query],
            model=self.model,
            dimensions=self.dimensions
        )
        return response.data[0].embedding


class OpenAIOptimizedEmbedder:
    """
    Optimized embedding strategy using OpenAI with OPT-1, OPT-5.

    Implements:
    - OPT-1: Context augmentation (report title, parent context)
    - OPT-5: Content type signal

    Note: OPT-4 (query prefix) is disabled by default as it can create asymmetry
    when documents don't use the same prefix style.
    """

    def __init__(self, api_key: str, dimensions: int = 1536, use_query_prefix: bool = False):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = "text-embedding-3-large"
        self.dimensions = dimensions
        self.use_query_prefix = use_query_prefix
        opt_label = "OPT-1,4,5" if use_query_prefix else "OPT-1,5"
        self.name = f"OpenAI Optimized ({opt_label})"
        self.query_prefix = "Retrieve audit finding: "

    def prepare_text(self, chunk: EvalChunk) -> str:
        """Prepare text for embedding with optimizations."""
        parts = []
        prefix_parts = []

        # OPT-5: Content type signal
        content_type = chunk.content_type
        content_signal = ""
        if content_type in ("table_markdown", "table"):
            content_signal = "TABLE"
        # Could also check finding_type/is_recommendation but EvalChunk doesn't have those

        # Build prefix with content signal
        hierarchy_prefix = chunk.get_hierarchy_prefix()
        if content_signal and hierarchy_prefix:
            prefix_parts.append(f"[{content_signal} | {hierarchy_prefix}]")
        elif content_signal:
            prefix_parts.append(f"[{content_signal}]")
        elif hierarchy_prefix:
            prefix_parts.append(f"[{hierarchy_prefix}]")

        # OPT-1: Include report title (truncated)
        if chunk.report_title:
            short_title = chunk.report_title[:80] + "..." if len(chunk.report_title) > 80 else chunk.report_title
            prefix_parts.insert(0, f"Report: {short_title}")

        # OPT-1: Parent section context
        if chunk.parent_content:
            parts.append(f"Section: {chunk.parent_content}")

        # Combine prefix
        if prefix_parts:
            parts.insert(0, ' | '.join(prefix_parts))

        # Add main content
        parts.append(chunk.content)

        return '\n\n'.join(parts)

    def embed_batch(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        """Embed texts in batches."""
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.client.embeddings.create(
                input=batch,
                model=self.model,
                dimensions=self.dimensions
            )
            embeddings = [e.embedding for e in response.data]
            all_embeddings.extend(embeddings)

        return all_embeddings

    def embed_chunks(self, chunks: List[EvalChunk]) -> Dict[str, List[float]]:
        """Embed all chunks with optimized text preparation."""
        texts = [self.prepare_text(c) for c in chunks]
        embeddings = self.embed_batch(texts)
        return {chunk.chunk_id: emb for chunk, emb in zip(chunks, embeddings)}

    def embed_query(self, query: str) -> List[float]:
        """Embed a query, optionally with OPT-4 instruction prefix."""
        # OPT-4: Add query instruction prefix (if enabled)
        if self.use_query_prefix:
            query_text = f"{self.query_prefix}{query}"
        else:
            query_text = query

        response = self.client.embeddings.create(
            input=[query_text],
            model=self.model,
            dimensions=self.dimensions
        )
        return response.data[0].embedding


class OpenAIExtendedContextEmbedder:
    """
    OpenAI embeddings with extended context (simulates late chunking benefit).

    This strategy includes neighboring chunk content in the embedding,
    approximating the contextual awareness that late chunking provides.
    If this improves retrieval, late chunking would likely help too.
    """

    def __init__(self, api_key: str, dimensions: int = 1536, context_window: int = 1):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = "text-embedding-3-large"
        self.dimensions = dimensions
        self.context_window = context_window  # Number of chunks before/after to include
        self.name = f"OpenAI Extended Context (±{context_window} chunks)"

    def prepare_text_with_context(
        self,
        chunk: EvalChunk,
        prev_chunks: List[EvalChunk],
        next_chunks: List[EvalChunk]
    ) -> str:
        """Prepare text with surrounding context (simulates late chunking)."""
        parts = []

        # Include context signal
        hierarchy_prefix = chunk.get_hierarchy_prefix()
        if hierarchy_prefix:
            parts.append(f"[{hierarchy_prefix}]")

        # Include previous context (truncated)
        if prev_chunks:
            prev_context = " ".join(c.content[:200] for c in prev_chunks[-self.context_window:])
            if prev_context:
                parts.append(f"[Previous context: {prev_context[:400]}...]")

        # Main content
        parts.append(chunk.content)

        # Include next context (truncated)
        if next_chunks:
            next_context = " ".join(c.content[:200] for c in next_chunks[:self.context_window])
            if next_context:
                parts.append(f"[Following context: {next_context[:400]}...]")

        return '\n\n'.join(parts)

    def embed_batch(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        """Embed texts in batches."""
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.client.embeddings.create(
                input=batch,
                model=self.model,
                dimensions=self.dimensions
            )
            embeddings = [e.embedding for e in response.data]
            all_embeddings.extend(embeddings)

        return all_embeddings

    def embed_chunks(self, chunks: List[EvalChunk]) -> Dict[str, List[float]]:
        """Embed all chunks with extended context."""
        # Group by report to maintain document order
        chunks_by_report = defaultdict(list)
        for chunk in chunks:
            chunks_by_report[chunk.report_id].append(chunk)

        texts = []
        chunk_order = []

        for report_id, report_chunks in chunks_by_report.items():
            # Sort by page for document order
            sorted_chunks = sorted(report_chunks, key=lambda c: c.page)

            for i, chunk in enumerate(sorted_chunks):
                prev_chunks = sorted_chunks[max(0, i - self.context_window):i]
                next_chunks = sorted_chunks[i + 1:i + 1 + self.context_window]

                text = self.prepare_text_with_context(chunk, prev_chunks, next_chunks)
                texts.append(text)
                chunk_order.append(chunk)

        embeddings = self.embed_batch(texts)
        return {chunk.chunk_id: emb for chunk, emb in zip(chunk_order, embeddings)}

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query."""
        response = self.client.embeddings.create(
            input=[query],
            model=self.model,
            dimensions=self.dimensions
        )
        return response.data[0].embedding


class VoyageContextEmbedder:
    """Voyage embeddings with contextual augmentation."""

    def __init__(self, api_key: str, model: str = "voyage-3.5"):
        import voyageai
        self.client = voyageai.Client(api_key=api_key)
        self.model = model  # voyage-3.5 is their latest best model
        self.name = f"Voyage ({self.model})"

    def embed_chunks_contextual(self, chunks: List[EvalChunk]) -> Dict[str, List[float]]:
        """
        Embed chunks with document context.
        Voyage context-4 handles contextual embedding natively.
        """
        # Group chunks by report for document-level context
        chunks_by_report = defaultdict(list)
        for chunk in chunks:
            chunks_by_report[chunk.report_id].append(chunk)

        all_embeddings = {}

        for report_id, report_chunks in tqdm(chunks_by_report.items(), desc="Embedding (Voyage)"):
            # Prepare texts with parent context (for Voyage's contextual model)
            texts = []
            for chunk in report_chunks:
                # Include parent section as context prefix
                context = chunk.parent_content or chunk.get_hierarchy_prefix()
                if context:
                    text = f"[Context: {context}]\n\n{chunk.content}"
                else:
                    text = chunk.content
                texts.append(text)

            # Embed with Voyage
            try:
                result = self.client.embed(
                    texts=texts,
                    model=self.model,
                    input_type="document"
                )

                for chunk, embedding in zip(report_chunks, result.embeddings):
                    all_embeddings[chunk.chunk_id] = embedding

            except Exception as e:
                logger.error(f"Voyage embedding error for {report_id}: {e}")
                # Fallback: embed individually
                for chunk, text in zip(report_chunks, texts):
                    try:
                        result = self.client.embed(
                            texts=[text],
                            model=self.model,
                            input_type="document"
                        )
                        all_embeddings[chunk.chunk_id] = result.embeddings[0]
                    except:
                        logger.warning(f"Skipping chunk {chunk.chunk_id}")

        return all_embeddings

    def embed_query(self, query: str) -> List[float]:
        """Embed a query with rate limit handling."""
        import time
        max_retries = 5
        for attempt in range(max_retries):
            try:
                result = self.client.embed(
                    texts=[query],
                    model=self.model,
                    input_type="query"
                )
                return result.embeddings[0]
            except Exception as e:
                if "rate" in str(e).lower() and attempt < max_retries - 1:
                    wait_time = 20 * (attempt + 1)  # 20, 40, 60, 80 seconds
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise


# ============================================================================
# Retrieval & Evaluation
# ============================================================================

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    v1 = np.array(v1)
    v2 = np.array(v2)
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))


def retrieve_top_k(
    query_embedding: List[float],
    chunk_embeddings: Dict[str, List[float]],
    k: int = 10,
    filter_report_id: Optional[str] = None
) -> List[RetrievalResult]:
    """Retrieve top-k chunks by cosine similarity."""

    scores = []
    for chunk_id, embedding in chunk_embeddings.items():
        # Optional report filtering
        if filter_report_id and not chunk_id.startswith(filter_report_id):
            continue

        score = cosine_similarity(query_embedding, embedding)
        scores.append((chunk_id, score))

    # Sort by score descending
    scores.sort(key=lambda x: x[1], reverse=True)

    results = []
    for rank, (chunk_id, score) in enumerate(scores[:k], 1):
        results.append(RetrievalResult(
            chunk_id=chunk_id,
            score=score,
            rank=rank
        ))

    return results


def evaluate_retrieval(
    queries: List[EvalQuery],
    embedder,
    chunk_embeddings: Dict[str, List[float]],
    k_values: List[int] = [1, 3, 5, 10]
) -> EvalMetrics:
    """
    Evaluate retrieval performance.

    Metrics:
    - MRR: Mean Reciprocal Rank
    - Recall@k: Fraction of relevant docs in top-k
    - Precision@k: Relevant docs in top-k / k
    - Hit Rate: Queries with at least one relevant doc in top-k
    """
    import time

    reciprocal_ranks = []
    recalls = {k: [] for k in k_values}
    precisions = {k: [] for k in k_values}
    hits = {k: 0 for k in k_values}
    total_latency_ms = 0

    for query in tqdm(queries, desc="Evaluating"):
        # Embed query
        start = time.time()
        query_emb = embedder.embed_query(query.query_text)
        latency_ms = (time.time() - start) * 1000
        total_latency_ms += latency_ms

        # Retrieve
        results = retrieve_top_k(
            query_emb,
            chunk_embeddings,
            k=max(k_values),
            filter_report_id=query.report_id  # Scope to same report
        )

        retrieved_ids = [r.chunk_id for r in results]
        relevant_ids = set(query.relevant_chunk_ids)

        # MRR: find rank of first relevant doc
        rr = 0
        for result in results:
            if result.chunk_id in relevant_ids:
                rr = 1.0 / result.rank
                break
        reciprocal_ranks.append(rr)

        # Recall@k and Precision@k
        for k in k_values:
            top_k_ids = set(retrieved_ids[:k])
            relevant_in_top_k = len(top_k_ids & relevant_ids)

            recall = relevant_in_top_k / len(relevant_ids) if relevant_ids else 0
            precision = relevant_in_top_k / k

            recalls[k].append(recall)
            precisions[k].append(precision)

            if relevant_in_top_k > 0:
                hits[k] += 1

    n_queries = len(queries)

    return EvalMetrics(
        mrr=np.mean(reciprocal_ranks),
        recall_at_1=np.mean(recalls[1]),
        recall_at_3=np.mean(recalls[3]),
        recall_at_5=np.mean(recalls[5]),
        recall_at_10=np.mean(recalls[10]),
        precision_at_1=np.mean(precisions[1]),
        precision_at_5=np.mean(precisions[5]),
        hit_rate=hits[10] / n_queries,
        avg_latency_ms=total_latency_ms / n_queries,
        total_queries=n_queries
    )


# ============================================================================
# Comparison Report
# ============================================================================

def print_comparison_report(
    metrics: Dict[str, EvalMetrics],
    output_file: Optional[Path] = None
):
    """Print side-by-side comparison of embedding strategies."""

    report_lines = []

    def add_line(line: str = ""):
        report_lines.append(line)
        print(line)

    add_line("\n" + "=" * 80)
    add_line("EMBEDDING STRATEGY EVALUATION REPORT")
    add_line("=" * 80)

    # Strategy names
    strategies = list(metrics.keys())

    add_line(f"\nStrategies Compared: {len(strategies)}")
    for name in strategies:
        add_line(f"  - {name}")

    add_line(f"\nTotal Queries: {metrics[strategies[0]].total_queries}")

    # Metrics table
    add_line("\n" + "-" * 80)
    add_line("RETRIEVAL METRICS")
    add_line("-" * 80)

    # Header
    header = f"{'Metric':<25}"
    for name in strategies:
        short_name = name.split('(')[0].strip()[:15]
        header += f"{short_name:>15}"
    if len(strategies) == 2:
        header += f"{'Δ (B-A)':>12}{'% Change':>12}"
    add_line(header)
    add_line("-" * 80)

    # Metrics rows
    metric_names = [
        ('MRR', 'mrr'),
        ('Recall@1', 'recall_at_1'),
        ('Recall@3', 'recall_at_3'),
        ('Recall@5', 'recall_at_5'),
        ('Recall@10', 'recall_at_10'),
        ('Precision@1', 'precision_at_1'),
        ('Precision@5', 'precision_at_5'),
        ('Hit Rate@10', 'hit_rate'),
        ('Avg Latency (ms)', 'avg_latency_ms'),
    ]

    for display_name, attr in metric_names:
        row = f"{display_name:<25}"
        values = [getattr(metrics[name], attr) for name in strategies]

        for val in values:
            if attr == 'avg_latency_ms':
                row += f"{val:>15.1f}"
            else:
                row += f"{val:>15.3f}"

        # Delta for two strategies
        if len(strategies) == 2 and attr != 'avg_latency_ms':
            delta = values[1] - values[0]
            pct_change = (delta / values[0] * 100) if values[0] > 0 else 0
            row += f"{delta:>+12.3f}{pct_change:>+11.1f}%"

        add_line(row)

    add_line("-" * 80)

    # Summary
    add_line("\nSUMMARY")
    add_line("-" * 80)

    # Compare Baseline vs Optimized if both present
    baseline_key = None
    optimized_key = None
    for name in strategies:
        if "Baseline" in name:
            baseline_key = name
        elif "Optimized" in name:
            optimized_key = name

    if baseline_key and optimized_key:
        baseline_m = metrics[baseline_key]
        optimized_m = metrics[optimized_key]

        mrr_delta = (optimized_m.mrr - baseline_m.mrr) / baseline_m.mrr * 100 if baseline_m.mrr > 0 else 0
        recall5_delta = (optimized_m.recall_at_5 - baseline_m.recall_at_5) / baseline_m.recall_at_5 * 100 if baseline_m.recall_at_5 > 0 else 0

        add_line(f"\n  Baseline vs Optimized (OPT-1,4,5):")
        add_line(f"  ─────────────────────────────────")

        if mrr_delta > 2:
            add_line(f"  ✅ Optimized shows +{mrr_delta:.1f}% MRR improvement")
        elif mrr_delta < -2:
            add_line(f"  ⚠️  Baseline outperforms by {-mrr_delta:.1f}% MRR")
        else:
            add_line(f"  ➖ MRR difference is marginal ({mrr_delta:+.1f}%)")

        if recall5_delta > 2:
            add_line(f"  ✅ Optimized shows +{recall5_delta:.1f}% Recall@5 improvement")
        elif recall5_delta < -2:
            add_line(f"  ⚠️  Baseline has better Recall@5 by {-recall5_delta:.1f}%")
        else:
            add_line(f"  ➖ Recall@5 difference is marginal ({recall5_delta:+.1f}%)")

        # Overall verdict
        add_line("")
        if mrr_delta > 3 or recall5_delta > 3:
            add_line(f"  VERDICT: Deploy optimizations (OPT-1, OPT-4, OPT-5)")
        elif mrr_delta < -3 or recall5_delta < -3:
            add_line(f"  VERDICT: Keep baseline, investigate optimization issues")
        else:
            add_line(f"  VERDICT: Optimizations show slight improvement, deploy for incremental gains")

    elif len(strategies) == 2:
        a_metrics = metrics[strategies[0]]
        b_metrics = metrics[strategies[1]]

        mrr_delta = (b_metrics.mrr - a_metrics.mrr) / a_metrics.mrr * 100 if a_metrics.mrr > 0 else 0
        recall5_delta = (b_metrics.recall_at_5 - a_metrics.recall_at_5) / a_metrics.recall_at_5 * 100 if a_metrics.recall_at_5 > 0 else 0

        if mrr_delta > 5:
            add_line(f"  ✅ {strategies[1]} shows +{mrr_delta:.1f}% MRR improvement")
        elif mrr_delta < -5:
            add_line(f"  ⚠️  {strategies[0]} outperforms by {-mrr_delta:.1f}% MRR")
        else:
            add_line(f"  ➖ MRR difference is marginal ({mrr_delta:+.1f}%)")

        if recall5_delta > 10:
            add_line(f"  ✅ {strategies[1]} shows +{recall5_delta:.1f}% Recall@5 improvement")
            add_line(f"\n  RECOMMENDATION: Consider migrating to {strategies[1]}")
        elif recall5_delta < -10:
            add_line(f"  ⚠️  {strategies[0]} has better Recall@5 by {-recall5_delta:.1f}%")
            add_line(f"\n  RECOMMENDATION: Keep current strategy ({strategies[0]})")
        else:
            add_line(f"  ➖ Recall@5 difference is marginal ({recall5_delta:+.1f}%)")
            add_line(f"\n  RECOMMENDATION: Improvements should focus on other areas (reranking, query expansion)")

    add_line("\n" + "=" * 80)

    # Save to file
    if output_file:
        with open(output_file, 'w') as f:
            f.write('\n'.join(report_lines))
        print(f"\nReport saved to: {output_file}")


# ============================================================================
# Cache Management
# ============================================================================

def get_cache_path(strategy_name: str, chunk_count: int) -> Path:
    """Get cache file path for embeddings."""
    cache_dir = Path("data/embedding_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Hash strategy name for filename
    name_hash = hashlib.md5(strategy_name.encode()).hexdigest()[:8]
    return cache_dir / f"embeddings_{name_hash}_{chunk_count}.json"


def save_embeddings_cache(embeddings: Dict[str, List[float]], cache_path: Path):
    """Save embeddings to cache."""
    with open(cache_path, 'w') as f:
        json.dump(embeddings, f)
    logger.info(f"Cached {len(embeddings)} embeddings to {cache_path}")


def load_embeddings_cache(cache_path: Path) -> Optional[Dict[str, List[float]]]:
    """Load embeddings from cache if exists."""
    if cache_path.exists():
        with open(cache_path) as f:
            embeddings = json.load(f)
        logger.info(f"Loaded {len(embeddings)} embeddings from cache")
        return embeddings
    return None


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Evaluate embedding strategies")
    parser.add_argument("--sample-size", type=int, default=200,
                       help="Number of chunks to evaluate")
    parser.add_argument("--max-reports", type=int, default=6,
                       help="Maximum reports to load")
    parser.add_argument("--voyage-key", type=str, default=None,
                       help="Voyage AI API key (or set VOYAGE_API_KEY env)")
    parser.add_argument("--openai-key", type=str, default=None,
                       help="OpenAI API key (or set OPENAI_API_KEY env)")
    parser.add_argument("--no-cache", action="store_true",
                       help="Disable embedding cache")
    parser.add_argument("--output", type=str, default="eval_report.txt",
                       help="Output file for report")
    parser.add_argument("--full", action="store_true",
                       help="Run full evaluation (500+ chunks)")
    parser.add_argument("--late-chunking-test", action="store_true",
                       help="Run late chunking A/B test (includes extended context embedder)")
    parser.add_argument("--cross-reference-focus", action="store_true",
                       help="Focus on cross-reference queries only")

    args = parser.parse_args()

    # API Keys
    openai_key = args.openai_key or os.getenv("OPENAI_API_KEY")
    voyage_key = args.voyage_key or os.getenv("VOYAGE_API_KEY")

    if not openai_key:
        logger.error("OpenAI API key required. Set OPENAI_API_KEY or use --openai-key")
        sys.exit(1)

    # Adjust for full evaluation
    if args.full:
        args.sample_size = 500
        args.max_reports = 10

    # Load chunks
    processed_dir = Path("data/processed")
    chunks, parent_map = load_chunks_from_reports(
        processed_dir,
        max_reports=args.max_reports,
        max_chunks_per_report=args.sample_size // args.max_reports
    )

    # Limit to sample size
    chunks = chunks[:args.sample_size]
    logger.info(f"Using {len(chunks)} chunks for evaluation")

    # Generate evaluation queries
    if args.cross_reference_focus or args.late_chunking_test:
        # Generate cross-reference queries for late chunking test
        xref_queries = generate_cross_reference_queries(chunks)
        regular_queries = generate_eval_queries(chunks)

        if args.cross_reference_focus:
            queries = xref_queries
            logger.info(f"Using {len(queries)} cross-reference queries only")
        else:
            queries = regular_queries + xref_queries
            logger.info(f"Using {len(regular_queries)} regular + {len(xref_queries)} cross-reference queries")
    else:
        queries = generate_eval_queries(chunks)

    if len(queries) < 10:
        logger.warning("Too few queries generated. Check chunk content.")

    # Initialize embedders
    embedders = {}
    embedders["OpenAI Baseline"] = OpenAIEmbedder(openai_key)
    embedders["OpenAI Optimized"] = OpenAIOptimizedEmbedder(openai_key)

    # Add extended context embedder for late chunking test
    if args.late_chunking_test:
        embedders["Extended Context (±1)"] = OpenAIExtendedContextEmbedder(openai_key, context_window=1)
        embedders["Extended Context (±2)"] = OpenAIExtendedContextEmbedder(openai_key, context_window=2)
        logger.info("Late chunking test mode: Added Extended Context embedders")

    if voyage_key:
        try:
            embedders["Voyage 3.5"] = VoyageContextEmbedder(voyage_key)
        except ImportError:
            logger.warning("voyageai package not installed. Run: pip install voyageai")
    elif not args.late_chunking_test:
        logger.info("No Voyage API key. Comparing OpenAI Baseline vs Optimized only.")

    # Embed and evaluate each strategy
    all_metrics = {}

    for name, embedder in embedders.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"Evaluating: {name}")
        logger.info(f"{'='*60}")

        # Check cache
        cache_path = get_cache_path(name, len(chunks))
        chunk_embeddings = None

        if not args.no_cache:
            chunk_embeddings = load_embeddings_cache(cache_path)

        if chunk_embeddings is None:
            # Generate embeddings
            logger.info("Generating embeddings...")

            if isinstance(embedder, VoyageContextEmbedder):
                chunk_embeddings = embedder.embed_chunks_contextual(chunks)
            else:
                chunk_embeddings = embedder.embed_chunks(chunks)

            # Cache embeddings
            if not args.no_cache:
                save_embeddings_cache(chunk_embeddings, cache_path)

        # Evaluate
        logger.info("Running retrieval evaluation...")
        metrics = evaluate_retrieval(queries, embedder, chunk_embeddings)
        all_metrics[name] = metrics

        logger.info(f"MRR: {metrics.mrr:.3f}, Recall@5: {metrics.recall_at_5:.3f}")

    # Print comparison report
    output_path = Path("logs") / args.output
    output_path.parent.mkdir(exist_ok=True)
    print_comparison_report(all_metrics, output_path)


if __name__ == "__main__":
    main()
