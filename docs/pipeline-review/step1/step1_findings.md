# Step 1: Output audit of the parsing pipeline, all tiers (2026-09-26)

This audit only reads. Nothing was changed in the repo or in GCS. Downloads, scripts and results are in `scratchpad/audit/`:

- Raw metrics: `step1_metrics.json` (per report), plus `preflight_all.json`, `preflight_gpu.json`, `metrics_structural.json`, `summary_number_check.json`, `table_fidelity.json` and `page_recall_*.json`.
- Parent trees for every report: `parents/*.txt`.
- Log warnings and errors grouped by template: `log_templates.txt`.
- Scripts: `scripts/`.

## Scope and method

**Corpus audited**
- **Union:** 19 reports, run 35994256570, *before today's fixes*. `2025_06` failed in that run: Docling timed out at 1800 s. The file in `processed/union/` is stale output from 2026-09-19.
- **Union after the fixes:** `2025_08`, GPU run 36194014772, in `gpu-test/`.
- **State:** OD_2025_05 and JH_2025_02, run 36167161942.
- **Local:** BR_2024_03, KA_2022_06, HP_2022 and HP_2019, run 36191270703. CG_2025_01 failed at OCR.

**Files per report**
- `*_chunks.json` and `*_overview.json`.
- In `batch_jobs/`: `summaries`, `hierarchical`, `overviews/*_overview_llm.json`, the job mapping files and `visual_extraction`.
- All four run logs, and `processed/manifest.json`.

**PDFs.** All 26 were downloaded from `raw/`. For BR, KA and HP_2019 the PDFs are under the union-style names left by the earlier tier bug, e.g. `raw/union/2024_03_...`.

**Checks run**

*Full coverage, every report:*
- `preflight_check.py`, unchanged, on every page of every report.
- A per-page recall scan: word recall below 0.85, or number recall below 0.7.
- Structural checks on all chunks: orphans, duplicate IDs, children outside their parent's pages, and consistency of metadata and stats.
- Phase 9 metrics.
- Table number fidelity: numbers in each single-page table chunk against the PDF text inside the chunk's bbox.
- Logical page number against the page number printed on the page.
- Detection of reversed and word-order-reversed text.
- Mis-nesting: a numbered header chunk sitting under a differently numbered parent.
- Summary numbers against the PDF text.
- Chart values against the text on the same page.

*Samples, sizes given with each issue:*
- Recommendation recall against numbered "Recommendation x.y" boxes (6 reports).
- A findings-recall proxy: paragraphs containing "Audit observed/noticed/found/noted", with a manual check on 2025_38.
- A DLQ page check (8 pages).
- Summary grounding, read by hand (OD, JH, KA, HP_2019, BR, 2020_16).

"Post-fix outputs" below means the 6 state/local reports plus the GPU `2025_08`. Every union finding is tagged **pre-fix**, and says whether the GPU `2025_08` output still shows the problem.

---

## Per-report scorecard

The raw values are in `step1_metrics.json`.

- **Wrong-parent headers:** numbered header chunks placed under a parent with a different number.
- **Logical-page mismatch:** share of pages where `source_page_logical` differs from the page number printed on the page.
- **Finding-cue capture:** share of "Audit observed/noticed/found/noted" paragraphs whose text appears in a finding.
- **Summary numbers not in PDF:** numbers in the five 10a summary variants that appear nowhere in the PDF text.

| Report | Tier | Pages | Parents/children | Word recall | Number recall | Reversed % | Garbage titles | Empty parents | Wrong-parent headers | Logical-page mismatch | Findings | Finding-cue capture | Findings 'other' | Recs | Findings w/ evidence | Xrefs resolved | Annex resolved | ESI cited/items | Summary numbers not in PDF | Image chunks = file path |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BR_2024_03 | local_body | 226 | 639/1719 | 0.97 | 0.97 | 0.12 | 178 | 54 | 0.0%* | 11% | 81 | 59% | 23.5% | 28 | 0 | 17/151 | 0/23 | 0/7 | 42.4% | 5 |
| HP_2019_An | local_body | 90 | 170/530 | 0.977 | 0.994 | 0.0 | 0 | 55 | 34.7% | 100% | 37 | 81% | 10.8% | 0 | 0 | 19/48 | 0/0 | 0/10 | 50.0% | 4 |
| HP_2022_AT | local_body | 142 | 286/957 | 0.973 | 0.98 | 0.0 | 0 | 117 | 21.6% | 100% | 87 | 58% | 32.2% | 0 | 0 | 45/84 | 29/29 | 0/3 | 35.0% | 4 |
| KA_2022_06 | local_body | 104 | 118/750 | 0.983 | 0.878 | 0.0 | 0 | 17 | 9.0% | 100% | 55 | 45% | 21.8% | 10 | 0 | 30/42 | 26/27 | ESI missing | 48.6% | 7 |
| JH_2025_02 | state | 168 | 205/1115 | 0.983 | 0.963 | 0.0 | 0 | 35 | 14.4% | 100% | 33 | 50% | 39.4% | 15 | 0 | 18/221 | 21/22 | 0/68 | 34.9% | 5 |
| OD_2025_05 | state | 178 | 170/1159 | 0.987 | 0.939 | 0.0 | 0 | 20 | 2.0% | 100% | 68 | 55% | 13.2% | 36 | 0 | 27/218 | 7/15 | 0/28 | 71.8% | 6 |
| 2020_16 | union (pre-fix) | 120 | 133/779 | 0.964 | 0.857 | 3.12 | 7 | 31 | 10.3% | 100% | 63 | 41% | 22.2% | 40 | 0 | 36/80 | 3/3 | 0/33 | 17.6% | 0 |
| 2022_29 | union (pre-fix) | 132 | 96/753 | 0.911 | 0.894 | 5.18 | 1 | 7 | 15.8% | 100% | 129 | 80% | 8.5% | 7 | 2 | 15/101 | 5/5 | 0/7 | 12.4% | 1 |
| 2023_07 | union (pre-fix) | 108 | 93/561 | 0.958 | 0.892 | 1.48 | 12 | 11 | 4.0% | 100% | 40 | 74% | 12.5% | 19 | 0 | 25/63 | 1/3 | 0/20 | 24.7% | 0 |
| 2023_11 | union (pre-fix) | 168 | 233/1080 | 0.947 | 0.907 | 0.38 | 60 | 61 | 7.5% | 100% | 25 | 19% | 8.0% | 11 | 1 | 57/134 | 24/40 | 0/60 | 13.8% | 0 |
| 2023_19 | union (pre-fix) | 264 | 239/1742 | 0.949 | 0.872 | 2.44 | 11 | 31 | 12.4% | 100% | 54 | 36% | 27.8% | 56 | 3 | 22/79 | 14/15 | 0/20 | 13.8% | 0 |
| 2023_20 | union (pre-fix) | 146 | 158/915 | 0.934 | 0.913 | 1.45 | 4 | 19 | 6.3% | 100% | 54 | 69% | 16.7% | 23 | 1 | 13/55 | 5/5 | 0/69 | 21.1% | 0 |
| 2024_01 | union (pre-fix) | 56 | 49/274 | 0.938 | 0.907 | 4.15 | 1 | 10 | 55.0% | 100% | 2 | 0% | 100% | 1 | 0 | 11/34 | 2/4 | ESI missing | 23.6% | 0 |
| 2024_13 | union (pre-fix) | 138 | 93/762 | 0.905 | 0.866 | 5.52 | 1 | 6 | 18.9% | 100% | 72 | 42% | 33.3% | 6 | 1 | 22/122 | 5/5 | 0/8 | 6.9% | 0 |
| 2025_03 | union (pre-fix) | 68 | 52/331 | 0.917 | 0.825 | 4.11 | 1 | 7 | 52.6% | 100% | 4 | 50% | 100% | 1 | 1 | 15/46 | 0/8 | 0/11 | 17.0% | 0 |
| 2025_04 | union (pre-fix) | 134 | 136/639 | 0.928 | 0.863 | 3.69 | 0 | 25 | 51.9% | 100% | 27 | 54% | 59.3% | 2 | 6 | 58/65 | 25/28 | 12/28 | 16.6% | 1 |
| 2025_06 | union (stale 09-19) | 426 | 407/1902 | 0.885 | 0.641 | 6.17 | 35 | 118 | 15.7% | 100% | 68 | 67% | 51.5% | 13 | 0 | 50/248 | 40/41 | ESI missing | no summaries | 23 |
| 2025_08 | union (pre-fix) | 158 | 142/795 | 0.966 | 0.857 | 2.36 | 0 | 16 | 5.3% | 100% | 29 | 64% | 69.0% | 20 | 0 | 22/46 | 0/6 | ESI missing | 32.4% | 0 |
| 2025_14 | union (pre-fix) | 136 | 99/706 | 0.902 | 0.881 | 5.39 | 0 | 11 | 20.5% | 100% | 107 | 83% | 6.5% | 12 | 0 | 24/129 | 6/6 | 0/11 | 6.7% | 0 |
| 2025_16 | union (pre-fix) | 158 | 124/682 | 0.931 | 0.903 | 2.76 | 0 | 12 | 64.3% | 100% | 43 | 48% | 55.8% | 2 | 7 | 69/83 | 24/33 | 15/27 | 22.0% | 2 |
| 2025_18 | union (pre-fix) | 68 | 36/293 | 0.944 | 0.843 | 1.43 | 0 | 7 | 66.7% | 100% | 6 | 75% | 83.3% | 2 | 1 | 15/48 | 0/9 | 0/5 | 15.1% | 0 |
| 2025_20 | union (pre-fix) | 108 | 114/760 | 0.959 | 0.89 | 2.24 | 4 | 17 | 5.8% | 100% | 13 | 15% | 7.7% | 11 | 1 | 42/98 | 5/10 | 5/16 | 11.2% | 0 |
| 2025_26 | union (pre-fix) | 162 | 140/975 | 0.94 | 0.788 | 0.95 | 1 | 10 | 8.1% | 0% | 71 | 73% | 49.3% | 23 | 0 | 35/102 | 12/12 | 0/10 | 14.8% | 1 |
| 2025_35 | union (pre-fix) | 86 | 77/479 | 0.929 | 0.748 | 4.91 | 3 | 4 | 8.5% | 0% | 21 | 30% | 14.3% | 20 | 0 | 21/36 | 0/5 | 0/28 | 18.9% | 0 |
| 2025_38 | union (pre-fix) | 90 | 67/511 | 0.901 | 0.748 | 12.35 | 2 | 7 | 10.4% | 100% | 15 | 18% | 13.3% | 11 | 0 | 22/48 | 0/0 | 0/6 | 15.8% | 0 |
| **GPU 2025_08** | union (post-fix) | 158 | 120/836 | 0.991 | 0.896 | 0.0 | 0 | 7 | 9.6% | 100% | 30 | 60% | 70.0% | 21 | 0 | 43/67 | 0/6 | 0/29 | 3.8% | 3 |

