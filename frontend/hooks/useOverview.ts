/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hook for fetching report overview data (Phase 10)
 * 
 * Provides rich overview data including:
 * - Audit scope, objectives, topics
 * - Findings summary and list
 * - Recommendations
 * - Glossary terms
 * - Table of contents for PDF navigation
 */

import { useState, useEffect, useCallback } from 'react';
import { 
  fetchReportOverview,
  OverviewResponse,
  AuditScope,
  TopicCovered,
  GlossaryTerm,
  FindingSummaryData,
  FindingItem,
  RecommendationItem,
  TOCEntry
} from '../lib/api';

export interface UseOverviewResult {
  // Full data
  overview: OverviewResponse | null;
  
  // Convenient accessors
  auditScope: AuditScope | null;
  auditObjectives: string[];
  topicsCovered: TopicCovered[];
  glossaryTerms: GlossaryTerm[];
  findingsSummary: FindingSummaryData | null;
  findingsList: FindingItem[];
  recommendations: RecommendationItem[];
  tableOfContents: TOCEntry[];
  
  // Metadata
  isLLMExtracted: boolean;
  hasSummaries: boolean;
  generatedAt: string | null;
  
  // State
  isLoading: boolean;
  error: string | null;
  
  // Actions
  refetch: () => Promise<void>;
}

export function useOverview(reportId: string | null): UseOverviewResult {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const fetchData = useCallback(async () => {
    if (!reportId) {
      setOverview(null);
      return;
    }
    
    setIsLoading(true);
    setError(null);
    
    try {
      const data = await fetchReportOverview(reportId);
      setOverview(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch overview';
      setError(message);
      setOverview(null);
    } finally {
      setIsLoading(false);
    }
  }, [reportId]);
  
  useEffect(() => {
    fetchData();
  }, [fetchData]);
  
  // Convenient accessors with safe defaults
  const auditScope = overview?.audit_scope || null;
  const auditObjectives = overview?.audit_objectives || [];
  const topicsCovered = overview?.topics_covered || [];
  const glossaryTerms = overview?.glossary_terms || [];
  const findingsSummary = overview?.findings_summary || null;
  const findingsList = overview?.findings_list || [];
  const recommendations = overview?.recommendations || [];
  const tableOfContents = overview?.table_of_contents || [];
  
  // Metadata flags
  const isLLMExtracted = overview?._metadata?.llm_extraction_available || false;
  const hasSummaries = overview?._metadata?.summaries_available || false;
  const generatedAt = overview?._metadata?.generated_at || null;
  
  return {
    overview,
    auditScope,
    auditObjectives,
    topicsCovered,
    glossaryTerms,
    findingsSummary,
    findingsList,
    recommendations,
    tableOfContents,
    isLLMExtracted,
    hasSummaries,
    generatedAt,
    isLoading,
    error,
    refetch: fetchData,
  };
}

export default useOverview;