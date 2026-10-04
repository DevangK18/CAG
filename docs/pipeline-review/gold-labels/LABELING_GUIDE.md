# Gold labels: findings and recommendations

The gold labels are a hand-made answer key: every real audit finding and every real
recommendation in 6 reports, labelled from the PDF itself.

They are used to:
- measure precision and recall of Phase 9's finding and recommendation extraction, per pattern
  and per strategy;
- check the LLM validator (whether it rejects false positives without rejecting real items);
- check the monetary parser against the amount labelled for each finding;
- serve as a regression test after the fixes (later moved to `tests/` fixtures).

## Reports

| Report | Tier | Type | Pages | Labeller |
|--------|------|------|-------|----------|
| 2025_38 Blast Furnace, SAIL | Union | Performance audit | 90 | Main session |
| 2025_08 INCOIS | Union | Compliance audit | 158 | Agent |
| OD_2025_05 School Education, Odisha | State | Performance audit | 178 | Agent |
| JH_2025_02 State Finances, Jharkhand | State | State Finances Audit Report | 168 | Agent |
| BR_2024_03 Local Government, Bihar | Local | Compliance / local bodies | 226 | Agent |
| HP_2022 ATIR, Himachal Pradesh | Local | Annual Technical Inspection Report | 142 | Agent |

## Rules for labelling blind

- **Label from the PDF text only.** Do NOT open the pipeline output (`*_chunks.json`, overview,
  enrichment) before your labels are finished. Seeing what the pipeline extracted biases the key.
- **Read every page in order.** Do not skim, sample or skip pages. Note in `pages_read` any
  page you could not read (image-only, garbled).
- **Extract the text for yourself** with PyMuPDF (`page.get_text("text")`). When the layout is
  hard to follow (two columns, boxes, tables), also look at `get_text("blocks")` or render the
  page to PNG and view it.
- **Page numbers** are **physical, 0-indexed** (PyMuPDF index), because that is what the pipeline
  stores in `source_page_physical`. Also record the printed page number when one is visible.

## What is a FINDING

A finding is an audit observation, grounded in audit evidence, that states something wrong
with what the auditee did or achieved: a deficiency, irregularity, non-compliance, loss,
shortfall, delay, idle or wasted resource, weak control, or an adverse outcome.

| Include | Exclude |
|---------|---------|
| "Audit observed / noticed / found that …" paragraphs in the audit chapters | Background: scheme descriptions, organisation, budget, legal framework |
| Implicit findings: body paragraphs stating a deficiency without the cue ("Out of 45 hospitals, 12 had no fire NOC…") | Audit objectives, criteria, scope, methodology, sampling |
| Case-study paragraphs that state what went wrong | Neutral statistics and trends ("revenue receipts grew 12 per cent") |
| State Finances: adverse analytical observations (deficit above FRBM target, unspent balances, off-budget borrowing, UCs pending, persistent savings) | Management replies ("The Ministry stated (June 2024) that …") |
| Adverse restatements in the Executive Summary / Overview / Conclusion (label them, with `location` = `executive_summary` or `conclusion`) | Audit's rebuttal of a reply ("The reply is not acceptable because …"): part of the finding it answers, not a new item |
| ATIR: the deficiencies listed per inspected unit | Positive observations; recommendations (label those separately) |
| | Content found only inside tables, charts, annexures or appendices |
| | Footnotes, table and chart captions, "Source:" lines |

**Granularity.** Use one item per audit paragraph: the paragraph as numbered in the report
(e.g. 3.2.1), or, when a numbered paragraph has several distinct observation paragraphs, one per
observation paragraph. If a paragraph states two unrelated deficiencies, it is still one item;
list both in `summary`. A finding that runs across a page break is one item on its first page.

## What is a RECOMMENDATION

A recommendation is an action the audit (CAG) asks the auditee or government to take.

