/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Hook for streaming chat with the RAG backend
 */

import { useCallback } from 'react';
import { streamChat } from '../lib/api';
import { useAppStore } from '../stores/appStore';
import { trackEvent } from '../lib/posthog';

export interface UseChatStreamResult {
  sendMessage: (query: string, reportIds?: string[]) => Promise<void>;
  isStreaming: boolean;
  clearChat: () => void;
}

export function useChatStream(): UseChatStreamResult {
  const {
    isStreaming,
    responseStyle,
    setIsStreaming,
    addMessage,
    appendToLastMessage,
    setLastMessageStreaming,
    setLastMessageWaiting,
    setCitationMap,
    clearMessages,
    setShowLowRelevanceCaveat,
  } = useAppStore();

  const sendMessage = useCallback(async (query: string, reportIds?: string[]) => {
    if (isStreaming) return;

    // Add user message
    addMessage({ role: 'user', content: query });

    // Track chat message sent
    trackEvent('chat_message_sent', {
      report_id: reportIds?.[0] || 'unknown',
      query_length: query.length
    });

    // Add empty assistant message with waiting flag (for loading animation)
    addMessage({ role: 'assistant', content: '', isStreaming: true, isWaitingForResponse: true });

    // Reset state
    setShowLowRelevanceCaveat(false);

    setIsStreaming(true);

    try {
      const stream = streamChat({
        query,
        style: responseStyle,
        report_ids: reportIds,
        top_k: 10,
      });

      let firstTokenReceived = false;

      for await (const event of stream) {
        switch (event.type) {
          case 'citation_map':
            // Store citation map FIRST before any tokens
            console.log('Received citation_map event with keys:', Object.keys(event.data || {}));
            setCitationMap(event.data);
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
            // Stream complete
            setLastMessageStreaming(false);
            break;

          case 'error':
            setLastMessageWaiting(false);
            appendToLastMessage(`\n\n_Error: ${event.data}_`);
            setLastMessageStreaming(false);
            break;
        }
      }
    } catch (err) {
      console.error('Chat stream error:', err);
      setLastMessageWaiting(false);
      appendToLastMessage(`\n\n_Error: ${err instanceof Error ? err.message : 'Unknown error'}_`);
      setLastMessageStreaming(false);
    } finally {
      setIsStreaming(false);
      setLastMessageStreaming(false);
    }
  }, [isStreaming, responseStyle, addMessage, appendToLastMessage, setLastMessageStreaming, setLastMessageWaiting, setCitationMap, setIsStreaming, setShowLowRelevanceCaveat]);

  return {
    sendMessage,
    isStreaming,
    clearChat: clearMessages,
  };
}

export default useChatStream;
