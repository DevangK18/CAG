/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
*/

export const generateId = () => Date.now().toString(36) + Math.random().toString(36).substring(2);

/**
 * Sanitize report titles for display in cards and lists
 * Removes redundant prefixes, CAG references, and boilerplate text
 *
 * @param title - Raw report title from API
 * @returns Cleaned title for display
 */
export function sanitizeReportTitle(title: string): string {
  if (!title) return '';

  let cleaned = title;

  // 1. Remove "Report No. X of YYYY" prefixes with all variations
  // Handles: "Report No. 13 of 2024 - ", "Report no. 3 of 2025, of the", "Report 16 of 2025 of the"
  cleaned = cleaned.replace(/^Report\s*(No\.?\s*)?\d+\s*of\s*\d{4}\s*[-–,]?\s*/i, '');

  // 1b. Remove leading "of the" that remains after stripping report number
  cleaned = cleaned.replace(/^of\s+the\s+/i, '');

  // 1c. Also handle "Report of the" prefix (without number)
  cleaned = cleaned.replace(/^Report\s+of\s+the\s+/i, '');

  // 2. Remove "Comptroller and Auditor General of India" references (anywhere in string)
  cleaned = cleaned.replace(/Comptroller and Auditor General of India\s*(on)?/gi, '');

  // 3. Remove "CAG" variations (with apostrophes and possessive forms)
  cleaned = cleaned.replace(/CAG['']?s?\s*/gi, '');

  // 4. Remove report number suffix patterns like "Report No. XX of 20XX (Financial Audit)" at the end
  cleaned = cleaned.replace(/Report\s*No\.?\s*\d+\s*of\s*\d{4}\s*\([^)]+\)\s*$/i, '');

  // 4b. Also remove trailing "Union Government Ministry of..." or "Union Government Department of..." boilerplate
  cleaned = cleaned.replace(/\s+Union Government\s+(Ministry|Department)\s+of\s+.+$/i, '');

  // 4c. Remove standalone trailing "Union Government (Civil)" or similar
  cleaned = cleaned.replace(/\s+Union Government\s*(\([^)]+\))?\s*$/i, '');

  // 5. Clean up again - remove any remaining leading "of the" after all transformations
  cleaned = cleaned.replace(/^of\s+the\s+/i, '');

  // 6. Trim, collapse whitespace, remove leading dashes/commas/colons
  cleaned = cleaned.trim();
  cleaned = cleaned.replace(/^[-–,:\s]+/, ''); // Remove leading punctuation
  cleaned = cleaned.replace(/[-–,:\s]+$/, ''); // Remove trailing punctuation
  cleaned = cleaned.replace(/\s+/g, ' '); // Collapse multiple spaces

  return cleaned || title; // Fallback to original if everything was stripped
}