# Home Redesign — Backend Implementation Plan

**Scope**: All API/RAG/parsing-pipeline changes needed to power the home page redesign, smart search, entity-first browsing, and "Surprise Me." This document assumes the frontend plan in `01_frontend_implementation_plan.md` and consumes the endpoints defined here.

**Baseline assumed**: RAG Pipeline v3.2 + Phases 11/12/13 + Bridge A/B/C/D all shipped. That means agentic streaming, entity graph, groundedness, auto-filter, two-pass canonicalization, query observability are all live.

---

## 1. The shape of the change

The backend already has ~95% of what's needed. The work here is almost entirely **thin orchestration**: new routes that compose existing services, plus one small addition to `ReportInfo` and one verification pass on ministry data.

What we do NOT need to build:
- New parsing pipeline phases — N/A
- New embedding or retrieval primitives — N/A
- New Qdrant collections or indexes — N/A
- New entity extraction — Phase 12 is done

What we DO need to build:
- Two new route modules (`home.py`, `search.py`)
- One new service (`search_service.py`)
- One enrichment to `ReportInfo` (`ingested_at`)
- One ministry-to-entity reconciliation map (`ministry_aliases.json`)
- Pre-computed startup aggregates in `report_service`

That's it. Estimated 4-5 backend days total.

---

## 2. New route modules

Two new routes, registered in `api/api/main.py` alongside the existing routers.

### 2.1 `api/api/routes/home.py`

Single-purpose endpoints for the home page hero, stats, facets, featured rails, and surprise-me.

```
GET /api/home/stats       → Aggregate counts (reports, entities, mentions, findings, charts, tables, latest_ingest)
GET /api/home/facets      → All facet values (tiers, states, years, ministries, entities, audit_categories)
GET /api/home/featured    → Featured rail content (top ministries, top entities, recent reports, deep dives)
GET /api/home/trending    → Trending searches (last 7d, anonymized) — Phase B+
GET /api/home/surprise/report  → Random report
GET /api/home/surprise/entity  → Random entity weighted by mention_count
```

Implementation note: every endpoint here is a thin dispatcher. The real work happens in `report_service` (for stats/facets) and `entity_service` (for entity-related rails). All responses cached at process startup, refreshed only on registry reload.

### 2.2 `api/api/routes/search.py`

```
GET /api/search?q=<query>&type=<channel>&limit=<n>
  type ∈ { all, reports, ministries, entities, findings, glossary }
  Returns grouped results by channel
```

Single endpoint. Multiplexes to `search_service.search()` which fans out to channel-specific handlers in parallel.

### 2.3 Both routes go into `api/api/main.py`

Add to the existing `include_router` block:

```python
from .routes import home, search   # alongside existing imports
app.include_router(home.router, prefix="/api/home", tags=["Home"])
app.include_router(search.router, prefix="/api/search", tags=["Search"])
```

Update the startup log block to advertise the new endpoints. Wire rate-limiting via the existing `limiter` decorator (reuse `RATE_LIMIT_CHAT` for `/search` since it can be expensive per-call when findings channel is hit).

---

## 3. Pydantic response models

Add to `api/api/models.py`. These mirror what the frontend types in §13 of the frontend plan expect.

### 3.1 Home stats and facets

```
class HomeStats(BaseModel):
    total_reports: int
    total_entities: int
    total_ministries: int
    total_mentions: int            # entity_mentions row count
    total_findings: int
    total_charts: int
    total_tables: int
    latest_ingest: Optional[str]   # ISO timestamp from ingested_at
    year_range: tuple[int, int]    # min/max audit_year across registry

class FacetValue(BaseModel):
    value: str
    label: Optional[str]
    count: int

class HomeFacets(BaseModel):
    tiers: List[FacetValue]
    states: List[FacetValue]
    years: List[FacetValue]
    ministries: List[FacetValue]    # (entity_id, canonical_name, count)
    entities: List[FacetValue]      # top-N PSUs/schemes/etc
    audit_categories: List[FacetValue]
```

### 3.2 Featured rail content

