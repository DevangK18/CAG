# Task: Fix Chat Markdown Rendering — DEFINITIVE FIX (v3)

## Confirmed Root Cause

After tracing the full data flow through all 6 files:

- `streaming_wrapper.py` → yields raw LLM tokens (no stripping) ✅
- `chat.py` → `json.dumps()` properly escapes `\n` in JSON ✅
- `api.ts` → SSE parser correctly splits on `\n\n` delimiters, `JSON.parse` restores newlines ✅
- `appStore.ts` → `appendToLastMessage` concatenates tokens correctly ✅
- `ChatMessage.tsx` → ReactMarkdown + rehype-raw setup is correct (citation badges render as proof) ✅

**The LLM is not generating newline characters.** The system prompt in `rag_service.py` does not instruct the model to use proper markdown line breaks. The model outputs `...text. ### Heading **bold**` as a continuous line instead of using `\n\n` before block elements.

## Two Fixes Required

### Fix A: Frontend normalizer (IMMEDIATE — do this first)
Transforms inline markdown markers into proper block-level markdown before ReactMarkdown processes it.

### Fix B: System prompt update (ROOT CAUSE — do this second)
Add explicit formatting instructions to the system prompt so the LLM generates proper markdown with newlines.

---

## Fix A: Frontend Normalizer in ChatMessage.tsx

### What to change

Add a single new function `normalizeMarkdownContent` at the top of `ChatMessage.tsx`, right before `preprocessCitations`:

```tsx
/**
 * Normalize markdown that arrives without proper line breaks.
 * The LLM generates markdown markers (###, **, -) but doesn't always
 * include \n\n before block-level elements. ReactMarkdown requires
 * headings and lists to start on their own line.
 * 
 * This function inserts \n\n before block elements so ReactMarkdown
 * can parse them correctly.
 */
function normalizeMarkdownContent(content: string): string {
  if (!content) return content;
  
  let result = content;
  
  // 1. Ensure headings start on their own line
  //    Match: non-newline character(s) followed by ## (heading marker)
  //    Insert \n\n before the heading marker
  //    Negative lookbehind: don't match if already preceded by newline
  result = result.replace(/([^\n])(#{1,6}\s)/g, '$1\n\n$2');
  
  // 2. Ensure there's a line break AFTER a heading before body text
  //    Match: heading line (# ... ) followed immediately by non-heading, non-newline content
  //    This regex finds: "### Title Some body text" and adds \n\n between title and body
  //    Strategy: headings end when we hit a pattern that starts body text
  //    Look for: ### Title Text<space><space>Content... or ### Title**bold start
  result = result.replace(
    /(#{1,6}\s[^#\n]*?)(\s{2,}(?=[A-Z*\-\d•]))/g,
    '$1\n\n'
  );
  
  // 3. Ensure list items start on their own line  
  //    Match: "- **" pattern (bold list items, very common in CAG responses)
  result = result.replace(/([^\n])\s+(- \*\*)/g, '$1\n\n$2');
  
  // 4. Ensure plain list items start on their own line
  //    Match: "- " followed by uppercase letter (start of list item)
  result = result.replace(/([^\n\-])\s+(- [A-Z])/g, '$1\n\n$2');
  
  // 5. Ensure table rows start on their own line
  //    Match: pipe-delimited content (markdown tables)
  result = result.replace(/([^\n|])\s*(\|[^|\n]+\|)/g, '$1\n$2');
  
  // 6. Clean up: collapse 3+ consecutive newlines to exactly 2
  result = result.replace(/\n{3,}/g, '\n\n');
  
  return result.trim();
}
```

### Update the rendering pipeline

Find this line in the assistant message rendering:

```tsx
const processedContent = preprocessCitations(content);
```

Change to:

```tsx
const normalizedContent = normalizeMarkdownContent(content);
const processedContent = preprocessCitations(normalizedContent);
```

### Add temporary debug logging

Add this right after normalizeMarkdownContent call to verify it works:

