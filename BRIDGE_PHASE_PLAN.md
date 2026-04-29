# Bridge Phase: Pre-700-Reports Implementation Plan

**Purpose**: Harden the RAG pipeline before scaling from 37 → 700+ reports
**Baseline**: Phases 11, 12, 13 complete and shipped
**Scope**: Auto-filter retrieval, two-pass canonicalization, query observability, comparative breadth cap
**Out of scope**: Evaluation set creation (separate effort), home page UI (already in flight)

---

## Design decisions confirmed

- **Decision A** (auto-filter universality): Apply to all retrieval calls; only kicks in when no filter already specified. Calling contexts that pre-set filters (directory, time series) are unaffected.
- **Decision B** (two-pass canonicalization): Build the logic now, gate behind `two_pass_threshold: 1000` so it auto-activates at scale.
- **Decision C** (query log storage): Postgres table in same DB as entity graph.
- **Decision D** (chunk content storage): IDs + scores + first 200 chars by default; full content behind dev debug flag.
- **Decision E** (LLM trace storage): Final answer only in prod; full trace (system + user prompts + token usage) behind dev debug flag.

---

## Build order

These four bridge tasks are mostly independent. Recommended order:

1. **Bridge A**: Auto-filter retrieval — most impactful for precision at scale
2. **Bridge C**: Query observability — needed before any production scaling so we can measure A's effect
3. **Bridge D**: Comparative breadth cap — small, surgical
4. **Bridge B**: Two-pass canonicalization — biggest payoff at 700 reports, no urgency at 37

C goes second because the ROI of A is invisible without observability data. Once A and C are live, you can measure precision in production before adding more reports.

---


## Bridge C: Query observability

### Goal

Capture every query (dev and prod) with full context for debugging, regression detection, and cost tracking. Postgres-backed in the same DB as entity graph.

### What gets logged

| Field | Always | Dev only |
|-------|--------|---------|
| `query_id` (UUID) | ✅ | |
| `timestamp` | ✅ | |
| `environment` (dev/prod) | ✅ | |
| `interaction_mode` (directory/series/home/agentic_sub) | ✅ | |
| `query_text` (the actual user query) | ✅ | |
| `report_ids_filter` (if directory or series) | ✅ | |
| `series_id` (if from time series) | ✅ | |
| `agentic_parent_query_id` (if this is a sub-query) | ✅ | |
| `query_enhancement` (question_type, expanded_queries, suggested_filters) | ✅ | |
| `auto_filters_applied` | ✅ | |
| `merged_filters_used` | ✅ | |
| `retrieved_chunks_summary` (chunk_id, score, first 200 chars, report_id) | ✅ | |
| `retrieved_chunks_full_content` | | ✅ |
| `rerank_scores` | ✅ | |
| `context_sufficiency_score` | ✅ | |
| `agentic_iterations` (sub-queries, reformulations, final iteration count) | ✅ | |
| `groundedness_report` | ✅ | |
| `final_answer` | ✅ | |
| `llm_system_prompt` | | ✅ |
| `llm_user_prompt` | | ✅ |
| `llm_raw_response` | | ✅ |
| `llm_provider_used` | ✅ | |
| `llm_model_used` | ✅ | |
| `token_usage` (prompt, completion, total) | ✅ | |
| `cost_estimate_usd` | ✅ | |
| `latency_breakdown_ms` (enhancement, retrieval, rerank, generation, groundedness, total) | ✅ | |
| `error` (if failed) | ✅ | |
| `client_session_id` (anonymous) | ✅ | |

### Schema

