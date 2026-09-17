# Citation Bug Fix — Implementation Plan for Claude Code Sonnet

## Two Bugs, Priority Order

**Bug 2 (page off-by-one)**: Fix first — small, isolated, easy to verify.  
**Bug 1 (citation key mismatch)**: Fix second — touches more files, needs careful testing.

---

## Bug 2: PDF Navigation Off-by-One

### Problem
Clicking a working citation pill navigates to the page BEFORE the actual content. If a finding is on page 31, the viewer opens to page 30.

### Root Cause Chain

```
build_citations() in rag_service.py:
    page = child.page_physical + 1     # 0-based → 1-based. If page_physical=30, page=31

_convert_citations() in streaming_wrapper.py:
    page_logical = str(page)           # "31" — sent to frontend as string
    page_physical = page - 1           # 30 — comment says "Convert to 0-based for react-pdf"

Frontend PDF viewer:
    Uses page_physical to navigate → opens page 30 instead of 31
```

react-pdf's `<Page>` component uses 1-based `pageNumber`. Sending 0-based is wrong.

### Fix Steps

#### Step 1: Diagnostic — find how frontend uses page_physical

Before changing anything, search the frontend to understand how `page_physical` is consumed:

```bash
grep -rn "page_physical" frontend/src/ frontend/components/ frontend/lib/
grep -rn "pageNumber" frontend/src/ frontend/components/
```

**If you find** `pageNumber={citation.page_physical}` (no +1):
→ The backend is sending the wrong value. Fix in `streaming_wrapper.py` (Step 2A).

**If you find** `pageNumber={citation.page_physical + 1}` (frontend compensates):
→ The frontend already works around it. The off-by-one might be in the chunk metadata itself (`page_physical` stored wrong during parsing). In that case, check what value `child.page_physical` actually holds in `build_citations()`. But more likely, the frontend is NOT adding +1, so proceed with Step 2A.

#### Step 2A: Fix `_convert_citations()` in `streaming_wrapper.py`

**File**: `services/api/services/streaming_wrapper.py`  
**Function**: `_convert_citations()`

Find this line:
```python
page_physical=page - 1,  # Convert to 0-based for react-pdf
```

Change to:
```python
page_physical=page,  # 1-based page number for react-pdf <Page pageNumber={}>
```

That's it. `page` is already 1-based (set as `child.page_physical + 1` in `build_citations()`).

#### Step 2B: If frontend adds +1, fix there instead

Only if the grep in Step 1 reveals the frontend does `page_physical + 1`. In that case, EITHER:
- Remove the `+ 1` in the frontend, OR  
- Keep the backend as-is and just fix the frontend

Pick whichever is cleaner. The rule is: react-pdf needs 1-based, so exactly one conversion should happen in the chain.

#### Verification

1. Start the app, send a chat query
2. Find a citation pill that works (clickable)
3. Note the page number shown (e.g., "p.31")
4. Click it — verify the PDF viewer shows page 31 content, not page 30
5. Test with citations from early pages (p.1-3) and late pages (p.50+)

---

## Bug 1: Citation Key Mismatch — Partial Match Failure

### Problem
In the same message, some citation pills are clickable (blue) and others render as plain gray text. The console shows `lookupCitation()` failing to find keys in the normalized citation map.

### Why It's Inconsistent

The citation map keys use `parent.toc_entry` text (e.g., `"Executive Summary"`, `"3.2 Revenue Collection"`).  
The LLM writes `[Section 10, p.11]` using numeric section references from the system prompt format.

Some TOC entries happen to be numeric-looking (`"Section 10"` or `"3.2"`) and coincidentally match after normalization. Descriptive entries (`"Executive Summary"`, `"Non-Maintenance of Truck Lay-byes"`) never match the LLM's invented numbers.

### Fix Strategy

**Make the LLM copy exact citation keys instead of inventing section numbers.**

How: Label each context chunk with its exact citation key (`[Source: Executive Summary, p.11]`) and instruct the LLM to use that label verbatim as its citation. The map already uses these keys, so they match by construction.

### Fix Steps

#### Step 1: Find the context assembly method in `rag_service.py`

**File**: `services/rag_pipeline/rag_service.py`

