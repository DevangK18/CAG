# RAG Pipeline Documentation

## Pipeline Overview

The RAG (Retrieval-Augmented Generation) pipeline is a production-ready question-answering system for CAG (Comptroller and Auditor General of India) audit reports. It indexes processed audit reports into a vector database and provides natural language queries with cited, style-adaptive responses.

### Multi-Tier Government Support

The pipeline supports three tiers of government audit reports:
- **Union**: Central government ministries and departments, audited through the office of the CAG
- **State**: State government departments, audited by the State Accountant General (AG) under CAG's mandate
- **Local Bodies**: Panchayati Raj Institutions (PRIs) and Urban Local Bodies (ULBs), audited through Annual Technical Inspection Reports (ATIRs) and Local Fund Audits

Tier-specific terminology (e.g., "State Exchequer", "Zila Parishad", "PRIASoft") is handled throughout the pipeline—from BM25 sparse vector boosts to LLM context injection.

### What It Does

1. **Indexes** processed audit reports (JSON format) into a vector database, organized by tier
2. **Enhances** user queries with LLM-powered expansion and filter suggestions
3. **Retrieves** relevant document chunks using hybrid search (dense + sparse vectors) with tier-aware vocabulary boosts
4. **Reranks** results using cross-encoder models for relevance
5. **Generates** natural language answers using LLM (Claude, GPT-4, or Gemini) with tier-aware context injection
6. **Cites** all claims with precise section and page references

### Programmatic Interface

```python
from src.rag_pipeline import RAGService, ResponseStyle

rag = RAGService()
response = rag.ask("What are the audit findings on toll collection?", style=ResponseStyle.EXECUTIVE)

print(response.answer)
for citation in response.citations:
    print(f"[{citation.id}] {citation.section} (p.{citation.page})")
```

---

## Two-Pipeline Architecture

The RAG system operates as two distinct pipelines with different runtime characteristics:

### Offline Pipeline (Indexing)

**Flow:** JSON files → Embedding generation → Qdrant vector database

- Runs once per report during data ingestion
- Processes all child chunks (paragraphs, tables, charts) and parent chunks (sections)
- Generates dense embeddings, sparse vectors, and table summaries
- **Cost:** ~$0.01-0.02 per report (embedding API calls + table summaries)
- **Throughput:** ~2 reports/second

### Online Pipeline (Query)

**Flow:** User question → Query embedding → Hybrid search → Reranking → LLM generation → Cited response

- Runs per user query
- Sub-second retrieval, 2-3 second total end-to-end latency
- **Cost per query:** ~$0.002-0.01 (query embedding + reranking + LLM generation)

This separation allows expensive indexing operations to run offline while keeping query latency low.

---

## Architecture Diagram

```mermaid
graph TB
    subgraph "Indexing Pipeline"
        A[JSON Files<br/>union/state/local_body] --> B[EmbeddingService]
        B --> C[Dense + Sparse + Tier Payloads]
        C --> D[(Qdrant Vector DB)]
    end

    subgraph "Query Pipeline"
        E[User Question] --> F[RAGService]
        F --> QE[QueryEnhancer]
        QE --> |Query Expansion<br/>+ Tier Context| G[RetrievalService]
        G --> H[Query Embedding]
        H --> I[Hybrid Search + RRF<br/>State/Local Boosts]
        D --> I
        I --> J[Reranking]
        J --> K[Neighbor Expansion]
        K --> L[Parent Grouping]
        L --> SC[Sufficiency Check]
        SC --> PR[Passage Reordering]
        PR --> M[Context Assembly]
        N[ReportRegistry] --> M
        M --> TC[Tier Context Injection]
        TC --> O[LLM Generation]
        O --> P[RAGResponse]
    end

    style D fill:#e1f5ff
    style P fill:#d4edda
    style QE fill:#fff3cd
    style TC fill:#fff3cd
```

---

## Tech Stack & Dependencies

### Core Libraries

| Library | Purpose |
|---------|---------|
| **OpenAI** | Dense embeddings (`text-embedding-3-large`), LLM generation (`gpt-4o-mini`), Query enhancement |
| **Anthropic** | LLM generation (`claude-sonnet-4-20250514`) |
| **Google GenAI** | LLM generation (`gemini-2.5-flash`) |
| **Qdrant Client** | Vector database operations (hybrid search, indexing) |
| **Cohere** | Cross-encoder reranking (`rerank-english-v3.0`) |
| **sentence-transformers** | BGE cross-encoder reranker (local fallback) |

### Built-in Components

- **BM25 Sparse Vector Engine:** Custom implementation optimized for CAG documents—avoids `huggingface_hub` dependency conflicts with Docling, enables CAG-specific pattern boosting, and includes State/Local Body vocabulary boosts
- **Query Enhancer:** Single-call LLM-powered query expansion and classification with tier-aware vocabulary
- **Neighbor Predictor:** O(1) chunk ID prediction for context expansion
- **Report Registry:** Multi-tier report metadata and time series management

### External Services

