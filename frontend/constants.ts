/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Constants for CAG Gateway
 * Static data for time series analysis
 */

import { ReportSeries } from './types';

/**
 * Pre-defined audit series for time series analysis
 * These link related reports across multiple years
 * 
 * Note: This is currently static/hardcoded. 
 * Future: Replace with dynamic API endpoint /series
 */
export const AUDIT_SERIES: ReportSeries[] = [
  {
    id: 'direct-taxes-series',
    topic: 'Direct Taxes Compliance',
    ministry: 'Ministry of Finance',
    description: 'Track compliance and assessment trends in direct tax collection across multiple financial years.',
    reportIds: [
      '2024_13_Report_of_the_Comptroller_and_Auditor_General_of_India_on_Direct_Taxes',
      '2020_16_Performance_Audit_on_Assessment_of_Cooperative_Societies_and_Cooperative_Banks_Union_Government_Department_of_Revenue_Direct_Taxes',
    ]
  },
  {
    id: 'union-accounts-series',
    topic: 'Union Government Accounts',
    ministry: 'Ministry of Finance',
    description: 'Annual financial audit of Union Government accounts covering receipts, expenditure, and fiscal management.',
    reportIds: [
      '2025_16_CAG_Report_on_Union_Government_Accounts_202324_Financial_Audit',
    ]
  },
  // Add more series as reports are added to the system
];

/**
 * Sector color mapping for visual differentiation in report cards
 * Professional muted tones for sector pills
 * Format: { bg: 'bg-class', text: 'text-class' }
 */
export const SECTOR_COLORS: Record<string, { bg: string; text: string }> = {
  'Taxes and Duties': { bg: 'bg-slate-100', text: 'text-slate-700' },
  'Direct Taxes': { bg: 'bg-slate-100', text: 'text-slate-700' },
  'Finance': { bg: 'bg-sky-50', text: 'text-sky-700' },
  'Commercial': { bg: 'bg-stone-100', text: 'text-stone-600' },
  'Social Infrastructure': { bg: 'bg-slate-100', text: 'text-slate-600' },
  'Education': { bg: 'bg-slate-100', text: 'text-slate-600' },
  'Health': { bg: 'bg-slate-100', text: 'text-slate-600' },
  'Union Government (Civil)': { bg: 'bg-slate-100', text: 'text-slate-600' },
  'Transport & Infrastructure': { bg: 'bg-slate-100', text: 'text-slate-600' },
  'Defence': { bg: 'bg-slate-100', text: 'text-slate-600' },
  'Railways': { bg: 'bg-slate-100', text: 'text-slate-600' },
  'GST': { bg: 'bg-slate-100', text: 'text-slate-700' },
  'Customs': { bg: 'bg-slate-100', text: 'text-slate-700' },
  'Income Tax': { bg: 'bg-slate-100', text: 'text-slate-700' },
  // Fallback for unmapped sectors
  'default': { bg: 'bg-slate-100', text: 'text-slate-600' }
};

/**
 * Get sector color classes with fallback
 * @param sector - Sector name
 * @returns Object with bg and text color classes
 */
export function getSectorColor(sector: string): { bg: string; text: string } {
  return SECTOR_COLORS[sector] || SECTOR_COLORS['default'];
}

/**
 * Report type mapping for badges
 */
export const REPORT_TYPES: Record<string, string> = {
  'Financial Audit': 'Financial Audit',
  'Performance Audit': 'Performance Audit',
  'Compliance Audit': 'Compliance Audit',
  'default': 'Audit Report'
};

/**
 * Get report type display name
 * @param reportType - Report type from metadata
 * @returns Display name for report type
 */
export function getReportType(reportType: string | undefined): string {
  if (!reportType) return REPORT_TYPES['default'];
  return REPORT_TYPES[reportType] || reportType;
}
