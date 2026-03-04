/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hook for fetching report summaries (Phase 10)
 * 
 * Provides:
 * - List of available summary variants
 * - Fetch specific variant content
 * - Random variant (Surprise Me)
 * - Caching of loaded variants
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchSummariesList,
  fetchSummary,
  fetchRandomSummary,
  SummariesListResponse,
  SummaryContentResponse,
  SummaryVariant,
  SummaryVariantInfo
} from '../lib/api';
import { trackEvent } from '../lib/posthog';

export interface UseSummariesResult {
  // Variant list
  variantList: SummaryVariantInfo[];
  totalVariants: number;
  generatedAt: string | null;
  
  // Current selected variant content
  currentVariant: SummaryVariant | null;
  currentContent: SummaryContentResponse | null;
  
  // State
  isLoadingList: boolean;
  isLoadingContent: boolean;
  listError: string | null;
  contentError: string | null;
  
  // Computed
  isAvailable: boolean;
  
  // Actions
  selectVariant: (variant: SummaryVariant) => Promise<void>;
  fetchRandom: () => Promise<void>;
  refetchList: () => Promise<void>;
  clearContent: () => void;
}

export function useSummaries(reportId: string | null): UseSummariesResult {
  // List state
  const [listData, setListData] = useState<SummariesListResponse | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  
  // Content state
  const [currentVariant, setCurrentVariant] = useState<SummaryVariant | null>(null);
  const [currentContent, setCurrentContent] = useState<SummaryContentResponse | null>(null);
  const [isLoadingContent, setIsLoadingContent] = useState(false);
  const [contentError, setContentError] = useState<string | null>(null);
  
  // Cache for loaded variants
  const contentCache = useRef<Map<string, SummaryContentResponse>>(new Map());
  
  // Fetch list of variants
  const fetchList = useCallback(async () => {
    if (!reportId) {
      setListData(null);
      return;
    }
    
    setIsLoadingList(true);
    setListError(null);
    
    try {
      const data = await fetchSummariesList(reportId);
      setListData(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch summaries';
      setListError(message);
      setListData(null);
    } finally {
      setIsLoadingList(false);
    }
  }, [reportId]);
  
  // Fetch specific variant content
  const selectVariant = useCallback(async (variant: SummaryVariant) => {
    if (!reportId) return;
    
    // Check cache first
    const cacheKey = `${reportId}:${variant}`;
    const cached = contentCache.current.get(cacheKey);
    
    if (cached) {
      setCurrentVariant(variant);
      setCurrentContent(cached);
      setContentError(null);

      // Track summary viewed (from cache)
      trackEvent('summary_viewed', {
        report_id: reportId,
        summary_type: variant,
        from_cache: true
      });

      return;
    }

    setCurrentVariant(variant);
    setIsLoadingContent(true);
    setContentError(null);

    try {
      const data = await fetchSummary(reportId, variant);
      setCurrentContent(data);

      // Track summary viewed
      trackEvent('summary_viewed', {
        report_id: reportId,
        summary_type: variant,
        from_cache: false
      });

      // Cache the result
      contentCache.current.set(cacheKey, data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch summary';
      setContentError(message);
      setCurrentContent(null);
    } finally {
      setIsLoadingContent(false);
    }
  }, [reportId]);
  
  // Fetch random variant
  const fetchRandom = useCallback(async () => {
    if (!reportId) return;
    
    setIsLoadingContent(true);
    setContentError(null);
    
    try {
      const data = await fetchRandomSummary(reportId);
      setCurrentVariant(data.variant);
      setCurrentContent(data);
      
      // Cache the result
      const cacheKey = `${reportId}:${data.variant}`;
      contentCache.current.set(cacheKey, data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch random summary';
      setContentError(message);
    } finally {
      setIsLoadingContent(false);
    }
  }, [reportId]);
  
  // Clear current content
  const clearContent = useCallback(() => {
    setCurrentVariant(null);
    setCurrentContent(null);
    setContentError(null);
  }, []);
  
  // Load list on mount/reportId change
  useEffect(() => {
    fetchList();
    // Reset content when report changes
    setCurrentVariant(null);
    setCurrentContent(null);
    setContentError(null);
    // Clear cache for new report
    contentCache.current.clear();
  }, [fetchList]);
  
  // Computed: whether summaries are available for this report
  const isAvailable = !listError && (listData?.total_variants ?? 0) > 0;
  
  return {
    variantList: listData?.variants || [],
    totalVariants: listData?.total_variants || 0,
    generatedAt: listData?.generated_at || null,
    currentVariant,
    currentContent,
    isLoadingList,
    isLoadingContent,
    listError,
    contentError,
    isAvailable,
    selectVariant,
    fetchRandom,
    refetchList: fetchList,
    clearContent,
  };
}

export default useSummaries;