```
class FeaturedMinistry(BaseModel):
    entity_id: int
    canonical_name: str
    report_count: int
    finding_count: int
    mention_count: int
    primary_tier: str

class FeaturedEntity(BaseModel):
    entity_id: int
    canonical_name: str
    entity_type: str
    mention_count: int
    finding_count: int
    primary_tier: str

class HomeFeatured(BaseModel):
    top_ministries: List[FeaturedMinistry]
    top_entities: List[FeaturedEntity]
    recent_reports: List[ReportSummary]   # reuse existing model
    deep_dives: List[TimeSeriesInfo]      # reuse existing model
    popular_starts: List[Union[FeaturedMinistry, FeaturedEntity]]  # 4-6 items
```

### 3.3 Search results

```
class SearchResultReport(BaseModel):
    kind: Literal["report"] = "report"
    report_id: str
    title: str
    ministry: Optional[str]
    audit_year: Optional[str]
    findings_count: int
    snippet: Optional[str] = None  # match highlight, optional

class SearchResultMinistry(BaseModel):
    kind: Literal["ministry"] = "ministry"
    entity_id: int
    canonical_name: str
    report_count: int
    finding_count: int

class SearchResultEntity(BaseModel):
    kind: Literal["entity"] = "entity"
    entity_id: int
    canonical_name: str
    entity_type: str
    mention_count: int
    primary_tier: str

class SearchResultFinding(BaseModel):
    kind: Literal["finding"] = "finding"
    chunk_id: str
    report_id: str
    section: str
    page: int
    finding_type: Optional[str]
    severity: Optional[str]
    amount_crore: Optional[float]
    snippet: str  # first ~200 chars of chunk
    score: float

class SearchResultGlossary(BaseModel):
    kind: Literal["glossary"] = "glossary"
    term: str
    abbreviation: Optional[str]
    definition: Optional[str]
    report_id: str  # which report this definition came from

class GroupedSearchResults(BaseModel):
    reports: List[SearchResultReport]
    ministries: List[SearchResultMinistry]
    entities: List[SearchResultEntity]
    findings: List[SearchResultFinding]
    glossary: List[SearchResultGlossary]
    top_hit_channel: Optional[str]    # for the smart-Enter behavior
    top_hit_score: Optional[float]
```

### 3.4 Surprise

Reuse `ReportSummary` for surprise-report. Add a new `EntitySummary` matching what `entity_service.get_entity()` returns today.

---

## 4. New service: `api/api/services/search_service.py`

This is the only new service module. It orchestrates the five channels and merges their results.

### 4.1 Public API

```
class SearchService:
    def __init__(self, registry, entity_service, retrieval_service, glossary_index):
        ...

    async def search(
        self,
        query: str,
        channel: str = "all",
        limit_per_channel: int = 5,
    ) -> GroupedSearchResults:
        ...
```

### 4.2 Channel handlers

Five private handlers, each returns one channel's results:

| Handler | Data source | Latency target | Implementation |
|---|---|---|---|
| `_search_reports()` | In-memory `report_registry.reports` | <10ms | rapidfuzz token-set ratio over `title + ministry + audit_year + report_no` concatenation |
| `_search_ministries()` | Entity graph: `entity_type='ministry'` | <30ms | Direct ILIKE on `canonical_name` and `aliases::text`, ordered by `mention_count DESC` |
| `_search_entities()` | Entity graph: all types except 'ministry' | <30ms | Same query as above without the type filter |
| `_search_findings()` | Qdrant semantic | ~200ms | Filtered call to `RetrievalService.retrieve()` with `filter={'finding_type': {'$ne': None}}`, return top-K with snippets |
| `_search_glossary()` | In-memory cross-report glossary aggregate | <10ms | Substring match on `term` and `abbreviation`, dedup by canonical term |

### 4.3 Parallel execution

`search()` runs all five handlers in `asyncio.gather()`. The slow channel (findings) runs in a thread pool via `loop.run_in_executor()` since `RetrievalService.retrieve()` is currently sync. (Same pattern as `_maybe_verify_groundedness` in `streaming_wrapper.py`.)