- **Qdrant Vector Database:** Local (Docker) or cloud-hosted
  - Collections: `cag_child_chunks` (hybrid vectors), `cag_parent_chunks` (metadata)

---

## Stage-by-Stage Breakdown

### Stage 1: Data Models & Configuration

**Purpose:** Define data structures and configuration for the entire pipeline.

**Files:** `models.py`, `src/core/config.py`

#### Core Data Structures

**`RetrievedChunk`** (in `models.py`):
```python
@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    score: float
    parent_chunk_id: Optional[str]
    hierarchy: Dict[str, str]      # TOC breadcrumbs
    report_id: str
    page_physical: int
    content_type: str              # paragraph, table_markdown, chart
    finding_type: Optional[str]    # loss_of_revenue, wasteful_expenditure, etc.
    severity: Optional[str]        # critical, high, medium, low
    total_amount_crore: Optional[float]
    is_recommendation: bool
    # Plus: previous_chunk, next_chunk for neighbor context
```

**`RAGResponse`** (in `models.py`):
```python
@dataclass
class RAGResponse:
    query: str
    answer: str                    # Generated answer
    citations: List[Citation]      # With section, page, metadata
    sources_used: int
    context_length: int
    reranker_used: str            # "cohere", "bge", "none"
    search_type: str              # "hybrid", "dense"
    model_used: str               # LLM identifier
```

**`ReportInfo`** (in `report_registry.py`):
```python
@dataclass
class ReportInfo:
    report_id: str
    report_title: str
    report_no: str
    filename: str
    report_year: int                    # Publication year (e.g., 2025)
    audit_year: str                     # Audit period (e.g., "2023-24")
    ministry: str
    sector: str
    report_type: str
    series_id: Optional[str]            # Time series membership
    government_body_type: str           # "union", "state", "local_body"
    state_name: Optional[str]           # e.g., "Odisha" (null for Union)
    department: Optional[str]           # State/Local department
    audit_category: str                 # "compliance", "performance", etc.
```

#### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | Yes | Embeddings, GPT-4, Query enhancement |
| `ANTHROPIC_API_KEY` | Optional | Claude generation |
| `GOOGLE_API_KEY` | Optional | Gemini generation |
| `COHERE_API_KEY` | Optional | Cohere reranking |
| `QDRANT_URL` | Yes | Qdrant connection (default: `http://localhost:6333`) |
| `QDRANT_API_KEY` | Optional | Qdrant Cloud authentication |
| `LLM_PROVIDER` | Optional | Provider selection: `openai`, `claude`, or `gemini` (default: `openai`) |

---

### Stage 2: Embedding Generation

**Purpose:** Convert text into dense and sparse vectors, generate table summaries, extract semantic metadata.

**File:** `embedding_service.py`

#### Component: SparseVectorService

Generates BM25-style sparse vectors optimized for CAG documents.

**Key Features:**
- Custom tokenization with 159-word stopword filtering
- CAG-specific pattern boosting:
  - **Legal references** (3.0x): `section_143`, `rule_86b`, `form_26as`
  - **Entity acronyms** (2.5x): `acronym_NHAI`, `acronym_PMJAY`
  - **Monetary/temporal** (1.5x): `money_crore`, `year_2023-24`
- BM25 term frequency saturation: `tf / (tf + k1)` where k1=1.2

**Design Decision:** We built custom BM25 rather than using fastembed to avoid `huggingface_hub` version conflicts with Docling and to enable CAG-specific optimizations. The tradeoff is maintenance burden, but the 3x boost on legal references significantly improves retrieval for queries like "Section 143(3) violations."

**Input/Output:**
- Input: `"Revenue loss of ₹64.60 crore in Section 143(3)"`
- Output: `{"indices": [45, 67, 89, 234, ...], "values": [1.5, 3.0, 1.2, 2.8, ...]}`

#### Component: TableSummaryService

Generates natural language summaries for markdown tables using LLM.

**Why LLM-based?** CAG tables have complex merged headers and nested structures. Rule-based parsing with `split("|")` fails on these. The LLM captures semantic meaning—e.g., "Table showing state-wise revenue collection with Maharashtra contributing highest at ₹12,450 crore."

**Implementation:**
- Model: `gpt-4o-mini` (cost: ~$0.0001 per table)
- Max tokens: 100, Temperature: 0 (deterministic)
- Fallback: Rule-based header extraction if LLM fails

**Design Decision:** We use `gpt-4o-mini` rather than Claude for table summaries because it's 5x cheaper and table summarization is a simple task that doesn't benefit from Claude's stronger reasoning. At ~10,000 tables across the corpus, this saves ~$5 in indexing costs.

#### Component: SemanticPayloadExtractor

Extracts semantic enrichment metadata for Qdrant payloads by matching `chunk_id` against the semantic enrichment data from the parsing pipeline.

**Extracted Fields:**
- Findings: `finding_type`, `severity`, `total_amount_crore`, `entities_mentioned`
- Recommendations: `is_recommendation`, `recommendation_target`, `action_required`
- Section classification: `section_type` (executive_summary, findings, recommendations, annexure)