\* For BR the wrong-parent figure is 0% only because Phase 7.5 reassigned every child; see P7-01.

Preflight also found:
- **Pre-fix union:**
  - oversized chunks in 17/19 reports (up to 26 in 2025_06);
  - split-cell tables at 30–90%;
  - shifted-font lines: 2023_07 15, 2023_19 46;
  - a DLQ leak in 12/19.
- **Post-fix:** all of these are 0, except JH with 1 shifted line.

Time per phase, from the run logs:

| Run | P1–3 | P5 Docling | P6 | P9 | P10a | P10b | Total |
|---|---|---|---|---|---|---|---|
| Union, 18 reports | cached | 3 h 29 m | 16 m | 3 h 20 m | 26 m | 1 h 56 m | 9 h 29 m |
| State, 2 reports | 2 m | 47 m | 3 m | 29 m | 5 m | 1 h 32 m | 2 h 59 m |
| Local, 4 reports | 10 m (OCR timeout) | 60 m | 8 m | 15 m | 7 m | 1 h 44 m | 3 h 24 m |
| GPU, 1 report | cached | 1.3 m | 0.5 m | 1 m | 2 m | 14 m | 19 m |

Gemini calls, counted as "AFC is enabled" log lines, with the calls that failed:

| Run | P9 calls (failed) | P10a calls (failed) | P10b calls (failed) |
|---|---|---|---|
| Union | 645 (318) | 1385 (21) | 551 (166) |
| State | 63 (10) | 200 (2) | 153 (73) |
| Local | 70 (5) | 745 (6) | 151 (37) |
| GPU | 18 (0) | 63 (0) | 69 (40) |

---

## Issues by phase

Severity is judged by the effect on the quality and correctness of RAG answers. "Suspected" names a hypothesis only; Step 2 will verify it in the code.

### Run level and Phases 1–3 (manifest, triage, OCR)

**P1-01 · OCR timeout throws away a finished OCR output**
- Status: CONFIRMED from the review list, refined. Severity: **high**.
- Affects 1/5 local (CG_2025_01). The whole report is lost.
- Evidence:
  - The manifest records `failed … "OCR processing timed out after 600s"`.
  - Yet `processed/ocred/CG_2025_01_…_ocred.pdf` (57 MB) was written at 21:58:27 by pikepdf. OCR started at about 21:51 and the timeout fired at about 22:01.
  - The file has a text layer on 113 of 129 pages; the source PDF has text on 1 page.
  - The file was even uploaded to GCS, but the report was marked failed.
- Suspected: `ocr_service.py`. The timeout wraps the whole ocrmypdf run, including the Ghostscript PDF/A step (`output_type: pdfa`). An output that exists is not reused, and the timeout doesn't scale with page count.

**P1-02 · OCR failure is silent in the logs**
- Status: CONFIRMED. Severity: medium.
- Affects the local run.
- Evidence:
  - No WARNING or ERROR line anywhere.
  - The console prints `✓ OCR: 0/1 successful`, with a check mark.
  - The error appears only in the manifest.
- Suspected: `ocr_service.py:166-178`, which only appends to `task.error_log`.

**P1-03 · Runs report "success" when reports or phases failed**
- Status: CONFIRMED, broadened from "filter matching 0 reports exits 0". Severity: medium.
- Affects all 4 runs.
- Evidence:
  - Union status is `success` although only 18/19 reports went through Phase 5. The Docling timeout on 2025_06 is logged at `pipeline.log:1681`.
  - Local status is `success` with 4/5 reports.
  - Summary variants lost to 429 (P10a-02), chart extractions lost (P10b-02), and 31 LLM validations lost (P9-14) all end in `🎉 FULL PIPELINE COMPLETE!`.
- Suspected: `main.py`, the final summary and exit code; also the workflow's status write.

**P1-04 · A failed report's stale output stays in `processed/` and is marked "completed"**
- Status: NEW. Severity: **high**.
- Affects 1/19 union (2025_06).
- Evidence:
  - `processed/union/2025_06_…_chunks.json` has timestamp 2026-09-19T23:14. `processed/manifest.json` lists it as `"status": "completed", last_updated 2026-09-19T22:45`, although it failed on 09-24.
  - There is no overview or summaries file for it.
  - It is the worst file in the corpus: word recall 0.885, number recall 0.641, 120 char-reversed chunks, and all 23 image chunks are file paths.
- Suspected: manifest update in `main.py`. A Phase-5 failure doesn't override an older "completed" entry, and the old output is not quarantined.