```sql
-- Stored in cag_entity_graph DB (same as entity graph)

CREATE TABLE query_logs (
    id BIGSERIAL PRIMARY KEY,
    query_id UUID NOT NULL UNIQUE,                     -- for joining with sub-queries
    parent_query_id UUID,                              -- for agentic sub-queries
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    environment VARCHAR(20) NOT NULL,                  -- 'dev' / 'prod'
    interaction_mode VARCHAR(40) NOT NULL,             -- 'directory' / 'series' / 'home' / 'agentic_sub' / 'comparative'

    -- Query inputs
    query_text TEXT NOT NULL,
    style VARCHAR(40),
    report_ids_filter TEXT[],                          -- nullable; populated for directory/series
    series_id VARCHAR(100),                            -- nullable; for time series queries
    explicit_filters JSONB,                            -- what the caller passed
    auto_filters JSONB,                                -- what AutoFilterExtractor produced
    merged_filters JSONB,                              -- final filters applied

    -- Query enhancement
    query_enhancement JSONB,                           -- {question_type, expanded_queries, recommended_style, ...}

    -- Retrieval
    retrieved_chunks JSONB,                            -- summary list (always); full content if dev_debug
    retrieval_search_type VARCHAR(40),                 -- 'hybrid' / 'merged' / 'agentic_merged'
    retrieval_total_candidates INTEGER,
    retrieval_total_after_rerank INTEGER,
    rerank_scores REAL[],                              -- top-N scores
    context_sufficient BOOLEAN,
    reranker_used VARCHAR(40),

    -- Agentic-specific
    agentic_complexity VARCHAR(40),                    -- 'simple' / 'multi_hop' / 'cross_report'
    agentic_sub_query_count INTEGER,
    agentic_total_iterations INTEGER,
    agentic_reformulation_count INTEGER,
    agentic_bail_reason VARCHAR(80),
    agentic_trace JSONB,                               -- full trace

    -- Generation
    llm_provider VARCHAR(40),
    llm_model VARCHAR(80),
    llm_system_prompt TEXT,                            -- nullable; populated only if dev_debug
    llm_user_prompt TEXT,                              -- nullable; populated only if dev_debug
    llm_raw_response TEXT,                             -- nullable; populated only if dev_debug
    final_answer TEXT,
    answer_length_chars INTEGER,
    citations_count INTEGER,

    -- Groundedness
    groundedness_score REAL,
    groundedness_verified BOOLEAN,
    groundedness_num_claims INTEGER,
    groundedness_num_grounded INTEGER,
    groundedness_report JSONB,                         -- full claim details

    -- Cost & latency
    token_usage_prompt INTEGER,
    token_usage_completion INTEGER,
    token_usage_total INTEGER,
    cost_estimate_usd NUMERIC(10, 6),
    latency_total_ms INTEGER,
    latency_breakdown_ms JSONB,                        -- {enhancement, retrieval, rerank, generation, groundedness}

    -- Errors
    success BOOLEAN NOT NULL,
    error_message TEXT,

    -- Session
    client_session_id VARCHAR(100),                    -- anonymous; rotates per browser session
    user_agent TEXT
);

CREATE INDEX idx_query_logs_timestamp ON query_logs (timestamp);
CREATE INDEX idx_query_logs_environment_mode ON query_logs (environment, interaction_mode);
CREATE INDEX idx_query_logs_parent ON query_logs (parent_query_id);
CREATE INDEX idx_query_logs_session ON query_logs (client_session_id);
CREATE INDEX idx_query_logs_groundedness ON query_logs (groundedness_score);
CREATE INDEX idx_query_logs_success ON query_logs (success);
CREATE INDEX idx_query_logs_complexity ON query_logs (agentic_complexity) WHERE agentic_complexity IS NOT NULL;
```

### Files to create

- `src/observability/__init__.py`
- `src/observability/models.py` — SQLAlchemy ORM `QueryLog` model matching the schema
- `src/observability/query_logger.py` — `QueryLogger` class with `log()` method, `start_query_context()` ContextManager, fire-and-forget async write
- `src/observability/cost_calculator.py` — token-to-$ pricing table for OpenAI/Claude/Gemini/Cohere

### Files to modify

- `src/core/config.py` — add `ObservabilityConfig` (enabled, environment, dev_debug, async_writes)
- `src/rag_pipeline/rag_service.py` — wrap `ask()` and `ask_comparative()` with logging
- `src/rag_pipeline/agentic_service.py` — wrap `ask()` with logging; sub-queries logged with parent_query_id
- `src/api/services/streaming_wrapper.py` — wrap `generate_stream()` and `generate_agentic_stream()`
- `src/api/main.py` — initialize `QueryLogger` singleton at lifespan startup
- `src/entity_graph/db.py` — table now lives alongside entity graph; share engine

### Key design: context manager pattern

The cleanest way to avoid sprinkling logging code everywhere is a context manager that captures everything during the query lifecycle:

```python
# Usage pattern
def ask(self, question, ...):
    with self.query_logger.start_query(
        query_text=question,
        interaction_mode="directory" if "report_id" in (filters or {}) else "home",
        environment=self.config.observability.environment,
        report_ids_filter=filters.get("report_id") if filters else None,
        explicit_filters=filters or {},
    ) as ctx:

        # During the query, code calls ctx.record_*() methods to attach data
        ctx.record_query_enhancement(enhancement)
        ctx.record_auto_filters(auto_filters)
        ctx.record_retrieval(retrieval_result)
        ctx.record_generation(answer, system_prompt, user_prompt, raw_response,
                            provider, model, token_usage)
        ctx.record_groundedness(groundedness_report)

        return RAGResponse(...)
    # On context exit, logger fires and writes async to Postgres
```

Why context managers:
- Centralizes the "build a row, commit it" logic
- Auto-captures latency at each phase via `ctx.start_phase()` / `ctx.end_phase()`
- Catches exceptions and records them as `success=False`
- Async write means even DB hiccups don't slow the response

### Async write strategy

Don't write inline (would add 5-15ms to every query). Use one of:
1. **Background task** via `asyncio.create_task()` after response is yielded
2. **Queue + worker** thread pool
3. **Batched writes** (queue up 50 logs, flush every 5 seconds)

Recommendation: **Option 1 (background task)** for simplicity. If write fails, log a warning but never block the response.

