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

/**
 * Government tier type for tier selector
 */
export type GovernmentTier = 'union' | 'state' | 'local';

/**
 * Demo report interface for State/Local tiers
 */
export interface DemoReport {
  id: string;
  title: string;
  state: string;
  year: number;
  reportNumber: string;
  auditType: string;
  sectors: string[];
  findings: number | null;
  bodyType?: string; // For Local Bodies only
}

/**
 * Hardcoded State Government reports
 */
export const STATE_REPORTS: DemoReport[] = [
  {
    id: 'state-uttarakhand-mgnregs-2025',
    title: "Mahatma Gandhi National Rural Employment Guarantee Scheme, Uttarakhand",
    state: "Uttarakhand",
    year: 2025,
    reportNumber: "Report 06 of 2025",
    auditType: "Performance Audit",
    sectors: ["Social Welfare"],
    findings: null,
  },
  {
    id: 'state-mh-workers-2025',
    title: "Welfare of Building and Other Construction Workers, Government of Maharashtra",
    state: "Maharashtra",
    year: 2025,
    reportNumber: "Report 04 of 2025",
    auditType: "Performance Audit",
    sectors: ["Social Welfare"],
    findings: null,
  },
  {
    id: 'state-assam-2024',
    title: "Audit Report on Social, Economic and General Sectors, Government of Assam",
    state: "Assam",
    year: 2024,
    reportNumber: "Report 02 of 2024",
    auditType: "Compliance Audit",
    sectors: ["Social Welfare"],
    findings: null,
  },
  {
    id: 'state-uttarakhand-finance-2025',
    title: "Audit Report on State Finances for Uttarakhand 2023-24",
    state: "Uttarakhand",
    year: 2025,
    reportNumber: "Report 01 of 2025",
    auditType: "Financial Audit",
    sectors: ["Finance"],
    findings: null,
  },
  {
    id: 'state-kerala-2025',
    title: "Combined Report of the Comptroller and Auditor General of India on Kerala for the period ended March 2023",
    state: "Kerala",
    year: 2025,
    reportNumber: "Report 06 of 2025",
    auditType: "Compliance Audit",
    sectors: ["Finance"],
    findings: null,
  },
  {
    id: 'state-odisha-2025',
    title: "School Education in Odisha, School and Mass Education Department",
    state: "Odisha",
    year: 2025,
    reportNumber: "Report 05 of 2025",
    auditType: "Performance Audit",
    sectors: ["Education, Health & Family Welfare"],
    findings: null,
  },
  {
    id: 'state-up-pmay-2025',
    title: "Performance Audit of Implementation of Pradhan Mantri Awaas Yojana - Gramin in Uttar Pradesh",
    state: "Uttar Pradesh",
    year: 2025,
    reportNumber: "Report 08 of 2025",
    auditType: "Performance Audit",
    sectors: ["Social Welfare"],
    findings: null,
  },
  {
    id: 'state-gujarat-nsap-2024',
    title: "Implementation of National Social Assistance Programme through Direct Benefit Transfer Scheme in Gujarat",
    state: "Gujarat",
    year: 2024,
    reportNumber: "Report 03 of 2024",
    auditType: "Performance Audit",
    sectors: ["Social Welfare"],
    findings: null,
  },
  {
    id: 'state-jharkhand-2025',
    title: "State Finances Audit Report of the Government of Jharkhand for the year 2023-24",
    state: "Jharkhand",
    year: 2025,
    reportNumber: "Report 02 of 2025",
    auditType: "Financial Audit",
    sectors: ["Finance"],
    findings: null,
  },
  {
    id: 'state-rajasthan-health-2025',
    title: "Audit of Public Health Infrastructure and Management of Health Services in Rajasthan",
    state: "Rajasthan",
    year: 2025,
    reportNumber: "Report 04 of 2025",
    auditType: "Performance Audit",
    sectors: ["Social Welfare", "Education, Health & Family Welfare"],
    findings: null,
  },
];

/**
 * Hardcoded Local Bodies reports
 */
export const LOCAL_BODY_REPORTS: DemoReport[] = [
  {
    id: 'local-bihar-2024',
    title: "Report on Local Government Institutions in Bihar",
    state: "Bihar",
    year: 2024,
    reportNumber: "Report of 2024",
    auditType: "Compliance Audit",
    bodyType: "PRIs & ULBs",
    sectors: ["Local Governance"],
    findings: null,
  },
  {
    id: 'local-chhattisgarh-2025',
    title: "Report on Local Bodies in Chhattisgarh",
    state: "Chhattisgarh",
    year: 2025,
    reportNumber: "Report of 2025",
    auditType: "Compliance Audit",
    bodyType: "PRIs & ULBs",
    sectors: ["Local Governance"],
    findings: null,
  },
  {
    id: 'local-hp-2024',
    title: "ATIR on Panchayati Raj Institutions and Urban Local Bodies",
    state: "Himachal Pradesh",
    year: 2024,
    reportNumber: "ATIR 2024",
    auditType: "ATIR",
    bodyType: "PRIs & ULBs",
    sectors: ["Local Governance"],
    findings: null,
  },
  {
    id: 'local-mh-2024',
    title: "ATIR on Local Bodies of Maharashtra",
    state: "Maharashtra",
    year: 2024,
    reportNumber: "ATIR 2024",
    auditType: "ATIR",
    bodyType: "ULBs",
    sectors: ["Local Governance"],
    findings: null,
  },
];

/**
 * Stats for State tier
 */
export const STATE_STATS = {
  totalReports: 10,
  totalFindings: '—',
  monetaryDisplay: '—',
  ministryCount: 9,
  sectorCount: 3,
  yearSpan: '2024–2025',
  ministryLabel: 'States',
};

/**
 * Stats for Local Bodies tier
 */
export const LOCAL_STATS = {
  totalReports: 4,
  totalFindings: '—',
  monetaryDisplay: '—',
  ministryCount: 4,
  sectorCount: 1,
  yearSpan: '2024–2025',
  ministryLabel: 'States',
};
