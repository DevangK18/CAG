# Phase 2 + 3: Index Enhancement & Advanced Query Pipeline
## Implementation Plan for Claude Code Sonnet

**Phase 2**: Index Quality Gate + Contextual Retrieval (one re-index pass, ~$0.26 LLM + embedding costs)  
**Phase 3**: HyDE, Citation Verification, Adaptive Retrieval Depth  
**Prerequisite**: Phase 1 must be complete and stable.

---

## Phase 2: Index Quality Gate + Contextual Retrieval

### Overview

Phase 2 does TWO things in a single re-index pass:

1. **Index Quality Gate** — filter out header stubs and near-empty chunks before they ever reach the embedding model or prefix generator. Removes ~2,400 low-value chunks (17% of corpus) that steal retrieval slots.

2. **Contextual Retrieval** — for chunks that pass the gate, prepend a 1-2 sentence semantic context summary before embedding. Situates chunks like "The department failed to comply with the above" within their report, section, and topic.

**Critical ordering**: The quality gate runs FIRST. Chunks that fail the gate are excluded from the contextual prefix batch — no point generating prefixes for chunks we won't index.

```
For each child chunk in report JSON:
    ↓
[Quality Gate] should_index_chunk()
    ├── FAIL → skip entirely (no prefix generation, no embedding, no upsert)
    └── PASS ↓
[Batch Assembly] group passing chunks by parent_chunk_id
    ↓
[Contextual Prefix] generate prefix via GPT-4o-mini (one call per parent group)
    ↓
[Embedding] contextual_prefix + existing_hierarchy_prefix + content
    ↓
[Upsert to Qdrant]
```

### Why Combined

- Both require a full re-index — do it once
- The quality gate reduces chunks from ~15,600 to ~13,200, saving ~$0.12 on prefix generation and ~$1.80 on embeddings
- A/B testing is simpler: one new collection vs. current

---

### Part A: Index Quality Gate

#### The Problem (from v4 diagnostics, Feb 28)

```
Corpus-wide:     2,655 / 15,669 chunks (17%) outside 50-3000 char sweet spot
Too short (<50): 2,428 chunks (overwhelmingly content_type: "header")
Too long (>3000):  227 chunks (large tables/annexures — separate concern)

Worst reports:
  2025_04 Union Accounts:   159 short / 675 children (23.6%)
  2023_11 Ayushman Bharat:  222 short / 1,126 children (19.7%)
  2023_19 Bharatmala:       270 short / 1,776 children (15.2%)
```

These chunks produce weak, low-information-density embeddings that partially overlap with many queries without being useful for any. With top-k retrieval, a header chunk that keyword-matches a query steals a slot from a substantive chunk that actually answers the question.

The structural role of headers (identifying which section content belongs to) is already encoded in every child chunk's `hierarchy` dict and the existing `[Chapter X > Section Y]` prefix prepended at embedding time. Embedding headers separately adds zero information that isn't already available.

#### Implementation

**File**: `services/rag_pipeline/embedding_service.py`

Add a gating function. This is called in `process_chunks()` BEFORE the chunk enters the contextual prefix batch or the embedding batch.

```python
def should_index_chunk(child_chunk: dict) -> bool:
    """
    Decide whether this chunk should get a vector embedding in Qdrant.
    
    Returns False for:
    - Header-only stubs (content_type == "header" and < 100 chars)
    - Near-empty chunks of any type (< 20 chars)
    
    These chunks remain in the source JSON and parent collection for:
    - Hierarchy navigation in the UI
    - Section-scoped filtering
    - TOC rendering
    - Metadata-based retrieval
    
    They just don't get their own vector embedding.
    """
    content = child_chunk.get("content", "").strip()
    content_type = child_chunk.get("content_type", "")
    
    # Skip near-empty chunks regardless of type
    if len(content) < 20:
        return False
    
    # Skip short header chunks — their signal is captured via hierarchy prefix
    if content_type == "header" and len(content) < 100:
        return False
    
    return True
```

