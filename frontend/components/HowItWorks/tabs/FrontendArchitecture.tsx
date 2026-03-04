import React from 'react';
import { DocSection } from '../shared/DocSection';
import { DiagramCard } from '../shared/DiagramCard';
import { CalloutBox } from '../shared/CalloutBox';
import { CodeBlock } from '../shared/CodeBlock';
import { MermaidDiagram } from '../shared/MermaidDiagram';

export const FrontendArchitecture: React.FC = () => {
    const componentArchitecture = `
graph TB
    App[App Component]

    App --> Landing[Landing View]
    App --> TimeSeries[Time Series View]
    App --> Report[Report View]
    App --> HowItWorks[How It Works]

    Landing --> ReportDirectory[Report Directory<br/>Grid/List]
    TimeSeries --> SeriesList[Series List]
    Report --> ReportDetail[Report Detail]

    ReportDetail --> Overview[Overview Tab]
    ReportDetail --> Chat[Chat Tab]
    ReportDetail --> Charts[Charts Tab]
    ReportDetail --> Tables[Tables Tab]
    ReportDetail --> Summaries[Summaries Tab]

    Report --> PDFViewer[PDF Viewer]
    Report --> ChatOverlay[Chat Overlay]

    style App fill:#f3f4f6
    style Report fill:#dbeafe
    style Chat fill:#fae8ff
    style PDFViewer fill:#dcfce7
`;

    const streamingFlow = `
sequenceDiagram
    participant User
    participant UI
    participant Hook
    participant API
    participant SSE

    User->>UI: Types message
    UI->>Hook: sendMessage()
    Hook->>API: POST /api/chat
    API->>SSE: Open EventSource

    loop For each token
        SSE-->>Hook: Token event
        Hook->>UI: Update message state
        UI->>User: Render token
    end

    SSE-->>Hook: Done event
    Hook->>UI: Mark complete
    UI->>User: Show final message
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">Frontend Architecture</h1>
            <p className="page-subtitle">
                React, TypeScript, Zustand, and streaming UI patterns
            </p>

            {/* Component Architecture */}
            <DocSection
                title="Component Architecture"
                description="Main page components and how they nest"
            >
                <DiagramCard title="Component Hierarchy">
                    <MermaidDiagram
                        chart={componentArchitecture}
                        caption="App component manages views: Landing (report directory), Time Series (cross-report analysis), Report (detailed view with tabs), and How It Works (documentation)."
                    />
                </DiagramCard>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Key Views</h3>
                    <CalloutBox type="success">
                        <strong>Landing View:</strong> Report directory with search, sector filter, and grid/list toggle. Uses ReportCard components.
                    </CalloutBox>
                    <CalloutBox type="info">
                        <strong>Report View:</strong> Split-pane interface with PDF viewer on left and tabbed content on right. Chat overlay toggles on demand.
                    </CalloutBox>
                    <CalloutBox type="warning">
                        <strong>Time Series View:</strong> Series selection → Series chat with multi-year PDF viewer and citation-based year switching.
                    </CalloutBox>
                </div>
            </DocSection>

            {/* Streaming UI Pattern */}
            <DocSection
                title="Streaming UI Pattern"
                description="How the chat interface handles Server-Sent Events"
            >
                <DiagramCard title="Streaming Message Flow">
                    <MermaidDiagram
                        chart={streamingFlow}
                        caption="User sends message → API opens SSE stream → Tokens arrive incrementally → UI updates token-by-token → Final message rendered with citations."
                    />
                </DiagramCard>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Implementation Details</h3>

                    <CodeBlock title="useChatStream Hook">
{`const useChatStream = () => {
  const [isStreaming, setIsStreaming] = useState(false);
  const { messages, addMessage, updateMessage } = useAppStore();

  const sendMessage = async (query: string, reportIds: string[]) => {
    setIsStreaming(true);
    addMessage({ role: 'user', content: query });

    const messageId = Date.now();
    addMessage({ id: messageId, role: 'assistant', content: '' });

    const eventSource = new EventSource(
      \`/api/chat/stream?query=\${query}&reports=\${reportIds.join(',')}\`
    );

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.done) {
        eventSource.close();
        setIsStreaming(false);
      } else {
        updateMessage(messageId, (prev) => prev + data.token);
      }
    };
  };

  return { sendMessage, isStreaming };
};`}
                    </CodeBlock>

                    <p style={{ marginTop: '16px', lineHeight: '1.7', color: '#475569' }}>
                        Message state is managed in Zustand store. Each token update triggers a re-render, creating the typewriter effect. Citations are parsed and highlighted after streaming completes.
                    </p>
                </div>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Citation Rendering</h3>
                    <CodeBlock>
{`const renderMessageWithCitations = (content: string) => {
  const segments = splitTextWithCitations(content);
  return segments.map((segment) => {
    if (segment.type === 'citation') {
      const citation = lookupCitation(segment.content);
      return (
        <button
          className="citation-chip"
          onClick={() => navigateToPage(citation.page)}
        >
          [{segment.content}]
        </button>
      );
    }
    return <span>{segment.content}</span>;
  });
};`}
                    </CodeBlock>
                </div>
            </DocSection>

            {/* Search & Filtering */}
            <DocSection
                title="Search & Filtering"
                description="How the report directory search, sector filter, and view toggle work"
            >
                <div style={{ lineHeight: '1.7', color: '#475569' }}>
                    <p>
                        The landing view provides instant client-side filtering of reports based on search term and sector. No backend calls required for filtering.
                    </p>

                    <CodeBlock title="Filter Logic">
{`const filteredReports = reports.filter(r => {
  const matchesSearch =
    r.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
    r.ministry.toLowerCase().includes(searchTerm.toLowerCase());

  const matchesSector =
    filterSector === 'All' || r.sector === filterSector;

  return matchesSearch && matchesSector;
});`}
                    </CodeBlock>

                    <p style={{ marginTop: '16px' }}>
                        The view toggle switches between grid and list layouts. Grid shows cards with thumbnails, list shows compact rows with key metadata.
                    </p>
                </div>
            </DocSection>

            {/* Key Hooks */}
            <DocSection
                title="Custom Hooks"
                description="Reusable hooks for API integration and state management"
            >
                <div style={{ lineHeight: '1.7', color: '#475569' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Data Fetching Hooks</h3>

                    <CalloutBox type="success">
                        <strong>useReports():</strong> Fetches all reports from /api/reports. Returns reports array, stats, and loading state.
                    </CalloutBox>

                    <CalloutBox type="info">
                        <strong>useReport(reportId):</strong> Fetches single report details, including pdfUrl. Caches in Zustand.
                    </CalloutBox>

                    <CalloutBox type="warning">
                        <strong>useCharts(reportId) / useTables(reportId):</strong> Fetch charts and tables for a report. Paginated, with total counts.
                    </CalloutBox>

                    <CalloutBox type="note">
                        <strong>useOverview(reportId):</strong> Fetches enhanced overview (scope, objectives, topics, glossary). Returns null if not available.
                    </CalloutBox>

                    <CalloutBox type="success">
                        <strong>useSummaries(reportId):</strong> Fetches AI summaries. Returns variant list, current content, and loading states.
                    </CalloutBox>
                </div>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Chat Hooks</h3>

                    <CalloutBox type="info">
                        <strong>useChatStream():</strong> Handles SSE streaming for report chat. Manages message state, streaming flag, and token accumulation.
                    </CalloutBox>

                    <CalloutBox type="warning">
                        <strong>useSeriesChat():</strong> Similar to useChatStream but for time series analysis. Includes multi-report context.
                    </CalloutBox>
                </div>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Time Series Hooks</h3>

                    <CalloutBox type="success">
                        <strong>useSeries():</strong> Fetches all time series definitions. Returns series list, total count, and error state.
                    </CalloutBox>
                </div>
            </DocSection>

            {/* State Management */}
            <DocSection
                title="State Management"
                description="Zustand store for global state"
            >
                <div style={{ lineHeight: '1.7', color: '#475569' }}>
                    <p>
                        CAG Gateway uses Zustand for lightweight global state management. No Redux complexity, just simple hooks and selectors.
                    </p>

                    <CodeBlock title="App Store Structure">
{`const useAppStore = create<AppStore>((set) => ({
  // Report state
  currentReportId: null,
  setCurrentReportId: (id) => set({ currentReportId: id }),

  // Chat state
  messages: [],
  addMessage: (msg) => set((state) => ({
    messages: [...state.messages, msg]
  })),
  clearMessages: () => set({ messages: [] }),

  // Citation state
  citationMap: {},
  normalizedCitationMap: {},

  // PDF state
  pdfPage: 1,
  setPdfPage: (page) => set({ pdfPage: page }),
  pdfHighlight: null,
  setPdfHighlight: (highlight) => set({ pdfHighlight: highlight }),

  // Response style
  responseStyle: 'adaptive',
  setResponseStyle: (style) => set({ responseStyle: style }),
}));`}
                    </CodeBlock>

                    <p style={{ marginTop: '16px' }}>
                        State updates are scoped to specific slices, preventing unnecessary re-renders. Citation map is normalized for O(1) lookups.
                    </p>
                </div>
            </DocSection>

            {/* UI Patterns */}
            <DocSection
                title="UI Patterns & Components"
                description="Reusable patterns used throughout the app"
            >
                <div style={{ lineHeight: '1.7', color: '#475569' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Split-Pane Layout</h3>
                    <CalloutBox type="info">
                        Draggable resizer between PDF viewer and content panel. Min/max constraints (25%-75%). Swap button to flip panes.
                    </CalloutBox>

                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px', marginTop: '16px' }}>Collapsible Sections</h3>
                    <CalloutBox type="success">
                        Overview tab uses collapsible sections for scope, objectives, topics, glossary. All expanded by default.
                    </CalloutBox>

                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px', marginTop: '16px' }}>Citation Chips</h3>
                    <CalloutBox type="warning">
                        Inline citation buttons with hover tooltips. Year badges for time series. Current year highlighted. Click to navigate PDF.
                    </CalloutBox>

                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px', marginTop: '16px' }}>Tab Navigation</h3>
                    <CalloutBox type="note">
                        Horizontal tabs with active state styling. Counts (Charts: 12, Tables: 45) and badges (Summaries: AI). Scrollable on mobile.
                    </CalloutBox>
                </div>
            </DocSection>

            {/* Performance Optimizations */}
            <DocSection
                title="Performance Optimizations"
                description="How the frontend stays fast and responsive"
            >
                <div style={{ lineHeight: '1.7', color: '#475569' }}>
                    <ul style={{ paddingLeft: '24px', lineHeight: '1.8' }}>
                        <li><strong>Lazy Loading:</strong> PDF viewer only loads visible pages. Charts/tables load on tab switch.</li>
                        <li><strong>Memoization:</strong> Expensive computations (filtered reports, citation lookups) are memoized with useMemo.</li>
                        <li><strong>Debouncing:</strong> Search input is debounced (300ms) to avoid excessive re-renders.</li>
                        <li><strong>Virtual Scrolling:</strong> Not yet implemented but planned for large report lists.</li>
                        <li><strong>Code Splitting:</strong> Vite automatically code-splits by route/component. react-pdf is lazy-loaded.</li>
                    </ul>
                </div>
            </DocSection>
        </div>
    );
};
