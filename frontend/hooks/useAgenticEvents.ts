/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Shared utility for handling agentic SSE events.
 *
 * This module provides state and handlers for the agentic-specific events
 * emitted by the AgenticRAGService:
 * - planning       — Query decomposition result
 * - sub_query      — Each sub-query starting
 * - iteration      — Each retrieval iteration
 * - reformulation  — When a query is rewritten
 * - synthesizing   — Final answer generation starting
 * - agentic_trace  — Full trace at end
 */

import { useState, useCallback } from 'react';
import { StreamEvent } from '../lib/api';

/**
 * Agentic query complexity types
 */
export type AgenticComplexity = 'simple' | 'multi_hop' | 'cross_report';

/**
 * Current phase of agentic processing
 */
export type AgenticPhase =
  | 'idle'
  | 'planning'
  | 'retrieving'
  | 'reformulating'
  | 'synthesizing'
  | 'done';

/**
 * Sub-query progress information
 */
export interface SubQueryProgress {
  index: number;
  query: string;
  status: 'pending' | 'running' | 'complete';
  iterations: number;
  reformulations: string[];
}

/**
 * State for tracking agentic query progress
 */
export interface AgenticProgress {
  phase: AgenticPhase;
  complexity: AgenticComplexity | null;
  reason: string | null;
  subQueries: SubQueryProgress[];
  currentSubQueryIndex: number;
  totalIterations: number;
  trace: Record<string, unknown> | null;
}

/**
 * Initial/reset state for agentic progress
 */
export const initialAgenticProgress: AgenticProgress = {
  phase: 'idle',
  complexity: null,
  reason: null,
  subQueries: [],
  currentSubQueryIndex: -1,
  totalIterations: 0,
  trace: null,
};

/**
 * Hook result for agentic events handling
 */
export interface UseAgenticEventsResult {
  progress: AgenticProgress;
  handleAgenticEvent: (event: StreamEvent) => boolean;
  resetProgress: () => void;
  isAgentic: boolean;
}

/**
 * Hook for managing agentic event state.
 *
 * Usage:
 * ```tsx
 * const { progress, handleAgenticEvent, resetProgress, isAgentic } = useAgenticEvents();
 *
 * // In your stream loop:
 * for await (const event of stream) {
 *   if (handleAgenticEvent(event)) continue; // Returns true if it was an agentic event
 *   // Handle other events...
 * }
 * ```
 */
export function useAgenticEvents(): UseAgenticEventsResult {
  const [progress, setProgress] = useState<AgenticProgress>(initialAgenticProgress);

  const resetProgress = useCallback(() => {
    setProgress(initialAgenticProgress);
  }, []);

  const handleAgenticEvent = useCallback((event: StreamEvent): boolean => {
    switch (event.type) {
      case 'planning': {
        const data = event.data as {
          complexity?: AgenticComplexity;
          reason?: string;
          sub_queries?: string[];
        };

        setProgress(prev => ({
          ...prev,
          phase: 'planning',
          complexity: data.complexity || null,
          reason: data.reason || null,
          subQueries: (data.sub_queries || []).map((query, index) => ({
            index,
            query,
            status: 'pending' as const,
            iterations: 0,
            reformulations: [],
          })),
        }));

        console.log('[agentic:planning]', data);
        return true;
      }

      case 'sub_query': {
        const data = event.data as {
          index?: number;
          query?: string;
          status?: string;
        };

        setProgress(prev => {
          const subQueries = [...prev.subQueries];
          const idx = data.index ?? prev.currentSubQueryIndex + 1;

          if (subQueries[idx]) {
            subQueries[idx] = {
              ...subQueries[idx],
              status: data.status === 'complete' ? 'complete' : 'running',
            };
          }

          return {
            ...prev,
            phase: 'retrieving',
            currentSubQueryIndex: idx,
            subQueries,
          };
        });

        console.log('[agentic:sub_query]', data);
        return true;
      }

      case 'iteration': {
        const data = event.data as {
          sub_query_index?: number;
          iteration?: number;
        };

        setProgress(prev => {
          const subQueries = [...prev.subQueries];
          const idx = data.sub_query_index ?? prev.currentSubQueryIndex;

          if (subQueries[idx]) {
            subQueries[idx] = {
              ...subQueries[idx],
              iterations: data.iteration || subQueries[idx].iterations + 1,
            };
          }

          return {
            ...prev,
            totalIterations: prev.totalIterations + 1,
            subQueries,
          };
        });

        console.log('[agentic:iteration]', data);
        return true;
      }

      case 'reformulation': {
        const data = event.data as {
          sub_query_index?: number;
          new_query?: string;
        };

        setProgress(prev => {
          const subQueries = [...prev.subQueries];
          const idx = data.sub_query_index ?? prev.currentSubQueryIndex;

          if (subQueries[idx] && data.new_query) {
            subQueries[idx] = {
              ...subQueries[idx],
              reformulations: [...subQueries[idx].reformulations, data.new_query],
            };
          }

          return {
            ...prev,
            phase: 'reformulating',
            subQueries,
          };
        });

        console.log('[agentic:reformulation]', data);
        return true;
      }

      case 'synthesizing': {
        setProgress(prev => ({
          ...prev,
          phase: 'synthesizing',
        }));

        console.log('[agentic:synthesizing]', event.data);
        return true;
      }

      case 'agentic_trace': {
        setProgress(prev => ({
          ...prev,
          phase: 'done',
          trace: event.data as Record<string, unknown>,
        }));

        console.log('[agentic:trace]', event.data);
        return true;
      }

      default:
        return false;
    }
  }, []);

  const isAgentic = progress.phase !== 'idle' || progress.complexity !== null;

  return {
    progress,
    handleAgenticEvent,
    resetProgress,
    isAgentic,
  };
}

/**
 * Get a human-readable status message for current agentic phase
 */
export function getAgenticStatusMessage(progress: AgenticProgress): string | null {
  switch (progress.phase) {
    case 'idle':
      return null;
    case 'planning':
      return 'Analyzing query...';
    case 'retrieving': {
      const current = progress.currentSubQueryIndex + 1;
      const total = progress.subQueries.length;
      return `Searching (${current}/${total})...`;
    }
    case 'reformulating':
      return 'Refining search...';
    case 'synthesizing':
      return 'Generating answer...';
    case 'done':
      return null;
    default:
      return null;
  }
}

export default useAgenticEvents;