Search for the method that builds the context string from retrieval results. It's the function that formats parent/child chunks into the text that gets sent to the LLM as context. Look for:
- A method that iterates over `retrieval_result.parents` and their `.children`
- String formatting that combines section headers with chunk content
- The result is a long string that becomes part of the user prompt or system prompt

It might be called `_build_context()`, `_format_context()`, `_assemble_context()`, or similar. Could also be inline in `prepare_generation_inputs()` or `ask()`.

The current format probably looks something like:
```python
f"[{parent.toc_entry}]\n{child.content}"
# or
f"--- Section: {parent.toc_entry} ---\n{child.content}\n"
```

#### Step 2: Add `[Source: ...]` labels to each chunk in the context

In the method found in Step 1, modify the chunk formatting to include an explicit citation key. The citation key MUST be built using the same formula as `_build_citation_map()` in `streaming_wrapper.py`:

```python
key = f"{section}, p.{page}"
```

where `section = parent.toc_entry` and `page = child.page_physical + 1`.

So in the context assembly, for each child chunk under each parent, prepend:

```python
# Build the same citation key that _build_citation_map() will use
citation_key = f"{parent.toc_entry}, p.{child.page_physical + 1}"

# Format this chunk's context block
chunk_block = (
    f"[Source: {citation_key}]\n"
    f"{child.content}"
)
```

**IMPORTANT**: The `[Source: ...]` line must appear directly above each chunk's content so the LLM clearly associates it. If there's existing section header formatting, keep it but add the source label:

```python
chunk_block = (
    f"[Source: {citation_key}]\n"
    f"[{parent.toc_entry}]\n"  # existing header, keep if present
    f"{child.content}"
)
```

**IMPORTANT**: Make sure the page number calculation here (`child.page_physical + 1`) matches EXACTLY what `build_citations()` uses. If `build_citations()` uses a different formula, copy that formula. The key is that the source label in the context and the key in the citation map must be identical strings.

#### Step 3: Update the citation format instructions in the system prompt

**File**: `services/rag_pipeline/rag_service.py`

Find the `CITATION_RULES` or equivalent section in the system prompt. It currently tells the LLM something like:

```
Cite sources as [Section X.Y, p.ZZ]
```

Replace the citation format instructions with:

```
CITATION FORMAT:
- Each source passage is labeled with [Source: ...] at the top.
- When citing information, use the EXACT text from the [Source: ...] label as your citation, wrapped in square brackets.
- Example: If a passage is labeled [Source: Executive Summary, p.11], cite it as [Executive Summary, p.11]
- Example: If a passage is labeled [Source: 3.2 Revenue Collection, p.45], cite it as [3.2 Revenue Collection, p.45]
- ALWAYS copy the source label exactly. Do NOT invent section numbers or reformat the label.
- Place each citation immediately after the specific claim it supports.
- A single sentence may have multiple citations if the claim draws from multiple sources.
- Every factual claim must have at least one citation.
```

**Key change**: The LLM is no longer asked to generate `[Section X, p.Y]` format. It copies the `[Source: ...]` label, which is the same string the backend uses as the citation map key.

#### Step 4: Verify `build_citations()` alignment

**File**: `services/rag_pipeline/rag_service.py`  
**Function**: `build_citations()`

Confirm this function builds `section` from `parent.toc_entry` and `page` from `child.page_physical + 1`. The values it produces must match what you put in the `[Source: ...]` labels in Step 2.

If `build_citations()` looks like this:
```python
citations.append(Citation(
    section=parent.toc_entry,
    page=child.page_physical + 1,
    ...
))
```

Then your source label `f"{parent.toc_entry}, p.{child.page_physical + 1}"` matches. Good.

If it uses a different field or calculation, align the source label to match.

#### Step 5: Frontend hardening — page-only fallback in `lookupCitation()`

**File**: `frontend/lib/citationUtils.ts`  
**Function**: `lookupCitation()`

Even with the backend fix, add a fallback for rare cases where the LLM paraphrases the source label. After the existing normalized lookup fails, add:

