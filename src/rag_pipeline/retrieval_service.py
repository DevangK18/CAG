"""
CAG RAG Pipeline - Retrieval Service
=====================================

Handles:
1. Query embedding (dense + sparse)
2. Hybrid search with filters
3. Cross-encoder reranking
4. O(1) neighbor chunk lookup

Requirements:
    pip install openai cohere sentence-transformers
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("Install openai: pip install openai")

# Reranking options
try:
    import cohere

    COHERE_AVAILABLE = True
except ImportError:
    COHERE_AVAILABLE = False

try:
    from sentence_transformers import CrossEncoder

    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False

# Note: fastembed not used due to huggingface_hub conflicts with docling
# Using built-in BM25 tokenization instead

try:
    from ..core.config import RAGConfig, RerankerType
    from .models import RetrievedChunk, ParentContext, RetrievalResult
    from .qdrant_service import QdrantService
    from .query_enhancer import QueryEnhancement
except ImportError:
    from src.core.config import RAGConfig, RerankerType
    from models import RetrievedChunk, ParentContext, RetrievalResult
    from qdrant_service import QdrantService
    from query_enhancer import QueryEnhancement

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# RERANKERS
# =============================================================================


class CohereReranker:
    """Cohere reranking service."""

    def __init__(self, api_key: str, model: str = "rerank-english-v3.0"):
        self.client = cohere.Client(api_key=api_key)
        self.model = model

    def rerank(
        self,
        query: str,
        chunks: List[RetrievedChunk],
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Rerank chunks using Cohere with hierarchy context."""
        if not chunks:
            return []

        # Prepend hierarchy breadcrumbs for better reranking context
        documents = []
        for c in chunks:
            prefix = ""
            if c.hierarchy:
                prefix = f"[{' > '.join(c.hierarchy.values())}] "
            documents.append(prefix + c.content)

        response = self.client.rerank(
            model=self.model,
            query=query,
            documents=documents,
            top_n=min(top_k, len(chunks)),
        )

        reranked = []
        for result in response.results:
            chunk = chunks[result.index]
            chunk.score = result.relevance_score
            reranked.append(chunk)

        return reranked


class BGEReranker:
    """Local BGE cross-encoder reranker."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model = CrossEncoder(model_name)
        logger.info(f"Loaded BGE reranker: {model_name}")

    def rerank(
        self,
        query: str,
        chunks: List[RetrievedChunk],
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Rerank using cross-encoder with hierarchy context."""
        if not chunks:
            return []

        # Prepend hierarchy breadcrumbs for better reranking context
        pairs = []
        for c in chunks:
            prefix = ""
            if c.hierarchy:
                prefix = f"[{' > '.join(c.hierarchy.values())}] "
            pairs.append((query, prefix + c.content))

        scores = self.model.predict(pairs)

        for chunk, score in zip(chunks, scores):
            chunk.score = float(score)

        chunks.sort(key=lambda c: -c.score)
        return chunks[:top_k]


# =============================================================================
# NEIGHBOR PREDICTOR (O(1) Optimization)
# =============================================================================