| Include | Exclude |
|---------|---------|
| Recommendation boxes ("Recommendation 2.2 …", "Recommendations" boxes after a section) | Rules, guidelines or Acts that "should / shall / may" (audit criteria) |
| "Audit recommends that …", "It is recommended that …", "The Ministry may consider …" | Recommendations of PAC, other committees or consultants that the report quotes |
| Passive advisory forms: "… may be ensured", "… may be increased", "… should be strengthened" | Commitments made by management in its replies |
| Consolidated recommendation chapters and the Executive Summary recommendation lists (label them, with `location` = `executive_summary`) | "should have …" in past tense (that is a finding) |
| ATIR: "The following recommendations / suggestions were made …", "The Department should pay adequate attention …" | |

**Granularity.** Use one item per recommendation: each numbered or bulleted item separately. If
the same recommendation appears in both the chapter and the Executive Summary, label both and
link the pair with `duplicate_of`.

## Output format

Write `docs/pipeline-review/gold-labels/<REPORT_PREFIX>.json`, e.g. `OD_2025_05.json`:

```json
{
  "report_id": "<full report id = PDF file name without .pdf>",
  "labeller": "agent | main-session",
  "pages_total": 178,
  "pages_read": "0-177",
  "unreadable_pages": [],
  "findings": [
    {
      "id": "F001",
      "page": 34,
      "printed_page": "21",
      "para_no": "3.2.1",
      "location": "chapter | executive_summary | conclusion | atir_unit",
      "anchor": "first 12-20 words of the finding paragraph, verbatim from get_text()",
      "text": "full paragraph text, verbatim (whitespace normalised)",
      "summary": "one line: what is wrong",
      "finding_type": "one of the pipeline taxonomy below, or null if none fits",
      "impact_amount": {"raw": "₹3.15 crore", "crore": 3.15},
      "other_amounts": ["₹25,208.86 crore (total expenditure: context, not impact)"],
      "borderline": false,
      "note": ""
    }
  ],
  "recommendations": [
    {
      "id": "R001",
      "page": 40,
      "printed_page": "27",
      "rec_number": "2.2",
      "location": "chapter | rec_box | rec_section | executive_summary | atir",
      "anchor": "first 12-20 words verbatim",
      "text": "full recommendation text verbatim",
      "addressee": "School and Mass Education Department",
      "form": "box_numbered | numbered | audit_recommends | may_consider | passive_may_be | should | suggestion | other",
      "duplicate_of": null,
      "borderline": false,
      "note": ""
    }
  ],
  "labelling_notes": "conventions or ambiguities specific to this report"
}
```

**Taxonomy for `finding_type`:** `irregular_expenditure`, `loss_of_revenue`,
`wasteful_expenditure`, `non_compliance`, `system_deficiency`, `performance_shortfall`,
`fraud_misappropriation`, `procedural_lapse`, `idle_assets`, `non_realization_of_dues`,
`incomplete_infrastructure`, `accounting_irregularity`, `fund_utilization_failure`.

**Amounts.**
- `impact_amount` is the single amount that quantifies the finding's impact: the loss, the
  irregular payment, the idle investment, the short levy. Give it as it appears, plus its value
  in crore (1 crore = 100 lakh; ₹ in lakh ÷ 100).
- Where a table header says "(₹ in crore)", the unit applies to the numbers in that table.
- Leave `impact_amount` null when the finding has no rupee impact.
- List other rupee amounts in the paragraph under `other_amounts`, with a short note on each
  (context, total, part of the impact).
- Quantities that are not money ("1.73 lakh students", "65.71 lakh sqm") are never amounts.

**Borderline items.** When you are unsure, still label the item, set `borderline: true` and
explain why in `note`. The metrics are reported both with and without borderline items.

## Adjudication (main session, after labelling)

1. Match pipeline findings to gold findings: same page ±1, and either the gold anchor (fuzzy) is
   found in the pipeline text or the texts overlap by 60% or more.
2. For every mismatch (a pipeline item with no gold match, or a gold item with no pipeline
   match), re-read the PDF page and decide whether the label or the pipeline is wrong.
   Corrections to the gold file are logged in `ADJUDICATION_LOG.md`.
3. Only then compute precision and recall.