#### Component: DenseEmbeddingService

Generates dense embeddings using OpenAI.

**Configuration:**
- Model: `text-embedding-3-large`
- Dimensions: 1536 (reduced from 3072)
- Batch size: 100 chunks per API call

**Design Decision:** We reduced dimensions from 3072 to 1536 to cut storage and search costs by 50%. OpenAI's research shows <1% quality degradation for this reduction on typical retrieval tasks. For CAG documents with technical vocabulary, we validated this empirically and found no measurable recall impact.

#### EmbeddingService Orchestration

The main `EmbeddingService` class orchestrates all sub-services via `process_chunks()`:

**Process:**
1. Build parent lookup dictionary for hierarchy resolution
2. For each child chunk:
   - Get hierarchy breadcrumbs from parent
   - Prepare text with hierarchy prefix + table summary (if applicable)
   - Extract semantic payload from enrichment data
   - Include multi-tier metadata fields
3. Generate dense embeddings (batched)
4. Generate sparse vectors (batched)

**Multi-Tier Payload Fields:**
Each chunk payload includes tier-specific metadata from the parsing pipeline:
```python
payload = {
    # ... existing fields ...
    "government_body_type": "state",     # "union", "state", "local_body"
    "state_name": "Odisha",               # null for Union reports
    "department": "Rural Development",    # State/Local department
    "audit_category": "compliance",       # "compliance", "performance", etc.
}
```

**Text Preparation Example:**
```
Input: Table chunk on page 45
Parent hierarchy: {"level_1": "Chapter II", "level_2": "2.3 Revenue Collection"}

Output text:
"[Chapter II > 2.3 Revenue Collection]

[Table Summary: State-wise revenue for FY 2022-23, Maharashtra at ₹12,450 crore.]

| State | Revenue (₹ crore) | Growth (%) |
|-------|-------------------|------------|
| Maharashtra | 12,450 | 8.3 |
| ..."
```

The hierarchy prefix improves retrieval by embedding section context directly into the vector. When users ask about "revenue collection," chunks from the Revenue Collection section rank higher.

---

### Stage 3: Vector Database Management

**Purpose:** Manage Qdrant collections, index chunks, perform hybrid searches.

**File:** `qdrant_service.py`

#### Collection Architecture

**Child Collection** (`cag_child_chunks`):
- **Dense vectors:** 1536-dim, cosine distance
- **Sparse vectors:** BM25 with IDF modifier
- **Payload indexes:**
  - Standard: `report_id`, `report_year`, `parent_chunk_id`, `content_type`, `page_physical`
  - Multi-tier: `government_body_type`, `state_name`, `audit_category`
  - Semantic: `finding_type`, `severity`, `section_type`, `total_amount_crore`, `is_recommendation`

**Parent Collection** (`cag_parent_chunks`):
- Metadata-only (dummy 4-dim vector required by Qdrant API)
- Stores: `toc_entry`, `toc_level`, `hierarchy`, `page_range_physical`

**Design Decision:** We use separate parent and child collections rather than a single collection with filtering. This enables efficient parent lookups during context assembly without polluting search results with section-level entries that lack searchable content. The parent collection serves purely as a metadata store for hierarchy and page ranges.

#### Indexing

`upsert_children()` converts chunks to Qdrant points:

1. Convert `chunk_id` to integer point ID using MD5 hash (first 8 bytes as unsigned long)
2. Build `PointStruct` with dense vector, sparse vector, and payload
3. Batch upsert in groups of 100

**Design Decision:** We use MD5 hashing for `chunk_id → point_id` because Qdrant requires integer IDs. MD5 provides deterministic, collision-resistant mapping with negligible collision probability for our corpus size (~1M chunks). Simpler hashes like CRC32 have higher collision risk at scale.

#### Hybrid Search

`hybrid_search()` implements RRF (Reciprocal Rank Fusion) to combine dense and sparse results.

**Algorithm (pseudocode):**
```
dense_results = search(dense_vector, limit=50)
sparse_results = search(sparse_vector, limit=50)

for each document:
    rrf_score = sum(1 / (k + rank_in_query_i)) for each query
    # k=60 (standard RRF constant)

return top_n by rrf_score
```

**Design Decision:** We chose RRF over linear combination because RRF is rank-based rather than score-based. Dense and sparse scores have different scales and distributions—dense cosine similarity ranges [0,1] while BM25 scores can be arbitrarily large. RRF normalizes these automatically. Research shows RRF consistently outperforms tuned linear combinations across domains.

**Why Hybrid?**
- Dense alone misses exact pattern matches ("Section 143(3)")
- Sparse alone misses paraphrased queries ("revenue shortfall" vs "loss of revenue")
- Hybrid captures both semantic similarity and lexical precision

#### Filter Support

Supports Qdrant filter conditions:
- Exact match: `{"report_id": "2023_07_..."}`
- Range: `{"total_amount_crore": {"gte": 10.0}}`
- Array match: `{"entities_mentioned": ["NHAI", "MoRTH"]}`

Payload indexing makes filtered searches fast (<50ms vs 5000ms unindexed).

