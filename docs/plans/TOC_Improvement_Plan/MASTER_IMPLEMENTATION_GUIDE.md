# TOC Improvement Initiative — Master Implementation Guide

## Strategy Overview

**5 items across 4 Claude Code sessions**, ordered by dependency chain:

```
Session 1 (Sonnet) ──→ Independent, run anytime
Session 2 (Sonnet) ──→ Independent, run anytime  
Session 3 (Opus)   ──→ Independent, run anytime (but highest priority)
Session 4 (Sonnet) ──→ DEPENDS on Session 3
```

**Recommended execution order:** Session 1 → Session 3 → Session 2 → Session 4

**Why this order:**
- Session 1 is a warmup — quick wins, low risk, builds confidence
- Session 3 is the highest-impact item, run it second while Opus budget is fresh
- Session 2 is independent medium work that benefits from Session 1's familiarity
- Session 4 depends on Session 3 and is the cleanup/tail-case handler

---

## Session Summary

| Session | Model | Items | Files Changed | Lines | Time Est. |
|---------|-------|-------|--------------|-------|-----------|
| 1 | Sonnet | K-Means quantile + Reranker breadcrumb | 2 existing files | ~40 | 30-45 min |
| 2 | Sonnet | Printed TOC pre-pass | 1 existing file | ~80-100 | 1-2 hrs |
| 3 | Opus | Phase 5.5 TOC Reconciliation | 1 new + 1 existing file | ~250-300 | 3-4 hrs |
| 4 | Sonnet | LLM validation for low-quality TOCs | 1 new + 1 existing file | ~120-150 | 1.5-2 hrs |

**Total: ~500-600 lines of new/modified code across 4 sessions**

---

## How to Use with Claude Code

### Before Each Session

1. Place these files in your project root (or wherever Claude Code can read them):
   - `TOC_IMPROVEMENT_CONTEXT.md` (shared context — read by ALL sessions)
   - `SESSION_N_*.md` (the specific session plan)

2. Start Claude Code with the appropriate model (Sonnet or Opus)

3. Use this prompt template:

```
Read these two files first:
1. TOC_IMPROVEMENT_CONTEXT.md — shared architecture context
2. SESSION_N_[name].md — specific implementation plan

Then implement the changes described in the session plan. 
Follow the plan closely. Ask me if anything is unclear.
After implementation, run the verification checklist at the bottom of the plan.
```

### After Each Session

1. Run the full test suite: `python -m pytest tests/ -v`
2. Check the verification checklist in the session plan
3. Commit with a descriptive message, e.g.: `feat(toc): Phase 5.5 reconciliation service`

---

## Files Included

```
TOC_IMPROVEMENT_CONTEXT.md       ← Shared context (read by every session)
SESSION_1_QUICK_WINS.md          ← K-Means quantile + Reranker breadcrumb  
SESSION_2_PRINTED_TOC_PREPASS.md ← Raw text TOC extraction
SESSION_3_PHASE_5_5_RECONCILIATION.md  ← Docling header fusion (THE BIG ONE)
SESSION_4_LLM_VALIDATION.md      ← Claude Haiku for tail cases
```

---

## Expected Impact

| Metric | Before | After (Est.) |
|--------|--------|-------------|
| TOC accuracy | ~90% | ~95-97% |
| Reports with heading Y-coordinates | ~60% | ~90%+ |
| Reports needing manual review | ~130 (10%) | ~30-50 (2-4%) |
| K-Means non-determinism | Present | Eliminated |
| Reranker hierarchy awareness | None | Full |
| New dependencies | — | None (all tools already in stack) |
| Per-report API cost (LLM validation) | $0 | ~$0.01 (tail cases only) |

---

## Rollback Plan

Every change is designed to be backward-compatible:

- **Session 1**: Quantile bucketing produces same level assignments for clear cases. Reranker breadcrumb is additive.
- **Session 2**: Printed TOC pre-pass only activates if it finds entries. Falls back to existing methods.
- **Session 3**: Phase 5.5 only improves quality scores, never decreases them (`max(current, new)`). If reconciliation produces worse results, original TOC is preserved.
- **Session 4**: LLM validation only triggers for quality < 50. Skipped entirely if no API key. Caps quality at 85 (never claims perfection).

If any session causes regressions:
1. The session's changes can be reverted independently
2. No session depends on another except Session 4 → Session 3
3. Test suite catches structural breaks immediately
