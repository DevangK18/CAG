/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Zustand Store for CAG Gateway
 */

import { create } from 'zustand';
import { CitationMap } from '../lib/api';
import { buildNormalizedCitationMap } from '../lib/citationUtils';
import { setManagedTimeout, clearManagedTimeout } from '../lib/timerManager';
import { generateId } from '../utils';
import { debug } from '../lib/debug';
import { GroundednessReport, ViewState } from '../types';

// Key for the highlight auto-dismiss timer
const HIGHLIGHT_TIMER_KEY = 'pdf-highlight-dismiss';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isWaitingForResponse?: boolean; // Waiting for first token
  groundednessReport?: GroundednessReport | null;
}

export type ResponseStyle = 'executive' | 'concise' | 'detailed' | 'technical' | 'comparative' | 'adaptive';

export interface PDFHighlight {
  page: number;
  bbox?: { x: number; y: number; width: number; height: number }; // percentages
  type: 'chart' | 'table' | 'citation';
  label: string;
  section?: string;
}

export interface HomePdfPanelState {
  reportId: string;
  page?: number;
  highlight?: { label: string; page: number; type: string };
}

/**
 * Centralized loading states for consistent tracking across the app.
 * Each key represents a different data-fetching operation.
 */
export interface LoadingStates {
  overview: boolean;
  summaries: boolean;
  charts: boolean;
  tables: boolean;
  chat: boolean;
  search: boolean;
}

export type LoadingStateKey = keyof LoadingStates;

export interface AppState {
  // Current report
  currentReportId: string | null;

  // PDF state
  pdfPage: number;
  pdfScale: number;
  pdfHighlight: PDFHighlight | null;

  // Chat state
  messages: Message[];
  isStreaming: boolean;
  responseStyle: ResponseStyle;
  showLowRelevanceCaveat: boolean; // Phase 1: Query enhancement caveat

  // Citation state - both raw and normalized
  citationMap: CitationMap;
  normalizedCitationMap: Map<string, CitationMap[string]>;

  // Home page state (Phase A)
  view: ViewState;
  previousView: ViewState | null;
  searchFilters: {
    tier?: 'union' | 'state' | 'local_body';
    states?: string[];
    years?: string[];
    ministry_entity_ids?: number[];
    entity_ids?: number[];
    audit_categories?: string[];
  };
  currentEntityId: number | null;
  chatMode: 'regular' | 'agentic';

  // Home PDF Panel state
  homePdfPanel: HomePdfPanelState | null;

  // Centralized loading states
  loadingStates: LoadingStates;

  // Actions
  setCurrentReportId: (id: string | null) => void;
  setPdfPage: (page: number) => void;
  setPdfScale: (scale: number) => void;
  setPdfHighlight: (highlight: PDFHighlight | null) => void;
  setResponseStyle: (style: ResponseStyle) => void;

  // Message actions
  addMessage: (message: Omit<Message, 'id'>) => void;
  updateLastMessage: (content: string) => void;
  appendToLastMessage: (token: string) => void;
  setLastMessageStreaming: (isStreaming: boolean) => void;
  setLastMessageWaiting: (isWaiting: boolean) => void;
  setIsStreaming: (isStreaming: boolean) => void;
  clearMessages: () => void;
  setShowLowRelevanceCaveat: (show: boolean) => void; // Phase 1
  setLastMessageGroundedness: (report: GroundednessReport) => void; // Phase D

  // Citation actions
  setCitationMap: (map: CitationMap) => void;

  // Home page actions (Phase A)
  setView: (view: ViewState) => void;
  setPreviousView: (view: ViewState | null) => void;
  setSearchFilters: (filters: AppState['searchFilters']) => void;
  clearSearchFilters: () => void;
  setCurrentEntityId: (id: number | null) => void;
  setChatMode: (mode: 'regular' | 'agentic') => void;
  goBack: () => void;

  // Home PDF Panel actions
  openHomePdf: (reportId: string, page?: number, highlight?: HomePdfPanelState['highlight']) => void;
  closeHomePdf: () => void;

  // Navigation helper
  navigateToCitation: (citation: CitationMap[string]) => void;

  // Loading state actions
  setLoading: (key: LoadingStateKey, isLoading: boolean) => void;
  resetAllLoading: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  // Initial state
  currentReportId: null,
  pdfPage: 1,
  pdfScale: 1.0,
  pdfHighlight: null,
  messages: [],
  isStreaming: false,
  responseStyle: 'adaptive',
  showLowRelevanceCaveat: false,
  citationMap: {},
  normalizedCitationMap: new Map(),

  // Home page state (Phase A)
  view: 'home',
  previousView: null,
  searchFilters: {},
  currentEntityId: null,
  chatMode: 'agentic',

  // Home PDF Panel initial state
  homePdfPanel: null,

