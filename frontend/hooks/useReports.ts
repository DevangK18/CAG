/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hook for fetching reports from API
 */

import { useState, useEffect, useCallback } from 'react';
import { fetchReports, APIReportSummary } from '../lib/api';
import { AuditReport } from '../types';

// Transform API response to match existing AuditReport type
function transformReport(apiReport: APIReportSummary): AuditReport {
  // Parse monetary impact from string like "₹847.00 crore"
  const impact = apiReport.monetary_impact || 'N/A';

  // Map API status to expected status type
  const statusMap: Record<string, AuditReport['status']> = {
    'Action Pending': 'Action Pending',
    'Under Review': 'Under Review',
    'Compliant': 'Compliant',
    'Partial Compliance': 'Partial Compliance',
  };

  // Handle report_no: only prepend "Report" if we have a valid, non-N/A value
  // Backend now returns normalized format like "16 of 2020" or "N/A" for missing
  const reportNo = apiReport.report_no;
  const hasValidReportNo = reportNo && reportNo !== 'N/A' && reportNo.toLowerCase() !== 'unknown';
  const reportNumber = hasValidReportNo ? `Report ${reportNo}` : null;

  return {
    id: apiReport.id,
    title: apiReport.title,
    reportNumber,
    ministry: apiReport.ministry,
    sector: apiReport.sector,
    year: apiReport.year,
    pages: 0, // Not in summary, will be fetched in detail
    findingsCount: apiReport.findings_count,
    impact: impact,
    status: statusMap[apiReport.status] || 'Under Review',
    summary: '', // Not in summary
    findings: [],
    recommendations: [],
    reportType: apiReport.report_type || undefined,
    government_body_type: (apiReport.government_body_type as any) || 'union',
    state_name: apiReport.state_name,
    department: apiReport.department,
    audit_category: (apiReport.audit_category as any) || 'compliance',
  };
}

export interface UseReportsResult {
  reports: AuditReport[];
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  
  // Computed stats
  stats: {
    totalReports: number;
    totalFindings: number;
    totalImpact: string;
    ministryCount: number;
  };
}

export function useReports(params?: {
  sector?: string;
  year?: number;
  government_body_type?: string;
  state_name?: string;
  audit_category?: string;
}): UseReportsResult {
  const [reports, setReports] = useState<AuditReport[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const data = await fetchReports(params);
      const transformed = data.reports.map(transformReport);
      setReports(transformed);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch reports');
    } finally {
      setIsLoading(false);
    }
  }, [params?.sector, params?.year, params?.government_body_type, params?.state_name, params?.audit_category]);
  
  useEffect(() => {
    fetchData();
  }, [fetchData]);
  
  // Compute statistics
  const stats = {
    totalReports: reports.length,
    totalFindings: reports.reduce((sum, r) => sum + r.findingsCount, 0),
    totalImpact: calculateTotalImpact(reports),
    ministryCount: new Set(reports.map(r => r.ministry)).size,
  };
  
  return {
    reports,
    isLoading,
    error,
    refetch: fetchData,
    stats,
  };
}

// Helper to calculate total impact from reports
function calculateTotalImpact(reports: AuditReport[]): string {
  let total = 0;
  
  for (const report of reports) {
    const match = report.impact.match(/₹?([\d,]+(?:\.\d+)?)\s*(?:crore|cr)/i);
    if (match) {
      total += parseFloat(match[1].replace(/,/g, ''));
    }
  }
  
  if (total === 0) return 'N/A';
  if (total >= 1000) return `₹${Math.round(total / 1000)},000cr+`;
  return `₹${Math.round(total)}cr+`;
}

export default useReports;
