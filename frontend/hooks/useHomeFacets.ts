/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * useHomeFacets - Fetch home page facets
 * Single fetch on mount, session-cached
 */

import { useState, useEffect } from 'react';
import { getHomeFacets } from '../lib/api';
import type { HomeFacets } from '../types';

interface UseHomeFacetsReturn {
  facets: HomeFacets | null;
  isLoading: boolean;
  error: string | null;
}

export function useHomeFacets(): UseHomeFacetsReturn {
  const [facets, setFacets] = useState<HomeFacets | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function fetchFacets() {
      try {
        setIsLoading(true);
        setError(null);
        const data = await getHomeFacets();
        if (isMounted) {
          setFacets(data);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Failed to fetch facets');
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    fetchFacets();

    return () => {
      isMounted = false;
    };
  }, []); // Empty deps - fetch once on mount

  return { facets, isLoading, error };
}
