/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hook for fetching time series from API
 * Replaces hardcoded AUDIT_SERIES with dynamic data
 */

import { useState, useEffect } from 'react';
import { fetchSeries, fetchSeriesById, TimeSeriesInfo, SeriesListResponse } from '../lib/api';

export interface UseSeriesResult {
  series: TimeSeriesInfo[];
  total: number;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export interface UseSeriesDetailResult {
  series: TimeSeriesInfo | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Hook to fetch all available time series
 */
export function useSeries(): UseSeriesResult {
  const [series, setSeries] = useState<TimeSeriesInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSeries = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetchSeries();
      setSeries(response.series);
      setTotal(response.total);
    } catch (err) {
      console.error('Failed to fetch series:', err);
      setError(err instanceof Error ? err.message : 'Failed to load time series');
      setSeries([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadSeries();
  }, []);

  return {
    series,
    total,
    isLoading,
    error,
    refetch: loadSeries,
  };
}

/**
 * Hook to fetch a specific time series by ID
 */
export function useSeriesDetail(seriesId: string | null): UseSeriesDetailResult {
  const [series, setSeries] = useState<TimeSeriesInfo | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSeries = async () => {
    if (!seriesId) {
      setSeries(null);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetchSeriesById(seriesId);
      setSeries(response);
    } catch (err) {
      console.error('Failed to fetch series detail:', err);
      setError(err instanceof Error ? err.message : 'Failed to load series');
      setSeries(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadSeries();
  }, [seriesId]);

  return {
    series,
    isLoading,
    error,
    refetch: loadSeries,
  };
}

export default useSeries;