If the user-supplied `channel` parameter is something other than `"all"`, only that channel runs. Other channels return empty lists.

### 4.4 Top-hit determination

After all channels return, compute `top_hit_channel`:
- For lexical channels: top result's match score (rapidfuzz returns 0-100)
- For semantic findings: rerank score (typically 0-1)
- Normalize: lexical scores divided by 100; rerank scores used as-is

Whichever has the highest normalized score becomes `top_hit_channel`. Used by frontend smart Enter routing.

### 4.5 Filter semantics

The `q` parameter is freeform text. We do **not** parse it for filters at the search service level — the existing Bridge A `AutoFilterExtractor` does that downstream when `RetrievalService` is invoked. So a query like "loss of revenue Maharashtra 2023" naturally:
- Matches reports/entities/ministries lexically on token overlap
- Triggers Bridge A's state/year detection inside the findings channel
- Returns Maharashtra-2023-filtered findings + lexical matches across the corpus

This is correct behavior. Don't try to be clever and over-filter at search time.

### 4.6 Service registration

Initialize at app startup in `lifespan()`:

```python
search_service = SearchService(
    registry=get_registry(),
    entity_service=get_entity_service(),
    retrieval_service=rag.retrieval,  # the rag service exposes this
    glossary_index=build_glossary_index(),  # see §5.2
)
app.state.search_service = search_service
```

Routes pull it from `request.app.state.search_service`.

---

## 5. Pre-computed aggregates at startup

These live on `report_service` (extending the existing module) and are built once during app startup, refreshed only on registry reload.

### 5.1 New aggregates in `report_service.py`

Add these as module-level dicts, populated inside `_load_reports()`:

```
_ministry_index: Dict[str, List[str]]      # ministry_canonical → [report_ids]
_year_index: Dict[int, List[str]]          # report_year → [report_ids]
_audit_year_index: Dict[str, List[str]]    # audit_year → [report_ids]
_state_index: Dict[str, List[str]]         # state_name → [report_ids]
_audit_category_index: Dict[str, List[str]]
_recent_reports: List[ReportSummary]       # sorted by ingested_at DESC, top 20
```

Expose getters: `get_ministry_index()`, `get_year_index()`, etc. These are O(1) dict lookups.

### 5.2 Glossary aggregate