---

### Stage 4: Metadata Management

**Purpose:** Manage report metadata for all three government tiers and organize time series for multi-year analysis.

**File:** `report_registry.py`

#### Data Models

**`ReportInfo`:**
```python
@dataclass
class ReportInfo:
    report_id: str
    report_title: str
    report_no: str
    filename: str
    report_year: int                    # 2025
    audit_year: str                     # "2023-24"
    ministry: str
    sector: str
    series_id: Optional[str]            # "frbm_compliance"
    # Multi-tier fields:
    government_body_type: str           # "union", "state", "local_body"
    state_name: Optional[str]           # e.g., "Odisha" (null for Union)
    department: Optional[str]           # State/Local department
    audit_category: str                 # "compliance", "performance", etc.
```

**`TimeSeries`:**
```python
@dataclass
class TimeSeries:
    series_id: str         # "union_govt_accounts"
    name: str              # "Union Government Accounts (Financial Audit)"
    report_ids: List[str]  # Ordered by audit_year
```

#### Time Series Definitions

Reports are grouped into series using regex patterns:

```python
SERIES_DEFINITIONS = {
    "union_govt_accounts": {
        "pattern": r"Union.?Government.?Accounts.*Financial.?Audit",
    },
    "frbm_compliance": {
        "pattern": r"Fiscal.?Responsibility.*Budget.?Management|FRBM",
    },
    "direct_taxes_audit": {
        "pattern": r"Compliance.?Audit.*Direct.?[Tt]axes",
        "exclude_pattern": r"Performance.?Audit",
    },
}
```

#### Multi-Tier Directory Structure

The registry recursively scans all tier subdirectories:
```
data/processed/
├── union/                  # Central government reports
│   ├── 2025_16_FRBM_chunks.json
│   └── 2025_17_Direct_Taxes_chunks.json
├── state/                  # State government reports
│   ├── OD_2024_01_Revenue_chunks.json
│   └── GJ_2024_02_Education_chunks.json
└── local_body/            # PRI/ULB reports
    ├── MH_ATIR_2024_chunks.json
    └── RJ_ATIR_2024_chunks.json
```

Filenames are prefixed with the tier subdirectory (e.g., `state/OD_2024_01_Revenue.pdf`) for correct PDF viewer path resolution.

#### Registry Loading

`load_from_json_dir()` recursively scans `**/*_chunks.json` files and:
1. Extracts `report_metadata` from each JSON
2. Parses audit year from title using multiple format patterns
3. Extracts multi-tier fields (`government_body_type`, `state_name`, `department`, `audit_category`)
4. Matches series using title regex patterns
5. Groups reports by series, ordered by audit year

#### Singleton Pattern

The registry uses a singleton to ensure consistent metadata across the application:

```python
def get_registry() -> ReportRegistry:
    global _registry
    if _registry is None:
        _registry = ReportRegistry()
    return _registry
```

---

### Stage 5: Retrieval & Search

**Purpose:** Orchestrate end-to-end retrieval: query encoding, hybrid search, reranking, neighbor expansion, parent grouping.

**File:** `retrieval_service.py`

#### Rerankers

**CohereReranker:**
- Model: `rerank-english-v3.0`
- Prepends hierarchy breadcrumbs to each chunk before reranking:
  ```
  "[Chapter II > 2.3 Revenue > 2.3.1 Direct Taxes] {chunk.content}"
  ```
- Returns top N with updated relevance scores

**BGEReranker:**
- Model: `BAAI/bge-reranker-v2-m3` (local cross-encoder)
- Same hierarchy context prepending
- Zero-cost fallback when Cohere unavailable

**Design Decision:** Cohere is primary because it consistently outperforms BGE on our benchmark queries by 8-12% in precision@10. However, BGE provides acceptable quality (within 5% of Cohere) as a free fallback for cost-sensitive deployments or when Cohere is unavailable.

#### NeighborPredictor

O(1) neighbor lookup using deterministic chunk ID patterns.

**Chunk ID Format:**
```
{report_id}_child_p{page:03d}_{content_type}_{index:04d}
Example: "2023_07_child_p045_paragraph_0123"
```

**Prediction Logic (pseudocode):**
```
parse chunk_id → (report_id, page, type, index)
prev_id = f"{report_id}_child_p{page}_{type}_{index - 1}"
next_id = f"{report_id}_child_p{page}_{type}_{index + 1}"
fetch_by_id(prev_id), fetch_by_id(next_id)  # Direct lookup, no search
```

**Design Decision:** Traditional approaches search for neighbors using vector similarity, which requires 2 additional vector searches per retrieved chunk. Our approach predicts neighbor IDs from the chunk naming pattern and fetches directly by ID—100x faster. The tradeoff is that we depend on consistent chunk ID formatting from the parsing pipeline.

#### SparseQueryEncoder

Encodes user queries to sparse vectors using the same BM25 logic as indexing.

