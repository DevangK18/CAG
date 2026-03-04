/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hook for fetching charts from a report
 */

import { useState, useEffect } from 'react';
import { fetchReportCharts, ChartItem, ChartsResponse } from '../lib/api';

export interface UseChartsResult {
  charts: ChartItem[];
  total: number;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useCharts(reportId: string | null): UseChartsResult {
  const [charts, setCharts] = useState<ChartItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCharts = async () => {
    if (!reportId) {
      setCharts([]);
      setTotal(0);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetchReportCharts(reportId);
      setCharts(response.charts);
      setTotal(response.total);
    } catch (err) {
      console.error('Failed to fetch charts:', err);
      setError(err instanceof Error ? err.message : 'Failed to load charts');
      setCharts([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchCharts();
  }, [reportId]);

  return {
    charts,
    total,
    isLoading,
    error,
    refetch: fetchCharts,
  };
}

export default useCharts;