**P1-05 · ATIRs are not detected**
- Status: CONFIRMED. Severity: medium.
- Affects 2/4 local (HP_2019, HP_2022).
- Evidence:
  - IDs are `HP_2019_Annual_Technical_Inspection_…`, not `{ST}_ATIR_{year}_…`.
  - `audit_category` is "compliance" and `report_type` is "Compliance Audit".
  - Phase 9 types them as compliance (P9-01).
  - The manifest has no audit-category column, but the titles contain "Annual Technical Inspection" or "ATI".
- Suspected: `manifest_ingestion_service.py`, the ID builder and `infer_audit_category_from_report_type`.

**P1-06 · Every manifest row is downloaded before the `--reports` filter**
- Status: CONFIRMED. Severity: low.
- Evidence: the local log reports `Ingestion complete: 8 downloads successful` for a 5-report filter.

**P1-07 · The triage cache is keyed by report ID only**
- Status: NEW. Severity: low.
- Affects all union reports.
- Evidence:
  - `raw/.cache/*_triage.json` holds only `{classification, timestamp}`, with union timestamps from 2026-09-18.
  - The union run logs `19/19 reports cached (skipping download/triage/OCR)`.
  - A replaced PDF would keep its stale classification.
- Suspected: triage cache in the manifest/triage service.