class NeighborPredictor:
    """
    Predicts neighbor chunk IDs without searching.

    Uses the deterministic chunk ID pattern:
    {report_id}_child_p{page:03d}_{content_type}_{index:04d}
    """

    @staticmethod
    def parse_chunk_id(chunk_id: str) -> Optional[Dict[str, Any]]:
        """
        Parse chunk ID into components.

        Returns:
            Dict with report_id, page, content_type, index
        """
        # Pattern: 2023_07_child_p045_paragraph_0123
        pattern = r"^(.+)_child_p(\d+)_(\w+)_(\d+)$"
        match = re.match(pattern, chunk_id)

        if not match:
            return None

        return {
            "report_id": match.group(1),
            "page": int(match.group(2)),
            "content_type": match.group(3),
            "index": int(match.group(4)),
        }

    @staticmethod
    def predict_neighbor_ids(chunk_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Predict previous and next chunk IDs.

        Returns:
            (prev_chunk_id, next_chunk_id)
        """
        parsed = NeighborPredictor.parse_chunk_id(chunk_id)
        if not parsed:
            return None, None

        # Previous (index - 1)
        prev_id = None
        if parsed["index"] > 0:
            prev_id = (
                f"{parsed['report_id']}_child_p{parsed['page']:03d}_"
                f"{parsed['content_type']}_{parsed['index'] - 1:04d}"
            )

        # Next (index + 1)
        next_id = (
            f"{parsed['report_id']}_child_p{parsed['page']:03d}_"
            f"{parsed['content_type']}_{parsed['index'] + 1:04d}"
        )

        return prev_id, next_id


# =============================================================================
# SPARSE QUERY ENCODER (Built-in BM25)
# =============================================================================


class SparseQueryEncoder:
    """
    Encodes queries to sparse vectors for hybrid search.

    Uses built-in BM25-style tokenization optimized for CAG documents.
    No fastembed dependency required.
    """

    def __init__(self, model_name: str = "built-in-bm25"):
        self._vocab: Dict[str, int] = {}
        self._next_id = 0

        # Stopwords
        self._stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "been",
            "be",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
            "they",
            "them",
            "their",
            "which",
            "who",
            "what",
            "where",
            "when",
            "why",
            "how",
            "all",
            "some",
            "any",
        }

        logger.info("SparseQueryEncoder initialized (built-in BM25)")

    def encode(self, text: str) -> Dict[str, List]:
        """Encode query to sparse vector."""
        tokens = []
        text_lower = text.lower()

        # Extract special patterns (high boost for exact matching)
        # Section references
        for match in re.finditer(r"section\s*(\d+)(?:\s*\(([^)]+)\))?", text_lower):
            section_num = match.group(1)
            subsection = match.group(2) if match.group(2) else ""
            if subsection:
                tokens.append(f"section_{section_num}_{subsection.replace(' ', '')}")
            else:
                tokens.append(f"section_{section_num}")

        # Rule references
        for match in re.finditer(r"rule\s*(\d+[a-z]?)", text_lower):
            tokens.append(f"rule_{match.group(1)}")

        # Form references
        for match in re.finditer(r"form\s*(\d+[a-z]*)", text_lower):
            tokens.append(f"form_{match.group(1)}")

        # Article references
        for match in re.finditer(r"article\s*(\d+)", text_lower):
            tokens.append(f"article_{match.group(1)}")

        # Monetary indicators
        if re.search(r"crore|lakh|₹", text_lower):
            tokens.append("money_crore")

        # Year references
        for match in re.finditer(r"\b(20\d{2}(?:-\d{2})?)\b", text):
            tokens.append(f"year_{match.group(1)}")

        # Acronyms (uppercase)
        for match in re.finditer(r"\b([A-Z]{2,6})\b", text):
            tokens.append(f"acronym_{match.group(1)}")

        # Regular words
        words = re.findall(r"\b[a-z]{2,}\b", text_lower)
        tokens.extend([w for w in words if w not in self._stopwords])

        # Build sparse vector
        tf: Dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1

        indices = []
        values = []

        for token, count in tf.items():
            if token not in self._vocab:
                self._vocab[token] = self._next_id
                self._next_id += 1

            # BM25-style TF saturation with pattern boost
            tf_score = count / (count + 1.2)

            if token.startswith(("section_", "rule_", "form_", "article_")):
                boost = 3.0
            elif token.startswith("acronym_"):
                boost = 2.5
            elif token.startswith(("money_", "year_")):
                boost = 1.5
            else:
                boost = 1.0

            indices.append(self._vocab[token])
            values.append(float(tf_score * boost))

        return {"indices": indices, "values": values}


# =============================================================================
# RETRIEVAL SERVICE
# =============================================================================


class RetrievalService:
    """
    Complete retrieval service with:
    - Hybrid search (dense + sparse)
    - Cross-encoder reranking
    - O(1) neighbor lookup
    - Semantic filtering
    """

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()

        # Validate
        if not self.config.openai_api_key:
            raise ValueError("OPENAI_API_KEY required")

        # OpenAI for dense embeddings
        self.openai_client = OpenAI(api_key=self.config.openai_api_key)

        # Qdrant
        self.qdrant = QdrantService(self.config)

        # Sparse encoder
        self.sparse_encoder = None
        if self.config.retrieval.enable_hybrid_search:
            self.sparse_encoder = SparseQueryEncoder()

        # Reranker
        self.reranker = None
        if self.config.retrieval.enable_reranking:
            self._init_reranker()

        # Neighbor predictor
        self.neighbor_predictor = NeighborPredictor()

        logger.info("RetrievalService initialized")

    def _init_reranker(self):
        """Initialize reranker based on config."""
        reranker_type = self.config.retrieval.reranker_type

        if reranker_type == RerankerType.COHERE:
            if COHERE_AVAILABLE and self.config.cohere_api_key:
                self.reranker = CohereReranker(
                    self.config.cohere_api_key,
                    self.config.retrieval.cohere_model,
                )
                logger.info("Using Cohere reranker")
            else:
                logger.warning("Cohere not available, reranking disabled")

        elif reranker_type == RerankerType.BGE:
            if CROSS_ENCODER_AVAILABLE:
                self.reranker = BGEReranker(self.config.retrieval.bge_model)
                logger.info("Using BGE reranker")
            else:
                logger.warning(
                    "sentence-transformers not available, reranking disabled"
                )

    def retrieve_multi_query(
        self,
        queries: List[str],
        top_k: Optional[int] = None,
        initial_candidates: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        enhancement: Optional[QueryEnhancement] = None,
    ) -> RetrievalResult:
        """
        Multi-query retrieval with RRF fusion.

        Args:
            queries: List of queries (original + expansions). First is the original.
            top_k: Final number of chunks after reranking.
            initial_candidates: Candidates per query before fusion.
            filters: Qdrant filters to apply.
            enhancement: Optional QueryEnhancement for filter merging.

        Returns:
            RetrievalResult with all metadata
        """
        top_k = top_k or self.config.retrieval.final_top_k
        initial_candidates = initial_candidates or self.config.retrieval.initial_candidates
        filters = filters or {}

        # Merge user-provided filters with enhancement suggested filters
        merged_filters = self._merge_filters(filters, enhancement)

        all_candidates = {}  # chunk_id -> (RetrievedChunk, rrf_score)

        # Run hybrid search for each query
        for rank_offset, query in enumerate(queries):
            # Embed this query
            dense_vector = self._embed_query_dense(query)
            sparse_vector = self._embed_query_sparse(query)

            # Search (each query gets a portion of the initial_candidates budget)
            per_query_limit = initial_candidates // len(queries)
            per_query_limit = max(per_query_limit, 20)  # Minimum 20 per query

            # Hybrid search
            search_type = "hybrid_multi_query" if len(queries) > 1 else "hybrid"
            if self.sparse_encoder and sparse_vector.get("indices"):
                results = self.qdrant.hybrid_search(
                    dense_vector,
                    sparse_vector,
                    limit=per_query_limit,
                    filters=merged_filters,
                )
            else:
                search_type = "dense_multi_query" if len(queries) > 1 else "dense"
                results = self.qdrant.dense_search(
                    dense_vector,
                    limit=per_query_limit,
                    filters=merged_filters,
                )

            # RRF merge: for each result, accumulate 1/(k + rank)
            for rank, chunk in enumerate(results):
                rrf_score = 1.0 / (60 + rank)  # k=60 is standard RRF constant

                if chunk.chunk_id in all_candidates:
                    existing_chunk, existing_score = all_candidates[chunk.chunk_id]
                    all_candidates[chunk.chunk_id] = (
                        existing_chunk,
                        existing_score + rrf_score,
                    )
                else:
                    all_candidates[chunk.chunk_id] = (chunk, rrf_score)

        if not all_candidates:
            return RetrievalResult(
                query=queries[0],
                total_candidates=0,
                total_after_rerank=0,
                parents=[],
                filters_applied=merged_filters,
                reranker_used="none",
                search_type=search_type,
            )

        # Sort by accumulated RRF score
        merged = sorted(all_candidates.values(), key=lambda x: x[1], reverse=True)
        candidates = [chunk for chunk, score in merged]

        # Update scores to RRF scores
        for i, (chunk, score) in enumerate(merged):
            candidates[i].score = score

        total_candidates = len(candidates)

        # Rerank against ORIGINAL query (queries[0])
        reranker_used = "none"
        if self.reranker and len(candidates) > top_k:
            candidates = self.reranker.rerank(queries[0], candidates, top_k)
            reranker_used = self.config.retrieval.reranker_type.value
        else:
            candidates = candidates[:top_k]

        # Neighbor expansion (unchanged)
        if self.config.retrieval.enable_neighbor_chunks:
            self._populate_neighbors(candidates)

        # Parent grouping (unchanged)
        parent_groups = self._group_by_parent(candidates)
        parents = self._build_parent_contexts(parent_groups)

        return RetrievalResult(
            query=queries[0],  # Original query
            total_candidates=total_candidates,
            total_after_rerank=len(candidates),
            parents=parents,
            filters_applied=merged_filters,
            reranker_used=reranker_used,
            search_type=search_type,
        )

    def _merge_filters(
        self,
        user_filters: Optional[Dict],
        enhancement: Optional[QueryEnhancement],
    ) -> Optional[Dict]:
        """Merge user-provided filters with QueryEnhancer suggested filters."""
        if not enhancement or not enhancement.suggested_filters:
            return user_filters

        merged = dict(user_filters) if user_filters else {}

        # Only add enhancement filters if user didn't already specify that key
        for key, value in enhancement.suggested_filters.items():
            if key not in merged:
                merged[key] = value

        return merged if merged else None

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        enhancement: Optional[QueryEnhancement] = None,
    ) -> RetrievalResult:
        """
        Main retrieval method (backward compatible).
        Now delegates to retrieve_multi_query.

        Args:
            query: User's question
            top_k: Number of final results
            filters: Semantic filters like:
                - report_id: str
                - report_year: int or {"gte": 2022}
                - finding_type: str
                - severity: str
                - total_amount_crore: {"gte": 10.0}
                - entities_mentioned: list
            enhancement: Optional QueryEnhancement for multi-query and filter suggestions

        Returns:
            RetrievalResult with all metadata
        """
        # Use enhanced parameters if available, otherwise use defaults
        queries = (
            enhancement.expanded_queries if enhancement else [query]
        )
        initial = (
            enhancement.initial_candidates
            if enhancement
            else self.config.retrieval.initial_candidates
        )
        actual_top_k = enhancement.top_k if enhancement else (top_k or self.config.retrieval.final_top_k)

        return self.retrieve_multi_query(
            queries=queries,
            top_k=actual_top_k,
            initial_candidates=initial,
            filters=filters,
            enhancement=enhancement,
        )

    def _original_retrieve_single_query(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RetrievalResult:
        """
        DEPRECATED: Original single-query retrieval method.
        Kept for reference, but retrieve() now uses multi-query internally.
        """
        top_k = top_k or self.config.retrieval.final_top_k
        filters = filters or {}

        # Step 1: Embed query
        dense_vector = self._embed_query_dense(query)
        sparse_vector = self._embed_query_sparse(query)

        # Step 2: Hybrid search
        search_type = "hybrid"
        if self.sparse_encoder and sparse_vector.get("indices"):
            candidates = self.qdrant.hybrid_search(
                dense_vector,
                sparse_vector,
                limit=self.config.retrieval.initial_candidates,
                filters=filters,
            )
        else:
            search_type = "dense"
            candidates = self.qdrant.dense_search(
                dense_vector,
                limit=self.config.retrieval.initial_candidates,
                filters=filters,
            )

        if not candidates:
            return RetrievalResult(
                query=query,
                total_candidates=0,
                total_after_rerank=0,
                parents=[],
                filters_applied=filters,
                reranker_used="none",
                search_type=search_type,
            )

        total_candidates = len(candidates)

        # Step 3: Rerank
        reranker_used = "none"
        if self.reranker and len(candidates) > top_k:
            candidates = self.reranker.rerank(query, candidates, top_k)
            reranker_used = self.config.retrieval.reranker_type.value
        else:
            candidates = candidates[:top_k]

        # Step 4: Fetch neighbors (O(1))
        if self.config.retrieval.enable_neighbor_chunks:
            self._populate_neighbors(candidates)

        # Step 5: Group by parent
        parent_groups = self._group_by_parent(candidates)

        # Step 6: Fetch parent context
        parents = self._build_parent_contexts(parent_groups)

        return RetrievalResult(
            query=query,
            total_candidates=total_candidates,
            total_after_rerank=len(candidates),
            parents=parents,
            filters_applied=filters,
            reranker_used=reranker_used,
            search_type=search_type,
        )

    def _embed_query_dense(self, query: str) -> List[float]:
        """Generate dense embedding for query."""
        response = self.openai_client.embeddings.create(
            model=self.config.embedding.model,
            input=query,
            dimensions=self.config.embedding.dimensions,
        )
        return response.data[0].embedding

    def _embed_query_sparse(self, query: str) -> Dict[str, List]:
        """Generate sparse embedding for query."""
        if self.sparse_encoder:
            return self.sparse_encoder.encode(query)
        return {"indices": [], "values": []}

    def _populate_neighbors(self, chunks: List[RetrievedChunk]):
        """
        Fetch neighbor chunks using O(1) ID prediction.

        Instead of searching, we:
        1. Parse chunk_id to get components
        2. Predict neighbor IDs (index ± 1)
        3. Fetch by ID directly
        """
        for chunk in chunks:
            prev_id, next_id = self.neighbor_predictor.predict_neighbor_ids(
                chunk.chunk_id
            )

            # Fetch previous
            if prev_id:
                prev_payload = self.qdrant.get_chunk_by_id(prev_id)
                if prev_payload:
                    chunk.previous_chunk = RetrievedChunk(
                        chunk_id=prev_payload.get("chunk_id", ""),
                        content=prev_payload.get("content", ""),
                        score=0,
                        page_physical=prev_payload.get("page_physical", 0),
                    )

            # Fetch next
            if next_id:
                next_payload = self.qdrant.get_chunk_by_id(next_id)
                if next_payload:
                    chunk.next_chunk = RetrievedChunk(
                        chunk_id=next_payload.get("chunk_id", ""),
                        content=next_payload.get("content", ""),
                        score=0,
                        page_physical=next_payload.get("page_physical", 0),
                    )

    def _group_by_parent(
        self,
        chunks: List[RetrievedChunk],
    ) -> Dict[str, List[RetrievedChunk]]:
        """Group chunks by parent_chunk_id."""
        groups = {}
        for chunk in chunks:
            parent_id = chunk.parent_chunk_id or "unknown"
            if parent_id not in groups:
                groups[parent_id] = []
            groups[parent_id].append(chunk)
        return groups

    def _build_parent_contexts(
        self,
        groups: Dict[str, List[RetrievedChunk]],
    ) -> List[ParentContext]:
        """Build ParentContext objects from grouped chunks."""
        parents = []

        for parent_id, children in groups.items():
            parent_data = self.qdrant.get_parent(parent_id)

            if parent_data:
                page_range = parent_data.get("page_range_physical", [0, 0])
                if isinstance(page_range, list) and len(page_range) >= 2:
                    page_range = (page_range[0], page_range[1])
                else:
                    page_range = (0, 0)

                parents.append(
                    ParentContext(
                        chunk_id=parent_id,
                        toc_entry=parent_data.get("toc_entry", "Unknown Section"),
                        hierarchy=parent_data.get("hierarchy", {}),
                        page_range=page_range,
                        children=sorted(children, key=lambda c: -c.score),
                    )
                )
            else:
                # Fallback using child hierarchy
                hierarchy = children[0].hierarchy if children else {}
                parents.append(
                    ParentContext(
                        chunk_id=parent_id,
                        toc_entry=list(hierarchy.values())[-1]
                        if hierarchy
                        else "Unknown",
                        hierarchy=hierarchy,
                        page_range=(0, 0),
                        children=sorted(children, key=lambda c: -c.score),
                    )
                )

        # Sort by best child score
        parents.sort(
            key=lambda p: -max(c.score for c in p.children) if p.children else 0
        )

        return parents