**Why 100-char threshold for headers**: Some "header" chunks contain a heading plus an introductory sentence. At 100+ chars there's enough substance to justify indexing. Below 100, diagnostics confirm it's almost always a bare heading.

**Why 20-char floor for all types**: Diagnostics show 0.3-1.8% empty/near-empty chunks across reports. These are OCR artifacts or whitespace remnants — never useful for retrieval.

**This gate is always on — no feature flag.** There is no scenario where indexing bare headers is desirable.

#### Expected Impact

```
Before:  ~15,669 indexed chunks, ~2,428 too-short
After:   ~13,200 indexed chunks, 0 too-short in vector store
Savings: 17% fewer embeddings, 17% fewer BM25 entries, cleaner retrieval
```

---

### Part B: Contextual Retrieval

#### What & Why

The existing hierarchy prefix (`[Chapter II > 2.3 Revenue Collection]`) is structural context — it tells you WHERE in the document, not WHAT is being discussed. A chunk saying "The department failed to comply with the above recommendation" still has no self-contained meaning: which recommendation? which department?

Contextual Retrieval (Anthropic's technique) prepends a 1-2 sentence semantic summary that situates the chunk:

```
CURRENT embedding text:
  "[Chapter II > 2.3 Revenue Collection]
   The department failed to comply with the above recommendation."

AFTER contextual prefix:
  "From the NHAI Toll Compliance Audit (2023), Section 2.3 discussing
   non-compliance with CAG's recommendation to install ETC equipment
   at southern toll plazas.
   [Chapter II > 2.3 Revenue Collection]
   The department failed to comply with the above recommendation."
```

**The prefix goes into embedding text and BM25 text, but NOT into the text sent to the LLM at generation time.** The stored `"content"` field in Qdrant payload remains the raw chunk text. This improves retrieval without inflating the generation context window.

#### Cost Estimate

After quality gate, ~13,200 chunks need prefixes. Batched by parent (~2,200 parent groups, ~6 children avg per group):

- LLM calls: ~2,200 (one per parent group, not one per chunk)
- Input per call: ~300 tokens (report metadata + parent context + 6 truncated children)
- Output per call: ~120 tokens (6 prefixes × ~20 tokens each)
- Total input: 2,200 × 300 = 660K tokens × $0.15/1M = $0.10
- Total output: 2,200 × 120 = 264K tokens × $0.60/1M = $0.16
- **Total: ~$0.26 for the entire corpus**

Even re-running 10 times during development stays under $3.

#### Implementation

##### Step 1: Create ContextualPrefixService

**File**: `services/rag_pipeline/contextual_prefix_service.py` (NEW)

```python
"""
Contextual Prefix Service
==========================
Generates 1-2 sentence semantic context prefixes for chunks at index time.

The prefix captures:
- Which report and section this chunk belongs to
- What specific topic/entity/finding is being discussed
- Temporal scope (audit period, financial year)

The prefix is prepended to chunk text ONLY for embedding and BM25.
The raw chunk text is stored separately in the payload for LLM generation.

IMPORTANT: Only called for chunks that have already passed should_index_chunk().
Header stubs and near-empty chunks must be excluded BEFORE reaching this service.
"""

class ContextualPrefixService:
    """
    Batch-generates contextual prefixes for chunks.
    
    Uses GPT-4o-mini with batching by parent section for cost efficiency.
    One LLM call per parent group (avg ~6 children) instead of per chunk.
    
    Usage:
        service = ContextualPrefixService(openai_client)
        prefix_map = service.generate_prefixes_for_report(
            indexable_children=indexable,  # MUST already be filtered by should_index_chunk
            parent_chunks=parents,
            report_metadata=metadata,
        )
    """
    
    def __init__(self, openai_client, model="gpt-4o-mini", max_children_per_call=15):
        self.client = openai_client
        self.model = model
        self.max_children_per_call = max_children_per_call
    
    def generate_prefixes_for_report(
        self,
        indexable_children: List[dict],
        parent_chunks: List[dict],
        report_metadata: dict,
    ) -> Dict[str, str]:
        """
        Generate contextual prefixes for all indexable children in one report.
        
        Args:
            indexable_children: ONLY chunks that passed should_index_chunk().
                                Must be pre-filtered before calling this method.
            parent_chunks: All parent chunks (for context lookup).
            report_metadata: Report title, audit year, ministry, etc.
        
        Returns: {chunk_id: prefix_string}
        
        Implementation strategy:
        1. Build parent lookup: {parent_chunk_id: parent_data}
        2. Group indexable_children by parent_chunk_id
        3. For each parent group:
           a. Assemble prompt with report metadata + parent context + children
           b. If group > max_children_per_call, split into sub-batches
           c. Call GPT-4o-mini with response_format={"type": "json_object"}
           d. Parse JSON, map prefixes to chunk_ids
        4. Return complete {chunk_id: prefix} dict
        
        Fallback: If LLM call fails for a group, generate template-based prefix:
           f"From {report_title} ({audit_year}), {parent_hierarchy_path}."
        """
        pass
```

**Prompt for each parent-group call**:

```python
CONTEXTUAL_PREFIX_SYSTEM = """You generate brief contextual prefixes for chunks from Indian CAG audit reports.
Each prefix should be ONE sentence, max 25 words, stating: the report name, section topic, and what the specific chunk discusses.
Return ONLY valid JSON (no markdown): {"prefixes": ["prefix 1", "prefix 2", ...]}"""

CONTEXTUAL_PREFIX_USER = """Report: {report_title} ({audit_year})
Ministry/Department: {ministry}
Section path: {parent_hierarchy}

Chunks to prefix (already filtered — all are substantive content):
{numbered_chunks}

Generate exactly {n} prefixes, one per chunk, in order."""
```

Where `{numbered_chunks}` is:
```
[1] (paragraph) "The audit found that the contractor failed to maintain..."
[2] (table_markdown) "| State | Revenue | Growth |..."
[3] (finding) "Consequently, a revenue loss of ₹12.5 crore..."
```

Each child is truncated to ~150 chars with its `content_type` label so the LLM understands the content form.

##### Step 2: Integrate into Embedding Pipeline

**File**: `services/rag_pipeline/embedding_service.py`

Modify `process_chunks()`. The critical ordering:

```python
def process_chunks(self, child_chunks, parent_chunks, report_metadata=None):
    """
    Process chunks for Qdrant indexing.
    
    Pipeline ordering (CRITICAL):
    1. Quality gate — filter out headers and empties
    2. Contextual prefixes — generate ONLY for chunks that passed gate
    3. Build embedding text — contextual_prefix + hierarchy_prefix + content
    4. Generate embeddings — dense + sparse
    5. Build payloads — store raw content (not prefixed) for generation
    """
    parent_lookup = {p["chunk_id"]: p for p in parent_chunks}
    
    # ===== STEP 1: Quality Gate (runs FIRST) =====
    indexable = []
    skipped = {"header": 0, "empty": 0}
    for child in child_chunks:
        if should_index_chunk(child):
            indexable.append(child)
        else:
            ct = child.get("content_type", "")
            skipped["header" if ct == "header" else "empty"] += 1
    
    logger.info(
        f"Quality gate: {len(indexable)} indexable, "
        f"{skipped['header']} headers skipped, {skipped['empty']} empties skipped"
    )
    
    # ===== STEP 2: Contextual Prefixes (only for indexable chunks) =====
    prefix_map = {}  # {chunk_id: prefix_string}
    if self.config.enable_contextual_prefix and report_metadata:
        prefix_map = self.contextual_service.generate_prefixes_for_report(
            indexable_children=indexable,  # Already filtered — no headers in here
            parent_chunks=parent_chunks,
            report_metadata=report_metadata,
        )
        logger.info(f"Generated {len(prefix_map)} contextual prefixes")
    
    # ===== STEP 3: Build embedding texts =====
    embedding_texts = []
    for child in indexable:
        parts = []
        
        # Contextual prefix (new, from LLM)
        if child["chunk_id"] in prefix_map:
            parts.append(prefix_map[child["chunk_id"]])
        
        # Hierarchy prefix (existing, keep as-is)
        if self.config.enable_hierarchy_prefix:
            hierarchy_prefix = self._build_hierarchy_prefix(child, parent_lookup)
            parts.append(hierarchy_prefix)
        
        # Table summary if applicable (existing)
        if child.get("content_type") == "table_markdown":
            summary = self._get_table_summary(child)
            if summary:
                parts.append(f"[Table Summary: {summary}]")
        
        # Actual content
        parts.append(child["content"])
        
        embedding_texts.append("\n".join(parts))
    
    # ===== STEP 4: Generate embeddings (unchanged) =====
    dense_embeddings = self._generate_dense_embeddings(embedding_texts)
    sparse_vectors = self._generate_sparse_vectors(embedding_texts)
    
    # ===== STEP 5: Build payloads =====
    payloads = []
    for child in indexable:
        payload = self._build_payload(child, parent_lookup)
        # Store prefix for debugging/inspection, not for generation
        if child["chunk_id"] in prefix_map:
            payload["contextual_prefix"] = prefix_map[child["chunk_id"]]
        payloads.append(payload)
    
    # Return indexable list so caller knows what was processed
    return indexable, embedding_texts, dense_embeddings, sparse_vectors, payloads
```

**IMPORTANT contract**: The `"content"` field in each payload remains the RAW chunk text. This is what the LLM sees at generation time via `retrieval_service.py`. The contextual prefix only influences the embedding vector and BM25 sparse vector — it is never sent to the generation LLM.

##### Step 3: Add Indexer Flags

**File**: `services/rag_pipeline/indexer.py`

```bash
# Full re-index with quality gate only (no contextual prefixes, no LLM cost)
python -m src.rag_pipeline.indexer --input-dir data/processed --recreate

# Full re-index with quality gate + contextual prefixes
python -m src.rag_pipeline.indexer --input-dir data/processed --recreate --contextual

# A/B test: index to separate collection (doesn't touch existing)
python -m src.rag_pipeline.indexer --input-dir data/processed --contextual --collection-suffix "_v2"
```

The `--collection-suffix` flag appends to collection names: `cag_child_chunks_v2`, `cag_parent_chunks_v2`. This enables A/B testing without touching the existing index.

The quality gate (`should_index_chunk`) is ALWAYS active — not behind a flag.

At the end of indexing, log summary stats:
```
Index complete: 13,247 chunks indexed, 2,422 skipped (2,389 headers, 33 empties)
Contextual prefixes: 13,247 generated, 0 fallback
Collection: cag_child_chunks_v2
```

##### Step 4: Config

**File**: `services/rag_pipeline/config.py`

Add to `EmbeddingConfig`:
```python
@dataclass
class EmbeddingConfig:
    # ... existing fields ...
    
    # Index quality gate thresholds (always active)
    min_content_length: int = 20          # Skip chunks shorter than this (any type)
    header_min_length: int = 100          # Skip header chunks shorter than this
    
    # Contextual prefix settings (opt-in via --contextual flag)
    enable_contextual_prefix: bool = False
    contextual_prefix_model: str = "gpt-4o-mini"
    contextual_prefix_max_children_per_call: int = 15
    contextual_prefix_max_tokens: int = 400  # Per LLM call (covers ~15 prefixes)
```

##### Step 5: A/B Testing Strategy

1. Keep current `cag_child_chunks` collection untouched
2. Run re-index: `--contextual --collection-suffix "_v2"`
3. Switch retrieval via env var: `QDRANT_COLLECTION_SUFFIX=_v2`
4. Test same 15-20 queries against both, compare:
   - Header chunks in top-10 (should drop to 0)
   - Reranker scores for top-3 (should increase)
   - Subjective answer quality
5. Once satisfied, make `_v2` the default and delete old collection

##### Step 6: Handle Missing Neighbors

**File**: `services/rag_pipeline/retrieval_service.py`

The O(1) neighbor predictor (`chunk_003` → predict `chunk_002` and `chunk_004`) may predict IDs for header chunks that were excluded from the index. The `_populate_neighbors()` method already handles missing lookups (Qdrant returns empty for unknown IDs), but add a debug log:

```python
# In _populate_neighbors():
if not prev_result:
    logger.debug(f"Neighbor {prev_id} not in index (likely filtered header)")
```

No functional change — just confirm it fails silently, which it already should.

### Phase 2 File Changes Summary

| File | Action | Lines |
|---|---|---|
| `services/rag_pipeline/contextual_prefix_service.py` | CREATE | ~180 |
| `services/rag_pipeline/embedding_service.py` | MODIFY | +50 (gate function, prefix wiring, return signature) |
| `services/rag_pipeline/indexer.py` | MODIFY | +20 (--contextual, --collection-suffix, stats logging) |
| `services/rag_pipeline/config.py` | MODIFY | +10 (gate thresholds + prefix config) |
| `services/rag_pipeline/retrieval_service.py` | MODIFY | +3 (debug log for missing neighbors) |

### Phase 2 Testing Checklist

```bash
# 1. Quality gate only (no contextual prefix, zero LLM cost)
python -m src.rag_pipeline.indexer --input-dir data/processed --recreate
# Verify logs: ~2,400 skipped, ~13,200 indexed

# 2. Contextual prefixes on single report first
python -m src.rag_pipeline.indexer \
  --input-dir data/processed/2023_07*.json \
  --contextual --collection-suffix "_test"
# Inspect: qdrant payload should have contextual_prefix field
# Verify: content field is still raw text, NOT prefixed

# 3. Full re-index with both improvements
python -m src.rag_pipeline.indexer \
  --input-dir data/processed \
  --recreate --contextual --collection-suffix "_v2"

# 4. A/B retrieval comparison
python -c "
from rag_service import RAGService
from config import RAGConfig

# Old index
r1 = RAGService().ask('What were the toll collection issues?')

# New index
cfg = RAGConfig()
cfg.qdrant.child_collection = 'cag_child_chunks_v2'
r2 = RAGService(cfg).ask('What were the toll collection issues?')

print('=== OLD INDEX ===')
for c in r1.citations[:5]:
    print(f'  [{c.score:.3f}] {c.section} (p.{c.page})')
print(f'  Search: {r1.search_type}')

print('=== NEW INDEX (gate + contextual) ===')
for c in r2.citations[:5]:
    print(f'  [{c.score:.3f}] {c.section} (p.{c.page})')
print(f'  Search: {r2.search_type}')
"

# 5. Verify zero header chunks in new index results
python -c "
from rag_service import RAGService
from config import RAGConfig
cfg = RAGConfig()
cfg.qdrant.child_collection = 'cag_child_chunks_v2'
rag = RAGService(cfg)
for q in ['toll revenue losses', 'ETC equipment', 'compliance audit findings']:
    result = rag.retrieval.retrieve(q)
    headers = [c for p in result.parents for c in p.children if c.content_type == 'header']
    print(f'{q}: {len(headers)} headers in results (should be 0)')
"
```

---

## Phase 3: Advanced Query Pipeline

### 3A. HyDE (Hypothetical Document Embeddings)

**What**: Generate a hypothetical *answer* to the query, embed that, and use it as an additional retrieval signal alongside the original query embedding.

**When to trigger**: Only when Phase 1's multi-query retrieval has already run and the top reranker score is below a threshold. HyDE is a **fallback amplifier**, not an always-on cost.

**Cost**: ~$0.001/query when triggered (GPT-4o-mini, ~200 token generation). Expected to trigger on ~30% of queries.

#### Implementation

**File**: `services/rag_pipeline/retrieval_service.py`

Add `HyDEGenerator` class:

```python
class HyDEGenerator:
    """
    Generates hypothetical document for improved retrieval.
    
    Only triggered when initial retrieval scores are low,
    making it a fallback rather than always-on cost.
    """
    
    def __init__(self, openai_client, config):
        self.client = openai_client
        self.config = config
    
    def generate_hypothetical(self, query: str) -> str:
        """Generate a hypothetical audit report excerpt that would answer this query."""
        response = self.client.chat.completions.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=0.3,
            messages=[{
                "role": "system",
                "content": (
                    "You are an Indian government auditor. Given a question, write a short "
                    "paragraph (3-4 sentences) that would appear in a CAG audit report as the "
                    "answer. Include specific audit terminology, mention amounts in crore where "
                    "relevant, and reference section numbers. This is a HYPOTHETICAL excerpt."
                )
            }, {
                "role": "user",
                "content": query
            }]
        )
        return response.choices[0].message.content.strip()
```

**Integration — two-pass retrieval in `retrieve_multi_query()`**:

```
Pass 1: Normal multi-query retrieval (Phase 1)
    ↓
Check: Is top reranker score < hyde_trigger_threshold (e.g., 0.4)?
    ├── NO  → return Pass 1 results (no extra cost)
    └── YES ↓
Pass 2: Generate HyDE doc → embed → search → merge with Pass 1 via RRF → rerank again
    ↓
Return merged results
```

HyDE adds ~700ms latency ONLY when the initial retrieval is struggling.

**Config**:
```python
@dataclass
class HyDEConfig:
    enabled: bool = True
    trigger_threshold: float = 0.4  # Only trigger if top rerank score below this
    model: str = "gpt-4o-mini"
    max_tokens: int = 200
```

Wire into `RAGConfig`:
```python
hyde: HyDEConfig = field(default_factory=HyDEConfig)
```

---

### 3B. Citation Verification

**What**: After the LLM generates an answer with `[Section X, p.YY]` citations, verify that each cited chunk actually supports the claim it's attached to.

**Cost**: ~$0.001/query (ONE GPT-4o-mini call with all claims + sources batched).

**Key insight**: Single batched call, not per-citation.

#### Implementation

**File**: `services/rag_pipeline/citation_verifier.py` (NEW)

```python
"""
Citation Verification Service
===============================
Post-generation check that verifies cited sources support their claims.
Single batched LLM call per answer — NOT per citation.
"""

class CitationVerifier:
    """
    Verifies citations in a generated answer against source chunks.
    
    Process:
    1. Parse citations from answer text: [Section..., p.XX]
    2. For each citation, find the corresponding chunk from retrieval_result
    3. Extract the "claim" — sentence(s) immediately before citation bracket
    4. Send ONE batched call to GPT-4o-mini with all claim-source pairs
    5. Return verification results
    
    Fallback: if LLM call fails, return all citations as "unverified" (not "unsupported")
    """
    
    def __init__(self, openai_client, model="gpt-4o-mini"):
        self.client = openai_client
        self.model = model
    
    def verify(self, answer: str, retrieval_result: RetrievalResult) -> VerificationResult:
        """
        Returns VerificationResult with:
        - overall_confidence: float (0-1, ratio of supported citations)
        - citation_verdicts: List[{citation_key, verdict, reason}]
        - flagged_citations: List[str] (keys that are partial/unsupported)
        """
        pass
```

**Prompt design** (single batched call):
```
Verify whether each source text supports its associated claim.
Return ONLY JSON: {"verdicts": [{"id": 1, "verdict": "supported|partial|unsupported", "reason": "..."}]}

Claims and sources:
[1] Claim: "Revenue loss was ₹64.60 crore at 12 toll plazas"
    Source: "{chunk content truncated to 300 chars}"
[2] Claim: "ETC equipment was non-functional"
    Source: "{chunk content truncated to 300 chars}"
```

**Integration points**:

For **sync** path (`rag_service.py ask()`): run verification after generation, attach to RAGResponse.

For **streaming** path (`streaming_wrapper.py`): accumulate the full answer from streamed tokens, then run verification. Emit a final event after `done`:
```json
{"type": "verification", "data": {"confidence": 0.85, "flagged_citations": ["Section 3.2, p.38"]}}
```

The frontend handles this by visually flagging uncertain citations (e.g., orange highlight instead of green).

**Config**:
```python
@dataclass
class CitationVerificationConfig:
    enabled: bool = True
    model: str = "gpt-4o-mini"
    max_tokens: int = 300
    max_claims_per_call: int = 15  # Truncate if answer has many citations
```

#### Model Changes

**File**: `services/rag_pipeline/models.py` — add to RAGResponse:
```python
citation_confidence: Optional[float] = None
flagged_citations: Optional[List[str]] = None
```

**File**: `services/api/models.py` — add to ChatResponse:
```python
citation_confidence: Optional[float] = None
flagged_citations: Optional[List[str]] = None
```

---

### 3C. Adaptive Retrieval Depth

**What**: Phase 1's QueryEnhancer already returns `top_k` and `initial_candidates`. This step refines them with corpus-aware heuristics that the LLM can't know about.

**Cost**: Zero — pure algorithmic logic.

#### Implementation

**File**: `services/rag_pipeline/retrieval_service.py`

Add to `retrieve()` before calling `retrieve_multi_query()`:

```python
def _adjust_retrieval_depth(self, enhancement, filters, num_reports_in_corpus):
    """
    Refine QueryEnhancer's retrieval params with corpus-aware heuristics.
    """
    base_top_k = enhancement.top_k if enhancement else 10
    base_initial = enhancement.initial_candidates if enhancement else 50
    
    # Filtering to specific report(s) → fewer candidates needed
    if filters and "report_id" in filters:
        num_target = 1 if isinstance(filters["report_id"], str) else len(filters["report_id"])
        if num_target <= 2:
            base_initial = min(base_initial, 40)
    else:
        # Full corpus search → scale with corpus size
        corpus_adjusted = max(50, num_reports_in_corpus * 3)
        base_initial = max(base_initial, corpus_adjusted)
    
    return base_top_k, base_initial
```

---

## Phase 3 Implementation Order

```
3C. Adaptive Retrieval Depth    — 0.5 day, $0 (pure logic)
3A. HyDE                        — 1-2 days, ~$0.001/query (conditional)
3B. Citation Verification       — 1-2 days, ~$0.001/query
```

3C first (free, instant). HyDE next (directly improves retrieval). Citation verification last (polish).

---

## Complete File Change Summary (Phase 2 + 3)

| File | Phase | Action |
|---|---|---|
| `services/rag_pipeline/contextual_prefix_service.py` | 2 | CREATE (~180 lines) |
| `services/rag_pipeline/embedding_service.py` | 2 | MODIFY (+50: gate function, prefix wiring, return signature) |
| `services/rag_pipeline/indexer.py` | 2 | MODIFY (+20: --contextual, --collection-suffix, stats) |
| `services/rag_pipeline/config.py` | 2+3 | MODIFY (+35: gate thresholds, prefix, HyDE, verification) |
| `services/rag_pipeline/retrieval_service.py` | 2+3A+3C | MODIFY (+90: neighbor log, HyDE class, adaptive depth) |
| `services/rag_pipeline/citation_verifier.py` | 3B | CREATE (~150 lines) |
| `services/rag_pipeline/rag_service.py` | 3B | MODIFY (+25: wire verification into ask + prepare) |
| `services/api/services/streaming_wrapper.py` | 3B | MODIFY (+15: verification event post-stream) |
| `services/rag_pipeline/models.py` | 3B | MODIFY (+5: verification fields) |
| `services/api/models.py` | 3B | MODIFY (+5: verification fields) |

---

## Cost Summary

### One-Time (Phase 2 re-index)

| Component | Cost |
|---|---|
| Contextual prefix generation (GPT-4o-mini, ~13,200 chunks) | ~$0.26 |
| Dense embeddings (OpenAI, ~13,200 chunks — 17% fewer than before) | ~$10.60 |
| Table summaries (unchanged) | ~$0.34 |
| **Total re-index** | **~$11.20** (was ~$12.80 without quality gate) |

### Per-Query (after all phases)

| Component | Phase | Cost | When |
|---|---|---|---|
| QueryEnhancer | 1 | $0.0002 | Every query |
| Dense embedding | — | $0.0001 | Every query |
| Cohere reranking | — | $0.001 | Every query |
| HyDE | 3A | $0.001 | ~30% of queries (fallback) |
| LLM Generation | — | $0.003-0.01 | Every query |
| Citation Verification | 3B | $0.001 | Every query |
| **Expected average** | | **~$0.007** | ~143 queries per dollar |