In `report_service.py`, add a startup function that loads enhanced overview data (from Phase 10's `*_overview_llm.json` files) and builds:

```
_glossary_index: Dict[str, List[GlossaryEntry]]
  # term-or-abbreviation (lowercase) → list of definitions with report_id attribution
```

Same lifecycle as the registry — built once at startup, queryable in <5ms.

### 5.3 Stats aggregator

Single function in `report_service.py`:

```
def get_home_stats() -> HomeStats:
    registry = get_registry()
    entity_service = get_entity_service()
    qdrant = get_qdrant_service()  # via rag service

    # Aggregate from registry
    total_reports = len(registry.reports)
    year_range = (min_year, max_year) computed from audit_year values

    # Aggregate from entity graph (Postgres counts, ~5ms each)
    total_entities = entity_service.count_all()
    total_ministries = entity_service.count_by_type("ministry")
    total_mentions = entity_service.count_mentions()

    # Aggregate from Qdrant (single scroll with filter)
    total_findings = qdrant.count_filtered(filter={'finding_type': {'$ne': None}})
    total_charts = qdrant.count_filtered(filter={'content_type': 'chart'})
    total_tables = qdrant.count_filtered(filter={'content_type': 'table_markdown'})

    return HomeStats(...)
```

These counts are all small integers; cache the result in memory and refresh hourly via a background task or on each registry reload. Don't recompute per request.

For the Qdrant counts, `entity_service` already does Postgres `SELECT COUNT(*)` queries; for findings/charts/tables we need a similar count helper on `qdrant_service`. If `qdrant.count_filtered()` doesn't exist, add it — it's a one-method addition using Qdrant's `count` API.

---

## 6. Adding `ingested_at` to `ReportInfo`

Two-step change.

### 6.1 Schema addition

In `services/rag_pipeline/report_registry.py`, add `ingested_at: Optional[str] = None` to the `ReportInfo` dataclass.

### 6.2 Population

In `report_registry.load_from_json_dir()`, populate `ingested_at` from one of three sources, in priority order:

1. If the source `*_chunks.json` has `metadata.processing_completed_at` (Phase 10 onwards should), use that.
2. If `*_overview_llm.json` has a `generated_at` field, use that.
3. Fall back to file mtime: `datetime.fromtimestamp(json_path.stat().st_mtime).isoformat()`.

The fallback is fragile across deployments (Docker rebuilds touch all files), so option 1 is strongly preferred. If it's missing for older reports, the parsing pipeline merge step (`merge_utils.py`) should add it on the next ingest.

### 6.3 Frontend exposure

The existing `ReportSummary` and `ReportDetail` Pydantic models in `api/api/models.py` need `ingested_at: Optional[str] = None`. Frontend won't display this directly — it's used for sorting `_recent_reports` and for the home page "latest_ingest" stat.

---

## 7. Ministry canonicalization — the one tricky piece

The capability audit flagged this; the prior assessment confirmed Phase 12 mostly solved it. But there's still a subtle bridge to build.

### 7.1 The two-name problem

- `ReportInfo.ministry` is **attribution metadata** — set during parsing, value comes from the report's title/header. Example: "Ministry of Railways", "Ministry of Road Transport and Highways", "Department of Revenue (Direct Taxes)".
- Phase 12 entity graph has `entities` rows with `entity_type='ministry'` — these are mentions in content, canonicalized across the corpus. Same ministry might appear with different `canonical_name` here than in the registry (e.g., entity-graph might have "Ministry of Road Transport and Highways" while registry says "MoRTH").

### 7.2 The bridge

Before ministry-related rails go live, run a one-off Claude batch call:

**Input**: distinct `ReportInfo.ministry` values (~50-100 strings) AND distinct ministry-type entity `canonical_name` values from Phase 12 (~50 strings).

**Output**: `data/canonical/ministry_bridge.json`:
```json
{
  "Ministry of Road Transport and Highways": {"entity_id": 234, "confidence": 0.99},
  "MoRTH": {"entity_id": 234, "confidence": 0.99},
  "Department of Revenue (Direct Taxes)": {"entity_id": 88, "confidence": 0.95},
  ...
}
```

Each `ReportInfo.ministry` value maps to an `entity_id` from Phase 12. Some won't match (department-level granularity that doesn't exist as a Phase 12 entity); leave those unmapped — frontend treats them as a flat string ministry.

### 7.3 Loading and use

Add a function `get_ministry_entity_id(ministry: str) -> Optional[int]` in `report_service.py` that does a dict lookup on the loaded bridge. Used:

1. In `home/featured` to count `report_count` per ministry entity
2. In `search/ministries` channel to expand fuzzy ministry-string matches into rich entity records
3. In the new entity page's "Reports" tab — given an entity_id, find all reports where `ReportInfo.ministry` maps to it

### 7.4 Cost

One-off Claude batch call: ~$2. Effort: half a day to run, verify, and check.

This is a **must-do before the home page ships** — without it, the "Most-referenced ministries" rail will undercount because variants of the same ministry will appear separately. The audit was right.

---

## 8. Findings snippet API — a minor refactor

The plan says "thin wrapper around RetrievalService for snippet rendering." Concretely:

In `services/rag_pipeline/retrieval_service.py`, add a method:

```
def search_findings_snippets(
    self,
    query: str,
    limit: int = 5,
    auto_filter: bool = True,
) -> List[FindingSnippet]:
    """
    Lightweight finding search that returns small result objects rather than
    full chunk assembly. Used by the home page search dropdown.
    """
```