**CAG-Specific Pattern Boosting:**
| Pattern Type | Boost | Examples |
|--------------|-------|----------|
| Legal references | 3.0x | `section_143`, `rule_86b`, `form_26as`, `article_311` |
| Entity acronyms | 2.5x | `acronym_NHAI`, `acronym_PMJAY`, `acronym_PRI`, `acronym_ULB` |
| **State/Local terms** | 2.0x | `state_audit_state_exchequer`, `local_body_gram_panchayat`, `local_body_zila_parishad` |
| Monetary/temporal | 1.5x | `money_crore`, `year_2023-24` |

**State/Local Body Vocabulary Patterns:**
```python
# Patterns extracted from queries (2.0x boost):
panchayat_patterns = [
    "panchayat", "panchayati", "gram panchayat", "zila parishad",
    "block development", "municipal corporation", "urban local",
    "local body", "local fund", "pri audit", "ulb audit"
]
state_patterns = [
    "state exchequer", "state consolidated", "state pse",
    "district collector", "state ag", "principal accountant",
    "accountant general", "state finance", "state revenue"
]
```

**Design Decision:** State and Local Body reports use distinct administrative vocabulary that wouldn't match Union report terminology. The 2.0x boost (below acronym but above monetary) ensures queries about "Zila Parishad" or "State Exchequer" retrieve the right chunks without overwhelming general terms.

#### RetrievalService Orchestration

**Main method: `retrieve(query, top_k, filters)`**

**Step-by-step process:**

1. **Query Embedding:** Generate dense (1536-dim) and sparse (BM25) vectors
2. **Hybrid Search:** Retrieve initial candidates (default: 50) using RRF fusion
3. **Reranking:** If results > final_top_k, rerank using Cohere/BGE
4. **Neighbor Expansion:** Populate `previous_chunk`, `next_chunk` via O(1) prediction
5. **Parent Grouping:** Group chunks by `parent_chunk_id`
6. **Parent Context Fetching:** Fetch parent metadata (TOC entry, hierarchy, page range)

**Design Decision:** We retrieve 50 initial candidates then rerank to 10. This 5:1 ratio balances recall vs precision—50 is enough to capture most relevant chunks (recall ~95%), while reranking ensures the final 10 are highly precise. Retrieving fewer initial candidates risks missing relevant content; more provides diminishing returns at increased reranking cost.

**Output:**
```python
RetrievalResult(
    query="What are the audit findings on toll collection?",
    total_candidates=50,
    total_after_rerank=10,
    parents=[
        ParentContext(
            toc_entry="2.3.1 Toll Collection Issues",
            hierarchy={"level_1": "Chapter II", "level_2": "2.3 Revenue"},
            page_range=(35, 42),
            children=[chunk1, chunk2, ...]
        ),
        ...
    ],
    reranker_used="cohere",
    search_type="hybrid"
)
```

#### Context Assembly

Builds final context string for LLM generation:

```markdown
## Chapter II > 2.3 Revenue Collection (Pages 35-42)

[1] Revenue loss of ₹64.60 crore occurred at 12 toll plazas...
    Finding: loss_of_revenue | Severity: HIGH | Amount: ₹64.60 crore

[2] Non-functional ETC equipment was the primary cause...
```

Each chunk is numbered for citation reference, with semantic metadata displayed for context.

---

### Stage 5.5: Query Enhancement

**Purpose:** Enhance user queries with LLM-powered expansion, classification, and tier-aware vocabulary.

**File:** `query_enhancer.py`

#### Component: QueryEnhancer

Single-call LLM service that provides query intelligence before retrieval.

**Inputs:**
- User question
- Response style preference
- Tier context (optional, e.g., "State audit report from Gujarat")

**Outputs (`QueryEnhancement`):**
```python
@dataclass
class QueryEnhancement:
    question_type: str              # factual, list, aggregation, comparison, explanation
    expanded_queries: List[str]     # Original + 2 alternative phrasings
    suggested_filters: Dict         # e.g., {"finding_type": "loss_of_revenue"}
    top_k: int                      # Recommended retrieval count
    initial_candidates: int         # Candidates before reranking
    max_context_chars: int          # Context truncation limit
    recommended_style: Optional[str] # Style recommendation for "adaptive"
```

**Example Enhancement:**
```
Input: "What went wrong with toll collection?"
Output:
  question_type: "explanation"
  expanded_queries: [
    "What went wrong with toll collection?",
    "toll revenue loss audit findings NHAI fee collection",
    "electronic toll collection ETC compliance shortfall observations"
  ]
  suggested_filters: {"finding_type": "loss_of_revenue"}
  top_k: 12
  recommended_style: "explanatory"
```

**Tier-Aware Query Expansion:**
When `tier_context` is provided (e.g., for a State report), the enhancer uses tier-appropriate vocabulary:
- **State reports:** "State AG", "State Exchequer", "State PSE", "State Consolidated Fund"
- **Local Body reports:** "Gram Panchayat", "Zila Parishad", "Urban Local Body", "PRI", "ULB", "ATIR", "PRIASoft"

