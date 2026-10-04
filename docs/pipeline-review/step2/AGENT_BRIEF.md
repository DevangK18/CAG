# Step 2 agent brief (shared by Agents A–D)

## Goal
Do a complete review of the logic of the code in your phases. For each phase, answer:

1. **Does it run?**
   - Confirm with evidence from the run logs that each step, service, config flag and fallback
     actually executes in production.
   - Classify each one as:
     - works;
     - runs but broken;
     - never runs;
     - dead code;
     - fails silently.
2. **Is the logic right?**
   - Trace every Step 1 issue in your scope to the exact `file:line` that causes it.
   - Also find latent bugs these 26 reports did not trigger, such as:
     - edge cases;
     - wrong thresholds;
     - state leaking between reports;
     - exceptions swallowed;
     - config keys that are defined but never read (or read but never defined);
     - assumptions that break for state or local reports and ATIRs.
3. **What should improve?**
   - Concrete improvements, even where nothing is "broken": a simpler approach, better
     heuristics, deterministic vs LLM trade-offs, performance.

"Do not leave any stone unturned." Read every file in your scope completely. Do not skim.

## Hard limits (read-only)
- Do not edit anything under `src/`, `scripts/`, `tests/`, `.github/`, `infra/`, the
  Dockerfiles or `parsing_config.yaml`.
- Do not commit, push, dispatch workflows, start VMs, or write to GCS.
- Your only writable locations:
  - your report file under `docs/pipeline-review/step2/agents/`;
  - your scratch folder `<scratchpad>/step2/<your letter>/`, where
    `<scratchpad>` = `/private/tmp/claude-501/-Users-dev-Projects-CAG/5b128fa5-8434-46e2-a3c3-a9695a9cdf81/scratchpad`.
- Running code to prove behaviour is encouraged. For example, call a function on text taken
  from the real outputs, or reproduce a bug in a scratch script. Use the poetry venv
  (`$(poetry env info -p)/bin/python`, run from the repo root). Import modules, but never modify
  them.

## Data already downloaded (reuse it; do not download again)
Everything is under `<scratchpad>/audit/`:

| Path | Contents |
|------|----------|
| `pdfs/` | All 26 PDFs |
| `allchunks/` | Every `*_chunks.json` |
| `gpuchunks/` | GPU 2025_08 output |
| `gcs/processed/`, `gcs/gpu-test/` | All other output files |
| `gcs/runs/`, `gcs/runs-gpu/` | Run logs |
| `gcs/batch_jobs/` | Phase 10 job files |
| `gcs/manifests/` | Manifests |
| `parents/` | Parent trees |
| `log_templates.txt` | Log lines grouped by template |
| `scripts/` | The Step 1 check scripts |

Step 1 findings: `docs/pipeline-review/step1/step1_findings.md`. Read it fully first. The
pre-audit list is at `docs/pipeline-review/step1/pre_audit_review_list.md`.

If something truly is missing, download it with curl plus an access token
(`gcloud storage cp` stalls on this Mac). macOS has no `timeout` command.

## Scope boundaries
Each agent owns a disjoint set of files (see `docs/pipeline-review/README.md`). If you find a
cause that sits in another agent's files, record it under **Hand-offs** with `file:line`. Do
not review that code in depth.

The main session owns:
- `finding_extractor.py`, `recommendation_extractor.py`, `llm_validator.py`,
  `monetary_processor.py`, `box_element_extractor.py`;
- `semantic_patterns.py`, `enrichment_patterns.yaml`;
- finding validation.

## Report format
Write to your report file and update it as you go, so partial work survives if you are
interrupted. Use this structure:

```
# Agent <X>: <scope>
## Work log
(each file read fully, with its line count; each script run, with its purpose and result;
what was verified by running code vs inferred from reading)

## Phase <n>: <name>
### Data flow
(inputs → steps → outputs, with file:line; what each consumes and produces)
### Does it run? (evidence)
### Issues
#### <X>-<n>-<NN> · <critical|high|medium|low> · <title>
- Location: file:line (all relevant lines)
- Root cause: what the code does and why it is wrong
- Explains Step 1: P?-?? (or "latent: not triggered by the audited reports")
- Evidence: log line, output example, or scratch-script result (script path)
- Fix proposal: concrete change; sketch the code if non-trivial
- Risk / effort: what could regress; S / M / L
- Confidence: verified by running | verified by reading | hypothesis
### Improvements (not bugs)
### Wired-and-working inventory
| Component / flag | Status | Evidence |

## Step 1 issue coverage
(every Step 1 ID in your scope → the issue ID(s) of yours that explain it, or "not explained, because …")
## Hand-offs
## Summary (ranked issue list)
```

Severity reflects the impact on RAG answer quality and correctness. Every issue needs a
`file:line` and evidence. Do not pad the report.

Your final message should include:
- the report path;
- the ranked issue list (ID, severity, title, `file:line`);
- the hand-offs;
- anything you could not verify.
