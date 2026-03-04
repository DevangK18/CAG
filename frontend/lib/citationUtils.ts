/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Citation Utilities - IMPROVED
 * Better parsing and normalization for citation matching
 */

import { CitationMap } from './api';

// ============================================================================
// Citation Parsing
// ============================================================================

export interface TextSegment {
  type: 'text' | 'citation';
  content: string;
}

/**
 * Split text into segments of regular text and citations
 * Handles multiple citation formats:
 * - [Section 2.3.3, p.54]
 * - [Sec 2.3, p.54]
 * - [Section 2.3.3, p54]
 * - [2.3.3, p.54]
 */
export function splitTextWithCitations(text: string): TextSegment[] {
  const segments: TextSegment[] = [];
  
  // More comprehensive regex to catch various citation formats
  // Matches: [anything with a page reference like p.54 or p54 or page 54]
  const citationRegex = /\[([^\]]*(?:p\.?\s*\d+|page\s*\d+)[^\]]*)\]/gi;
  
  let lastIndex = 0;
  let match;
  
  while ((match = citationRegex.exec(text)) !== null) {
    // Add text before citation
    if (match.index > lastIndex) {
      segments.push({
        type: 'text',
        content: text.slice(lastIndex, match.index),
      });
    }
    
    // Add citation (inner content without brackets)
    segments.push({
      type: 'citation',
      content: match[1].trim(),
    });
    
    lastIndex = match.index + match[0].length;
  }
  
  // Add remaining text
  if (lastIndex < text.length) {
    segments.push({
      type: 'text',
      content: text.slice(lastIndex),
    });
  }
  
  return segments;
}

// ============================================================================
// Citation Normalization - IMPROVED
// ============================================================================

/**
 * Normalize a citation key for fuzzy matching
 * IMPROVED: Preserves structure while normalizing case/whitespace
 */
export function normalizeCitationKey(key: string): string {
  return key
    .replace(/^\[|\]$/g, '')                    // Remove brackets
    .toLowerCase()                              // Case insensitive
    .replace(/\s+/g, ' ')                       // Collapse multiple whitespace to single space
    .replace(/\s*,\s*/g, ',')                   // Normalize comma spacing (no spaces around commas)
    .replace(/\b(page|pg)\s*/gi, 'p')           // Normalize "page" and "pg" to "p"
    .replace(/p\.\s*/gi, 'p')                   // Normalize "p." to "p"
    .trim();
}

/**
 * Extract section number and page number from citation
 */
export function extractCitationParts(citation: string): { section: string | null; page: number | null } {
  // Extract section number (e.g., "2.3.3" or "3.4")
  const sectionMatch = citation.match(/(\d+(?:\.\d+)*)/);
  const section = sectionMatch ? sectionMatch[1] : null;
  
  // Extract page number
  const pageMatch = citation.match(/(?:p\.?|page)\s*(\d+)/i);
  const page = pageMatch ? parseInt(pageMatch[1], 10) : null;
  
  return { section, page };
}

/**
 * Build a normalized lookup map from citation data
 * Creates multiple keys for each citation to improve matching
 */
export function buildNormalizedCitationMap(
  citationMap: CitationMap
): Map<string, CitationMap[string]> {
  const normalizedMap = new Map<string, CitationMap[string]>();
  
  for (const [key, value] of Object.entries(citationMap)) {
    // Primary key (fully normalized)
    const normalizedKey = normalizeCitationKey(key);
    normalizedMap.set(normalizedKey, value);
    
    // Also store with original key normalized
    const simpleNormalized = key.toLowerCase().replace(/\s+/g, '').replace(/,/g, '');
    normalizedMap.set(simpleNormalized, value);
    
    // Extract section and page for additional matching
    const { section, page } = extractCitationParts(key);
    
    if (section && page) {
      // Key format: "2.3.3p54"
      const shortKey = `${section}p${page}`;
      normalizedMap.set(shortKey, value);
      
      // Also try "section2.3.3p54"
      normalizedMap.set(`section${shortKey}`, value);
    }
    
    // Store by page_logical from the value itself
    if (value.page_logical && value.section) {
      const pageNum = value.page_logical.replace(/\D/g, '');
      const sectionNum = value.section.replace(/[^\d.]/g, '');
      if (pageNum && sectionNum) {
        normalizedMap.set(`${sectionNum}p${pageNum}`, value);
      }
    }
  }
  
  console.log('Built normalized citation map with', normalizedMap.size, 'entries');
  
  return normalizedMap;
}

/**
 * Look up a citation in the normalized map
 * Tries multiple matching strategies
 */
export function lookupCitation(
  citationText: string,
  normalizedMap: Map<string, CitationMap[string]>
): CitationMap[string] | null {
  if (normalizedMap.size === 0) {
    console.log('Citation map is empty');
    return null;
  }
  
  // Strategy 1: Try exact normalized match
  const normalized = normalizeCitationKey(citationText);
  console.log('Looking up citation:', citationText, '-> normalized:', normalized);
  
  if (normalizedMap.has(normalized)) {
    console.log('Found via exact normalized match');
    return normalizedMap.get(normalized)!;
  }
  
  // Strategy 2: Extract section and page, try direct match
  const { section, page } = extractCitationParts(citationText);
  console.log('Extracted parts - section:', section, 'page:', page);
  
  if (section && page) {
    const shortKey = `${section}p${page}`;
    if (normalizedMap.has(shortKey)) {
      console.log('Found via short key:', shortKey);
      return normalizedMap.get(shortKey)!;
    }
  }
  
  // Strategy 3: Try matching just by page number if we have one
  if (page) {
    // Look for any entry that matches this page
    for (const [key, value] of normalizedMap.entries()) {
      if (value.page_physical === page - 1 || value.page_logical === `${page}`) {
        console.log('Found via page number match');
        return value;
      }
    }
  }
  
  // Strategy 4: Fuzzy match - find closest
  const searchTerms = normalized.split(/p/);
  if (searchTerms.length >= 2) {
    const sectionPart = searchTerms[0];
    const pagePart = searchTerms[searchTerms.length - 1];

    for (const [key, value] of normalizedMap.entries()) {
      if (key.includes(sectionPart) && key.includes(`p${pagePart}`)) {
        console.log('Found via fuzzy match');
        return value;
      }
    }
  }

  // Strategy 5: Page-only fallback (safety net for LLM paraphrasing)
  // Only use if exactly one citation has this page number
  const pageMatch = citationText.match(/p\.?\s*(\d+)/i);
  if (pageMatch) {
    const targetPage = pageMatch[1];
    const pageMatches = Array.from(normalizedMap.entries()).filter(([key, value]) => {
      // Extract page number from normalized key (typically at end after 'p')
      const keyPageMatch = key.match(/p(\d+)/);
      return keyPageMatch && keyPageMatch[1] === targetPage;
    });

    // Only use this fallback if exactly one citation has this page number
    // If multiple citations share a page, we can't disambiguate
    if (pageMatches.length === 1) {
      console.log(`Citation fallback: matched "${citationText}" by unique page ${targetPage}`);
      return pageMatches[0][1];
    }
  }

  console.log('Citation not found in map. Available keys:', Array.from(normalizedMap.keys()).slice(0, 10));
  return null;
}
