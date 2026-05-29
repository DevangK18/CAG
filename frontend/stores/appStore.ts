/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Zustand Store for CAG Gateway
 */

import { create } from 'zustand';
import { CitationMap } from '../lib/api';
import { buildNormalizedCitationMap } from '../lib/citationUtils';
import { GroundednessReport, ViewState } from '../types';

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

  // View actions
  setCurrentReportId: (id) => set({ 
    currentReportId: id,
    pdfPage: 1,
    messages: [],
    citationMap: {},
    normalizedCitationMap: new Map(),
  }),
  
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
      { ...message, id: Date.now().toString() }
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
    const messages = [...state.messages];
    if (messages.length > 0) {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        content: messages[messages.length - 1].content + token,
      };
    }
    return { messages };
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
    console.log('[goBack] previousView:', prev, 'current view:', get().view);
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
    set({ pdfPage: targetPage });

    // Set PDF highlight for citation
    set({
      pdfHighlight: {
        page: targetPage,
        type: 'citation',
        label: citation.section,
        section: citation.section,
      }
    });

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      set({ pdfHighlight: null });
    }, 5000);
  },
}));

export default useAppStore;
