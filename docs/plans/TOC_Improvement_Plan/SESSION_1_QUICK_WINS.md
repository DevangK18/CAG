# Session 1: Quick Wins — K-Means Replacement + Reranker Breadcrumb Fix

> **Model:** Sonnet | **Estimated effort:** 30-45 min | **Lines changed:** ~40
> **Pre-requisite:** Read `TOC_IMPROVEMENT_CONTEXT.md` first

---

## Context

Two independent, low-risk fixes that each improve a specific weakness in the current system.

---

## Task A: Replace K-Means Font Clustering with Quantile Bucketing

### Problem
`scaffolding_service.py` uses sklearn's K-Means to cluster font sizes into TOC levels. This is over-engineered for 20-50 headings and introduces non-determinism (K-Means has random initialization). It also adds sklearn as a heavy dependency for a trivial classification task.

### What to do

In `scaffolding_service.py`, find the method that clusters font sizes to determine heading levels (likely in the heuristic TOC extraction path). Replace the K-Means logic with deterministic quantile bucketing:

```python
import numpy as np

def _assign_heading_levels_quantile(self, font_sizes: List[float], n_levels: int = 3) -> List[int]:
    """
    Assign heading levels using quantile-based bucketing.
    
    Replaces K-Means clustering with deterministic quantile boundaries.
    Largest fonts → level 1, smallest → level n_levels.
    
    Args:
        font_sizes: List of font sizes from detected headings
        n_levels: Number of hierarchy levels to create (default 3)
    
    Returns:
        List of level assignments (1-based, 1=highest/largest)
    """
    if not font_sizes:
        return []
    
    unique_sizes = sorted(set(font_sizes), reverse=True)
    
    # If fewer unique sizes than levels, map directly
    if len(unique_sizes) <= n_levels:
        size_to_level = {size: i + 1 for i, size in enumerate(unique_sizes)}
        return [size_to_level[fs] for fs in font_sizes]
    
    # Quantile boundaries: split into n_levels buckets
    boundaries = np.percentile(
        unique_sizes, 
        [100 * i / n_levels for i in range(1, n_levels)]
    )
    
    levels = []
    for fs in font_sizes:
        level = n_levels  # Default to deepest
        for i, boundary in enumerate(boundaries):
            if fs >= boundary:
                level = i + 1
                break
        levels.append(level)
    
    return levels
```

### Key requirements
- Keep the same method signature/return type so callers don't change
- Largest font = level 1 (chapter), smallest = deepest level
- Handle edge case: all same font size → all level 1
- Handle edge case: only 1-2 unique sizes → map directly
- Remove sklearn import if it was only used for this
- Add a brief docstring explaining the change

### Testing
- Verify with: `[14.0, 14.0, 12.0, 12.0, 10.0]` → should produce `[1, 1, 2, 2, 3]`
- Verify with: `[12.0, 12.0, 12.0]` → should produce `[1, 1, 1]` (all same)
- Run existing tests: `python -m pytest tests/ -v -k "scaffold or toc"`

---

## Task B: Reranker Breadcrumb Fix

### Problem
The embedding pipeline prepends hierarchy breadcrumbs to text before embedding (`embedding_service.py:576-596`), so dense + sparse search benefit from hierarchy context. But the rerankers in `retrieval_service.py` operate on raw `chunk.content`, so the cross-encoder sees content WITHOUT hierarchy context.

### What to do

In `retrieval_service.py`, modify both `CohereReranker.rerank()` and `BGEReranker.rerank()` to prepend hierarchy breadcrumbs before reranking.

**CohereReranker (line ~77):**
```python
def rerank(self, query, chunks, top_k):
    if not chunks:
        return []
    
    # Prepend hierarchy for better reranking context
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
    # ... rest unchanged
```

**BGEReranker (line ~112):**
```python
def rerank(self, query, chunks, top_k):
    if not chunks:
        return []
    
    pairs = []
    for c in chunks:
        prefix = ""
        if c.hierarchy:
            prefix = f"[{' > '.join(c.hierarchy.values())}] "
        pairs.append((query, prefix + c.content))
    
    scores = self.model.predict(pairs)
    # ... rest unchanged
```

### Key requirements
- Match the exact breadcrumb format used in `embedding_service.py:594-595`: `[Level1 > Level2 > Level3]`
- Only prepend if `chunk.hierarchy` exists and is non-empty
- Don't modify the chunk objects themselves (the breadcrumb is only for reranking input)
- Keep score assignment and sorting unchanged

### Testing
- This is a runtime improvement — no unit test needed
- Verify the `RetrievedChunk` model has a `hierarchy` field (it does, per `qdrant_service.py:422`)

---

## Verification Checklist

After both changes:
- [ ] `python -m pytest tests/ -v` — all existing tests pass
- [ ] No sklearn import remains if it was only used for K-Means TOC clustering
- [ ] Reranker changes don't modify chunk objects (content field stays raw)
- [ ] Quantile bucketing produces deterministic results (same input → same output every time)