**P1-08 · Manifest data errors (the user's to fix)**
- Status: NEW. Severity: low.
- Evidence:
  - 2025_18: `report_no` is "18 of 2025", but the PDF cover says "Report No. 19 of 2025".
  - HP_2019 and HP_2022: `report_no` is null.
  - HP_2019 is "Report of 2017", yet `report_year` is 2019, taken from the publication date.

### Phases 4, 5.5 and 5.7 (TOC)

**P4-01 · The printed-contents parser breaks on three-column contents pages (Title | Para no. | Page)**
- Status: NEW. Severity: **high**.
- Affects 3/3 post-fix reports that used a printed TOC: OD, JH, BR.
- The verification score (89–100%) doesn't measure structure, so these pass.
- Evidence (PDF contents vs parent titles):
  - **The paragraph number is appended to the title.**
    - OD L2 `Audit objectives 1.2`.
    - OD L2 `Deficient infrastructure and school facilities in the 5.3 sampled schools`: the number lands inside the title.
  - **The chapter is merged with its first section.**
    - OD L1 `Chapter-1 Introduction Introduction 1.1`.
    - JH L1 `CHAPTER 2: FINANCES OF THE STATE Major changes in key fiscal aggregates vis-à-vis 2022-23 2.1`.
    - BR L1 `II COMPLIANCE AUDIT Panchayati Raj Department Fraudulent payment 2.1`.
  - **Sections are promoted to L1.**
    - BR L1 `Organisational setup of PRIs 1.2`, `Functioning of PRIs 1.3`, and so on.
    - JH L1 `Total Liabilities 1.6`.
  - **A wrapped line is attached to the next entry.**
    - JH's printed contents (p.5–6) say "Appendix 2.3 Summarised financial position … as on 31.03.2024" and "Appendix 3.1 Details of cases where supplementary provision (₹ 0.50 crore …) proved unnecessary".
    - The parents read `Appendix 2.3 as on 31.03.2024 Details of cases where supplementary provision` and `Appendix 3.1 (₹ 0.50 crore or more in each case) proved unnecessary`.
    - So every multi-line appendix title from 2.3 to 3.10 is shifted by one line.
    - BR has `Management Segregation, Collection and Transportation 5.5 of Municipal Solid Was`.
  - **A running header is glued into an entry.** BR L1 `Audit Report (Local Government) for the year ended March 2022 Reference to Parag`, which is where 5.3 "Accounting procedure…" should be.
- Suspected: `printed_toc_parser.py`, `parse_printed_toc`, which joins lines and places the para-no. column.

**P4-02 · PDF-merger bookmarks are accepted as the TOC**
- Status: NEW. Severity: **high**.
- Affects 2/4 local (HP_2022, KA). The preflight `garbage_titles` check reports 0 for both.
- Evidence:
  - HP_2022 parents: `ATIR 2017-19_HP_English_Cover`, `1 Cover pages`, `2 TOC`, `4 Overiew HP ATIR`, `5 Chapter 1 HP ATIR`, `Binder1.pdf`, `Blank Page`. Eleven of these are L1 on page 2, and 10 are empty.
  - KA L1s: `1. Nagarothana Front Page English`, `3. Table of Contents`, `Blank Page` (twice), `10. Appendix Median`, `11. Appendices`, `12. Glossary`.
  - BR's junk bookmarks (`Audit Report of Local Government COVER.pdf`) were rejected correctly.
- Suspected: `scaffolding_service.py`, bookmark quality scoring against `bookmark_quality_threshold`; and `toc_quality.is_garbage_title`, which lacks patterns for file names, "Blank Page" and "N TOC".

**P4-03 · Duplicate chapter parents**
- Status: NEW. Severity: medium.
- Affects 6/6 state and local reports, and GPU 2025_08 in part.
- Evidence:
  - OD: `Chapter 3 Access to Education` appears three times (p.36–38, 38, 38–61), as do Chapter 5 and Chapter 6. The printed-TOC entry, the Docling header and the chapter banner are all kept.
  - HP_2022: `CHAPTER-1 PROFILE OF PANCHAYATI RAJ INSTITUTIONS` ×2, and CHAPTER-3 and CHAPTER-4 ×2.
  - KA: `6.Chapter 1-Introduction` plus `Chapter-I`, and likewise for II and III.
  - JH: `Chapter-1 OVERVIEW` plus `CHAPTER 1: OVERVIEW Profile of the State 1.1`.
  - HP_2019 splits one chapter title over three L1s: `Chapter-1` / `Profile of Panchayati Raj` / `Institutions`.
- Suspected: `toc_reconciliation_service.py`, the dedup and merge of Phase 4 with Docling headers.

**P5.5-01 · Phase 5.5 turns non-headings into sections**
- Status: CONFIRMED, refined. Severity: **high**.
- Affects all post-fix reports.
- Entry growth: HP_2022 26→291, HP_2019 21→170, KA 22→122, OD 55→170, JH 91→205, GPU 2025_08 10→120.
- What gets promoted:
  - **Recommendation boxes.** OD has 15 parents like `Recommendation 2.2`, most with n=0. Real sections are then nested under them: `2.2.1–2.2.5` sit under `Recommendation 2.1`.
  - **Epigraphs.** OD L2 `“A child without education is like a bird without wings.” —Tibetan Proverb`.
  - **Paragraph openings and list items.** BR `The Solid Waste Management Rules, 2016, enjoined U`, `ii According to this State Policy…`.
  - **Finding lead sentences.** HP_2022 `(a) Due to ineffective monitoring, revenue of ₹11.80 crore…`; HP_2019 `Seventy eight GPs did not realise house tax of \` 22.80 lakh…`.
- Result:
  - Empty parents: HP_2022 117/286 (41%), HP_2019 55/170, BR 54, JH 35, OD 20.
  - The log arithmetic doesn't add up: "Supplemented: +305 headers" yet 26→291.
- Suspected: `toc_reconciliation_service.py`, the supplement/merge path; Docling `section_header` labels are accepted without a heading test.

**P5.5-02 · Reconciled TOC quality is a constant, so the "keep Phase 4" guard doesn't really work**
- Status: CONFIRMED, refined. Severity: medium.
- Affects 26/26 reports.
- Evidence:
  - The reconciled score is 85 for 25 reports and 80 for JH.
  - The supplemented TOC was adopted even when Phase 4 scored higher: OD 99→85, HP_2019 100→85, GPU 2025_08 100→85, 2025_04 94→85, 2025_16 94→85, 2024_01/2025_03/2025_18 93→85.
  - Only BR (91→85) logged `kept_phase4`, so the guard applies to one mode only.
- Suspected: `toc_reconciliation_service.py`, the quality scoring and mode selection.

**P5.7-01 · Phase 5.7 LLM TOC validation never runs**
- Status: NEW. Severity: medium.
- Affects 26/26 reports.
- Evidence: all four runs log `✓ LLM Validation: 0 validated, N skipped`. The gate uses the reconciled score, which is always 85 (P5.5-02). So even BR, JH, OD, HP and KA, with the broken structures above, were never validated.
- Suspected: the Phase 5.7 gate in `main.py` or `llm_toc_validator`.

### Phases 5 and 6 (layout, content extraction)

**P6-00 · The union corpus in GCS is pre-fix output with known text defects**
- Status: CONFIRMED. Severity: **high**.
- Affects 19/19 union reports. Fixed in GPU 2025_08, so the union corpus needs a re-run.
- Pre-fix preflight results:
  - word recall 0.885–0.966 and number recall 0.641–0.913;
  - char-reversed chunks 0.38–12.35%;
  - shifted-font lines: 2023_07 15, 2023_19 46;
  - split-cell tables 30–90%;
  - oversized chunks in 17/19;
  - DLQ leak in 12/19;
  - missing chapters in 2023_11 (9), 2024_13 (3) and 2025_08 (3);
  - garbage parent titles such as `5HSRUW\x03RI…` (font-shifted) and `(Paragraph 3.2, Page no. 11)`.
- Post-fix GPU 2025_08: everything is ok except number recall 0.896 (WARN).

**P6-01 · Text rotated on portrait pages is still reversed after the fixes**
- Status: NEW, refining the earlier fix. Severity: **high**.
- Affects 2/6 post-fix state/local reports (BR, KA). Pre-fix union has the wider version (P6-00). GPU 2025_08 is clean because its rotated pages are landscape pages.
- Evidence:
  - The affected pages have `page.rotation=0`, a portrait rect, and all text lines in direction `(0,-1)`.
  - **BR, p.169–219 (appendix tables):**
    - 6 table chunks are char-reversed, e.g. p.175 `| skrameR | 81-7102 tegduB | -od- |` against the PDF's "Remarks … Budget 2017-18".
    - 41 header and paragraph chunks have their word order reversed, e.g. p.170 `2022 March ended year the for Government) (Local Report Audit` and p.175 `46) Page Appendix-5.2Paragraph-5.2.1, (Refer:`.
    - Table number recall is 0.01–0.18 on p.175, 176, 194, 199, 207, 216, 217 and 219.
  - **KA, p.79, 80 and 90:** 9 word-order-reversed chunks, e.g. `lakh) in (₹` and `(SBI) repayment loan for KWSPFT by excess in demanded amount of details Month-wise`. Table number recall is 0.0 on p.79/80 (`pdfplumber-text_fallback`).
  - The preflight checks miss this: `reversed_pct` is 0.12 for BR, and there is no word-order check.
- Suspected:
  - `extractors/text_repair.py`: rotation detection keys on page rotation or landscape, not on the line `dir`.
  - `pdfplumber_table_extractor` gets no derotation.

**P6-02 · A page is dropped when multi-page tables are merged**
- Status: NEW. Severity: medium.
- Affects: GPU 2025_08 (post-fix); pre-fix 2023_19 and 2025_06.
- Evidence:
  - GPU log: `[table_141_67_70_merged] Missing pages detected: {145} in range 141-146`. Part 5 has `source_pages [144, 146]`, and p.145 has word recall 0.63: the INCOIS sub-project table rows for "Kerala … Kozhikode" are missing.
  - The union log shows the same for 2023_19 (p.93, 211, 228, 235, 246, 252) and 2025_06 (p.136, 145, 147).
- Suspected: `multi_page_table_handler.py`. A gap page is logged but not extracted on its own.

**P6-03 · Split merged tables repeat the first data row and leave one-row fragments**
- Status: NEW, a regression after the fixes. Severity: low–medium.
- Affects all 7 post-fix outputs: BR 3, HP_2019 3, HP_2022 3, KA 4, JH 6, OD 2, GPU 4. None in pre-fix union.
- Evidence (HP_2022, `table_109_71_126_merged`):
  - Parts 1, 2 and 3 all start with row `1. | Nor | Nirmand | Kullu | 0.39`, repeated as header context.
  - Part 3 (p.111, `source_pages [111]`) holds only the header, that row and `Total 42.67`. Page 111's real rows (51–62…) are in part 2.
  - A reader or retriever sees a 1-row table whose total doesn't match it.
- Suspected: the table part splitter (`multi_page_table_handler.py`, or the chunking of oversized tables). `num_header_rows` includes the first data row.

**P6-04 · Table captions and titles are generic or wrong**
- Status: NEW. Severity: medium–high. This is also the root of P9-08.
- Affects 26/26 reports.
- Evidence:
  - Registry `caption` is `Table on page N` for nearly every table (OD 85/85, BR 109/109, GPU 40/40).
  - `structured_data.title` is usually a section heading, a running header or an unrelated paragraph:
    - GPU: 4 tables titled `Report No. 8 of 2025`;
    - BR: 17 tables titled `8 Efficiency in redressal of customer complaints: Awareness among households…`;
    - HP_2022: 13 titled `Municipal Corporations`;
    - JH: 6 titled `Appendix 3.7 above) was made but no expenditure was incurred`.
  - Titles starting with "Table x.y" or "Appendix": OD 11/85, JH 27/128, BR 1/109, HP_2022 1/131, GPU 0/40.
  - The real caption is a separate paragraph chunk, e.g. OD p.35 `Table 2.7: Short release of Central share (₹ in crore)`.
  - Phase 10c logs `Titles enriched: 312`, but the registry captions are unchanged.
- Suspected: `assembly_service` builds the visual registry; caption binding in `content_extraction_service`; and `visual_post_processor`, whose title writes don't reach the registry.

**P6-05 · Chart values are not in any embeddable text**
- Status: NEW. Severity: medium.
- Affects the post-fix reports that have charts (JH, OD, GPU, KA).
- Evidence:
  - `image_caption` content is one sentence ("Comparison of budgetary provision versus actual expenditure…"). The series values sit only in `structured_data`.
  - Pages dominated by charts lose number recall: JH p.31 0.38, p.38 0.34, p.88 0.42; OD p.22 0.36 (Chart 1.1 values 15737.21, 17388.09 … missing), p.53 0.45; GPU p.32 0.39.
  - The chart values themselves are mostly right on vector charts (JH 298/335 match page text, OD 183/220). They just can't be retrieved.
- Suspected: `gemini_visual_extractor`, or the 10c hydration step, which doesn't write series into `content` ("Charts hydrated: 18").

**P6-06 · Photo chunks hold a local file path as their content**
- Status: NEW, a regression after the fixes. Severity: medium.
- Affects all 7 post-fix outputs: BR 5, HP_2019 4, HP_2022 4, KA 7, JH 5, OD 6, GPU 3. Pre-fix union is ≤2 per report, but stale 2025_06 has 23/23.
- Evidence:
  - The content is `data/extraction_images/charts/OD_2025_05_…_picture_p0_204_70.png`, with `extraction_method: image-crop-for-gemini` and `visual_subtype: photo`.
  - The registry entry for the same image says `visual_subtype: "chart"` and uses the path as its `caption`.
- Suspected: `gemini_visual_extractor`. Items skipped as "signature/emblem/icon" (logged `skipped 5 … images`) keep their placeholder content instead of being dropped.

**P6-07 · Photos and banners are sent to chart extraction, producing noise chunks and wasted calls**
- Status: NEW. Severity: medium, for cost and noise.
- Affected, approximately by regex (±10%): BR ~86/103 image chunks, 2025_20 31/46, OD 23/51, 2023_07 14/21, KA 6/19.
- Evidence:
  - OD p.20 `Header banner for 'Chapter 1 Introduction' containing no graphical chart data.`
  - KA p.61 `Section header banner denoting Chapter-IV: Monitoring.`
  - The local 10b ran 114 "charts", mostly BR site photos, over 1 h 44 m.
- Suspected: `gemini_visual_extractor`, the pre-filter; Docling picture classification.

**P6-08 · The Phase 6 figure and table counters are wrong**
- Status: CONFIRMED and extended. Severity: low.
- Affects all runs.
- Evidence: `✓ 1723 blocks (113 tables, 0 figures)` for BR, which has 103 figures, and the corpus line `Tables: 0 Figures: 0`.
- Suspected: `main.py:899-904`, plus the corpus-total aggregation.

**P6-09 · M2-DLQ entries are almost all noise**
- Status: CONFIRMED. Severity: low.
- Affects all runs. Union logs 479 `M2-DLQ` warnings; post-fix DLQ counts are GPU 31, OD 44, JH 35, BR 40.
- Evidence:
  - Every entry has `reason: no_fragment_extracted` and `section_id: "temp"`.
  - DLQ pages with a ≥3-row pdfplumber table: OD 8/44, JH 6/35, BR 2/40, GPU 13/31.
  - A sample of 8 of those (OD 51, 64, 85; GPU 30, 40, 44; JH 48, 123) were all charts, photo grids or boxed text. No real table was lost.
- Suspected: `multi_page_table_handler.py:305-334`.

**P6-10 · Normal extraction fallbacks are logged at ERROR, and banners reach Tier 3**
- Status: CONFIRMED, refined. Severity: low.
- Evidence:
  - The union log has 139 ERROR lines `Native PDF: pdfplumber failed, using Docling`.
  - Every post-fix Tier-3 `saving for Gemini` page (OD p.20, JH p.20, KA p.61) is a chapter banner that Docling labelled as a table. The union page was not checked.
- Suspected: `content_extraction_service.py`.

**P6-11 · The rupee sign survives as a backtick in chunk text**
- Status: NEW. Severity: low–medium.
- Affects HP_2019 (187 occurrences) and pre-fix union 2020_16 (373), 2023_19 (324) and 2024_13 (711).
- Evidence:
  - HP_2019 parent `Material of \` 1.40 crore was not accounted for…`.
  - Money extraction copes (0 findings lost their amount), but the content shown to users and matched by BM25 says "`" instead of "₹".
- Suspected: `extractors/text_repair.py`, with no Rupee-font glyph mapping.

**P6-12 · Footnotes are never linked**
- Status: NEW. Severity: low–medium.
- Affects 26/26 reports (`footnote_index` is `{}` everywhere).
- Evidence:
  - Footnotes become tiny standalone chunks: GPU `13 World Meteorological Organisation.`, `35 Hybrid Coordinate Ocean Model.`
  - Footnote markers stay glued to amounts: BR `₹ 1.14 crore36 5`, GPU finding `₹4.57 crore41), fitted…`.
  - Footnotes are extracted as findings: 2022_29 `30 Includes 194 cases…`, OD `58 Out of the total bicycle incentive…`.
- Suspected: the footnote detector in `content_extraction_service` or `assembly_service`.

### Phases 7 and 7.5 (chunking, hierarchy)

**P7-01 · Phase 7.5 duplicates parents and wrecks BR's hierarchy**
- Status: NEW. Severity: **critical**.
- Affects 1/1 report where 7.5 ran (BR). It logged `Hierarchy Enrichment: 1 enriched, 3 skipped`; union and state had 0.
- Evidence:
  - **Duplicate IDs.** BR has 639 parents but only 329 unique `chunk_id`s. 268 IDs are duplicated, up to ×5: `…parent_L3_1_1_1_609201ed` "1.1.1 State Profile" ×5 and "1.1 Introduction" ×4.
  - **A fake L1 swallows the report.** A synthetic L1 `Corporation` spans p.5–214, and 1,645/1,719 children have `hierarchy.level_1 = "Corporation"`.
  - **Page ranges are wrong.**
    - Sub-parents get single-page ranges, so 611 children fall outside their parent's pages.
    - Chapter IV content (`CHAPTER - IV COMPLIANCE AUDIT`, p.61–63) sits under `3.8.6 Impact of Audit` [59,59].
  - **List items become parents.** `ii For the aforesaid period…` and `iii For the purpose of segregation…` are L3 parents, each twice.
  - Log: `Added 581 sub-sections, updated 1681 child assignments … fixed 1634 child↔parent mismatches`. Section detection ran in overlapping batches ("Detected 33 sections", "Detected 34 sections"…), and each batch re-added the same sections.
  - Downstream, Phase 10a produced 525 hierarchical summaries for BR, 434 of them at "chapter" level.
- Suspected: `hierarchy_enricher.py`, with no dedup across batches, a synthetic L1, and wrong page-range propagation. Also check its trigger condition.

**P7-02 · Section content attached to the wrong parent**
- Status: NEW. Severity: **high**.
- Affects: 6/7 post-fix outputs above 2%, and pre-fix union up to 67%.
- Share of numbered header chunks whose parent carries a different number:

| Report | Share |
|---|---|
| HP_2019 | 34.7% |
| HP_2022 | 21.6% |
| JH | 14.4% |
| GPU 2025_08 | 9.6% |
| KA | 9.0% |
| OD | 2.0% |
| 2025_18 (pre-fix) | 66.7% |
| 2025_16 (pre-fix) | 64.3% |
| 2024_01 (pre-fix) | 55% |
| 2025_03 (pre-fix) | 52.6% |
| 2025_04 (pre-fix) | 51.9% |

- Examples:
  - HP_2019 p.15: header `1.4` sits under parent `1.3.2 Institutional arrangements…`.
  - JH p.92: header `3.4` sits under `3.3.3 Major policy pronouncements…`.
  - GPU p.50: `3.2.3` and `3.3` sit under `3.2.2 Procurement and Deployments under Monsoon…`.
- A RAG answer then cites the wrong section, and the parent context is wrong.
- Suspected: `chunking_service.py`, which assigns children to parents by page and `start_y_position`. It has boundary off-by-one errors when a heading shares a page with the previous section, made worse by the bad TOC positions from P4-01 and P5.5-01.

**P7-03 · Parents are fragmented and heading-only**
- Status: CONFIRMED, refined. Severity: medium–high.
- Affects all post-fix outputs.
- Evidence:
  - Parents with ≤2 children: HP_2022 58%, HP_2019 57%, BR 41%, JH 35%, GPU 22.5%.
  - Header chunks as a share of children: HP_2019 196/530 (37%), HP_2022 281/957, OD 175/1159.
  - Parents with 0 children: HP_2022 117, HP_2019 55, BR 54, JH 35, OD 20.
  - Assembly logged `P2-19: Removed 5 empty artifact parents` for HP_2022, yet 117 remain.
- Suspected: the result of P5.5-01 and P4-02. Also the `assembly_service` P2-19 filter.

**P7-04 · Captions, sources and footnotes are split into tiny chunks**
- Status: NEW. Severity: low.
- Affects all reports. Non-header chunks under 40 chars: BR 44, OD 34, HP_2022 29, JH 23, GPU 18.
- Examples: `Table 1.4 Standing Committees in PRIs` separated from its table; `(Source: Records of test-checked ULBs)`; `(Figures represent percentage)`.
- Suspected: `chunking_service.py`, with no merging of captions and sources into their table or figure.

**P7-05 · `processing_stats` parent count is stale after artifact removal**
- Status: NEW. Severity: low.
- Evidence: HP_2022 stats say 291 but the file has 286; KA stats say 122 but the file has 118.
- Suspected: `assembly_service`, which applies P2-19 after computing stats.

### Phase 8 (assembly, metadata)

**P8-01 · Parent chunks always carry `audit_category: "compliance"`**
- Status: NEW. Severity: medium.
- Affects the 13/26 reports whose category is performance or financial, including OD, KA, JH and all union PA/FA reports.
- Evidence: OD report metadata and children say "performance", but all 170 parents say "compliance". JH says "financial" and its parents say "compliance".
- A metadata filter in RAG would drop the parents.
- Suspected: `chunking_service` or `assembly_service` sets a parent default and never propagates the real value.

**P8-02 · Metadata fields are always empty or placeholders**
- Status: NEW. Severity: medium.
- Affects 26/26 reports.
- Evidence:
  - `department` is null in 26/26 and `report_subtype` null in 26/26.
  - `ministry` is "Unknown" in 6/6 state and local reports; the corpus summary says "FINDINGS BY MINISTRY: Unknown: 260 findings".
  - `content_summary` is null on every parent, even though `batch_jobs/hierarchical/*` holds summaries whose `parent_chunk_id`s match the current parents: OD 87/87, JH 99/99, GPU 57/57.
  - `report_metadata.processing_status` stays "chunking_complete" after Phases 9 and 10.
  - `page_range_logical` mixes int and str (`[2, '7']`).
  - The overview has no summaries.
- Suspected: `assembly_service`, and the absence of a merge step for the batch outputs.

**P8-03 · `source_page_logical` is just physical+1, not the printed page**
- Status: NEW. Severity: medium–high, because every page citation is affected.
- Affects 23/26 reports, where it mismatches the printed number on 100% of pages. BR matches 89%; 2025_26 and 2025_35 match 100%.
- Evidence: OD p.22 prints "3" (Chapter 1, page 3) but the chunk logical page is "23". GPU p.4 prints "i" but logical is "5".
- Consequence: citations won't match the page numbers readers see, or that the report's own cross-references use ("Paragraph 3.2, Page no. 11").
- Suspected: the logical-page mapping in `scaffolding_service` or `assembly_service`, which works only when a page-label or offset source exists.

**P8-04 · `processed/manifest.json` has a stale header and is shared across tiers**
- Status: CONFIRMED. Severity: low (infra).
- Evidence: `generation_timestamp` is still 2026-09-19 while entries run to 09-26, and all three tiers share one file.

### Phase 9 (semantic enrichment)

**P9-01 · Recommendations: numbered boxes are missed, ATIR recommendations are missed, and duplicates and false positives appear**
- Status: CONFIRMED, refined. Severity: **high**.
- Affects OD, JH, KA, HP ×2 and GPU post-fix, and union pre-fix.
- Evidence:
  - **"Recommendation x.y" boxes phrased with "may" are missed.** Box recall, sampled on 6 reports:
    - OD 15/24 captured. Missed: `2.2 In view of large scale shortages … may be increased`, `2.3 Efficient utilisation … may be ensured`, `6.1 The Department may take steps…`.
    - 2023_07 11/21 (pre-fix).
    - 2025_06 6/37 (stale).
    - 2025_35 9/10 (pre-fix).
    - OD has `structural=0`, although 15 boxes even became parents (P5.5-01).
  - **ATIRs have 0 recommendations.** HP_2019 has "The following recommendations were made: i. Income and expenditure … may be shown … ii. Reference to rules may be given…". HP_2022 has "The Department should pay adequate attention towards compliance…".
  - **`rec_number` is null** for OD's 15 recs that start with "1.", "5." and so on, all `extraction_strategy: verb`.
  - **Executive-summary and chapter copies aren't linked or deduped.** OD has 15 duplicate texts.
  - **False positives.** 5 of OD's 21 chapter-level recs:
    - p.26 `This Chapter focuses on the process of Planning…`;
    - p.56 `The State had neither notified the neighbourhood norms…`;
    - p.68 `Paragraphs 5.5.5 and 5.5.6 of SSIF stipulate…`;
    - p.73;
    - p.128 `The guidelines issued by OSEPA stipulate that uniforms should…`.
- Suspected: `enrichment/recommendation_extractor`. The structural strategy doesn't use "Recommendation x.y" headers, and the verb patterns lack "may".

**P9-02 · Findings recall is low, especially in performance audits**
- Status: NEW. Severity: **high**.
- Method: a proxy measure, the share of "Audit/We observed|noticed|found|noted" paragraphs whose text appears in a finding. 2025_38 was checked by hand.
- Results:

| Report | Captured |
|---|---|
| OD | 57/104 (55%) |
| KA | 17/38 (45%) |
| BR | 44/74 (59%) |
| HP_2022 | 7/12 (58%) |
| GPU 2025_08 | 15/25 (60%) |
| 2025_20 (pre-fix) | 4/26 (15%) |
| 2025_38 (pre-fix) | 6/34 (18%) |
| 2023_11 (pre-fix) | 8/43 (19%) |
| 2025_35 (pre-fix) | 9/30 (30%) |
| 2024_01 (pre-fix) | 0/9 |

- Examples of missed findings:
  - 2025_38 p.31: `Audit observed that the consumption of iron ore lump more than the norm was mainly due to…`.
  - 2025_35 p.31: `Audit noted that NLC India dumped overburden in Mine-II upto 120 metre…`.
- Phase 9 code wasn't changed by today's fixes, so union results should carry over.
- Suspected: `enrichment/finding_extractor`, or a pattern set, cap, or dedup that drops candidates; the LLM-validation filter (JH "13 invalid findings filtered … 33 remaining").

**P9-03 · Finding type "other" is overused**
- Status: CONFIRMED. Severity: medium.
- Share typed "other":
  - GPU 2025_08 70%;
  - pre-fix: 2025_16 56%, 2025_04 59%, 2025_06 52%, 2025_26 49%, 2024_01 and 2025_03 100%, 2025_18 83%;
  - post-fix JH 39% and HP_2022 32%.
- Examples from GPU:
  - `INCOIS lacked a comprehensive physical access control system for data centers…` → other; it is a system deficiency.
  - `three major equipment … remained idle` → other; it is idle assets.
- Suspected: the finding classifier's pattern tables.

**P9-04 · Severity simply tracks the summed amount**
- Status: NEW. Severity: medium.
- Evidence:
  - JH: 29/33 findings are critical; they are context amounts from state finances.
  - 2025_16: 40/43 critical.
  - GPU 2025_08: 0 high or critical. The IT-security finding is "low", and `₹3.15 crore sub-projects … closed mid-way` is "medium".
  - OD: 55/68 low.
- Suspected: the severity scorer.

**P9-05 · Money figures are wrong: nested amounts summed, counts read as rupees, and unit naming**
- Status: NEW. Severity: **high**, because these figures reach overviews and summaries.
- **Nested amounts are summed.**
  - JH finding: "total expenditure of ₹25,208.86 crore … of which ₹15,668.71 crore … ₹8,603.74 crore" gives `total_amount_inr` 49,481.31 crore.
  - JH "total savings ₹32,744.35 crore … ₹25,822.15 crore … ₹6,922.20 crore" gives 65,756 crore.
  - Ratio of summed total to the per-finding maximum: HP_2019 1.83, HP_2022 1.77, JH 1.57, 2025_18 2.33, 2025_03 1.95.
- **Report totals are absurd:**
  - 2025_04: ₹80,17,690 crore;
  - 2025_16: ₹25,39,181 crore;
  - 2023_19: ₹9,45,856 crore;
  - JH: ₹3,89,445 crore.
  - Summaries repeat them: the 2023_07 executive summary says "40 findings with a cumulative monetary impact of ₹2,522.78 Crore".
- **Quantities are parsed as money.**
  - OD: 26 values, e.g. `1.73 lakh (six per cent) students` gives ₹17.3 lakh; `1.40 lakh and 3.02 lakh students`.
  - 2025_20: 11 values, e.g. `24.53 lakh certified candidates`.
  - 2025_26: `65.71 lakh sqm`.
  - 2025_14: `4.98 lakh sq. ft.`
- **Unit naming.** The `normalized_inr` and `total_amount_inr` fields hold **paise**: `₹ 13,499.10 crore` is stored as 13,499,100,000,000. The `_crore` fields are correct. Any consumer trusting the field name is 100× off.
- Suspected: `enrichment/monetary_extractor`, which has no ₹/Rs guard for lakh or crore, no containment logic, and misleading field names.

**P9-06 · Evidence links are always empty**
- Status: CONFIRMED. Severity: medium.
- Affects 7/7 post-fix outputs with 0 each. Pre-fix union has 0–7 per report (2025_16 7, 2025_04 6, 2023_19 3).
- Suspected: the evidence linker. It probably needs table and annexure resolution, which fails (P6-04, P9-09).

**P9-07 · Executive-summary index: citations, coverage and item types**
- Status: PARTLY DISPROVED, refined. Severity: medium.
- **Disproved for OD and JH.** Their executive summaries contain no paragraph references (0 found in pages 12–20 and 12–18), so 0 citations is correct.
- **Confirmed where references exist:**
  - GPU 2025_08 has 5 `(Paras 2.1.1, 2.1.2, 2.2 and 2.3)` references and 0 citations; the plural "Paras" is not matched.
  - 2023_11 has 56 `(Paragraph 3.2, Page no. 11)` references and 0 citations; they also became garbage parent titles.
  - BR has 9 `(Paragraph 2.1)` references and 0 citations.
- **Page range and coverage:**
  - BR's index covers page range [21,21] only, although its Overview spans p.9–21.
  - HP_2022 covers [12,12] with 3 items; 2022_29 and 2024_13 cover [8,8].
- **Index missing** (`executive_summary_index: null`) for KA (the parent is titled `5.Executive Summary`), 2024_01, 2025_06 and pre-fix 2025_08.
- **Item typing:** OD's `Article 21-A of the Constitution…` is typed "recommendation".
- Suspected: `enrichment/exec_summary_indexer`, the citation regex and section detection.

**P9-08 · Cross-references: table references never resolve, and chapter references fail on "Chapter-N"**
- Status: CONFIRMED, refined. Severity: medium.
- Affects 26/26 reports.
- **Table references resolve 0% everywhere:** OD 0/126, JH 0/186, BR 0/127, GPU 0/22. The root is P6-04.
- **Chapter references:** OD 12/24; `Chapter 1` and `Chapter 2` are unresolved because the L1 titles read `Chapter-1 Introduction Introduction 1.1`.
- **Overall resolution:** OD 27/218, JH 18/221, BR 17/151, GPU 43/67.
- Suspected: `enrichment/cross_reference_resolver`.

**P9-09 · Annexure links fail when appendices aren't parents**
- Status: CONFIRMED, refined. Severity: medium.
- Evidence:
  - Resolved: BR 0/23, GPU 0/6, pre-fix 2025_03 0/8, 2025_18 0/9, 2025_35 0/5; OD 7/15, mainly `Appendix 8.x` resolved.
  - HP_2022 29/29, KA 26/27 and JH 21/22 are fine.
  - BR has header chunks `Appendix-5.2` and `Appendix 5.17` that could be used, but the only appendix parents are `APPENDIX DESCRIPTION` ×2.
  - GPU has a single `Annexures` parent.
- Suspected: the annexure linker, which matches parent titles only.

**P9-10 · `previous_audit_refs` is garbage**
- Status: NEW. Severity: low–medium.
- **Substring matches** hit "atna" inside Patna, Visakhapatnam, Ratnagiri and Navaratna in 11 reports:
  - BR: 10/10 refs, e.g. `atna Municipal Corporation (PMC)…`;
  - GPU `atnam in January 2022`;
  - 2023_07 `atniam yb cilbuP…`, from reversed text.
- **Self-references:** the report's own number is listed in 18/26 reports (OD `Report No. 5 of 2025`).
- Suspected: the temporal extractor. It looks like a case-insensitive `ATN` or "Action Taken Note" pattern without word boundaries.

**P9-11 · Section classification is mostly "other" with confidence 0.0**
- Status: CONFIRMED. Severity: low–medium.
- Share "other": HP_2022 278/286 (97%), HP_2019 95%, OD 75%, JH 49%, GPU 57%.
- Evidence:
  - `is_low_confidence` is false despite confidence 0.0.
  - `Recommendation 3.1` sections are typed "other".
  - INCOIS sections are typed "employment" (7).
- Suspected: the section classifier.

**P9-12 · Entity lists are noisy**
- Status: NEW. Severity: low.
- Evidence:
  - OD `schemes`: `Head Master`, `Day Meals`, `Jhasiketan Sahoo` (a person), `IF stipulated constitution of a District Level Committee`, `Gross Enrolment Ratio`.
  - 2025_04 lists 74 "ministries".
- Suspected: the entity extractor's regexes.

**P9-13 · Findings include replies, footnotes and sentence fragments**
- Status: NEW. Severity: low–medium.
- **Management replies:** 1–4 per report, about 18 in total, e.g. GPU `MoES stated (December 2023) that … data gaps are inevitable` and 2025_16 `O/o CPAO stated in reply…`.
- **Findings starting mid-sentence or with a footnote:** 2025_14 21, 2022_29 18, 2020_16 15, BR 6, KA 5. E.g. `₹4.57 crore41), fitted and configured…` and `ii) 2019-20: For the months…`.
- Suspected: the finding extractor's boundary rules.

**P9-14 · LLM validation is sequential and fails under 429s**
- Status: CONFIRMED. Severity: medium (time, and possibly unvalidated findings).
- Evidence:
  - Union Phase 9 made 645 Gemini calls, 318 of which failed; Phase 9 took 3 h 20 m.
  - 31 `LLM validation failed … 429` lines, about 2.5–3 minutes apart (e.g. 2025_16 findings 002–040, 15:49–16:17). What happens to those findings is not visible in the output.
- Suspected: `enrichment/llm_validator`.

**P9-15 · `audit_period` is null in 10 reports**
- Status: NEW. Severity: low.
- Affects 2022_29, 2024_13, 2025_03, 2025_04, 2025_14, 2025_16, 2025_18, 2025_20, HP_2019 and HP_2022.
- The overview LLM does return periods, e.g. OD "2018-19 to 2022-23". The regex path misses these reports.

### Phase 10a (overview, summaries, RAPTOR)

**P10a-01 · The five summary variants for state and local reports are fabricated**
- Status: NEW. Severity: **critical**.
- Affects 6/6 state and local reports. 0/19 union reports and GPU 2025_08 are fine.
- **OD** (a school-education performance audit):
  - The journalist variant's headline is `₹156 Crore in Life-Saving Equipment Left to Rust in Odisha Hospitals`, and it cites "₹45.50 crore worth of essential medicines expired".
  - The executive variant describes a "Compliance Audit Report on the Economic Sector … DoWR, Works, RD, PR&DW … 2018-19 to 2020-21".
  - The simple variant says "The specific department checked is not stated in the report".
  - School, student and teacher terms appear 0 times in the executive, journalist and policy variants.
- **KA** (a performance audit of the Nagarothana scheme in 10 city corporations): the executive variant calls it "ATIR on Local Bodies … 30 ZPs, 226 TPs, 5,963 GPs".
- **JH** (a State Finances Audit Report): the journalist variant's headline is `₹1,200 Crore Meant for Jharkhand's Mining-Affected Villages Diverted…` (DMF), which is not in the report.
- **HP_2019** executive: "₹ 145.23 Crores remained unspent", "₹ 22.45 Crores", "₹ 89.12 Crores". None of these is in the PDF.
- **Numbers in the summaries not found in the PDF:**
  - state and local: OD 72%, HP_2019 50%, KA 49%, BR 42%, JH 35%, HP_2022 35%;
  - union: 7–25%;
  - GPU union: 3.8%.
- The same reports' `overview_llm` and hierarchical summaries are grounded, e.g. OD objectives and sample of 108 schools.
- So only the summary requests lack the report content for non-union tiers.
- Suspected: the summary request builder in `batch_pipeline/batch_service.py`. It probably loads findings or chunk context from a union-only path or `processed/union`, gets nothing for state and local, and the prompt proceeds with metadata alone.

**P10a-02 · Summary variants lost to a 429 are not retried**
- Status: NEW. Severity: medium.
- Affects 2/18 union reports.
- Evidence: `batch_jobs/summaries/2023_07_…json` has `errors: [{variant: deep_dive, 429 RESOURCE_EXHAUSTED}]`, and 2024_13 lost `journalist`. The run still ended in success.
- Suspected: `batch_service.py`, which has no final retry pass.

**P10a-03 · Hierarchical summaries are generated for fragment and duplicate parents**
- Status: NEW. Severity: low–medium (cost).
- Evidence:
  - BR: 525 summaries, 434 of them at "chapter" level, for 329 unique parents.
  - The local 10a made 745 Gemini calls.
  - The chapter counts don't match the L1 counts (BR 434 against 39 L1s).
- Suspected: the RAPTOR request builder, which takes every parent; together with P7-01 and P5.5-01.

### Phases 10b and 10c (visual extraction)

**P10b-01 · Chart extraction is sequential and bound by 429s**
- Status: CONFIRMED. Severity: medium (time).
- Evidence:
  - Union: 1 h 56 m, 551 calls, 166 failed.
  - State: 1 h 32 m, 153 calls, 72 × 429.
  - Local: 1 h 44 m, 151 calls.
  - GPU: 14 m, 69 calls, 39 × 429, while it shared quota with the CPU run.
  - Most of it goes to non-charts (P6-07).
- Suspected: `gemini_visual_extractor`.

**P10b-02 · Chart results are lost to 429s, truncated JSON and list responses**
- Status: CONFIRMED, refined. Severity: low–medium.
- Evidence:
  - Union: 2 charts were lost after retries, `2022_29 p119` and `2025_26 p75`.
  - 3 responses had truncated or invalid JSON: `2025_04 p42` "Expecting value line 36", `2025_16 p21` "Unterminated string", `2025_16 p45`. This suggests an output token limit.
  - State: 5 × "Top-level value is not an object" ending in 1 loss (OD p.44 `image_caption_0271`).
- Suspected: `gemini_visual_extractor`, which doesn't unwrap lists and has a low `max_output_tokens`.

**P10c-01 · Phase 10c doesn't hydrate tables and doesn't update the registry**
- Status: NEW. Severity: low. It is part of P6-04 and P6-05.
- Evidence: the local log says `Tables hydrated: 0`, `Charts hydrated: 18`, `Titles enriched: 312`, while registry captions stay `Table on page N`.
- Suspected: `visual_post_processor`.

### Cross-cutting and tooling

**X-01 · The preflight check misses several post-fix defect classes**
- Status: NEW. Severity: low (tooling).
- It passes HP_2022 and KA on garbage titles (0) although they have `Blank Page`, `Binder1.pdf` and `2 TOC`.
- It has no check for:
  - word-order reversal (P6-01);
  - wrong-parent assignment (P7-02);
  - duplicate parent IDs (P7-01);
  - logical pages (P8-03);
  - summary grounding (P10a-01).
- Every state and local report "passes" except BR.

**X-02 · Gemini quota is shared across runs**
- Status: CONFIRMED. Severity: medium (infra).
- The GPU run's 10b hit 39 × 429 on 69 calls while the CPU local run was in its 10b.

---

## Review list: item by item

| Review-list item | Result | See |
|---|---|---|
| OCR timeout fixed at 600 s | CONFIRMED; refined: a usable OCR output was written before the timeout | P1-01 |
| OCR failures silent | CONFIRMED | P1-02 |
| `pdfa` output slow | CONFIRMED indirectly: the file was finished at 21:58 and the process timed out at about 22:01 | P1-01 |
| Filter matching 0 reports exits 0 | CONFIRMED and broadened: all partial failures report success | P1-03 |
| All manifest PDFs downloaded before the filter | CONFIRMED | P1-06 |
| ATIR not detected | CONFIRMED | P1-05 |
| HP_2019 printed TOC verified 35%, heuristic used | CONFIRMED: the chapter title is split into 3 L1s and there are 34.7% wrong-parent headers | P4-03, P7-02 |
| HP_2022 printed TOC verified 18%, bookmarks used | CONFIRMED and worse: the bookmarks are merger junk | P4-02 |
| Phase 5.5 over-supplements | CONFIRMED, with a list of what gets promoted | P5.5-01 |
| Reconciled quality always 85 | CONFIRMED (25/26; JH 80), and it disables Phase 5.7 | P5.5-02, P5.7-01 |
| Parent fragmentation (BR 639/1719) | CONFIRMED; the BR root cause is Phase 7.5 duplication, 310 duplicate parents | P7-01, P7-03 |
| "0 figures" counter | CONFIRMED; the corpus table total is also 0 | P6-08 |
| M2-DLQ noise | CONFIRMED on a sample of 8 pages | P6-09 |
| Tier-3 fallbacks logged at ERROR | CONFIRMED; the Tier-3 pages are chapter banners | P6-10 |
| OD recommendations all verb-based | CONFIRMED: box recall 15/24, 5 false positives | P9-01 |
| Evidence links 0 in state and local | CONFIRMED (7/7 post-fix) | P9-06 |
| Executive-summary citations 0% | PARTLY DISPROVED: OD and JH have no references; real misses in GPU 2025_08, 2023_11 and BR | P9-07 |
| Cross-references 8–12% resolved | CONFIRMED; tables 0% everywhere | P9-08 |
| LLM validation sequential | CONFIRMED | P9-14 |
| ATIRs have 0 recommendations | CONFIRMED | P9-01 |
| ATIR typed compliance | CONFIRMED | P1-05 |
| BR annexure links 0/23 | CONFIRMED: appendices aren't parents | P9-09 |
| Findings typed "other" | CONFIRMED | P9-03 |
| 10b sequential | CONFIRMED | P10b-01 |
| 10b JSON-list responses | CONFIRMED | P10b-02 |
| Shared `manifest.json` | CONFIRMED; the header timestamp is also stale | P8-04 |
| Shared log file, GPU quota, GCS cleanup, retry count, cu121 line, worktree | Not output issues; nothing in the output contradicts them | — |

## What was not checked, or only sampled

- **CG_2025_01 has no output**, so only the OCR failure was audited. The OCR'd PDF looks usable: 113/129 pages have text.
- **Recommendation recall** was measured on 6 reports only (OD, 2023_07, 2025_06, JH, 2025_35, 2025_38). Other reports were compared against rough PDF pattern counts only.
- **Findings recall** is a proxy based on cue phrases, verified by hand for 2025_38 and 2025_35. Precision was sampled with regex patterns, not read in full.
- **Table fidelity** checked numbers only, and only for single-page tables inside the chunk's bbox: 456 tables in the post-fix reports, plus 10 in pre-fix 2025_08. It didn't check cell alignment or header structure. Multi-page tables were checked for overlap and fragments, not number by number.
- **Chart values** were compared only for vector charts with text labels (60 charts). Raster charts can't be verified from the PDF text. The "no-chart" counts come from a regex over the descriptions (±10%).
- **Summary faithfulness** was measured by matching numbers against the PDF (all 25 reports with summaries) and by reading 8 variants by hand. Claims without numbers were not checked, and hierarchical summaries were spot-read only (5 per report for OD and KA).
- **Pre-fix union reports** were measured but not examined page by page. Their text defects are fixed in the GPU 2025_08 output, so a union re-run is needed before any union-specific extraction item is final.
- **Some things can't be seen in the output:**
  - What the pipeline does with findings whose LLM validation failed (P9-14).
  - Why Phase 7.5 triggered only for BR.
  - Exactly what input the state and local summary requests got (P10a-01). The job mapping files don't contain the prompts.
