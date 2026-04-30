/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * useHomeStats - Fetch home page stats
 * Single fetch on mount, session-cached
 */

import { useState, useEffect } from 'react';
import { getHomeStats } from '../lib/api';
import type { HomeStats } from '../types';

interface UseHomeStatsReturn {
  stats: HomeStats | null;
  isLoading: boolean;
  error: string | null;
}

export function useHomeStats(): UseHomeStatsReturn {
  const [stats, setStats] = useState<HomeStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function fetchStats() {
      try {
        setIsLoading(true);
        setError(null);
        const data = await getHomeStats();
        if (isMounted) {
          setStats(data);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Failed to fetch stats');
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    fetchStats();

    return () => {
      isMounted = false;
    };
  }, []); // Empty deps - fetch once on mount

  return { stats, isLoading, error };
}
