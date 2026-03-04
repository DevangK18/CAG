/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hook for fetching tables from a report
 */

import { useState, useEffect } from 'react';
import { fetchReportTables, TableItem, TablesResponse } from '../lib/api';

export interface UseTablesResult {
  tables: TableItem[];
  total: number;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useTables(reportId: string | null): UseTablesResult {
  const [tables, setTables] = useState<TableItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTables = async () => {
    if (!reportId) {
      setTables([]);
      setTotal(0);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetchReportTables(reportId);
      setTables(response.tables);
      setTotal(response.total);
    } catch (err) {
      console.error('Failed to fetch tables:', err);
      setError(err instanceof Error ? err.message : 'Failed to load tables');
      setTables([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTables();
  }, [reportId]);

  return {
    tables,
    total,
    isLoading,
    error,
    refetch: fetchTables,
  };
}

export default useTables;