```python
def _async_write(query_log: dict):
    """Fire-and-forget DB write. Never raises."""
    try:
        with session_scope() as session:
            session.add(QueryLog(**query_log))
    except Exception as e:
        logger.error(f"Failed to log query: {e}")  # log to file, don't crash

# In context manager __exit__:
def __exit__(self, *args):
    log_dict = self._build_log_dict()
    asyncio.create_task(asyncio.to_thread(_async_write, log_dict))
```

### Sampling strategy

At 700 reports + many users, you might generate 10k+ queries/day. Storing every single one isn't always desirable.

Recommendation: **log everything in dev, log everything in prod for the first 3 months**, then add `observability.sampling_rate: 0.1` (10%) once you have enough baseline data. Errors and groundedness-failed queries are always logged regardless of sampling.

### Cost calculation

Build a pricing table that maps `(provider, model)` → `(prompt_per_million, completion_per_million)`. Update quarterly as providers change pricing.

```python
PRICING = {
    ("openai", "gpt-4o-mini"): {"prompt": 0.15, "completion": 0.60},   # per million
    ("openai", "gpt-4o"): {"prompt": 2.50, "completion": 10.00},
    ("anthropic", "claude-sonnet-4-20250514"): {"prompt": 3.00, "completion": 15.00},
    ("anthropic", "claude-haiku-4-5-20251001"): {"prompt": 1.00, "completion": 5.00},
    ("google", "gemini-2.5-flash"): {"prompt": 0.30, "completion": 2.50},
    # Cohere rerank: $1 per 1k searches; track separately
}

def calculate_cost(provider, model, prompt_tokens, completion_tokens) -> float:
    rates = PRICING.get((provider, model))
    if not rates:
        return 0.0
    return (prompt_tokens * rates["prompt"] / 1_000_000 +
            completion_tokens * rates["completion"] / 1_000_000)
```

### Querying logs (the payoff)

Once data is flowing:

```sql
-- Daily query volume by mode
SELECT DATE(timestamp), interaction_mode, COUNT(*) FROM query_logs
WHERE environment = 'prod' AND timestamp > NOW() - INTERVAL '30 days'
GROUP BY 1, 2 ORDER BY 1 DESC;

-- Average groundedness by interaction mode
SELECT interaction_mode, AVG(groundedness_score), COUNT(*) FROM query_logs
WHERE environment = 'prod' AND groundedness_score IS NOT NULL
GROUP BY 1;

-- Slowest 100 queries (for perf debugging)
SELECT query_text, latency_total_ms, agentic_complexity, retrieval_total_candidates
FROM query_logs WHERE environment = 'prod' ORDER BY latency_total_ms DESC LIMIT 100;

-- Daily cost by provider
SELECT DATE(timestamp), llm_provider, SUM(cost_estimate_usd) as total_cost
FROM query_logs WHERE environment = 'prod' AND timestamp > NOW() - INTERVAL '30 days'
GROUP BY 1, 2 ORDER BY 1 DESC;

-- Queries where groundedness failed
SELECT query_text, groundedness_score, final_answer FROM query_logs
WHERE groundedness_verified = false AND timestamp > NOW() - INTERVAL '7 days'
ORDER BY timestamp DESC LIMIT 50;

-- Agentic queries that bailed on iteration budget
SELECT query_text, agentic_bail_reason, agentic_total_iterations FROM query_logs
WHERE agentic_bail_reason IS NOT NULL ORDER BY timestamp DESC;
```

### Privacy

- `client_session_id`: hashed/UUID, never includes IP, name, or any PII
- `user_agent`: stored for debugging but truncate to 200 chars
- No login/auth fields (you don't have auth)
- Add a config option to disable `query_text` logging (for sensitive deployments) — defaults to enabled

### Effort

~5 days
- Day 1: Schema + model + Postgres migration
- Day 2: `QueryLogger` class with context manager pattern
- Day 3: Wire into `RAGService.ask()`, `ask_comparative()`, `AgenticRAGService.ask()`
- Day 4: Wire into streaming paths (trickier; need to capture across async event loop)
- Day 5: Cost calculator + smoke testing + verification queries

---



## Notes for execution

1. **Run prompts strictly in order.** Bridge C depends on Bridges A and D being mergeable cleanly because all three touch `rag_service.py`. If you parallelize, you'll merge-conflict.

2. **Check Postgres connection pool capacity.** Adding query log writes increases connection demand. Bump `pool_size` in `db.py` from 5 to 10 in the same PR as Bridge C.

3. **Don't enable observability sampling yet.** Log everything for the first 30 days. After that, you'll know what you actually want to keep at scale and can tune `sampling_rate`.

4. **One thing NOT to build yet**: a stats dashboard or admin UI. You'll know what charts you need only after looking at the raw data. Premature dashboards always end up showing the wrong things.

5. **After all four bridges land**: spend a week running real dev queries through the system. The observability data is your input for the eval set work that comes next.
