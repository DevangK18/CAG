/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Hook for fetching report filter options from API
 */

import { useState, useEffect } from 'react';
import { fetchReportFilters, ReportFiltersResponse } from '../lib/api';

export interface UseFiltersResult {
  filters: ReportFiltersResponse | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useFetchFilters(): UseFiltersResult {
  const [filters, setFilters] = useState<ReportFiltersResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const data = await fetchReportFilters();
      setFilters(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch filters');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  return {
    filters,
    isLoading,
    error,
    refetch: fetchData,
  };
}

export default useFetchFilters;