  // Centralized loading states
  loadingStates: {
    overview: false,
    summaries: false,
    charts: false,
    tables: false,
    chat: false,
    search: false,
  },

  // View actions
  setCurrentReportId: (id) => {
    // Cancel any pending highlight timer when switching reports
    clearManagedTimeout(HIGHLIGHT_TIMER_KEY);
    set({
      currentReportId: id,
      pdfPage: 1,
      pdfHighlight: null,
      messages: [],
      citationMap: {},
      normalizedCitationMap: new Map(),
      chatMode: 'agentic', // Reset to default mode (Issue #11)
    });
  },
  
  // PDF actions
  setPdfPage: (page) => set({ pdfPage: page }),
  setPdfScale: (scale) => set({ pdfScale: scale }),
  setPdfHighlight: (highlight) => set({ pdfHighlight: highlight }),
  
  // Style action
  setResponseStyle: (style) => set({ responseStyle: style }),
  
  // Message actions
  addMessage: (message) => set((state) => ({
    messages: [
      ...state.messages,
      { ...message, id: generateId() } // Use collision-resistant ID (Issue #15)
    ],
  })),
  
  updateLastMessage: (content) => set((state) => {
    const messages = [...state.messages];
    if (messages.length > 0) {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        content,
        isStreaming: false,
      };
    }
    return { messages };
  }),
  
  appendToLastMessage: (token) => set((state) => {
    if (state.messages.length === 0) return state;

    const lastIdx = state.messages.length - 1;
    const lastMessage = state.messages[lastIdx];

    // Create new array with only the last message updated (more efficient)
    const newMessages = state.messages.slice(0, -1);
    newMessages.push({
      ...lastMessage,
      content: lastMessage.content + token,
    });

    return { messages: newMessages };
  }),
  
  setLastMessageStreaming: (isStreaming) => set((state) => {
    const messages = [...state.messages];
    if (messages.length > 0) {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        isStreaming,
      };
    }
    return { messages };
  }),

  setLastMessageWaiting: (isWaiting) => set((state) => {
    const messages = [...state.messages];
    if (messages.length > 0) {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        isWaitingForResponse: isWaiting,
      };
    }
    return { messages };
  }),

  setIsStreaming: (isStreaming) => set({ isStreaming }),

  setShowLowRelevanceCaveat: (show) => set({ showLowRelevanceCaveat: show }),

  setLastMessageGroundedness: (report) => set((state) => {
    const messages = [...state.messages];
    if (messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        groundednessReport: report,
      };
    }
    return { messages };
  }),

  clearMessages: () => set({
    messages: [],
    citationMap: {},
    normalizedCitationMap: new Map(),
    showLowRelevanceCaveat: false,
  }),

  // Citation actions
  setCitationMap: (map) => {
    const normalizedMap = buildNormalizedCitationMap(map);
    set({
      citationMap: map,
      normalizedCitationMap: normalizedMap,
    });
  },

  // Home page actions (Phase A)
  setView: (newView) => set((state) => {
    // Automatically track previous view when view changes
    if (state.view !== newView) {
      return { view: newView, previousView: state.view };
    }
    return { view: newView };
  }),

  setPreviousView: (view) => set({ previousView: view }),

  setSearchFilters: (filters) => set({ searchFilters: filters }),

  clearSearchFilters: () => set({ searchFilters: {} }),

  setCurrentEntityId: (id) => set({ currentEntityId: id }),

  setChatMode: (mode) => set({ chatMode: mode }),

  goBack: () => {
    const prev = get().previousView;
    debug.tagged('goBack', 'previousView:', prev, 'current view:', get().view);
    set({ view: prev || 'home', previousView: null });
  },

  // Home PDF Panel actions
  openHomePdf: (reportId, page, highlight) => {
    set({ homePdfPanel: { reportId, page, highlight } });
  },

  closeHomePdf: () => {
    set({ homePdfPanel: null });
  },

  // Navigate to citation
  navigateToCitation: (citation) => {
    const targetPage = citation.page_physical + 1;

    // Set page and highlight in one update
    set({
      pdfPage: targetPage,
      pdfHighlight: {
        page: targetPage,
        type: 'citation',
        label: citation.section,
        section: citation.section,
      }
    });

    // Auto-dismiss after 5 seconds using managed timeout
    // This cancels any previous timer before setting a new one,
    // preventing stale closures from clearing the wrong highlight
    setManagedTimeout(
      HIGHLIGHT_TIMER_KEY,
      () => set({ pdfHighlight: null }),
      5000
    );
  },

  // Loading state actions
  setLoading: (key, isLoading) => set((state) => ({
    loadingStates: {
      ...state.loadingStates,
      [key]: isLoading,
    },
  })),

  resetAllLoading: () => set({
    loadingStates: {
      overview: false,
      summaries: false,
      charts: false,
      tables: false,
      chat: false,
      search: false,
    },
  }),
}));

export default useAppStore;