**Design Decision:** Query enhancement uses `gpt-4o-mini` (or `gemini-2.5-flash`) with a single LLM call (~$0.0002/query). This replaces the previous regex-based question type detection with LLM-powered classification that can also suggest filters and expand queries. The tradeoff is a small latency addition (~100ms), but the improved retrieval quality from multi-query search justifies this.

**Integration with Retrieval:**
1. `RAGService.ask()` calls `QueryEnhancer.enhance()` with tier context
2. Enhancement's `expanded_queries` enables multi-query retrieval with RRF fusion
3. Enhancement's `suggested_filters` are merged with user-provided filters
4. Enhancement's `top_k` and `max_context_chars` override defaults for question type

---

### Stage 6: Answer Generation

**Purpose:** Generate natural language answers with citations using LLM.

**File:** `rag_service.py`

#### Response Styles

| Style | Target Use Case | Word Count |
|-------|-----------------|------------|
| `CONCISE` | Quick answers, mobile users | 50-100 |
| `DETAILED` | Comprehensive analysis | 300-500 |
| `EXECUTIVE` | Decision-makers, bottom-line first | 150-250 |
| `TECHNICAL` | Deep-dive for analysts | 400-600 |
| `COMPARATIVE` | Theme-based multi-year analysis | 300-500 |
| `ADAPTIVE` | Auto-detects question type | Varies |

Two additional styles (`EXPLANATORY`, `REPORT`) are available programmatically but not exposed in the frontend.

#### System Prompt Architecture

The prompt system has several layered components:

**Base Expertise:** CAG domain knowledge covering all three government tiers:
- Union: Central ministries, Consolidated Fund of India, Parliamentary committees
- State: State AG, State Exchequer, State Consolidated Fund, State PSEs
- Local Bodies: PRIs, ULBs, Gram Panchayat, Zila Parishad, ATIR, PRIASoft

Critical rules: ONLY state facts in context, NEVER invent amounts

**Anti-Pattern Rules:** Forbidden phrases ("The question is asking...", "Based on the context..."), required behaviors (start directly with answer, use proper markdown)

**Citation Rules:**
- Format: `[Section Name, p.XX]` (strict)
- Placement: END of sentence, never mid-sentence
- Correct: `"Revenue loss was ₹64.60 crore. [Section 3.2.1, p.36]"`
- Wrong: `"Revenue loss was ₹64.60 crore [Section 3.2.1, p.36] due to..."`

**Style-Specific Instructions:** Each style has tailored structure and word count guidance. For example, `CONCISE` requires: lead with key finding, main amount, 1-2 supporting details, citation at end.

**Design Decision:** We use temperature 0.1 rather than 0 because temperature 0 in OpenAI's API can produce repetitive outputs for similar queries. Temperature 0.1 provides near-deterministic behavior while avoiding the repetition trap. We prioritize consistency over creativity for factual Q&A.

#### Question Type Detection

When Query Enhancement is enabled (default), question type classification is handled by `QueryEnhancer` (see Stage 5.5). As a fallback, `_detect_question_type()` uses regex-based detection:

| Type | Trigger Patterns | Adjustments |
|------|------------------|-------------|
| LIST | "what are", "list all", "enumerate" | top_k → 15, bullet format |
| AGGREGATION | "total", "sum", "overall" | context limit 1.5x, warn against calculation |
| COMPARISON | "compare", "trend", "over years" | COMPARATIVE style |
| EXPLANATION | "why", "explain", "cause" | EXPLANATORY style |
| FACTUAL | (default) | No adjustment |

#### Main Ask Method

`ask(question, filters, top_k, style)`:

1. **Query Enhancement** (if enabled): Call `QueryEnhancer.enhance()` with tier context
2. **Retrieval:** Call `RetrievalService.retrieve()` with expanded queries and merged filters
3. **Passage Reordering:** Reorder parents to mitigate "lost in the middle" attention effect
4. **Sufficiency Check:** Evaluate if top reranker score meets threshold (tier-adjusted)
5. **Context Assembly:** Build markdown with hierarchy headers, semantic tags
6. **Tier Context Injection:** Prepend tier-aware context header for State/Local reports
7. **Truncation:** Limit to `max_context_chars` (default: 15,000)
8. **Generation:** Call LLM (Claude, GPT-4, or Gemini)
9. **Caveat Injection:** If context insufficient, prepend warning to answer
10. **Citation Building:** Enrich citations with report metadata from `ReportRegistry`
11. **Return:** `RAGResponse` with answer, citations, and metadata

**Design Decision:** We truncate context to 15,000 characters (~3,750 tokens) because our experiments showed answer quality plateaus after ~4,000 tokens of context. More context increases LLM cost linearly but provides diminishing quality returns. For list/aggregation questions, we increase to 22,500 characters since these questions benefit from more sources.

#### Tier Context Injection

`_build_tier_context()` generates a contextual header for State and Local Body reports:

**Example (State report):**
```
📋 REPORT CONTEXT: This is a State audit report from Odisha.
Department/Sector: Rural Development
Audit type: Compliance Audit
Note: State audit terminology may include 'State AG', 'State Exchequer',
'State Consolidated Fund', 'SPSE' (State Public Sector Enterprise).
```

