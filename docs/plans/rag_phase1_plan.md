# Phase 1: Query Intelligence & Context Optimization
## Implementation Plan for Claude Code Sonnet

**Goal**: Add query-time intelligence to the RAG pipeline with exactly ONE new LLM call per query.  
**Cost**: ~$0.0002/query (single GPT-4o-mini call) + zero-cost algorithmic improvements  
**No re-indexing required. All changes are query-time only.**

---

## Architecture Summary

Currently, a user query goes straight to embedding → hybrid search → rerank → generate.  
After Phase 1, the flow becomes:

```
User Query
    ↓
[QueryEnhancer] ← ONE GPT-4o-mini call (~$0.0002)
    Returns: question_type, expanded_queries[3], suggested_filters, retrieval_params
    ↓
[Multi-Query Hybrid Search] ← runs N hybrid searches, merges via RRF
    ↓
[Reranking] (unchanged)
    ↓
[Passage Reordering] ← NEW, zero-cost, "lost in the middle" mitigation
    ↓
[Context Sufficiency Check] ← score-threshold based, zero-cost
    ↓
[Context Assembly] ← uses adaptive context limits from QueryEnhancer
    ↓
[Generation] (unchanged, but with better context)
```

**Key design decision**: One LLM call (`QueryEnhancer`) replaces BOTH the old regex-based `_detect_question_type()` AND adds query expansion + filter extraction. No separate calls.

---

## Step-by-Step Implementation

### Step 1: Add QueryEnhancement Config

**File**: `services/rag_pipeline/config.py`

Add a new dataclass BEFORE the `RAGConfig` class, and wire it into `RAGConfig`:

```python
@dataclass
class QueryEnhancementConfig:
    """Configuration for query-time intelligence."""
    
    # Feature flags
    enabled: bool = True
    enable_query_expansion: bool = True
    enable_passage_reordering: bool = True
    enable_sufficiency_check: bool = True
    
    # Model (shared single call)
    model: str = "gpt-4o-mini"
    max_tokens: int = 300
    temperature: float = 0.0
    
    # Query expansion
    num_expansions: int = 3  # Total queries including original
    
    # Sufficiency check
    min_rerank_score: float = 0.25  # Minimum top-1 Cohere score to consider sufficient
    
    # Passage reordering
    reorder_strategy: str = "best_first_last"  # "best_first_last" or "none"
```

Add to `RAGConfig`:
```python
@dataclass
class RAGConfig:
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    query_enhancement: QueryEnhancementConfig = field(default_factory=QueryEnhancementConfig)  # NEW
    # ... rest unchanged
```

---

### Step 2: Create QueryEnhancer Service

**File**: `services/rag_pipeline/query_enhancer.py` (NEW FILE)

This is the core new component. Single LLM call, structured output.

