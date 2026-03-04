/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Hook for streaming chat across a time series
 */

import { useCallback } from 'react';
import { streamSeriesChat, CitationMap } from '../lib/api';
import { useAppStore } from '../stores/appStore';
import { trackEvent } from '../lib/posthog';

export interface UseSeriesChatResult {
  sendSeriesMessage: (seriesId: string, query: string) => Promise<void>;
  isStreaming: boolean;
}

export function useSeriesChat(): UseSeriesChatResult {
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

  const sendSeriesMessage = useCallback(async (seriesId: string, query: string) => {
    if (!query.trim() || isStreaming) return;

    // Add user message
    addMessage({ role: 'user', content: query });

    // Track series chat message sent
    trackEvent('series_chat_sent', {
      series_id: seriesId,
      query_length: query.length
    });

    // Add empty assistant message with waiting flag (for loading animation)
    addMessage({ role: 'assistant', content: '', isStreaming: true, isWaitingForResponse: true });

    // Reset state
    setShowLowRelevanceCaveat(false);

    setIsStreaming(true);

    try {
      const stream = streamSeriesChat(seriesId, {
        query,
        style: responseStyle,
        compare_years: true,
        top_k_per_report: 5,
      });

      let firstTokenReceived = false;

      for await (const event of stream) {
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
  }, [isStreaming, responseStyle, addMessage, appendToLastMessage, setLastMessageStreaming, setLastMessageWaiting, setIsStreaming, setCitationMap, setShowLowRelevanceCaveat]);

  return {
    sendSeriesMessage,
    isStreaming,
  };
}

export default useSeriesChat;