```typescript
// Fallback: match by page number only if unique
const pageMatch = raw.match(/p\.?\s*(\d+)/i);
if (pageMatch) {
    const targetPage = pageMatch[1];
    const pageMatches = Object.entries(normalizedMap).filter(([key]) => {
        // Extract page number from normalized key
        const keyPageMatch = key.match(/(\d+)$/);  // page number is typically at end
        return keyPageMatch && keyPageMatch[1] === targetPage;
    });
    // Only use this fallback if exactly one citation has this page number
    // If multiple citations share a page, we can't disambiguate
    if (pageMatches.length === 1) {
        console.log(`Citation fallback: matched "${raw}" by unique page ${targetPage}`);
        return pageMatches[0][1];
    }
}
```

**This is a safety net, not the primary fix.** The backend changes (Steps 2-3) are the real fix. This catches the remaining 5% of cases where the LLM doesn't perfectly copy the label.

#### Step 6: Consider normalizing the citation map keys for robustness

**File**: `frontend/lib/citationUtils.ts`  
**Function**: `buildNormalizedCitationMap()`

Check what the existing normalization does. It should handle case differences, extra whitespace, and minor punctuation variations. If it currently does aggressive stripping (removing "Section", reducing to just numbers), update it to preserve the full key structure but normalize whitespace and case:

```typescript
function normalizeCitationKey(key: string): string {
    return key
        .toLowerCase()
        .replace(/\s+/g, ' ')     // collapse whitespace
        .replace(/\s*,\s*/g, ',') // normalize comma spacing
        .trim();
}
```

This way `"Executive Summary, p.11"` normalizes to `"executive summary, p.11"` and the LLM's output `"Executive Summary, p.11"` normalizes to the same thing. No information is lost.

**IMPORTANT**: If the existing normalization strips too aggressively (e.g., removes all non-numeric chars), that's part of why matching fails. The normalization should preserve words, not strip them.

---

## Verification Plan

### Bug 2 Quick Check
```
1. Send any chat query
2. Find a working citation pill
3. Click it → verify PDF shows correct page (not one before)
```

### Bug 1 Comprehensive Check

**Test 1: Basic match**
```
1. Send: "What are the main audit findings?"
2. Open browser console
3. Look for: "Citation map keys: [...]"
4. Look for: "Looking up citation: ..."
5. Verify ALL lookups succeed (no "Citation not found" messages)
6. Verify ALL citation pills are clickable (blue, not gray)
```

**Test 2: Descriptive TOC entries**
```
1. Pick a report with descriptive section names (e.g., "Non-Maintenance of Truck Lay-byes")
2. Send a query targeting that section
3. Verify citations like [Non-Maintenance of Truck Lay-byes, p.45] render as pills
```

**Test 3: Numeric TOC entries**
```
1. Pick a report with numeric sections (e.g., "3.2 Revenue Collection")
2. Send a query targeting that section
3. Verify citations like [3.2 Revenue Collection, p.12] render as pills
```

**Test 4: Mixed in single response**
```
1. Send a broad query that pulls from multiple sections
2. Verify ALL citations in the response are clickable, not just some
```

**Test 5: Streaming path**
```
1. Use the chat interface (streaming endpoint)
2. Verify citation_map event arrives before tokens
3. Verify pills render correctly as tokens stream in
```

---

## File Change Summary

| File | Bug | What to Do |
|---|---|---|
| `services/api/services/streaming_wrapper.py` | 2 | Change `page_physical=page - 1` → `page_physical=page` |
| `services/rag_pipeline/rag_service.py` | 1 | Add `[Source: key]` labels in context assembly method |
| `services/rag_pipeline/rag_service.py` | 1 | Rewrite CITATION_RULES in system prompt |
| `frontend/lib/citationUtils.ts` | 1 | Add page-only fallback in `lookupCitation()` |
| `frontend/lib/citationUtils.ts` | 1 | Review `normalizeCitationKey()` — ensure it preserves words |

### Order of Implementation
1. **Bug 2** — one line in `streaming_wrapper.py`, verify with click test
2. **Bug 1 Step 1** — find context assembly method (read-only, understand the code)
3. **Bug 1 Step 2** — add `[Source: ...]` labels to context chunks
4. **Bug 1 Step 3** — update system prompt citation rules
5. **Bug 1 Step 4** — verify `build_citations()` alignment
6. **Bug 1 Step 5** — frontend fallback (safety net)
7. **Bug 1 Step 6** — review normalization function
8. **Full verification** — run all 5 test scenarios
