/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * useSurpriseMe - Random report or entity on demand
 * No automatic fetch, manual trigger only
 */

import { useState } from 'react';
import { getSurpriseReport, getSurpriseEntity } from '../lib/api';
import type { APIReportSummary } from '../lib/api';
import type { EntitySummary } from '../types';

type SurpriseMeVariant = 'report' | 'entity';

interface UseSurpriseMeReturn {
  result: APIReportSummary | EntitySummary | null;
  isLoading: boolean;
  error: string | null;
  trigger: () => Promise<void>;
}

export function useSurpriseMe(variant: SurpriseMeVariant): UseSurpriseMeReturn {
  const [result, setResult] = useState<APIReportSummary | EntitySummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trigger = async () => {
    try {
      setIsLoading(true);
      setError(null);

      if (variant === 'report') {
        const data = await getSurpriseReport();
        setResult(data);
      } else {
        const data = await getSurpriseEntity();
        setResult(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch surprise');
    } finally {
      setIsLoading(false);
    }
  };

  return { result, isLoading, error, trigger };
}
