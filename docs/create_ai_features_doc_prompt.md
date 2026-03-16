# Prompt: Create AI_FEATURES.md

## Context
You are creating `@docs/guides/AI_FEATURES.md` — the architectural reference guide for ALL AI/LLM usage across the CAG Gateway project. This is a **cross-cutting** document: unlike PARSING_PIPELINE.md (which covers PDF→JSON) or RAG_PIPELINE.md (which covers indexing→querying), this document catalogs every place in the codebase where an AI model is called, what prompt it receives, why that model was chosen, and what it costs.

This document serves two purposes:
1. **Engineering reference**: A developer can find every AI integration point, understand the prompt design, and know the cost implications
2. **Frontend content source**: The "AI Features" tab in the How It Works section will be built from this document's content

## What This Document Must Capture

For EVERY AI/LLM call in the codebase, document:
- **Where**: File path, class/method name
- **Model**: Exact model string used
- **When it runs**: Offline (batch/indexing) vs online (per-query)
- **Prompt**: The FULL prompt text — system prompt and user prompt template. Copy the actual strings from the code, don't paraphrase. Use markdown code blocks for prompts.
- **Input**: What data gets sent (and any preprocessing/truncation)
- **Output**: What the model returns and how it's parsed
- **Cost**: Per-call and corpus-level estimates
- **Why this model**: Decision rationale for model choice
- **Fallback**: What happens if the call fails

## Where to Find AI Calls

Search the entire codebase systematically. Here are the known locations — but scan for any others:

### Parsing Pipeline (`src/parsing_pipeline`)

1. **Phase 5.7: LLM TOC Validation**
   - Uses Claude Haiku
   - Fires only when TOC quality < 50 (~15% of reports)
   - Sends first ~15 pages of raw text
   - Returns corrected TOC as JSON array
   - Find the prompt in the TOC validation module

2. **Phase 10a: Enhanced Overview Extraction**
   - Uses Claude Batch API
   - Extracts: audit scope, objectives, topics, glossary
   - Find the prompt template — it should specify the JSON structure expected
   - Document the merge strategy: how LLM-extracted fields combine with algorithmic extraction

3. **Phase 10a: Summary Generation (5 variants)**
   - Uses Claude Batch API + Extended Thinking
   - 5 distinct prompt variants: Executive Brief, Journalist's Take, Deep Dive, Simple Explainer, Policy Brief
   - Each has different tone, structure, word count target, audience model
   - Find ALL 5 prompt templates — copy them in full
   - Document the Extended Thinking configuration (budget_tokens, thinking model, etc.)

4. **Phase 10b: Gemini Visual Extraction**
   - Uses Gemini 2.5 Flash
   - Two sub-tasks: table extraction (returns markdown) and chart description
   - Find the prompts for both table and chart extraction
   - Document image preprocessing (cropping, resolution, format)

### RAG Pipeline

5. **Table Summary Generation (Indexing)**
   - Uses GPT-4o-mini
   - Generates natural language summaries for markdown tables
   - Find the prompt in embedding_service.py (TableSummaryService)
   - Document the fallback (rule-based extraction if LLM fails)

6. **RAG Chat Generation (6+ Response Styles)**
   - Uses Claude Sonnet or GPT-4o-mini (configurable)
   - Has a layered prompt system:
     a. Base expertise prompt (CAG domain knowledge)
     b. Anti-pattern rules (forbidden phrases, required behaviors)
     c. Citation rules (format, placement)
     d. Style-specific prompts (one per style: CONCISE, DETAILED, EXECUTIVE, TECHNICAL, COMPARATIVE, ADAPTIVE, EXPLANATORY, REPORT)
     e. Question-type hints (LIST, AGGREGATION, COMPARISON, EXPLANATION)
   - Find the prompt in rag_service.py
   - Copy the FULL system prompt text for each style variant
   - Copy the query templates for each style
   - Document the prompt construction order (what gets concatenated in what order)



### Other Possible Locations
- Any prompt templates in a `prompts/` directory
- Any AI calls in utility scripts or batch processing scripts
- Any AI calls in the FastAPI routes themselves (unlikely but check)
- Environment variable defaults that reference model names

## Document Structure