```python
"""
Query Enhancement Service
==========================
Single LLM call that provides:
1. Question type classification (replaces regex _detect_question_type)
2. Query expansion (2 additional search queries)
3. Filter suggestions (report_id hints, finding_type, temporal scope)
4. Retrieval parameter recommendations (top_k, context_limit)

IMPORTANT: This is ONE call to GPT-4o-mini per query (~$0.0002).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from openai import OpenAI

from config import QueryEnhancementConfig

logger = logging.getLogger(__name__)


@dataclass
class QueryEnhancement:
    """Output of the query enhancement step."""
    
    # Question classification
    question_type: str  # factual, list, aggregation, comparison, explanation, procedural
    
    # Expanded queries for multi-query retrieval
    expanded_queries: List[str]  # Always includes original as first element
    
    # Filter suggestions
    suggested_filters: Dict[str, Any]  # e.g., {"finding_type": "loss_of_revenue"}
    
    # Retrieval parameters
    top_k: int = 10
    initial_candidates: int = 50
    max_context_chars: int = 15000
    
    # Style recommendation
    recommended_style: Optional[str] = None  # Only set if style is "adaptive"
    
    # Raw response for debugging
    raw_response: Optional[str] = None


# System prompt for the single enhancement call
ENHANCEMENT_SYSTEM_PROMPT = """You analyze questions about Indian CAG (Comptroller and Auditor General) audit reports.

Return ONLY valid JSON (no markdown, no backticks) with this exact schema:
{
  "question_type": "factual|list|aggregation|comparison|explanation|procedural",
  "expanded_queries": ["original query reworded for search", "alternative phrasing with domain terms"],
  "suggested_filters": {},
  "retrieval_params": {"top_k": 10, "initial_candidates": 50, "max_context_chars": 15000},
  "recommended_style": "concise|detailed|executive|technical|comparative|explanatory"
}

Rules for expanded_queries:
- Generate exactly 2 alternative queries (the original is added automatically)
- Rephrase using CAG/audit domain vocabulary (e.g., "money lost" → "revenue loss quantified in crore")
- Include specific terms likely in audit reports (findings, observations, recommendations, compliance)
- If the query mentions an entity, include its full name AND acronym in different queries

Rules for suggested_filters:
- Only include filters you're confident about. Empty {} is fine.
- Valid filter keys: "finding_type" (loss_of_revenue|non_compliance|fraud_misappropriation|wasteful_expenditure|performance_shortfall), "severity" (critical|high|medium|low)
- Do NOT guess report_id — leave that to the caller

Rules for retrieval_params:
- factual: {"top_k": 8, "initial_candidates": 30, "max_context_chars": 10000}
- list/aggregation: {"top_k": 18, "initial_candidates": 80, "max_context_chars": 25000}
- comparison: {"top_k": 15, "initial_candidates": 60, "max_context_chars": 22000}
- explanation: {"top_k": 12, "initial_candidates": 50, "max_context_chars": 18000}
- procedural: {"top_k": 10, "initial_candidates": 40, "max_context_chars": 15000}

Rules for recommended_style:
- factual → "concise", list → "detailed", aggregation → "executive"
- comparison → "comparative", explanation → "explanatory", procedural → "technical"
"""


class QueryEnhancer:
    """
    Single-call query intelligence.
    
    Usage:
        enhancer = QueryEnhancer(config, openai_client)
        enhancement = enhancer.enhance("What went wrong with toll collection?")
        # enhancement.expanded_queries = ["What went wrong with toll collection?", "toll revenue loss audit findings NHAI", "fee collection shortfall compliance observations"]
        # enhancement.question_type = "explanation"
        # enhancement.suggested_filters = {"finding_type": "loss_of_revenue"}
    """
    
    def __init__(self, config: QueryEnhancementConfig, openai_client: OpenAI):
        self.config = config
        self.client = openai_client
    
    def enhance(self, query: str, style: str = "adaptive") -> QueryEnhancement:
        """
        Enhance a query with a single LLM call.
        
        If enhancement is disabled or fails, returns a safe fallback
        with the original query and default parameters.
        """
        if not self.config.enabled:
            return self._fallback(query)
        
        try:
            user_prompt = f'Question: "{query}"'
            if style != "adaptive":
                user_prompt += f"\n(User selected style: {style} — do NOT override recommended_style)"
            
            response = self.client.chat.completions.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {"role": "system", "content": ENHANCEMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                # Request JSON output
                response_format={"type": "json_object"},
            )
            
            raw = response.choices[0].message.content.strip()
            parsed = json.loads(raw)
            
            # Build expanded queries: original first, then expansions
            expanded = [query]  # Original always first
            for eq in parsed.get("expanded_queries", []):
                if eq and eq != query:
                    expanded.append(eq)
            # Ensure we have at least the original
            expanded = expanded[:self.config.num_expansions]
            
            # Extract retrieval params with defaults
            ret_params = parsed.get("retrieval_params", {})
            
            enhancement = QueryEnhancement(
                question_type=parsed.get("question_type", "factual"),
                expanded_queries=expanded,
                suggested_filters=parsed.get("suggested_filters", {}),
                top_k=ret_params.get("top_k", 10),
                initial_candidates=ret_params.get("initial_candidates", 50),
                max_context_chars=ret_params.get("max_context_chars", 15000),
                recommended_style=parsed.get("recommended_style") if style == "adaptive" else None,
                raw_response=raw,
            )
            
            logger.info(
                f"QueryEnhancer: type={enhancement.question_type}, "
                f"queries={len(enhancement.expanded_queries)}, "
                f"filters={enhancement.suggested_filters}, "
                f"top_k={enhancement.top_k}"
            )
            
            return enhancement
            
        except Exception as e:
            logger.warning(f"QueryEnhancer failed, using fallback: {e}")
            return self._fallback(query)
    
    def _fallback(self, query: str) -> QueryEnhancement:
        """Safe fallback when enhancement is disabled or fails."""
        return QueryEnhancement(
            question_type="factual",
            expanded_queries=[query],
            suggested_filters={},
            top_k=10,
            initial_candidates=50,
            max_context_chars=15000,
        )
```