`FindingSnippet` is a small dataclass:
```
@dataclass
class FindingSnippet:
    chunk_id: str
    report_id: str
    section: str
    page: int
    snippet: str  # first ~200 chars
    finding_type: Optional[str]
    severity: Optional[str]
    amount_crore: Optional[float]
    score: float
```

Internally this method:
1. Calls `self.retrieve(query, top_k=limit, filter={'finding_type': {'$ne': None}})` with the auto_filter pipeline still active
2. Walks the `RetrievalResult.parents` and pulls one chunk per finding (the highest-scored)
3. Truncates `chunk.content` to 200 chars
4. Returns the list

No new infrastructure. Just a different shape of the existing retrieval pipeline's output.

---

## 9. Trending searches — uses Bridge C query logs

Phase B+ feature. Adds a single SQL query against the `query_logs` table.

### 9.1 Endpoint

`GET /api/home/trending`

### 9.2 Query

```sql
SELECT
    query_text,
    COUNT(*) AS hit_count,
    MAX(timestamp) AS last_seen
FROM query_logs
WHERE
    environment = 'prod'
    AND timestamp > NOW() - INTERVAL '7 days'
    AND interaction_mode IN ('home', 'directory', 'agentic_sub')
    AND success = TRUE
    AND length(query_text) BETWEEN 5 AND 100
GROUP BY query_text
HAVING COUNT(*) >= 3   -- privacy: don't surface unique queries
ORDER BY hit_count DESC
LIMIT 10;
```

The `HAVING COUNT(*) >= 3` is the key privacy guard — never surface a query unless it's been asked by multiple people (or many times by one person; the IP-hashed `client_session_id` could be used to enforce "different sessions" but for v1 the count threshold is sufficient).

### 9.3 Sanitization

In Python, before returning, run each `query_text` through a small regex-based sanitizer to drop anything that looks like an email, phone number, or document ID. This is defensive — these shouldn't be in CAG queries — but worth doing.

### 9.4 Caching

The trending list refreshes hourly via a startup background task. Same pattern as the home stats. Don't query Postgres on every request.

---

## 10. Surprise endpoints

Both are trivial.

### 10.1 `GET /api/home/surprise/report`

```python
async def surprise_report():
    reports = get_all_reports()
    return random.choice(reports)
```

That's it.

### 10.2 `GET /api/home/surprise/entity`

```python
async def surprise_entity():
    entity_service = get_entity_service()
    # Weighted random by mention_count
    return entity_service.random_weighted_entity(min_mentions=10)
```

Add `random_weighted_entity` to `entity_service.py`. Implementation: `SELECT * FROM entities WHERE mention_count >= :min ORDER BY -log(random()) * mention_count DESC LIMIT 1`. Or fetch top 100 by mention_count and use Python's `random.choices(weights=...)`. Either works.

The `min_mentions=10` filter prevents the user from getting a one-off entity with no real coverage.

---

## 11. Auto-filter integration check

Bridge A's `AutoFilterExtractor` is wired into the agentic and home-page chat paths. Confirm it's also active for the home-page smart-search findings channel.

In `search_service._search_findings()`, call `RetrievalService.retrieve()` with `auto_filter=True` (it's the default — just don't disable it). Bridge A will detect "Maharashtra 2023" patterns in the query text and apply them as Qdrant filters before the semantic search runs.

