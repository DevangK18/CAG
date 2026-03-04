# CAG RAG Evaluation Framework

## Complete Guide for Testing & Verification

---

## Table of Contents

1. [Overview](#overview)
2. [Evaluation Dimensions](#evaluation-dimensions)
3. [Creating Ground Truth](#creating-ground-truth)
4. [Manual Testing Protocol](#manual-testing-protocol)
5. [Automated Evaluation](#automated-evaluation)
6. [Scoring Rubrics](#scoring-rubrics)
7. [Issue Taxonomy](#issue-taxonomy)
8. [Reporting Template](#reporting-template)

---

## Overview

### Why Evaluate RAG?

RAG systems can fail in subtle ways:
- **Retrieval failures**: Right answer exists but wrong chunks retrieved
- **Generation failures**: Right chunks retrieved but wrong answer generated
- **Hallucinations**: Facts invented that aren't in any source
- **Attribution errors**: Citations don't support the claims
- **Incompleteness**: Partial answers missing key information

### Evaluation Goals

1. **Measure baseline quality** across different question types
2. **Identify systematic failure patterns**
3. **Track improvement over iterations**
4. **Build confidence before production deployment**

---

## Evaluation Dimensions

### 1. Retrieval Quality

> "Did the system find the right information?"

| Metric | Description | Target |
|--------|-------------|--------|
| **Recall@10** | % of relevant chunks in top 10 results | >80% |
| **Precision@10** | % of top 10 results that are relevant | >60% |
| **MRR** | Mean Reciprocal Rank of first relevant result | >0.5 |
| **Source Coverage** | Does it pull from the right report(s)? | 100% |

### 2. Answer Accuracy

> "Is the answer factually correct?"

| Metric | Description | Target |
|--------|-------------|--------|
| **Factual Correctness** | Are all stated facts true? | >95% |
| **Amount Accuracy** | Are ₹ figures exact matches? | >98% |
| **Entity Accuracy** | Are names/orgs/places correct? | >98% |
| **No Hallucination** | No invented facts | 100% |

### 3. Answer Completeness

> "Does the answer cover all key points?"

| Metric | Description | Target |
|--------|-------------|--------|
| **Key Fact Coverage** | % of expected facts included | >80% |
| **Key Amount Coverage** | % of expected amounts included | >85% |
| **Balanced Coverage** | Doesn't over-focus on one aspect | Subjective |

### 4. Citation Quality

> "Do the sources support the claims?"

| Metric | Description | Target |
|--------|-------------|--------|
| **Citation Relevance** | Does cited source relate to claim? | >90% |
| **Citation Accuracy** | Is page/section number correct? | >95% |
| **Claim Support** | Does source actually support claim? | >90% |

### 5. Response Quality

> "Is the answer well-formed and useful?"

| Metric | Description | Target |
|--------|-------------|--------|
| **Relevance** | Does it answer the actual question? | >95% |
| **Coherence** | Is it logically structured? | Subjective |
| **Style Adherence** | Does it follow requested style? | >90% |
| **Appropriate Length** | Not too short or verbose? | Subjective |

---

## Creating Ground Truth

### Question Categories

Create test cases across these categories:

#### A. By Difficulty

| Level | Description | Example |
|-------|-------------|---------|
| **Easy** | Single fact, single source | "What was the total revenue loss in NHAI toll report?" |
| **Medium** | Multiple facts, single source | "What are the main findings on toll collection delays?" |
| **Hard** | Synthesis across sections | "Explain the systemic issues in NHAI toll management" |
| **Expert** | Cross-report analysis | "Compare tax assessment errors across 2021-2023 reports" |

#### B. By Question Type

| Type | Description | Example |
|------|-------------|---------|
| **Factual** | Specific fact lookup | "How much was the short collection on NH 44?" |
| **List** | Enumerate findings | "List all revenue loss categories in NHAI audit" |
| **Explanation** | Why/How questions | "Why did revenue loss occur in toll collection?" |
| **Comparison** | Compare entities/periods | "Compare findings on Ayushman Bharat vs NHAI" |
| **Aggregation** | Sum/count across sources | "What's the total tax effect of assessment errors?" |
| **Negative** | Questions with no answer | "What are the audit findings on Railways?" |

#### C. By Report Coverage

Ensure test cases cover all 14 reports:

```
Reports to cover:
├── 2020_16_Cooperative_Societies (tax assessment)
├── 2022_29_Direct_taxes_2020-21
├── 2023_07_NHAI_Toll_Operation
├── 2023_11_Ayushman_Bharat_PMJAY
├── 2023_19_Bharatmala_Pariyojana
├── 2023_20_Food_grains_Storage
├── 2024_01_FRBM_Compliance
├── 2024_13_Direct_taxes_2021-22
├── 2025_03_FRBM_Compliance
├── 2025_04_Union_Accounts_2022-23
├── 2025_06_CPSE_Compliance
├── 2025_14_Direct_taxes_2022-23
├── 2025_16_Union_Accounts_2023-24
└── 2025_18_FRBM_Compliance
```

### Ground Truth Template

Each test case should include:

```json
{
  "id": "TC001",
  "question": "What was the revenue loss due to toll collection delays by NHAI?",
  "category": {
    "difficulty": "easy",
    "type": "factual",
    "reports": ["2023_07_NHAI_Toll"]
  },
  "expected": {
    "answer_summary": "₹64.60 crore due to delays in toll collection",
    "key_facts": [
      "Revenue loss of ₹64.60 crore",
      "Delay in toll collection in four stretches",
      "Violation of NH Fee Rules, 2008 time limits"
    ],
    "key_amounts": [
      {"value": 64.60, "unit": "crore", "context": "revenue loss from delays"},
      {"value": 129.20, "unit": "crore", "context": "total amount mentioned"}
    ],
    "key_entities": ["NHAI", "NH Fee Rules 2008"],
    "source_sections": ["3.2.1", "Executive Summary"],
    "source_pages": [36, 37, 38]
  },
  "negative_criteria": {
    "must_not_contain": ["Railways", "PMJAY", "invented figures"],
    "must_not_hallucinate": true
  },
  "metadata": {
    "created_by": "manual",
    "verified": false,
    "notes": "Straightforward factual query"
  }
}
```

### Minimum Test Set Size

| Category | Minimum Cases | Recommended |
|----------|---------------|-------------|
| Easy factual | 15 | 25 |
| Medium multi-fact | 15 | 25 |
| Hard synthesis | 10 | 20 |
| Cross-report | 5 | 10 |
| Negative (no answer) | 5 | 10 |
| **Total** | **50** | **90** |

---

## Manual Testing Protocol

### Step 1: Structured Query Testing

For each test case:

```
1. Run query with default settings
   $ python -m services.rag_pipeline.cli --provider openai "your question"

2. Record the response:
   - Full answer text
   - Listed sources
   - Any error messages

3. Verify against ground truth:
   □ Check each key fact - present/absent/wrong
   □ Check each key amount - exact match/close/wrong
   □ Check citations - do they support claims?
   □ Check for hallucinations - any invented facts?

4. Score using rubric (see below)

5. Document any issues found
```

### Step 2: Source Verification

For each citation in the response:

```
1. Locate the cited page in original PDF
2. Verify:
   □ Page number is correct
   □ Section reference is correct
   □ The cited text actually exists
   □ The cited text supports the claim made
3. Flag any misattributions
```

### Step 3: Edge Case Testing

Test these specific scenarios:

```
□ Ambiguous queries ("What about toll collection?" - which aspect?)
□ Multi-part questions ("What was the loss AND what caused it?")
□ Queries with typos ("What are NHAI toal findings?")
□ Very specific queries ("Revenue loss on Madurai-Kanyakumari stretch")
□ Very broad queries ("Tell me everything about compliance failures")
□ Out-of-scope queries ("What are the findings on defense spending?")
□ Temporal queries ("Findings from 2023 only")
□ Filtered queries (using --min-year, --min-amount flags)
```

### Step 4: Style Verification

Test each style produces appropriate output:

```
□ concise: Actually short (3-4 sentences)?
□ conversational: Natural flow, no bullet points?
□ executive: Has bottom line + bullets + amounts?
□ analytical: Deep, themed, 400+ words?
□ report: Formal sections, complete structure?
□ adaptive: Varies by question complexity?
```

---

## Automated Evaluation

### Running the Evaluation Script

```bash
# Run full evaluation
python evaluation/evaluate.py --test-cases test_cases.json --output results/

# Run specific category
python evaluation/evaluate.py --test-cases test_cases.json --category easy

# Run with specific style
python evaluation/evaluate.py --test-cases test_cases.json --style concise

# Verbose mode (see each query)
python evaluation/evaluate.py --test-cases test_cases.json --verbose
```

### Automated Metrics

The script calculates:

1. **Exact Match Scores**
   - Amount extraction accuracy
   - Entity extraction accuracy

2. **Fuzzy Match Scores**
   - Key fact coverage (semantic similarity)
   - Answer similarity to expected

3. **LLM-as-Judge Scores**
   - Factual accuracy (0-5)
   - Completeness (0-5)
   - Relevance (0-5)
   - Citation quality (0-5)

4. **Aggregate Metrics**
   - Pass rate by category
   - Mean scores by dimension
   - Failure mode distribution

---

## Scoring Rubrics

### Factual Accuracy (0-5)

| Score | Criteria |
|-------|----------|
| 5 | All facts correct, no errors |
| 4 | Minor imprecision (e.g., "about ₹65 crore" vs "₹64.60 crore") |
| 3 | One factual error, rest correct |
| 2 | Multiple minor errors OR one major error |
| 1 | Mostly incorrect but some relevant content |
| 0 | Completely wrong or hallucinated |

### Completeness (0-5)

| Score | Criteria |
|-------|----------|
| 5 | All key facts and amounts included |
| 4 | 80%+ of key information, minor gaps |
| 3 | 60-80% coverage, noticeable gaps |
| 2 | 40-60% coverage, significant gaps |
| 1 | <40% coverage, mostly incomplete |
| 0 | Doesn't address the question |

### Citation Quality (0-5)

| Score | Criteria |
|-------|----------|
| 5 | All citations accurate and support claims |
| 4 | Minor citation issues (wrong page, not section) |
| 3 | Some citations don't fully support claims |
| 2 | Multiple citation errors or missing citations |
| 1 | Citations mostly irrelevant |
| 0 | No citations or completely wrong sources |

### Relevance (0-5)

| Score | Criteria |
|-------|----------|
| 5 | Directly answers the question asked |
| 4 | Answers question with minor tangents |
| 3 | Partially answers, misses key aspect |
| 2 | Related but doesn't answer the question |
| 1 | Mostly off-topic |
| 0 | Completely irrelevant |

---

## Issue Taxonomy

When you find issues, categorize them:

### Retrieval Issues

| Code | Issue | Example |
|------|-------|---------|
| R1 | Wrong report retrieved | Asked about NHAI, got PMJAY content |
| R2 | Right report, wrong section | Found report but missed key section |
| R3 | Missed cross-reference | Didn't find related content in annexures |
| R4 | Keyword mismatch | Query "revenue loss" didn't match "loss of revenue" |

### Generation Issues

| Code | Issue | Example |
|------|-------|---------|
| G1 | Hallucination | Invented a ₹ figure not in source |
| G2 | Misinterpretation | Confused "short levy" with "revenue loss" |
| G3 | Incomplete synthesis | Had all chunks but missed key point |
| G4 | Wrong aggregation | Added amounts that shouldn't be summed |
| G5 | Temporal confusion | Mixed findings from different years |

### Citation Issues

| Code | Issue | Example |
|------|-------|---------|
| C1 | Wrong page number | Cited p.40, content is on p.42 |
| C2 | Wrong section | Cited 3.2.1, content is in 3.2.2 |
| C3 | Unsupported claim | Citation doesn't support the statement |
| C4 | Missing citation | Made claim with no source |

### Style Issues

| Code | Issue | Example |
|------|-------|---------|
| S1 | Wrong length | Concise style gave 500 words |
| S2 | Wrong format | Executive style used paragraphs not bullets |
| S3 | Inconsistent tone | Mixed formal/informal language |

---

## Reporting Template

### Weekly Evaluation Report

```markdown
# RAG Evaluation Report - Week of [DATE]

## Executive Summary

- **Test Cases Run**: X
- **Overall Pass Rate**: X%
- **Critical Issues Found**: X

## Scores by Dimension

| Dimension | Score | Target | Status |
|-----------|-------|--------|--------|
| Factual Accuracy | X.X/5 | 4.5 | ✅/⚠️/❌ |
| Completeness | X.X/5 | 4.0 | ✅/⚠️/❌ |
| Citation Quality | X.X/5 | 4.0 | ✅/⚠️/❌ |
| Relevance | X.X/5 | 4.5 | ✅/⚠️/❌ |

## Scores by Category

| Category | Pass Rate | Avg Score |
|----------|-----------|-----------|
| Easy | X% | X.X |
| Medium | X% | X.X |
| Hard | X% | X.X |
| Cross-report | X% | X.X |

## Top Issues

1. **[Issue Code]**: Description (X occurrences)
   - Example query: "..."
   - Expected: "..."
   - Got: "..."
   - Root cause: ...

2. ...

## Recommendations

1. [Specific fix for top issue]
2. [Process improvement]
3. [Additional test cases needed]

## Appendix: Failed Test Cases

[List of all failed cases with details]
```

---

## Quick Start Checklist

```
□ Create 10 easy test cases (start here)
□ Run manual evaluation on those 10
□ Document issues found
□ Create 10 medium test cases
□ Run automated evaluation
□ Review LLM-judge scores
□ Create 10 hard test cases
□ Test all 6 response styles
□ Document systematic issues
□ Create improvement plan
```

---

## Files in This Framework

```
evaluation_framework/
├── RAG_EVALUATION_GUIDE.md      # This document
├── ground_truth_template.json    # Schema for test cases
├── sample_test_cases.json        # 30 example test cases
├── evaluate.py                   # Automated evaluation script
├── evaluation_utils.py           # Helper functions
└── results/                      # Output directory
    └── .gitkeep
```