**Key points for Claude Code**:
- The file goes at `services/rag_pipeline/query_enhancer.py`
- The `_fallback()` method ensures the pipeline NEVER breaks even if the LLM call fails
- `response_format={"type": "json_object"}` ensures GPT-4o-mini returns valid JSON
- The original query is ALWAYS the first element in `expanded_queries`

---

### Step 3: Add Multi-Query Support to RetrievalService

**File**: `services/rag_pipeline/retrieval_service.py`

Modify the `retrieve()` method to accept multiple queries and merge results.

**Changes needed**:

1. Add a new method `retrieve_multi_query()` that:
   - Takes `List[str]` queries instead of single query
   - For each query: generates dense embedding + sparse vector, runs hybrid search
   - Merges all results using RRF (Reciprocal Rank Fusion)
   - Deduplicates by chunk_id (keep highest RRF score)
   - Then reranks the merged set against the ORIGINAL query (first in list)
   - Then does neighbor expansion and parent grouping as before

2. Modify existing `retrieve()` to be a thin wrapper that calls `retrieve_multi_query([query])`

Here's the key logic for the new method (pseudocode for Claude Code):

```python
def retrieve_multi_query(
    self,
    queries: List[str],
    top_k: int = 10,
    initial_candidates: int = 50,
    filters: Optional[Dict] = None,
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
    """
    # Merge user-provided filters with enhancement suggested filters
    merged_filters = self._merge_filters(filters, enhancement)
    
    all_candidates = {}  # chunk_id -> (RetrievedChunk, rrf_score)
    
    for rank_offset, query in enumerate(queries):
        # Embed this query
        dense_vector = self._embed_query_dense(query)
        sparse_vector = self._embed_query_sparse(query)
        
        # Search (each query gets initial_candidates results)
        per_query_limit = initial_candidates // len(queries)  # Split budget
        per_query_limit = max(per_query_limit, 20)  # Minimum 20 per query
        
        results = self.qdrant.hybrid_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            limit=per_query_limit,
            filters=merged_filters,
        )
        
        # RRF merge: for each result, accumulate 1/(k + rank)
        for rank, chunk in enumerate(results):
            rrf_score = 1.0 / (60 + rank)  # k=60 is standard RRF constant
            
            if chunk.chunk_id in all_candidates:
                existing_chunk, existing_score = all_candidates[chunk.chunk_id]
                all_candidates[chunk.chunk_id] = (existing_chunk, existing_score + rrf_score)
            else:
                all_candidates[chunk.chunk_id] = (chunk, rrf_score)
    
    # Sort by accumulated RRF score
    merged = sorted(all_candidates.values(), key=lambda x: x[1], reverse=True)
    candidates = [chunk for chunk, score in merged]
    
    # Update scores to RRF scores
    for i, (chunk, score) in enumerate(merged):
        candidates[i].score = score
    
    # Rerank against ORIGINAL query (queries[0])
    if self.reranker and len(candidates) > top_k:
        candidates = self.reranker.rerank(queries[0], candidates, top_k)
    else:
        candidates = candidates[:top_k]
    
    # Neighbor expansion (unchanged)
    if self.config.enable_neighbor_chunks:
        self._populate_neighbors(candidates)
    
    # Parent grouping (unchanged)
    parent_groups = self._group_by_parent(candidates)
    parent_contexts = self._fetch_parent_contexts(parent_groups)
    
    return RetrievalResult(
        query=queries[0],  # Original query
        total_candidates=len(all_candidates),
        total_after_rerank=len(candidates),
        parents=parent_contexts,
        reranker_used=self._reranker_name(),
        search_type="hybrid_multi_query" if len(queries) > 1 else "hybrid",
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
    top_k: int = 10,
    filters: Optional[Dict] = None,
    enhancement: Optional[QueryEnhancement] = None,
) -> RetrievalResult:
    """
    Single-query retrieval (backward compatible).
    Now delegates to retrieve_multi_query.
    """
    queries = enhancement.expanded_queries if enhancement else [query]
    initial = enhancement.initial_candidates if enhancement else self.config.initial_candidates
    actual_top_k = enhancement.top_k if enhancement else top_k
    
    return self.retrieve_multi_query(
        queries=queries,
        top_k=actual_top_k,
        initial_candidates=initial,
        filters=filters,
        enhancement=enhancement,
    )
```

