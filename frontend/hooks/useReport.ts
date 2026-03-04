/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hook for fetching a single report's details
 */

import { useState, useEffect, useCallback } from 'react';
import { fetchReport, APIReportDetail, getPdfUrl } from '../lib/api';
import { AuditReport } from '../types';

// Transform API response to match existing AuditReport type
function transformReport(apiReport: APIReportDetail): AuditReport {
  const impact = apiReport.monetary_impact || 'N/A';
  
  const statusMap: Record<string, AuditReport['status']> = {
    'Action Pending': 'Action Pending',
    'Under Review': 'Under Review',
    'Compliant': 'Compliant',
    'Partial Compliance': 'Partial Compliance',
  };
  
  return {
    id: apiReport.id,
    title: apiReport.title,
    reportNumber: `Report ${apiReport.report_no}`,
    ministry: apiReport.ministry,
    sector: apiReport.sector,
    year: apiReport.year,
    pages: apiReport.pages,
    findingsCount: apiReport.findings_count,
    impact: impact,
    status: statusMap[apiReport.status] || 'Under Review',
    summary: apiReport.executive_summary,
    findings: apiReport.key_findings,
    recommendations: apiReport.recommendations,
    reportType: apiReport.report_type || undefined
  };
}

export interface UseReportResult {
  report: AuditReport | null;
  pdfUrl: string | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useReport(reportId: string | null): UseReportResult {
  const [report, setReport] = useState<AuditReport | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const fetchData = useCallback(async () => {
    if (!reportId) {
      setReport(null);
      setPdfUrl(null);
      return;
    }
    
    setIsLoading(true);
    setError(null);
    
    try {
      const data = await fetchReport(reportId);
      const transformed = transformReport(data);
      setReport(transformed);
      
      // Build PDF URL
      setPdfUrl(getPdfUrl(data.filename));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch report');
      setReport(null);
      setPdfUrl(null);
    } finally {
      setIsLoading(false);
    }
  }, [reportId]);
  
  useEffect(() => {
    fetchData();
  }, [fetchData]);
  
  return {
    report,
    pdfUrl,
    isLoading,
    error,
    refetch: fetchData,
  };
}

export default useReport;