```tsx
const normalizedContent = normalizeMarkdownContent(content);

// === DEBUG: Remove after confirming fix works ===
if (content.length > 100 && !content.includes('\n')) {
  console.log('[ChatMessage] Content has NO newlines from LLM');
  console.log('[ChatMessage] After normalizer, has newlines:', normalizedContent.includes('\n'));
  console.log('[ChatMessage] First 300 chars:', JSON.stringify(normalizedContent.substring(0, 300)));
}
// === END DEBUG ===

const processedContent = preprocessCitations(normalizedContent);
```

---

## Fix B: System Prompt Update in rag_service.py

Open `rag_service.py` and find where system prompts are constructed (look for the response style templates or the main system prompt builder).

Add these formatting instructions to EVERY system prompt, either in the base system prompt or in each style template:

```
CRITICAL FORMATTING RULES:
- Use proper markdown with line breaks
- Always put a blank line (two newlines) BEFORE each heading (##, ###, ####)
- Always put a blank line AFTER each heading before body text  
- Always put a blank line before a list (bullet points with -)
- Each list item (- ) should be on its own line
- Separate paragraphs with blank lines
- For markdown tables, each row must be on its own line

Example of CORRECT formatting:

### Key Findings

**Safety Compliance**: Bhilai Steel Plant had all 158 recommendations complied.

- **Production Targets**: SAIL aimed for 35.80 million tonnes by 2025-26
- **Historical Performance**: Under the 2008 Modernization Plan, capacity targets were missed

### Context & Background

The audit was initiated in response to the National Steel Policy, 2017.

Example of INCORRECT formatting (DO NOT DO THIS):
### Key Findings **Safety Compliance**: Bhilai Steel Plant had all 158 recommendations complied. - **Production Targets**: SAIL aimed for 35.80 million tonnes
```

This is the ROOT FIX. Once the LLM generates proper markdown, the frontend ReactMarkdown setup you already have will render it perfectly without needing the normalizer.

---

## Implementation Order

1. **First**: Apply Fix A (frontend normalizer) — this is a single-file change to ChatMessage.tsx
2. **Test**: Send a chat message, check browser console for debug output, verify headings render
3. **Second**: Apply Fix B (system prompt) — update rag_service.py prompt templates
4. **Test again**: The LLM should now generate proper markdown natively
5. **Clean up**: Remove the debug console.log from ChatMessage.tsx

## Files to change

| File | Change | Priority |
|------|--------|----------|
| `frontend/components/ChatMessage.tsx` | Add `normalizeMarkdownContent()`, update render pipeline | HIGH — do first |
| `services/rag_pipeline/rag_service.py` | Add formatting instructions to system prompts | HIGH — do second |

## What NOT to change

- `api.ts` — SSE parser is correct
- `chat.py` — SSE serialization is correct  
- `streaming_wrapper.py` — token streaming is correct
- `appStore.ts` — state management is correct
- `citationUtils.ts` — citation logic is correct
- ReactMarkdown component overrides in ChatMessage.tsx — already correct

## Verification Checklist

After Fix A (normalizer):
- [ ] Browser console shows: `Content has NO newlines from LLM`  
- [ ] Browser console shows: `After normalizer, has newlines: true`
- [ ] `### Heading` renders as actual styled heading (not literal `###`)
- [ ] `**bold text**` renders as bold
- [ ] `- list item` renders as bullet point
- [ ] Citation badges `[Section X, p.Y]` still render as blue pills
- [ ] Citation badges are still clickable (navigate to PDF page)

After Fix B (system prompt):
- [ ] Browser console shows content now HAS newlines from LLM directly
- [ ] Markdown renders cleanly without needing the normalizer
- [ ] Different response styles (Executive, Concise, Detailed, Technical) all have proper formatting

## Why previous fix attempts failed

The v1 instruction file correctly set up ReactMarkdown, component overrides, and citation handling. All of that code works — proven by citation badges rendering. But it assumed the content string contained newlines. Without newlines, `### Heading` in the middle of a line is treated by ReactMarkdown as literal text (per the CommonMark spec, ATX headings must be at the start of a line). The fix was always about the missing newlines, not the markdown renderer setup.