**Important implementation notes for Claude Code**:
- The existing `retrieve()` signature MUST remain backward compatible (it's called from many places)
- `enhancement` parameter is Optional — when None, behavior is identical to current code
- The per-query candidate budget is SPLIT across queries to avoid retrieving 150 candidates total (which would slow down reranking). With 3 queries at 50 initial_candidates, each gets ~20 candidates, giving ~60 unique chunks after dedup → rerank to 10.
- Reranking always uses the ORIGINAL query (queries[0]), not the expansions
- The `_embed_query_dense` and `_embed_query_sparse` methods already exist — just call them in a loop

---

### Step 4: Add Passage Reordering to RAG Service

**File**: `services/rag_pipeline/rag_service.py`

Add a reordering step in the context assembly. This goes AFTER retrieval and BEFORE context is formatted for the LLM.

Add this as a static/utility method:

```python
@staticmethod
def _reorder_for_attention(parents: List[ParentContext]) -> List[ParentContext]:
    """
    Reorder parent contexts to mitigate 'lost in the middle' effect.
    
    Research (ICLR 2025) shows LLMs attend most to content at the
    beginning and end of context, with degraded attention in the middle.
    
    Strategy: interleave by relevance score.
    - Position 1: highest-scored parent (best content first)
    - Position 2: lowest-scored parent  
    - Position 3: second-highest
    - Position 4: second-lowest
    - etc.
    
    This ensures the most and least relevant are at attention-optimal positions.
    """
    if len(parents) <= 2:
        return parents
    
    # Score each parent by its best child's score
    scored = []
    for p in parents:
        best_child_score = max((c.score for c in p.children), default=0.0)
        scored.append((p, best_child_score))
    
    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    
    # Interleave: best, worst, 2nd best, 2nd worst, ...
    reordered = []
    left = 0
    right = len(scored) - 1
    toggle = True  # True = take from left (high), False = take from right (low)
    
    while left <= right:
        if toggle:
            reordered.append(scored[left][0])
            left += 1
        else:
            reordered.append(scored[right][0])
            right -= 1
        toggle = not toggle
    
    return reordered
```

**Where to call it**: In the `ask()` method, AFTER `retrieval_result` is obtained but BEFORE context assembly. Also in `prepare_generation_inputs()` which is used by the streaming path.

Find where context is assembled from `retrieval_result.parents` and insert:
```python
if self.config.query_enhancement.enable_passage_reordering:
    retrieval_result.parents = self._reorder_for_attention(retrieval_result.parents)
```

---

### Step 5: Add Context Sufficiency Check

**File**: `services/rag_pipeline/rag_service.py`

This is score-threshold based — zero LLM cost. Add a method:

```python
def _check_context_sufficiency(
    self,
    retrieval_result: RetrievalResult,
) -> bool:
    """
    Check if retrieved context is likely sufficient to answer the question.
    
    Uses the top reranker score as a proxy. If the best chunk scores
    below the threshold, the context is likely insufficient.
    
    Returns True if sufficient, False if insufficient.
    """
    if not self.config.query_enhancement.enable_sufficiency_check:
        return True  # Skip check if disabled
    
    threshold = self.config.query_enhancement.min_rerank_score
    
    # Find the best score across all children in all parents
    best_score = 0.0
    for parent in retrieval_result.parents:
        for child in parent.children:
            best_score = max(best_score, child.score)
    
    sufficient = best_score >= threshold
    
    if not sufficient:
        logger.info(
            f"Context sufficiency check FAILED: best_score={best_score:.3f} < threshold={threshold}"
        )
    
    return sufficient
```

**Where to use it**: In `ask()` and in the streaming wrapper. When insufficient:
- In `ask()`: prepend a caveat to the answer: "Note: The available reports may not contain specific information to fully answer this question. Based on what was found:\n\n"
- In streaming: yield a `{"type": "caveat", "data": "low_relevance"}` event before tokens, so the frontend can show a banner.

---

### Step 6: Wire Everything Together in RAGService

**File**: `services/rag_pipeline/rag_service.py`

Modify the `ask()` method. Here's the key integration logic:

```python
def ask(self, question, filters=None, top_k=10, style=ResponseStyle.ADAPTIVE):
    """Modified ask() with query enhancement."""
    
    # ===== NEW: Query Enhancement (single LLM call) =====
    enhancement = None
    if self.config.query_enhancement.enabled:
        enhancement = self.query_enhancer.enhance(question, style=style.value)
        
        # Apply recommended style if adaptive
        if style == ResponseStyle.ADAPTIVE and enhancement.recommended_style:
            try:
                style = ResponseStyle(enhancement.recommended_style)
            except ValueError:
                pass  # Keep adaptive if recommendation is invalid
        
        # Override retrieval params from enhancement
        top_k = enhancement.top_k
    else:
        # Legacy path: use existing regex detection
        question_type = self._detect_question_type(question)
        # ... existing adjustment logic
    
    # ===== Retrieval (now with multi-query + auto-filters) =====
    retrieval_result = self.retrieval.retrieve(
        query=question,
        top_k=top_k,
        filters=filters,
        enhancement=enhancement,  # NEW parameter
    )
    
    # ===== NEW: Passage Reordering =====
    if self.config.query_enhancement.enable_passage_reordering:
        retrieval_result.parents = self._reorder_for_attention(retrieval_result.parents)
    
    # ===== NEW: Context Sufficiency Check =====
    context_sufficient = self._check_context_sufficiency(retrieval_result)
    
    # ===== Context Assembly (with adaptive length) =====
    max_chars = enhancement.max_context_chars if enhancement else self.config.llm.max_context_chars
    context = self._build_context(retrieval_result, max_context_chars=max_chars)
    
    # ===== Question type for generation hints =====
    question_type = enhancement.question_type if enhancement else self._detect_question_type(question)
    
    # ===== Generation (unchanged) =====
    answer = self._generate_answer(question, context, style, question_type)
    
    # Prepend caveat if context insufficient
    if not context_sufficient:
        caveat = ("⚠️ **Note**: The available reports may not contain specific information "
                   "to fully answer this question. Based on the closest matches found:\n\n")
        answer = caveat + answer
    
    # ===== Build citations (unchanged) =====
    citations = self.build_citations(retrieval_result)
    
    return RAGResponse(
        query=question,
        answer=answer,
        citations=citations,
        sources_used=retrieval_result.total_after_rerank,
        context_length=len(context),
        reranker_used=retrieval_result.reranker_used,
        search_type=retrieval_result.search_type,
        model_used=self._model_name(),
    )
```

**Also modify `__init__`** to create the QueryEnhancer:
```python
def __init__(self, config=None):
    self.config = config or RAGConfig()
    # ... existing init ...
    
    # NEW: Query enhancer
    if self.config.query_enhancement.enabled:
        from query_enhancer import QueryEnhancer
        self.query_enhancer = QueryEnhancer(
            config=self.config.query_enhancement,
            openai_client=self._openai_client,  # Reuse existing OpenAI client
        )
```

---

### Step 7: Wire Streaming Path

**File**: `services/api/services/streaming_wrapper.py`

The streaming path calls `rag.retrieval.retrieve()` and `rag.prepare_generation_inputs()` separately. Modify `generate_stream()`:

```python
async def generate_stream(query, style="adaptive", report_ids=None, top_k=10):
    # ... existing setup ...
    
    # NEW: Run query enhancement first (in thread pool)
    enhancement = None
    if hasattr(rag, 'query_enhancer') and rag.config.query_enhancement.enabled:
        enhancement = await loop.run_in_executor(
            _executor,
            lambda: rag.query_enhancer.enhance(query, style=style)
        )
        
        # Apply recommended style
        if style == "adaptive" and enhancement and enhancement.recommended_style:
            try:
                style_enum = RAGResponseStyle(enhancement.recommended_style)
            except ValueError:
                pass
        
        # Use enhancement's top_k
        top_k = enhancement.top_k if enhancement else top_k
    
    # Step 1: Retrieval (now with enhancement)
    retrieval_result = await loop.run_in_executor(
        _executor,
        lambda: rag.retrieval.retrieve(
            query, top_k=top_k, filters=filters if filters else None,
            enhancement=enhancement,
        )
    )
    
    # ... existing empty-result check ...
    
    # NEW: Passage reordering
    if rag.config.query_enhancement.enable_passage_reordering:
        retrieval_result.parents = rag._reorder_for_attention(retrieval_result.parents)
    
    # NEW: Context sufficiency check + emit caveat event
    context_sufficient = rag._check_context_sufficiency(retrieval_result)
    if not context_sufficient:
        yield {"type": "caveat", "data": "low_relevance"}
    
    # Step 2: Citations (unchanged)
    # Step 3: Generation inputs — pass adaptive context length
    generation_inputs = await loop.run_in_executor(
        _executor,
        lambda: rag.prepare_generation_inputs(
            question=query,
            retrieval_result=retrieval_result,
            style=style_enum,
            question_type=enhancement.question_type if enhancement else None,
            max_context_chars=enhancement.max_context_chars if enhancement else None,
        )
    )
    
    # Step 4: Stream from LLM (unchanged)
    # ...
```

**Important**: The `prepare_generation_inputs()` method in `rag_service.py` needs to accept optional `question_type` and `max_context_chars` overrides so it doesn't re-detect the question type with regex. Add these as optional parameters — when provided, skip the regex detection.

---

### Step 8: Add `caveat` Event Handling to Frontend

**File**: `frontend/` — minimal change

The streaming endpoint may now emit a `{"type": "caveat", "data": "low_relevance"}` event before tokens. The frontend SSE handler should:

1. Listen for `type === "caveat"` events
2. When received, show a subtle banner/toast above the answer: "Results may not fully address your question"

This is a small frontend change — just add a case to the existing SSE event handler switch.

---

## Testing Checklist

After implementation, verify:

```bash
# 1. Basic functionality (should still work with enhancement disabled)
python -c "
from config import RAGConfig, QueryEnhancementConfig
cfg = RAGConfig()
cfg.query_enhancement.enabled = False
from rag_service import RAGService
rag = RAGService(cfg)
r = rag.ask('What is the total revenue loss in toll collection?')
print(r.answer[:200])
print(f'Sources: {r.sources_used}, Search: {r.search_type}')
"

# 2. Enhancement enabled (should show multi_query search type)
python -c "
from rag_service import RAGService
rag = RAGService()
r = rag.ask('What went wrong with toll collection?')
print(f'Search type: {r.search_type}')  # Should be 'hybrid_multi_query'
print(f'Sources: {r.sources_used}')
print(r.answer[:200])
"

# 3. Query enhancer standalone test
python -c "
from openai import OpenAI
from config import QueryEnhancementConfig
from query_enhancer import QueryEnhancer
client = OpenAI()
enhancer = QueryEnhancer(QueryEnhancementConfig(), client)
result = enhancer.enhance('What were the issues with ETC equipment at NHAI toll plazas?')
print(f'Type: {result.question_type}')
print(f'Queries: {result.expanded_queries}')
print(f'Filters: {result.suggested_filters}')
print(f'Top-k: {result.top_k}')
"

# 4. Streaming test via API
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "List all revenue losses above 50 crore", "style": "adaptive"}'
```

---

## File Change Summary

| File | Action | Lines Changed |
|---|---|---|
| `services/rag_pipeline/config.py` | MODIFY | +20 (new QueryEnhancementConfig dataclass) |
| `services/rag_pipeline/query_enhancer.py` | CREATE | ~180 lines |
| `services/rag_pipeline/retrieval_service.py` | MODIFY | +80 (retrieve_multi_query, _merge_filters, modify retrieve) |
| `services/rag_pipeline/rag_service.py` | MODIFY | +60 (reorder method, sufficiency check, wire enhancement into ask + prepare_generation_inputs) |
| `services/api/services/streaming_wrapper.py` | MODIFY | +25 (enhancement call, caveat event, pass-through params) |
| `services/rag_pipeline/models.py` | MODIFY | +3 (optional context_sufficient field on RAGResponse) |
| Frontend SSE handler | MODIFY | +10 (handle caveat event type) |

**Total**: ~1 new file, ~6 modified files, ~380 lines of new/changed code.
