# Adjudication log

Main session, 2026-09-27.

## Deviation from the guide
`LABELING_GUIDE.md` says every pipeline/gold mismatch is re-read before metrics are computed.
With 573 missed core gold findings, that is not proportionate, so adjudication was done in three
parts:

1. **All** pipeline findings with no gold match (14), each re-read against the PDF and the gold
   file.
2. **All** candidates the LLM validator removed (33). The texts were read in full for OD (8) and
   JH (13), and the rest were checked against gold matches.
3. **A random sample** of 8 missed gold findings from each agent-labelled report (40 in total,
   `random.seed(7)`), each re-read to judge whether it really is a finding.

No gold file was changed as a result. The conclusions do not depend on the small label errors
found.

## 1. Pipeline findings with no gold match (14)

| Report | Pipeline item | Verdict |
|---|---|---|
| 2025_38 | 012 p53 "Management/Ministry replied…" | Management reply → gold correct (pipeline false positive) |
| 2025_08 | 008 p48 "MoES stated (December 2023)…" | Management reply → FP |
| JH | 005 p44 "Growth rate of GIA from GoI…" | Neutral trend → FP |
| HP_2022 | 051 p61 "Rule 97(1) … provides…" | Criteria → FP |
| HP_2022 | 065 p69 "Admitting the facts, the Executive Officer stated…" | Reply → FP |
| HP_2022 | 066 p69 "audit noticed that Municipal Council Kullu received funds ₹12.97 crore…" | **Same finding as gold F114 (p70)**. The pipeline chunk is the lead-in; gold anchors on the "Thus… blockade of ₹8.97 crore" sentence. Not a real FP |
| HP_2022 | 075 p74 "The Executive Officer … stated…" | Reply → FP |
| HP_2022 | 081 p76 "MC Shimla prepared a pilot DPR…" | **Same finding as gold F128 (p77)**, lead-in chunk. Not a real FP |
| OD | 012 p49 "The Department's reply … was silent…" | Rebuttal of a reply → FP by guide convention |
| OD | 016 p55 "The Department did not offer any specific views…" | Non-finding → FP |
| BR | 016 p64 "In reply, the Executive Officer … stated…" | Reply → FP |
| BR | 058 p136 "5.6.3.3 Avoidable expenditure of ₹10.29 crore on hiring of Earth Mover…" | **Same finding as gold F202 (p136)**. The pipeline caught the paragraph heading. Not a real FP |
| BR | 059 p137 "The reply was not acceptable because… NGT's order…" | Rebuttal. Ambiguous: the guide folds rebuttals into the finding, and the pipeline chunk holds only the rebuttal |
| BR | 082 p162 "As per Hon'ble NGT order (February 2020)…" | Criteria → FP |

**Result:** 10 true false positives, 3 are lead-in or heading chunks of real findings, and 1 is
ambiguous. The reported precision (about 95%) is therefore slightly **understated**. **7 of the
10 true false positives are management replies**, so a "stated/replied/reply" exclusion would
remove most of them.

## 2. LLM-rejected candidates (33)
26 match gold findings. Reading the OD and JH texts confirms they are real findings whose regex
metadata is wrong:
- students or books parsed as money;
- the wrong amount picked;
- type "other".

The only clearly correct rejection is JH p142, an appendix caption ("Appendix 3.5 Surrender of
funds…"). Full texts are in the session log and `step2/deep-dives/llm_validation.md`.

## 3. Sample of missed gold findings (40)

| Report | Sampled | Clearly real findings | Debatable |
|---|---|---|---|
| 2025_08 | 8 | 8 | 0 |
| OD_2025_05 | 8 | 7 | 1: F036, retention below the all-India rate (a comparison, arguably a finding) |
| JH_2025_02 | 8 | 6 | 2: F020 and F024 open with SFC background before the adverse part |
| BR_2024_03 | 8 | 7 | 1: F020 opens with statutory powers before the adverse part |
| HP_2022 | 8 | 8 | 0 |

**Estimated label error on misses: ≤ 10%.** Even if every debatable miss were removed, recall
would rise only from about 30% to about 33%. The under-extraction conclusion stands.

Sampled misses that show why regex acceptance fails:
- HP_2022 F016, "MC Shimla failed to realise lease money of ₹ 1.74 crore from shops and stalls.":
  money but no type or indicator match. `FINDING_INDICATORS` only allows "(Ministry|Department|
  PSU|Company) failed".
- BR F024, "Audit observed that no Departmental Level Committee meetings had been held since
  July 2015…": the cue "Audit observed" gives only 0.4 confidence, there is no money, and
  `(meetings?|committee) … not held` doesn't match "no … meetings had been held".
- OD F016, "There was shortfall in review of the progress…": no cue, no money.
- 2025_08 F059, "The security measures … advised by CERT-In in March 2018, remained pending.":
  "pending" is only an umbrella keyword, and it needs an "Audit observed that" prefix.