**Example (Local Body report):**
```
📋 REPORT CONTEXT: This is a Local Body (Panchayati Raj Institutions / Urban Local Bodies) audit report from Maharashtra.
Note: Local Body terminology may include 'PRI' (Panchayati Raj Institution),
'ULB' (Urban Local Body), 'GP' (Gram Panchayat), 'ZP' (Zila Parishad),
'ATIR' (Annual Technical Inspection Report), 'PRIASoft', 'Local Fund Audit'.
```

This context is prepended to the user prompt, helping the LLM understand tier-specific vocabulary and generate appropriately styled responses.

#### Context Sufficiency Check

`_check_context_sufficiency()` evaluates whether retrieved chunks are relevant enough to answer the question:

- Checks if the top reranker score exceeds `min_rerank_score` (default: 0.25)
- **Tier-adjusted threshold:** For State/Local Body reports, the threshold is lowered by 30% (to 0.175) because the Cohere reranker was calibrated for Union report vocabulary

If context is insufficient, a caveat is prepended:
```
⚠️ **Note**: The available reports may not contain specific information
to fully answer this question. Based on the closest matches found:
```

**Design Decision:** The 30% threshold reduction for State/Local reports accounts for vocabulary differences—terms like "Zila Parishad" score lower with Cohere's general English model, but answers are still good. This prevents false-positive insufficiency warnings for valid State/Local queries.

#### Passage Reordering

`_reorder_for_attention()` reorders parent contexts to mitigate the "lost in the middle" attention effect (ICLR 2025 research shows LLMs attend most to content at the beginning and end of context).

**Strategy:** Interleave by relevance score:
- Position 1: highest-scored parent (best content first)
- Position 2: lowest-scored parent (to end of attention window)
- Position 3: second-highest
- Position 4: second-lowest
- etc.

This ensures the most and least relevant parents are at attention-optimal positions.

#### Answer Generation

`_generate_answer(question, context, style, question_type)`:

- Constructs prompt from style-specific system prompt + context + question + type hints
- Calls Claude, OpenAI, or Gemini depending on `LLM_PROVIDER` configuration
- Max tokens: 2000, Temperature: 0.1

#### Time Series / Comparative Analysis

`ask_comparative(question, report_ids, top_k_per_report)`:

For multi-year analysis, retrieves from each report separately and constructs context with strong year boundaries:

```markdown
============================================================
YEAR: 2022-23
Report: FRBM Compliance Report 2022-23
============================================================

All findings below are from 2022-23. Cite as: [2022-23 - Section X, p.XX]

{context_from_retrieval}
```

**Time Series Prompt Enhancements:**
- Mandatory year in citations: `[2022-23 - Section 3.1, p.45]`
- Missing data handling: "Data not available for 2021-22" (explicit instruction to state rather than hallucinate)
- Theme-based organization (not chronological)
- Trend indicators (↑ ↓ →)

**Example Output:**
```markdown
### Fiscal Deficit
**Trend:** ↑ Improving
- **2021-22:** 6.71% of GDP, exceeding target. [2021-22 - Section 2.3, p.25]
- **2022-23:** 6.4% of GDP, within ceiling. [2022-23 - Section 2.3, p.24]
- **2023-24:** Data not available for this year

Progressive reduction indicates improved consolidation.
```

#### Citation Building

`build_citations()` enriches citations with full report metadata:

```python
Citation(
    id=num,
    report_id=child.report_id,
    section=parent.toc_entry,
    page=child.page_physical + 1,  # Convert to 1-indexed
    score=round(child.score, 3),
    finding_type=child.finding_type,
    severity=child.severity,
    amount_crore=child.total_amount_crore,
    report_title=report_info.report_title,  # From registry
    filename=report_info.filename,
    audit_year=report_info.audit_year,
)
```

---

### Stage 7: Indexing Orchestration

**Purpose:** Batch indexing orchestration for processing JSON files into Qdrant.

**File:** `indexer.py`

#### Indexer Architecture

The `Indexer` class orchestrates the offline indexing pipeline:

**Multi-Tier Directory Scanning:**
The indexer recursively scans all tier subdirectories:
```bash
python -m src.rag_pipeline.indexer --input-dir data/processed --recreate

# Scans:
# data/processed/union/**/*_chunks.json
# data/processed/state/**/*_chunks.json
# data/processed/local_body/**/*_chunks.json
```

**`index_all(input_dir, recreate)`:**
1. Recursively find all `**/*_enriched.json` or `**/*_chunks.json` files across tier subdirectories
2. Create Qdrant collections (recreate if flag set)
3. Process each file via `index_file()`
4. Return statistics (files processed, chunks indexed, errors)

**`index_file(json_path)`:**
1. Load JSON data
2. Call `EmbeddingService.process_chunks()` to generate embeddings + tier-aware payloads
3. Upsert children (with `government_body_type`, `state_name`, etc.) and parents to Qdrant
4. Return per-file stats

