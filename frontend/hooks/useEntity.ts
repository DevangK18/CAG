/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Hook for fetching entity details with per-ID caching
 * Phase D: Entity page support
 */

import { useState, useEffect } from 'react';
import { getEntityFull } from '../lib/api';
import { EntityDetail } from '../types';

// Module-level cache: Map<entityId, EntityDetail>
const entityCache = new Map<number, EntityDetail>();

export interface UseEntityResult {
  entity: EntityDetail | null;
  isLoading: boolean;
  error: string | null;
}

export function useEntity(entityId: number | null): UseEntityResult {
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Reset state when entityId changes
    if (!entityId) {
      setEntity(null);
      setIsLoading(false);
      setError(null);
      return;
    }

    // Check cache first
    const cached = entityCache.get(entityId);
    if (cached) {
      setEntity(cached);
      setIsLoading(false);
      setError(null);
      return;
    }

    // Fetch if not cached
    let cancelled = false;

    const fetchEntity = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const data = await getEntityFull(entityId);
        if (!cancelled) {
          // Cache the result
          entityCache.set(entityId, data);
          setEntity(data);
          setIsLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          const errorMessage = err instanceof Error ? err.message : 'Failed to fetch entity';
          setError(errorMessage);
          setIsLoading(false);
        }
      }
    };

    fetchEntity();

    return () => {
      cancelled = true;
    };
  }, [entityId]);

  return { entity, isLoading, error };
}
