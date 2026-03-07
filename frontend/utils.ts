/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
*/

export const generateId = () => Date.now().toString(36) + Math.random().toString(36).substring(2);

/**
 * Sanitize report titles for display in cards and lists.
 * 
 * Strategy:
 *  - Leading patterns: CONSERVATIVE — only strip clearly redundant prefixes
 *  - Trailing patterns: AGGRESSIVE — government labels, audit type tags, report numbers are always boilerplate
 *  - Always capitalize first letter as final step
 *
 * @param title - Raw report title from API
 * @returns Cleaned title for display
 */
export function sanitizeReportTitle(title: string): string {
  if (!title) return '';

  let cleaned = title;

  // =============================================
  // PHASE 1: Leading prefixes (conservative)
  // =============================================

  // 1. "Audit Report No. X of YYYY-" prefix
  cleaned = cleaned.replace(/^Audit\s+Report\s*(No\.?\s*)?\d+\s*of\s*\d{4}\s*[-–,]?\s*/i, '');

  // 2. "Report No. X of YYYY" prefix (all variations)
  cleaned = cleaned.replace(/^Report\s*(No\.?\s*)?\d+\s*of\s*\d{4}\s*[-–,]?\s*/i, '');

  // 3. Leading "of the" left over after prefix strip
  cleaned = cleaned.replace(/^of\s+the\s+/i, '');

  // 4. "Report of the" prefix (without number)
  cleaned = cleaned.replace(/^Report\s+of\s+the\s+/i, '');

  // 5. TARGETED: "Union Government – Ministry of X – Performance/Compliance Audit on/of Y"
  //    Only strip when the FULL chain (UG → Ministry → Audit keyword) is present.
  //    This avoids over-stripping titles like "Union Government, Department of Revenue – Direct Taxes"
  cleaned = cleaned.replace(
    /^Union\s+Government\s*(\([^)]*\))?\s*[-–,]\s*(Ministry|Department)\s+of\s+[^–-]+[-–]\s*(Performance|Compliance|Financial)\s+Audit\s+(on|of)\s+/i,
    ''
  );

  // =============================================
  // PHASE 2: Internal boilerplate
  // =============================================

  // 6. "Comptroller and Auditor General of India"
  cleaned = cleaned.replace(/Comptroller and Auditor General of India\s*(on)?/gi, '');

  // 7. "CAG" variations
  cleaned = cleaned.replace(/CAG['''\u2019]?s?\s*/gi, '');

  // =============================================
  // PHASE 3: Trailing boilerplate (aggressive — always safe to remove)
  // =============================================

  // 8. Trailing "(Performance Audit-Commercial)", "(Compliance Audit-Railways)", "(Financial Audit)" etc.
  cleaned = cleaned.replace(/\s*\((Performance|Compliance|Financial)\s+Audit[-–]?[^)]*\)\s*$/i, '');

  // 9. Trailing "- Report No.26 of 2025" or "Report No. 3 of 2025 (Type)"
  cleaned = cleaned.replace(/[-–]?\s*Report\s*No\.?\s*\d+\s*of\s*\d{4}\s*(\([^)]+\))?\s*$/i, '');

  // 10. Trailing "No. X of YYYY" without "Report" word
  cleaned = cleaned.replace(/\s+No\.?\s*\d+\s*of\s*\d{4}\s*$/i, '');

  // 11. Trailing "Government (qualifier)" — e.g., "Government (Compliance Audit-Railways)" or standalone "Government"
  cleaned = cleaned.replace(/\s+Government\s*(\([^)]+\))?\s*$/i, '');

  // 12. Trailing "Union Government (Civil) National Health Authority Ministry of Health and Family Welfare" etc.
  cleaned = cleaned.replace(/\s+Union\s+Government\s*(\([^)]*\))?\s*(National\s+\w+\s+Authority\s+)?(Ministry|Department)\s+of\s+.+$/i, '');

  // 13. Trailing standalone "Union Government (qualifier)"
  cleaned = cleaned.replace(/\s+Union\s+Government\s*(\([^)]+\))?\s*$/i, '');

  // 14. Trailing "Ministry of X No. X of YYYY" — handles "Ministry of Coal No. 35 of 2025"
  cleaned = cleaned.replace(/\s+Ministry\s+of\s+[\w\s]+?No\.?\s*\d+\s*of\s*\d{4}\s*$/i, '');

  // 15. Trailing "– Ministry/Department of X"
  cleaned = cleaned.replace(/\s*[-–]\s*(Ministry|Department)\s+of\s+.+$/i, '');

  // =============================================
  // PHASE 4: Final cleanup
  // =============================================

  // 16. Re-run leading "of the" (trailing strips may have exposed it)
  cleaned = cleaned.replace(/^of\s+the\s+/i, '');

  // 17. Leading "on " residual
  cleaned = cleaned.replace(/^on\s+/i, '');

  // 18. Surrounding smart/straight quotes
  cleaned = cleaned.replace(/^["""\u201C\u201D]+/, '');
  cleaned = cleaned.replace(/["""\u201C\u201D]+$/, '');

  // 19. Trim, collapse whitespace, strip leading/trailing punctuation
  cleaned = cleaned.trim();
  cleaned = cleaned.replace(/^[-–,:\s]+/, '');
  cleaned = cleaned.replace(/[-–,:\s]+$/, '');
  cleaned = cleaned.replace(/\s+/g, ' ');

  // 20. Capitalize first letter
  if (cleaned.length > 0) {
    cleaned = cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
  }

  return cleaned || title;
}