If a user types "loss of revenue NHAI" in the home search:
1. Bridge A extracts: no state, no year, no tier (NHAI is union-implied but the regex doesn't catch it)
2. Findings retrieves loss-of-revenue chunks where NHAI is mentioned (entity match via Aho-Corasick)
3. The findings channel returns top 5

Works as-is, no new code.

---

## 12. Observability — log home page queries

Bridge C already logs queries with `interaction_mode` field. The new chat flow from the home page should set `interaction_mode='home'` (it already does for `/chat/agentic` calls). The new search endpoint should also log:

In `search.py`'s route handler, wrap the call in:

```python
async with request.app.state.query_logger.start_query(
    interaction_mode="home_search",
    query_text=q,
    style=None,
    ...
) as ctx:
    results = await search_service.search(q, type, limit)
    ctx.record_search(channel_counts={c: len(getattr(results, c)) for c in CHANNELS})
    return results
```

Add `record_search()` to `QueryLogContext` if it doesn't already exist — small extension. Logs the channel hit counts so we can later see "users typing 3-letter queries don't get findings results" or similar patterns.

---

## 13. Configuration

Two new config values in `src/core/config.py`:

```python
class HomeConfig(BaseModel):
    enabled: bool = True
    cache_ttl_seconds: int = 3600   # how long stats/featured are cached
    surprise_min_mentions: int = 10
    trending_min_count: int = 3
    trending_window_days: int = 7

class SearchConfig(BaseModel):
    enabled: bool = True
    limit_per_channel: int = 5
    findings_min_query_length: int = 3
    findings_debounce_ms: int = 300   # advisory; frontend enforces
    fuzzy_match_threshold: int = 60   # rapidfuzz cutoff (0-100)
```

Add both to `RAGConfig`. Wire feature flags so search/home can be disabled if needed for ops.

---

## 14. Dependencies

New Python packages needed:

- `rapidfuzz` — for lexical fuzzy matching. Fast, C-backed. Add to `pyproject.toml`.

That's the only new dependency. All other functionality leverages existing libraries (asyncio, sqlalchemy, qdrant_client).

---

## 15. Build order (backend perspective)

Maps to the frontend phases.

### Phase 0 — Prep (1 day)

- Add `ingested_at` to `ReportInfo` and populate it
- Add `home_search` to `interaction_mode` enum in observability
- Add `rapidfuzz` dependency
- Add `HomeConfig` and `SearchConfig` to `RAGConfig`

### Phase A — Home routes scaffold (0.5 day)

- Create empty `home.py` and `search.py` route files
- Register in `main.py`
- Stub all endpoints to return placeholder shapes so the frontend can integrate

### Phase A.5 — Ministry bridge (1 day, blocks Phase B)

- Run one-off Claude batch to generate `ministry_bridge.json`
- Verify by spot-check
- Add `get_ministry_entity_id()` to `report_service`
- Wire bridge data into the registry load step

### Phase B — Real home endpoints (1 day)

- Implement `get_home_stats()`, `get_home_facets()`, `get_home_featured()` in `report_service` (delegating to entity graph for entity-related parts)
- Add `qdrant.count_filtered()` if it doesn't exist
- Wire into `home.py`
- Implement `surprise/report` and `surprise/entity`

### Phase C — Smart search (1.5 days)

- Implement `search_service.SearchService` with all 5 channels
- Implement `RetrievalService.search_findings_snippets()`
- Wire into `search.py`
- Test latency: lexical channels under 30ms each, findings under 250ms

### Phase D — Trending and observability (0.5 day)

- Implement `/api/home/trending` with Postgres aggregate
- Add `record_search()` to `QueryLogContext`
- Background task to refresh trending list hourly

### Phase E — Polish (0.5 day)

- Tune rapidfuzz threshold by testing real queries
- Add LRU caches where helpful
- Verify all home endpoints respond in <100ms (excluding findings semantic)

**Total**: ~5 backend days end-to-end.

---

## 16. Testing checklist

For each new endpoint, verify:

| Endpoint | Test |
|---|---|
| `GET /api/home/stats` | Numbers match `SELECT COUNT(*)` from each source independently |
| `GET /api/home/facets` | Top facet values are correct; counts match `WHERE` filters on raw data |
| `GET /api/home/featured` | Top ministries' `report_count` match manual SQL count |
| `GET /api/home/surprise/report` | Returns valid `ReportSummary` from registry |
| `GET /api/home/surprise/entity` | Returns entity with `mention_count >= 10` |
| `GET /api/search?q=NHAI` | Top hit is the NHAI entity, score > 0.9 |
| `GET /api/search?q=railway+safety` | Reports + entities + findings all return non-empty |
| `GET /api/search?q=xyz123` | Empty results, 200 response, no error |

Plus: load-test the search endpoint at 50 RPS and verify p95 latency stays <300ms.

---

## 17. Things to NOT change

Same principle as the frontend plan — don't touch what's working:

- The parsing pipeline (Phases 1-10) — completely orthogonal
- The agentic loop (`agentic_service.py`) — already used by frontend's agentic streaming
- Groundedness verification (`groundedness_service.py`) — already wired
- Bridge A auto-filter (`auto_filter.py`) — used transitively
- The entity graph CLI (`src/entity_graph/cli.py`) — operator surface, not affected
- Bridge C observability (`src/observability/`) — only extension is new `record_search` method
- Existing `/api/chat`, `/api/chat/stream`, `/api/chat/agentic`, `/api/chat/agentic/stream` — unchanged
- `RAGService.ask()` and `ask_comparative()` — used as-is

---

## 18. Operational notes

### 18.1 Cache invalidation

Home endpoints cache aggregates for 1 hour by default. After a new report is ingested:

- `report_service` should expose `invalidate_aggregates()` to clear caches
- `entity_service.canonicalize` and `entity_service.index` operations should call it post-completion

For now, restarting the API process suffices — these aren't real-time. Document the invalidation step in your ingestion runbook.

### 18.2 Postgres connection budget

`/api/search` makes potentially 4 Postgres queries (entities by name, entities by alias, mentions count, glossary). With `asyncio.gather()` these run in parallel using SQLAlchemy connection pool. Default pool size is fine for early traffic; if you scale beyond 50 concurrent users, bump `pool_size` in the entity_graph DSN.

### 18.3 Rate limiting

The `/api/search` endpoint should be rate-limited. Apply the existing `RATE_LIMIT_CHAT` decorator (typically 30/min/IP). Findings channel triggers a Cohere rerank API call, which costs real money — don't let one user blow through your Cohere budget by holding down a key on the search bar.

The frontend debounce should already prevent this, but defense-in-depth.

### 18.4 Cost projection

Per home-page search hit (assuming all 5 channels):
- Lexical channels: free
- Findings channel: ~$0.001 (Cohere rerank + embedding cost)
- Total: ~$0.001 per search

At 1000 searches/day: $1/day, $30/month. Same order of magnitude as chat.

---

## 19. Open questions for backend

1. **Sector handling**: the existing `ReportInfo.sector` field will be populated for some reports and stale or `'General'` for others. We're skipping the Sector facet for v1, but should we still compute and expose it as a debug-only field for inspection? Probably not worth the time.
2. **Phase 12 entity types** — which ones go in the "Entities" search channel vs. "Ministries"? Current mapping: ministries-only for the Ministries channel, everything else (`psu`, `scheme`, `state_government`, `local_body`, etc.) for Entities. This means state governments end up in Entities, not Ministries. That's probably right but worth confirming with a few sample queries.
3. **Glossary deduplication**: if "ETC" is defined as "Electronic Toll Collection" in one report and "Energy Tariff Calculation" in another, both should surface. The dropdown should group by abbreviation and show both definitions. Confirm UI is OK rendering this — handled in frontend §6.5.
4. **Chunk metadata**: the `findings_count` in `ReportSummary` comes from `len(semantic.findings)`, not from Qdrant chunk counts. These should agree but might not if some findings didn't make it into chunks. Worth a one-time consistency check during Phase 0.

---

## 20. Summary

The home redesign is overwhelmingly a frontend project. The backend additions are:

- 2 new route files (~150 LOC each)
- 1 new service file (~250 LOC)
- ~50 LOC of additions to `report_service.py`
- 1 small `RetrievalService` method
- 1 one-off batch script for ministry canonicalization
- Schema/config additions
- 1 new dependency (`rapidfuzz`)

Total new code: ~700 LOC, 5 days. Everything else is reusing what Phases 11/12/13 + Bridge A/B/C/D already shipped.

The frontend has an order of magnitude more component work to do, but it composes cleanly with this thin backend. Both can be built in parallel; the only sequencing constraint is that Phase A.5 (ministry bridge) must complete before frontend Phase B activates real ministry rails.