```markdown
# AI Features Documentation

## Overview
- Total AI models used: N
- Total distinct prompts: N
- Offline vs online split
- Total corpus processing cost: $X

## Multi-Model Strategy
[Why 4+ models instead of one. Map each model to its tasks with cost/quality rationale]

## Model Inventory
[Table: Model | Tasks | Online/Offline | Cost per call | Why chosen]

## Prompt Catalog

### 1. TOC Validation (Phase 5.7)
[Full details per the template above]

### 2. Overview Extraction (Phase 10a)
[Full details]

### 3. Summary Generation — Executive Brief
[Full prompt + details]

### 4. Summary Generation — Journalist's Take
[Full prompt + details]

### 5. Summary Generation — Deep Dive
[Full prompt + details]

### 6. Summary Generation — Simple Explainer
[Full prompt + details]

### 7. Summary Generation — Policy Brief
[Full prompt + details]

### 8. Visual Extraction — Tables (Gemini)
[Full prompt + details]

### 9. Visual Extraction — Charts (Gemini)
[Full prompt + details]

### 10. Table Summary (Indexing)
[Full prompt + details]

### 11. RAG Chat — Base System Prompt
[The shared base that all styles include]

### 12. RAG Chat — Citation Rules
[The citation instruction block]

### 13. RAG Chat — CONCISE Style
[Full style-specific prompt]

### 14. RAG Chat — DETAILED Style
[Full style-specific prompt]

### 15. RAG Chat — EXECUTIVE Style
[Full style-specific prompt]

### 16. RAG Chat — TECHNICAL Style
[Full style-specific prompt]

### 17. RAG Chat — COMPARATIVE Style
[Full style-specific prompt]

### 18. RAG Chat — ADAPTIVE Style
[Full style-specific prompt]

### 19. RAG Chat — EXPLANATORY Style
[Full style-specific prompt]

### 20. RAG Chat — REPORT Style
[Full style-specific prompt]

### 21. RAG Chat — Query Templates
[The user-message templates per style]

### 22. Time Series System Prompt
[Full prompt]

### 23. Question Type Detection
[If it uses an LLM — otherwise just document the regex/heuristic approach]

## Batch API Architecture
[How batch jobs are submitted, tracked, polled, and results parsed]
- Job lifecycle
- Request-to-report mapping
- Result hydration
- Error handling and retries
- Extended Thinking configuration

## Prompt Engineering Patterns
[Cross-cutting patterns used across multiple prompts]
- JSON output enforcement
- Anti-hallucination guardrails
- Citation format standardization
- Word count control
- Audience adaptation
- Missing data handling

## Cost Architecture
[Full cost breakdown]
- Per-model cost table
- Offline processing costs (per report, full corpus)
- Online query costs (per query, projected monthly)
- Cost optimization strategies (Batch API savings, model tiering, caching)
```

## How to Search

Use these search strategies to find all AI calls:

```bash
# Find all Anthropic API calls
grep -rn "anthropic\|claude\|messages.create\|batch" --include="*.py" src/ services/

# Find all OpenAI API calls
grep -rn "openai\|gpt-4\|text-embedding\|chat.completions" --include="*.py" src/ services/

# Find all Gemini/Google AI calls
grep -rn "gemini\|google.generativeai\|genai" --include="*.py" src/ services/

# Find all prompt strings (look for multi-line strings and f-strings)
grep -rn "system_prompt\|SYSTEM_PROMPT\|system_message\|PROMPT" --include="*.py" src/ services/

# Find model name references
grep -rn "claude-\|gpt-4\|gemini-\|text-embedding" --include="*.py" src/ services/

# Find batch API usage
grep -rn "batch\|BatchAPI\|batch_service" --include="*.py" src/ services/

# Find temperature, max_tokens, and other LLM config
grep -rn "temperature\|max_tokens\|top_p" --include="*.py" src/ services/
```

Also check:
- `data/batch_jobs/` for batch job configuration files
- Any `.env.example` or config files for model defaults
- Any `prompts/` or `templates/` directories

## Formatting Rules

- **Copy prompts verbatim** from the source code. Don't summarize or paraphrase prompts. These are the most valuable part of the document.
- For long prompts (>50 lines), still include the full text — this document IS the prompt catalog
- Use ` ```python ` blocks for code, ` ```markdown ` blocks for prompt text
- Include the file path and method name as a header before each prompt
- Note any f-string variables in prompts with `{variable_name}` and explain what each variable contains
- If a prompt is constructed by concatenating multiple parts, show the concatenation order AND the individual parts

## Important
- This document should be COMPREHENSIVE. Every AI call, every prompt, every model. Missing one means the frontend tab will be incomplete.
- Do NOT add content about the frontend rendering, React components, or UI
- Do NOT add troubleshooting or usage examples (those go in README)
- Do NOT add version numbers, dates, or changelog artifacts
- The document will likely be 800-1500+ lines because it includes full prompt texts — that's expected and correct
- If you find AI calls not listed in "Where to Find AI Calls" above, include them. The list above is a starting point, not exhaustive.
- For the prompt catalog entries, maintain a consistent structure. Every entry should have: Location (file + method), Model, When (offline/online), Full Prompt Text, Input Description, Output Description, Cost, Why This Model, Fallback Behavior