**Output Statistics:**
- Files processed
- Children indexed (paragraphs, tables, charts)
- Parents indexed (sections)
- Files with enrichment
- Embedding costs (dense + table summaries)

---

## Configuration Reference

### Embedding Configuration

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `model` | `text-embedding-3-large` | OpenAI embedding model |
| `dimensions` | 1536 | Vector dimensions (reduced from 3072 for cost) |
| `batch_size` | 100 | Chunks per API call |
| `enable_sparse_vectors` | true | Generate BM25 sparse vectors |
| `enable_table_summaries` | true | LLM-generated table summaries |
| `enable_hierarchy_prefix` | true | Prepend TOC breadcrumbs to text |

### Retrieval Configuration

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `initial_candidates` | 50 | Candidates before reranking |
| `final_top_k` | 10 | Results after reranking |
| `enable_hybrid_search` | true | Use dense + sparse fusion |
| `enable_reranking` | true | Cross-encoder reranking |
| `enable_neighbor_chunks` | true | Fetch ±1 neighbors |
| `neighbor_window` | 1 | Neighbor expansion range |
| `reranker_type` | `COHERE` | Primary: Cohere, Fallback: BGE |

### LLM Configuration

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `provider` | `OPENAI` | LLM provider (OPENAI, CLAUDE, GEMINI) |
| `openai_model` | `gpt-4o-mini` | OpenAI model for generation |
| `claude_model` | `claude-sonnet-4-20250514` | Claude model for generation |
| `gemini_model` | `gemini-2.5-flash` | Gemini model for generation |
| `max_tokens` | 2000 | Max response tokens |
| `temperature` | 0.1 | Near-deterministic for factual Q&A |
| `max_context_chars` | 15000 | Context truncation limit |

### Query Enhancement Configuration

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `enabled` | true | Enable LLM-powered query enhancement |
| `enable_query_expansion` | true | Expand query with alternative phrasings |
| `enable_passage_reordering` | true | Reorder for attention optimization |
| `enable_sufficiency_check` | true | Check context relevance before generation |
| `provider` | `OPENAI` | Provider for enhancement (OPENAI or GEMINI) |
| `model` | `gpt-4o-mini` | OpenAI model for enhancement |
| `gemini_model` | `gemini-2.5-flash` | Gemini model for enhancement |
| `num_expansions` | 3 | Total queries (original + expansions) |
| `min_rerank_score` | 0.25 | Minimum top-1 score for sufficiency (30% lower for State/Local) |

---

## Performance Profile

### Latency Breakdown (Typical Query)

| Stage | Time |
|-------|------|
| Query enhancement (LLM) | ~100ms |
| Query embedding (dense + sparse) | ~100ms |
| Hybrid search + RRF | ~50ms |
| Reranking (Cohere) | ~200ms |
| Neighbor expansion | ~20ms |
| Context assembly | ~10ms |
| Sufficiency check + Passage reordering | ~5ms |
| Tier context injection | ~5ms |
| LLM generation | ~1500-2000ms |
| **Total end-to-end** | **~2-3s** |

### Cost Breakdown

**Per-Query Cost:**
- Query enhancement (gpt-4o-mini): ~$0.0002
- Query embedding: ~$0.0001
- Cohere reranking: ~$0.001
- LLM generation (gpt-4o-mini): ~$0.002-0.005
- **Total:** ~$0.003-0.008 per query

**Per-Report Indexing Cost:**
- Dense embeddings: ~$0.01 (varies with report length)
- Table summaries: ~$0.001 (varies with table count)
- **Total:** ~$0.01-0.02 per report

### Key Optimizations

**O(1) Neighbor Lookup:**
Traditional neighbor search requires 2 vector searches per retrieved chunk. Our ID prediction approach uses direct Qdrant retrieval by ID—100x faster. This keeps neighbor expansion at ~20ms for 10 chunks.

**Batch Processing:**
- Embedding: 100 chunks per API call (reduces N calls to N/100)
- Qdrant upsert: 100 points per batch (reduces network round-trips)

**Payload Indexing:**
Indexed fields (`report_id`, `finding_type`, `total_amount_crore`, etc.) enable filtered searches in <50ms. Without indexes, the same filters would scan all vectors (~5000ms).

**Context Truncation:**
Limiting context to 15,000 chars prevents quality plateau while keeping LLM costs linear with actual content needs. List/aggregation questions get 1.5x context since they benefit from more sources.

**Table Summary Caching:**
LLM table summaries are generated during indexing and stored in payloads—never regenerated at query time. For 10,000 tables, this is $1 one-time vs $1 per query.

**Tier-Aware Sufficiency Thresholds:**
State and Local Body reports use different administrative vocabulary than Union reports, causing lower Cohere reranker scores for valid matches. Reducing the sufficiency threshold by 30% for these tiers prevents false-positive "low relevance" warnings while maintaining answer quality.

**Passage Reordering for Attention:**
Research shows LLMs attend most to the beginning and end of context. Interleaving parents by relevance (best→worst→second-best→second-worst) places the most relevant content at attention-optimal positions, improving answer quality at zero additional cost.
