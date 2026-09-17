/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * useHomeFeatured - Fetch home page featured content
 * Single fetch on mount, session-cached
 */

import { useState, useEffect } from 'react';
import { getHomeFeatured } from '../lib/api';
import type { HomeFeatured } from '../types';

interface UseHomeFeaturedReturn {
  featured: HomeFeatured | null;
  isLoading: boolean;
  error: string | null;
}

export function useHomeFeatured(): UseHomeFeaturedReturn {
  const [featured, setFeatured] = useState<HomeFeatured | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function fetchFeatured() {
      try {
        setIsLoading(true);
        setError(null);
        const data = await getHomeFeatured();
        if (isMounted) {
          setFeatured(data);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Failed to fetch featured content');
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    fetchFeatured();

    return () => {
      isMounted = false;
    };
  }, []); // Empty deps - fetch once on mount

  return { featured, isLoading, error };
}
