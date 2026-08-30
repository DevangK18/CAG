/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Hook for streaming chat across a time series.
 * Supports both standard and agentic RAG modes.
 */

import { useCallback } from 'react';
import { streamSeriesChat, streamSeriesChatAgentic, CitationMap } from '../lib/api';
import { useAppStore } from '../stores/appStore';
import { trackEvent } from '../lib/posthog';
import { useAgenticEvents, AgenticProgress } from './useAgenticEvents';

export interface UseSeriesChatOptions {
  /** Use agentic RAG mode (default: true) */
  useAgentic?: boolean;
}

export interface UseSeriesChatResult {
  sendSeriesMessage: (seriesId: string, query: string) => Promise<void>;
  isStreaming: boolean;
  /** Agentic progress (only populated when useAgentic=true) */
  agenticProgress: AgenticProgress;
  /** Whether the current query is using agentic mode */
  isAgenticMode: boolean;
}

export function useSeriesChat(options: UseSeriesChatOptions = {}): UseSeriesChatResult {
  const { useAgentic = true } = options;

  const {
    addMessage,
    appendToLastMessage,
    setLastMessageStreaming,
    setLastMessageWaiting,
    setIsStreaming,
    isStreaming,
    responseStyle,
    setCitationMap,
    setShowLowRelevanceCaveat,
  } = useAppStore();

  // Agentic event handling
  const {
    progress: agenticProgress,
    handleAgenticEvent,
    resetProgress,
  } = useAgenticEvents();

  const sendSeriesMessage = useCallback(async (seriesId: string, query: string) => {
    if (!query.trim() || isStreaming) return;

    // Add user message
    addMessage({ role: 'user', content: query });

    // Track series chat message sent
    trackEvent('series_chat_sent', {
      series_id: seriesId,
      query_length: query.length,
      agentic_mode: useAgentic,
    });

    // Add empty assistant message with waiting flag (for loading animation)
    addMessage({ role: 'assistant', content: '', isStreaming: true, isWaitingForResponse: true });

    // Reset state
    setShowLowRelevanceCaveat(false);
    resetProgress(); // Reset agentic progress

    setIsStreaming(true);

    try {
      // Choose stream based on agentic mode
      const stream = useAgentic
        ? streamSeriesChatAgentic(seriesId, {
            query,
            style: responseStyle,
            compare_years: true,
            top_k_per_report: 5,
          })
        : streamSeriesChat(seriesId, {
            query,
            style: responseStyle,
            compare_years: true,
            top_k_per_report: 5,
          });

      let firstTokenReceived = false;

      for await (const event of stream) {
        // Try agentic event handler first (returns true if handled)
        if (useAgentic && handleAgenticEvent(event)) {
          continue;
        }

        switch (event.type) {
          case 'citation_map':
            // Series citations include audit_year
            if (event.data && typeof event.data === 'object') {
              setCitationMap(event.data as CitationMap);
            }
            break;

          case 'caveat':
            // Phase 1: Query enhancement caveat (low relevance warning)
            if (event.data === 'low_relevance') {
              setShowLowRelevanceCaveat(true);
            }
            break;

          case 'token':
            // On first token, disable waiting state
            if (!firstTokenReceived) {
              setLastMessageWaiting(false);
              firstTokenReceived = true;
            }
            // Append token directly to message content
            appendToLastMessage(event.data);
            break;

          case 'done':
            setLastMessageStreaming(false);
            break;

          case 'error':
            setLastMessageWaiting(false);
            appendToLastMessage(`\n\n_Error: ${event.data}_`);
            setLastMessageStreaming(false);
            break;
        }
      }
    } catch (error) {
      console.error('Series chat error:', error);
      setLastMessageWaiting(false);
      appendToLastMessage('\n\n_Error: Failed to get response from server._');
      setLastMessageStreaming(false);
    } finally {
      setIsStreaming(false);
    }
  }, [isStreaming, responseStyle, useAgentic, addMessage, appendToLastMessage, setLastMessageStreaming, setLastMessageWaiting, setIsStreaming, setCitationMap, setShowLowRelevanceCaveat, resetProgress, handleAgenticEvent]);

  return {
    sendSeriesMessage,
    isStreaming,
    agenticProgress,
    isAgenticMode: useAgentic,
  };
}

export default useSeriesChat;
