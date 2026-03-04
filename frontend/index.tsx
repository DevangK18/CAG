/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * CAG Gateway - Main Application v7
 * 
 * v7 Updates (Phase 10):
 * - Enhanced Overview tab with audit scope, objectives, topics, glossary
 * - New Summaries tab with 5 AI-generated variants
 * - Professional Markdown rendering for summaries
 */

import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import ReactDOM from 'react-dom/client';

import { ViewState, AuditReport, TabState, SummaryVariant, SUMMARY_VARIANT_CONFIG } from './types';

// API Integration imports
import { useReports } from './hooks/useReports';
import { useReport } from './hooks/useReport';
import { useCharts } from './hooks/useCharts';
import { useTables } from './hooks/useTables';
import { useSeries } from './hooks/useSeries';
import { useChatStream } from './hooks/useChatStream';
import { useSeriesChat } from './hooks/useSeriesChat';
import { useOverview } from './hooks/useOverview';
import { useSummaries } from './hooks/useSummaries';
import { useAppStore } from './stores/appStore';
import { PDFViewer } from './components/PDFViewer';
import { TablePreview } from './components/TablePreview';
import { ChatMessage } from './components/ChatMessage';
import { lookupCitation } from './lib/citationUtils';
import { ChartItem, TableItem, TimeSeriesInfo, getPdfUrl, TopicCovered, GlossaryTerm } from './lib/api';

import {
    SearchIcon,
    FilterIcon,
    FileTextIcon,
    ChevronLeftIcon,
    ArrowRightIcon,
    BarChartIcon,
    ExternalLinkIcon,
    DownloadIcon,
    CheckCircleIcon,
    SwapIcon,
    LayoutGridIcon,
    ListIcon
} from './components/Icons';
import { ReportCard } from './components/ReportCard';
import { HowItWorks } from './components/HowItWorks/HowItWorks';
import { AccessGate } from './components/AccessGate';
import { initPostHog, trackEvent } from './lib/posthog';
import './index.css';
import './how-it-works.css';

// Icons
const ChatIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
);

const CloseIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"/>
        <line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
);

const SparkleIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/>
    </svg>
);

const ChartIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="20" x2="18" y2="10"/>
        <line x1="12" y1="20" x2="12" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="14"/>
    </svg>
);

const TableIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <line x1="3" y1="9" x2="21" y2="9"/>
        <line x1="3" y1="15" x2="21" y2="15"/>
        <line x1="9" y1="3" x2="9" y2="21"/>
    </svg>
);

const LocationIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="10" r="3"/>
        <path d="M12 21.7C17.3 17 20 13 20 10a8 8 0 1 0-16 0c0 3 2.7 6.9 8 11.7z"/>
    </svg>
);

const CalendarIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
        <line x1="16" y1="2" x2="16" y2="6"/>
        <line x1="8" y1="2" x2="8" y2="6"/>
        <line x1="3" y1="10" x2="21" y2="10"/>
    </svg>
);

const TrendingIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>
        <polyline points="17 6 23 6 23 12"/>
    </svg>
);

const BookIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
    </svg>
);

const TargetIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <circle cx="12" cy="12" r="6"/>
        <circle cx="12" cy="12" r="2"/>
    </svg>
);

// ListIcon is now imported from './components/Icons'

const ShuffleIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 3 21 3 21 8"/>
        <line x1="4" y1="20" x2="21" y2="3"/>
        <polyline points="21 16 21 21 16 21"/>
        <line x1="15" y1="15" x2="21" y2="21"/>
        <line x1="4" y1="4" x2="9" y2="9"/>
    </svg>
);

const LoadingSpinner = () => (
    <div className="tab-loading">
        <div className="tab-spinner"></div>
        <span>Loading...</span>
    </div>
);

// Response style type
type ResponseStyle = 'executive' | 'concise' | 'detailed' | 'technical' | 'comparative' | 'adaptive';

const RESPONSE_STYLES: { value: ResponseStyle; label: string; description: string }[] = [
    { value: 'executive', label: 'Executive', description: 'High-level strategic summary' },
    { value: 'concise', label: 'Concise', description: 'Brief, to-the-point answers' },
    { value: 'detailed', label: 'Detailed', description: 'Comprehensive explanations' },
    { value: 'technical', label: 'Technical', description: 'In-depth technical analysis' },
    { value: 'comparative', label: 'Comparative', description: 'Cross-reference findings' },
    { value: 'adaptive', label: 'Auto', description: 'AI chooses best style' },
];

const CHART_TYPE_LABELS: Record<string, string> = {
    bar: 'BAR', line: 'LINE', pie: 'PIE', area: 'AREA', table_chart: 'TABLE', unknown: 'CHART'
};

// Simple Markdown renderer for summaries
const renderMarkdown = (content: string): React.ReactNode => {
    if (!content) return null;
    
    // Split into lines
    const lines = content.split('\n');
    const elements: React.ReactNode[] = [];
    let currentList: string[] = [];
    let listType: 'ul' | 'ol' | null = null;
    let key = 0;
    
    const flushList = () => {
        if (currentList.length > 0) {
            if (listType === 'ol') {
                elements.push(
                    <ol key={key++} className="summary-list ordered">
                        {currentList.map((item, i) => <li key={i}>{renderInlineFormatting(item)}</li>)}
                    </ol>
                );
            } else {
                elements.push(
                    <ul key={key++} className="summary-list">
                        {currentList.map((item, i) => <li key={i}>{renderInlineFormatting(item)}</li>)}
                    </ul>
                );
            }
            currentList = [];
            listType = null;
        }
    };
    
    const renderInlineFormatting = (text: string): React.ReactNode => {
        // Handle bold: **text** or __text__
        let result: React.ReactNode[] = [];
        const parts = text.split(/(\*\*[^*]+\*\*|__[^_]+__)/g);
        
        parts.forEach((part, i) => {
            if (part.startsWith('**') && part.endsWith('**')) {
                result.push(<strong key={i}>{part.slice(2, -2)}</strong>);
            } else if (part.startsWith('__') && part.endsWith('__')) {
                result.push(<strong key={i}>{part.slice(2, -2)}</strong>);
            } else if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
                result.push(<em key={i}>{part.slice(1, -1)}</em>);
            } else {
                result.push(part);
            }
        });
        
        return result;
    };
    
    lines.forEach((line, lineIndex) => {
        const trimmed = line.trim();
        
        // Headers
        if (trimmed.startsWith('# ')) {
            flushList();
            elements.push(<h1 key={key++} className="summary-h1">{trimmed.slice(2)}</h1>);
        } else if (trimmed.startsWith('## ')) {
            flushList();
            elements.push(<h2 key={key++} className="summary-h2">{trimmed.slice(3)}</h2>);
        } else if (trimmed.startsWith('### ')) {
            flushList();
            elements.push(<h3 key={key++} className="summary-h3">{trimmed.slice(4)}</h3>);
        } else if (trimmed.startsWith('#### ')) {
            flushList();
            elements.push(<h4 key={key++} className="summary-h4">{trimmed.slice(5)}</h4>);
        }
        // Horizontal rule
        else if (trimmed === '---' || trimmed === '***') {
            flushList();
            elements.push(<hr key={key++} className="summary-hr" />);
        }
        // Ordered list
        else if (/^\d+\.\s/.test(trimmed)) {
            if (listType !== 'ol') {
                flushList();
                listType = 'ol';
            }
            currentList.push(trimmed.replace(/^\d+\.\s/, ''));
        }
        // Unordered list
        else if (trimmed.startsWith('- ') || trimmed.startsWith('* ') || trimmed.startsWith('• ')) {
            if (listType !== 'ul') {
                flushList();
                listType = 'ul';
            }
            currentList.push(trimmed.slice(2));
        }
        // Blockquote
        else if (trimmed.startsWith('> ')) {
            flushList();
            elements.push(<blockquote key={key++} className="summary-blockquote">{renderInlineFormatting(trimmed.slice(2))}</blockquote>);
        }
        // Empty line
        else if (trimmed === '') {
            flushList();
        }
        // Regular paragraph
        else {
            flushList();
            elements.push(<p key={key++} className="summary-paragraph">{renderInlineFormatting(trimmed)}</p>);
        }
    });
    
    flushList();
    return elements;
};

function App() {
    const [view, setView] = useState<ViewState>('landing');
    const [selectedSeries, setSelectedSeries] = useState<TimeSeriesInfo | null>(null);
    const [activeTab, setActiveTab] = useState<TabState>('overview');
    const [searchTerm, setSearchTerm] = useState('');
    const [filterSector, setFilterSector] = useState('All');
    const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
    const [inputValue, setInputValue] = useState('');
    const [chatOpen, setChatOpen] = useState(false);
    const [citationFeedback, setCitationFeedback] = useState<{show: boolean; section: string; page: number; auditYear?: string; switched?: boolean} | null>(null);
    const [splitRatio, setSplitRatio] = useState(45);
    const [isSwapped, setIsSwapped] = useState(false);
    const splitContainerRef = useRef<HTMLDivElement>(null);
    const isDragging = useRef(false);
    const chatContainerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    // SERIES-SPECIFIC STATE
    const [selectedSeriesYear, setSelectedSeriesYear] = useState<string | null>(null);
    const [seriesPagePositions, setSeriesPagePositions] = useState<Record<string, number>>({});
    const [seriesCurrentReportId, setSeriesCurrentReportId] = useState<string | null>(null);

    // OVERVIEW EXPAND STATE - all expanded by default
    const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
        summary: true,
        scope: true,
        objectives: true,
        topics: true,
        glossary: true,
    });

    // ASK AI BANNER STATE
    const [bannerMinimized, setBannerMinimized] = useState(false);

    // API INTEGRATION
    const {
        currentReportId, setCurrentReportId, messages, responseStyle, setResponseStyle,
        normalizedCitationMap, citationMap, clearMessages, setPdfPage, pdfPage,
        showLowRelevanceCaveat,
    } = useAppStore();
    
    const { reports, stats, isLoading: reportsLoading } = useReports();
    const { report: selectedReport, pdfUrl, isLoading: reportLoading } = useReport(currentReportId);
    const { sendMessage, isStreaming } = useChatStream();
    const { sendSeriesMessage, isStreaming: isSeriesStreaming } = useSeriesChat();
    const { charts, total: chartsTotal, isLoading: chartsLoading, error: chartsError } = useCharts(currentReportId);
    const { tables, total: tablesTotal, isLoading: tablesLoading, error: tablesError } = useTables(currentReportId);
    const { series: allSeries, total: seriesTotal, isLoading: seriesLoading, error: seriesError } = useSeries();
    
    // Phase 10: Overview & Summaries
    const {
        overview, auditScope, auditObjectives, topicsCovered, glossaryTerms,
        findingsSummary, isLoading: overviewLoading, error: overviewError, isLLMExtracted
    } = useOverview(currentReportId);
    
    const {
        variantList, currentVariant, currentContent, isAvailable: summariesAvailable,
        isLoadingList: summariesListLoading, isLoadingContent: summaryLoading,
        listError: summariesError, contentError: summaryContentError,
        selectVariant, fetchRandom
    } = useSummaries(currentReportId);

    // Computed values for series
    const currentSeriesReport = useMemo(() => {
        if (!selectedSeries || !seriesCurrentReportId) return null;
        return selectedSeries.reports.find(r => r.report_id === seriesCurrentReportId) || null;
    }, [selectedSeries, seriesCurrentReportId]);
    
    const currentSeriesPdfUrl = useMemo(() => {
        if (!currentSeriesReport) return null;
        return getPdfUrl(currentSeriesReport.filename);
    }, [currentSeriesReport]);
    
    const currentSeriesPage = useMemo(() => {
        if (!seriesCurrentReportId) return 1;
        return seriesPagePositions[seriesCurrentReportId] || 1;
    }, [seriesCurrentReportId, seriesPagePositions]);

    // Effects
    useEffect(() => {
        if (chatContainerRef.current) {
            chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
        }
    }, [messages]);

    useEffect(() => {
        if (chatOpen && inputRef.current) inputRef.current.focus();
    }, [chatOpen]);

    useEffect(() => {
        if (citationFeedback?.show) {
            const timer = setTimeout(() => setCitationFeedback(null), 4000);
            return () => clearTimeout(timer);
        }
    }, [citationFeedback]);

    useEffect(() => {
        if (selectedSeries && selectedSeries.reports.length > 0) {
            const sortedReports = [...selectedSeries.reports].sort((a, b) =>
                b.audit_year.localeCompare(a.audit_year)
            );
            const latestReport = sortedReports[0];
            setSelectedSeriesYear(latestReport.audit_year);
            setSeriesCurrentReportId(latestReport.report_id);
        }
    }, [selectedSeries]);

    // Banner state management - always start expanded on new report
    useEffect(() => {
        // Reset to expanded when navigating to a new report or series
        setBannerMinimized(false);
    }, [currentReportId, selectedSeries]);

    // Handlers
    const handleReportClick = (report: AuditReport) => {
        // Track report viewed
        trackEvent('report_viewed', { report_id: report.id });

        setCurrentReportId(report.id);
        setSelectedSeries(null);
        setView('report');
        setActiveTab('overview');
        setChatOpen(false);
    };

    const handleSeriesClick = (series: TimeSeriesInfo) => {
        setSelectedSeries(series);
        setCurrentReportId(null);
        setView('series-chat');
        setChatOpen(true);
        clearMessages();
        setSeriesPagePositions({});
    };

    const handleBackToLanding = () => {
        setCurrentReportId(null);
        setChatOpen(false);
        setView('landing');
    };

    const handleBackToTimeSeries = () => {
        setCurrentReportId(null);
        setSelectedSeries(null);
        setChatOpen(false);
        clearMessages();
        setSeriesPagePositions({});
        setView('time-series');
    };

    const handleSeriesYearSelect = (year: string) => {
        if (!selectedSeries) return;
        if (seriesCurrentReportId) {
            setSeriesPagePositions(prev => ({ ...prev, [seriesCurrentReportId]: currentSeriesPage }));
        }
        const report = selectedSeries.reports.find(r => r.audit_year === year);
        if (report) {
            setSelectedSeriesYear(year);
            setSeriesCurrentReportId(report.report_id);
        }
    };

    const handleSeriesPageChange = (page: number) => {
        if (seriesCurrentReportId) {
            setSeriesPagePositions(prev => ({ ...prev, [seriesCurrentReportId]: page }));
        }
    };

    const handleSendMessage = async () => {
        if (!inputValue.trim() || isStreaming || isSeriesStreaming) return;
        const query = inputValue.trim();
        setInputValue('');
        if (!chatOpen) setChatOpen(true);
        if (view === 'series-chat' && selectedSeries) {
            await sendSeriesMessage(selectedSeries.series_id, query);
        } else if (currentReportId) {
            await sendMessage(query, [currentReportId]);
        }
    };

    const handleClearChat = () => clearMessages();
    const handleCloseChat = () => setChatOpen(false);

    const handleBannerToggle = () => {
        setBannerMinimized(!bannerMinimized);
    };

    const handleNavigateToPage = (page: number, section: string, type: 'chart' | 'table' = 'chart', bbox?: number[] | null) => {
        setPdfPage(page);
        setCitationFeedback({ show: true, section, page });

        // Set PDF highlight
        useAppStore.getState().setPdfHighlight({
            page,
            bbox: bbox && bbox.length >= 4 ? {
                x: bbox[0],
                y: bbox[1],
                width: bbox[2] - bbox[0],
                height: bbox[3] - bbox[1]
            } : undefined,
            type,
            label: section,
            section
        });

        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            useAppStore.getState().setPdfHighlight(null);
        }, 5000);
    };

    const handleTopicClick = (topic: TopicCovered) => {
        handleNavigateToPage(topic.page_start, topic.name);
    };

    const toggleSection = (section: string) => {
        setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
    };

    const handleCitationClick = (citationText: string) => {
        const citation = lookupCitation(citationText, normalizedCitationMap);
        if (!citation) return;
        const targetPage = citation.page_physical + 1;
        
        if (view === 'series-chat' && selectedSeries) {
            const citationReportId = citation.report_id;
            const citationReport = selectedSeries.reports.find(r => r.report_id === citationReportId);
            
            if (citationReport) {
                const needsSwitch = citationReportId !== seriesCurrentReportId;
                if (needsSwitch) {
                    if (seriesCurrentReportId) {
                        setSeriesPagePositions(prev => ({ ...prev, [seriesCurrentReportId]: currentSeriesPage }));
                    }
                    setSelectedSeriesYear(citationReport.audit_year);
                    setSeriesCurrentReportId(citationReportId);
                    setSeriesPagePositions(prev => ({ ...prev, [citationReportId]: targetPage }));
                    setCitationFeedback({ show: true, section: citation.section || citationText, page: targetPage, auditYear: citationReport.audit_year, switched: true });
                } else {
                    handleSeriesPageChange(targetPage);
                    setCitationFeedback({ show: true, section: citation.section || citationText, page: targetPage, auditYear: citationReport.audit_year });
                }
            }
        } else {
            setPdfPage(targetPage);
            setCitationFeedback({ show: true, section: citation.section || citationText, page: targetPage, auditYear: citation.audit_year });
        }
    };

    // Drag logic
    const startDrag = (e: React.MouseEvent) => {
        isDragging.current = true;
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
        document.body.style.userSelect = 'none';
    };

    const handleMouseMove = useCallback((e: MouseEvent) => {
        if (!isDragging.current || !splitContainerRef.current) return;
        const containerRect = splitContainerRef.current.getBoundingClientRect();
        const newX = e.clientX - containerRect.left;
        let newRatio = (newX / containerRect.width) * 100;
        newRatio = Math.max(25, Math.min(75, newRatio));
        setSplitRatio(newRatio);
    }, []);

    const handleMouseUp = () => {
        isDragging.current = false;
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
        document.body.style.userSelect = 'auto';
    };

    // Computed
    const filteredReports = reports.filter(r => {
        const matchesSearch = r.title.toLowerCase().includes(searchTerm.toLowerCase()) || r.ministry.toLowerCase().includes(searchTerm.toLowerCase());
        const matchesSector = filterSector === 'All' || r.sector === filterSector;
        return matchesSearch && matchesSector;
    });
    const sectors = ['All', ...Array.from(new Set(reports.map(r => r.sector)))];
    const getSeriesReportDetails = (series: TimeSeriesInfo) => series.reports.sort((a, b) => a.audit_year.localeCompare(b.audit_year));
    const truncateReportName = (name: string, maxLength: number = 60) => name.length <= maxLength ? name : name.substring(0, maxLength) + '...';
    const getShortSection = (section: string): string => section.split(' > ')[0] || section;
    const isCurrentlyStreaming = isStreaming || isSeriesStreaming;

    // Tab renderers
    const renderChartsTab = () => {
        if (chartsLoading) return <div className="charts-tab"><LoadingSpinner /></div>;
        if (chartsError) return <div className="charts-tab"><div className="tab-error"><p>Failed to load charts: {chartsError}</p></div></div>;
        return (
            <div className="charts-tab">
                <div className="tab-intro"><ChartIcon /><p>All charts from this report. Click to navigate.</p></div>
                {charts.length === 0 ? <p className="placeholder-text">No charts found.</p> : (
                    <>
                        <div className="visual-items-grid">
                            {charts.map(chart => (
                                <div key={chart.id} className="visual-item-card">
                                    <div className="visual-item-preview chart-preview"><ChartIcon /><span className="chart-type">{CHART_TYPE_LABELS[chart.type] || 'CHART'}</span></div>
                                    <div className="visual-item-content">
                                        <h4>{chart.title}</h4>
                                        <p className="visual-item-analysis">{chart.analysis}</p>
                                        <div className="visual-item-meta"><span className="meta-section">{getShortSection(chart.section)}</span><span className="meta-page">Page {chart.page}</span></div>
                                        <button className="goto-btn" onClick={() => handleNavigateToPage(chart.page, chart.section, 'chart', chart.bbox)}><LocationIcon /> View in PDF</button>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <p className="items-count">Showing {charts.length} of {chartsTotal} charts</p>
                    </>
                )}
            </div>
        );
    };

    const renderTablesTab = () => {
        if (tablesLoading) return <div className="tables-tab"><LoadingSpinner /></div>;
        if (tablesError) return <div className="tables-tab"><div className="tab-error"><p>Failed to load tables: {tablesError}</p></div></div>;
        return (
            <div className="tables-tab">
                <div className="tab-intro"><TableIcon /><p>All tables from this report. Click to navigate.</p></div>
                {tables.length === 0 ? <p className="placeholder-text">No tables found.</p> : (
                    <>
                        <div className="visual-items-grid">
                            {tables.map(table => (
                                <div key={table.id} className="visual-item-card">
                                    <div className="visual-item-preview table-preview">
                                        <TableIcon />
                                        <span className="table-size">{table.rows}×{table.columns}</span>
                                    </div>
                                    <div className="visual-item-content">
                                        <h4>{table.title}</h4>
                                        <p className="visual-item-analysis">{table.analysis}</p>
                                        <div className="visual-item-meta"><span className="meta-section">{getShortSection(table.section)}</span><span className="meta-page">Page {table.page}</span></div>
                                        <button className="goto-btn" onClick={() => handleNavigateToPage(table.page, table.section, 'table', table.bbox)}><LocationIcon /> View in PDF</button>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <p className="items-count">Showing {tables.length} of {tablesTotal} tables</p>
                    </>
                )}
            </div>
        );
    };

    // Enhanced Overview Tab (Phase 10)
    const renderOverviewTab = () => {
        if (!selectedReport) return null;

        // Use findings summary from overview if available
        const monetaryImpact = findingsSummary
            ? `₹${findingsSummary.total_monetary_crore.toLocaleString('en-IN', { maximumFractionDigits: 2 })} crore`
            : selectedReport.impact;
        const findingsCount = findingsSummary?.total_count || selectedReport.findingsCount;

        return (
            <div className="overview-tab enhanced">
                {/* Key Metrics */}
                <div className="impact-grid">
                    <div className="impact-box">
                        <label>Monetary Impact</label>
                        <span className="value">{monetaryImpact}</span>
                    </div>
                    <div className="impact-box">
                        <label>Audit Findings</label>
                        <span className="value">{findingsCount}</span>
                    </div>
                    <div className="impact-box">
                        <label>Reference Year</label>
                        <span className="value">{selectedReport.year}</span>
                    </div>
                </div>

                {/* 1. Overview Summary */}
                {overview?.executive_summary && (
                    <section className="collapsible-section">
                        <button className="section-header" onClick={() => toggleSection('summary')}>
                            <span className="section-icon"><FileTextIcon /></span>
                            <span className="section-title">Overview Summary</span>
                            <span className={`expand-icon ${expandedSections.summary ? 'expanded' : ''}`}>▼</span>
                        </button>
                        {expandedSections.summary && (
                            <div className="section-content">
                                <p style={{ fontSize: '14px', lineHeight: '1.7', color: '#475569', margin: 0 }}>
                                    {overview.executive_summary}
                                </p>
                                <button
                                    onClick={() => {
                                        setActiveTab('summaries');
                                        selectVariant('executive');
                                    }}
                                    style={{
                                        marginTop: '16px',
                                        fontSize: '13px',
                                        color: '#2563eb',
                                        fontWeight: 500,
                                        background: 'none',
                                        border: 'none',
                                        cursor: 'pointer',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '4px',
                                        padding: 0
                                    }}
                                >
                                    Read full summary <span>→</span>
                                </button>
                            </div>
                        )}
                    </section>
                )}

                {/* 2. Audit Objectives */}
                {auditObjectives.length > 0 && (
                    <section className="collapsible-section">
                        <button className="section-header" onClick={() => toggleSection('objectives')}>
                            <span className="section-icon"><ListIcon /></span>
                            <span className="section-title">Audit Objectives</span>
                            <span className="section-count">{auditObjectives.length}</span>
                            <span className={`expand-icon ${expandedSections.objectives ? 'expanded' : ''}`}>▼</span>
                        </button>
                        {expandedSections.objectives && (
                            <div className="section-content">
                                <ol className="objectives-list">
                                    {auditObjectives.map((obj, i) => (
                                        <li key={i}>{obj}</li>
                                    ))}
                                </ol>
                            </div>
                        )}
                    </section>
                )}

                {/* 3. Audit Scope */}
                {auditScope && (
                    <section className="collapsible-section">
                        <button className="section-header" onClick={() => toggleSection('scope')}>
                            <span className="section-icon"><TargetIcon /></span>
                            <span className="section-title">Audit Scope</span>
                            <span className={`expand-icon ${expandedSections.scope ? 'expanded' : ''}`}>▼</span>
                        </button>
                        {expandedSections.scope && (
                            <div className="section-content">
                                <div className="scope-grid">
                                    <div className="scope-item">
                                        <label>Period</label>
                                        <span>{auditScope.period.description}</span>
                                    </div>
                                    <div className="scope-item">
                                        <label>Geographic Coverage</label>
                                        <span>{auditScope.geographic_coverage.join(', ')}</span>
                                    </div>
                                    {auditScope.sample_size?.description && (
                                        <div className="scope-item">
                                            <label>Sample Size</label>
                                            <span>{auditScope.sample_size.description}</span>
                                        </div>
                                    )}
                                </div>
                                {auditScope.entities_covered.length > 0 && (
                                    <div className="entities-list">
                                        <label>Entities Covered</label>
                                        <div className="entity-tags">
                                            {auditScope.entities_covered.map((entity, i) => (
                                                <span key={i} className="entity-tag">{entity}</span>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </section>
                )}

                {/* 4. Topics Covered - Clickable for PDF navigation */}
                {topicsCovered.length > 0 && (
                    <section className="collapsible-section">
                        <button className="section-header" onClick={() => toggleSection('topics')}>
                            <span className="section-icon"><BookIcon /></span>
                            <span className="section-title">Topics Covered</span>
                            <span className="section-count">{topicsCovered.length}</span>
                            <span className={`expand-icon ${expandedSections.topics ? 'expanded' : ''}`}>▼</span>
                        </button>
                        {expandedSections.topics && (
                            <div className="section-content">
                                <p className="section-hint">Click a topic to navigate to it in the PDF</p>
                                <div className="topics-grid">
                                    {topicsCovered.map((topic, i) => (
                                        <div key={i} className="topic-card" onClick={() => handleTopicClick(topic)}>
                                            <h5>{topic.name}</h5>
                                            <p className="topic-desc">{topic.description}</p>
                                            <div className="topic-meta">
                                                <span>Sections: {topic.sections.join(', ')}</span>
                                                <span>Pages {topic.page_start}-{topic.page_end}</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </section>
                )}

                {/* 5. Findings Breakdown */}
                {findingsSummary && (
                    <section className="findings-breakdown">
                        <h4>Findings Breakdown</h4>
                        <div className="breakdown-grid">
                            <div className="breakdown-category">
                                <label>By Severity</label>
                                <div className="severity-stats">
                                    {findingsSummary.by_severity.critical > 0 && (
                                        <div className="stat-badge critical">
                                            <span className="badge-label">Critical</span>
                                            <span className="badge-count">{findingsSummary.by_severity.critical}</span>
                                        </div>
                                    )}
                                    {findingsSummary.by_severity.high > 0 && (
                                        <div className="stat-badge high">
                                            <span className="badge-label">High</span>
                                            <span className="badge-count">{findingsSummary.by_severity.high}</span>
                                        </div>
                                    )}
                                    {findingsSummary.by_severity.medium > 0 && (
                                        <div className="stat-badge medium">
                                            <span className="badge-label">Medium</span>
                                            <span className="badge-count">{findingsSummary.by_severity.medium}</span>
                                        </div>
                                    )}
                                    {findingsSummary.by_severity.low > 0 && (
                                        <div className="stat-badge low">
                                            <span className="badge-label">Low</span>
                                            <span className="badge-count">{findingsSummary.by_severity.low}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                            <div className="breakdown-category">
                                <label>By Type</label>
                                <div className="type-stats">
                                    {Object.entries(findingsSummary.by_type).map(([type, data]) => (
                                        <div key={type} className="type-item">
                                            <span className="type-name">{type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</span>
                                            <span className="type-count">{data.count} findings</span>
                                            <span className="type-amount">₹{data.total_crore.toLocaleString('en-IN', { maximumFractionDigits: 2 })} cr</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </section>
                )}

                {/* 6. Glossary */}
                {glossaryTerms.length > 0 && (
                    <section className="collapsible-section">
                        <button className="section-header" onClick={() => toggleSection('glossary')}>
                            <span className="section-icon">📚</span>
                            <span className="section-title">Glossary & Abbreviations</span>
                            <span className="section-count">{glossaryTerms.length}</span>
                            <span className={`expand-icon ${expandedSections.glossary ? 'expanded' : ''}`}>▼</span>
                        </button>
                        {expandedSections.glossary && (
                            <div className="section-content">
                                <div className="glossary-grid">
                                    {glossaryTerms.map((term, i) => (
                                        <div key={i} className="glossary-item">
                                            <span className="abbr">{term.abbreviation}</span>
                                            <span className="term">{term.term}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </section>
                )}

                {/* Loading indicator for overview */}
                {overviewLoading && (
                    <div className="overview-loading">
                        <LoadingSpinner />
                    </div>
                )}
            </div>
        );
    };

    // Summaries Tab (Phase 10)
    const renderSummariesTab = () => {
        if (summariesListLoading) {
            return <div className="summaries-tab"><LoadingSpinner /></div>;
        }

        if (summariesError) {
            return (
                <div className="summaries-tab">
                    <div className="summaries-unavailable">
                        <div className="unavailable-icon">📄</div>
                        <h3>Summaries Not Available</h3>
                        <p>AI-generated summaries have not been created for this report yet.</p>
                    </div>
                </div>
            );
        }

        return (
            <div className="summaries-tab">
                {/* Variant Selector */}
                <div className="variant-selector">
                    <div className="variant-buttons">
                        {variantList.map((variant) => {
                            const config = SUMMARY_VARIANT_CONFIG[variant.id as SummaryVariant];
                            const isActive = currentVariant === variant.id;
                            const isDisabled = !variant.available;
                            
                            return (
                                <button
                                    key={variant.id}
                                    className={`variant-btn ${isActive ? 'active' : ''} ${isDisabled ? 'disabled' : ''}`}
                                    onClick={() => !isDisabled && selectVariant(variant.id as SummaryVariant)}
                                    disabled={isDisabled}
                                    title={`${variant.description}\nAudience: ${variant.audience}`}
                                    style={{
                                        '--variant-color': config?.color,
                                        '--variant-bg': config?.bgColor,
                                    } as React.CSSProperties}
                                >
                                    <span className="variant-icon">{variant.icon}</span>
                                    <span className="variant-name">{variant.name}</span>
                                    {variant.available && variant.word_count > 0 && (
                                        <span className="variant-words">{variant.word_count.toLocaleString()} words</span>
                                    )}
                                </button>
                            );
                        })}
                    </div>
                    <button className="surprise-btn" onClick={fetchRandom} title="Get a random summary style">
                        <ShuffleIcon />
                        <span>Surprise Me</span>
                    </button>
                </div>

                {/* Summary Content */}
                <div className="summary-content-area">
                    {!currentVariant && !summaryLoading && (
                        <div className="select-variant-prompt">
                            <div className="prompt-icon">📖</div>
                            <h3>Select a Summary Style</h3>
                            <p>Choose a variant above to read an AI-generated summary of this audit report, tailored to different audiences and purposes.</p>
                            <div className="variant-descriptions">
                                <div className="desc-item"><strong>Executive Brief:</strong> For boardroom presentations</div>
                                <div className="desc-item"><strong>Journalist's Take:</strong> News-style for general public</div>
                                <div className="desc-item"><strong>Deep Dive:</strong> Academic analysis for researchers</div>
                                <div className="desc-item"><strong>Simple Explainer:</strong> Plain language for everyone</div>
                                <div className="desc-item"><strong>Policy Brief:</strong> Action-oriented for government</div>
                            </div>
                        </div>
                    )}

                    {summaryLoading && (
                        <div className="summary-loading">
                            <LoadingSpinner />
                            <p>Loading summary...</p>
                        </div>
                    )}

                    {summaryContentError && (
                        <div className="summary-error">
                            <p>⚠️ {summaryContentError}</p>
                        </div>
                    )}

                    {currentContent && !summaryLoading && (
                        <div className="summary-display">
                            <div className="summary-header">
                                <div className="summary-title-row">
                                    <span className="summary-icon">{currentContent.icon}</span>
                                    <h3>{currentContent.name}</h3>
                                    {currentContent.is_random && <span className="random-badge">🎲 Random Pick</span>}
                                </div>
                                <p className="summary-audience">
                                    <strong>Audience:</strong> {currentContent.audience}
                                </p>
                                <div className="summary-meta">
                                    <span>{currentContent.word_count.toLocaleString()} words</span>
                                    {currentContent.thinking_used && <span className="thinking-badge">✨ Extended Thinking</span>}
                                </div>
                            </div>
                            <div className="summary-body">
                                {renderMarkdown(currentContent.content)}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        );
    };

    // Ask AI Banner
    const renderAskAIBanner = (isSeries: boolean = false) => {
        if (chatOpen) return null;
        const hasMessages = messages.length > 0;

        if (bannerMinimized) {
            // Minimized state - small pill bottom-right
            // Clicking expands the banner back to full state (not opens chat directly)
            return (
                <div className="ask-ai-banner minimized" onClick={handleBannerToggle}>
                    <div className="banner-pill">
                        <SparkleIcon />
                        <span>Ask AI →</span>
                    </div>
                </div>
            );
        }

        // Expanded state - floating rounded bar on the right side
        return (
            <div className="ask-ai-banner expanded">
                <div className="banner-content">
                    <div className="banner-icon">
                        <SparkleIcon />
                    </div>
                    <div className="banner-text">
                        <span className="banner-title">
                            {isSeries ? "Ask AI to compare across years" : "Ask AI about this report"}
                        </span>
                        <span className="banner-subtitle">
                            {isSeries ? "Analyze trends, identify patterns" : "Get summaries, find data"}
                        </span>
                    </div>
                    <button className="banner-cta" onClick={() => setChatOpen(true)}>
                        Start chat →
                    </button>
                    <button className="banner-close" onClick={handleBannerToggle} title="Minimize">
                        <CloseIcon />
                    </button>
                </div>
            </div>
        );
    };

    // Chat overlay
    const renderChatOverlay = (title: string, subtitle: string, isSeries: boolean = false) => {
        const hasMessages = messages.length > 0;
        if (!chatOpen) return null;
        return (
            <div className="chat-overlay">
                <div className="chat-overlay-header">
                    <div className="chat-header-left">
                        <div className="chat-header-icon"><ChatIcon /></div>
                        <div className="chat-header-info">
                            <span className="chat-header-title">AI Assistant</span>
                            <span className="chat-header-report" title={title}>{subtitle} • {truncateReportName(title, 40)}</span>
                        </div>
                    </div>
                    <div className="chat-header-actions">
                        {hasMessages && <button className="chat-action-btn" onClick={handleClearChat}>Clear</button>}
                        <button className="chat-close-btn" onClick={handleCloseChat} title="Close chat"><CloseIcon /></button>
                    </div>
                </div>
                <div className="chat-style-bar">
                    <span className="style-label">Response style:</span>
                    <div className="style-options">
                        {RESPONSE_STYLES.map(style => (
                            <button key={style.value} className={`style-option ${responseStyle === style.value ? 'active' : ''}`}
                                onClick={() => setResponseStyle(style.value as any)} title={style.description}>{style.label}</button>
                        ))}
                    </div>
                </div>
                <div className="chat-messages" ref={chatContainerRef}>
                    {!hasMessages ? (
                        <div className="chat-empty-state">
                            <div className="chat-empty-icon"><SparkleIcon /></div>
                            <h3>Start a conversation</h3>
                            <p>{isSeries ? "Compare trends, track changes, and analyze patterns across multiple years." : "Ask questions about this audit report."}</p>
                            <div className="chat-suggestions">
                                {isSeries ? (
                                    <><button onClick={() => setInputValue("How have the findings changed over the years?")}>How have findings changed?</button>
                                    <button onClick={() => setInputValue("What are the recurring issues across years?")}>Recurring issues?</button>
                                    <button onClick={() => setInputValue("Show me the trend in monetary impact")}>Monetary impact trend</button></>
                                ) : (
                                    <><button onClick={() => setInputValue("What are the key findings?")}>Key findings?</button>
                                    <button onClick={() => setInputValue("Summarize the main recommendations")}>Summarize recommendations</button>
                                    <button onClick={() => setInputValue("What is the total monetary impact?")}>Monetary impact?</button></>
                                )}
                            </div>
                        </div>
                    ) : (
                        <>
                            {showLowRelevanceCaveat && (
                                <div className="chat-caveat-banner">
                                    <div className="caveat-icon">⚠️</div>
                                    <div className="caveat-message">
                                        <strong>Limited relevance:</strong> The available reports may not contain specific information to fully answer this question. Results shown are the closest matches found.
                                    </div>
                                </div>
                            )}
                            {messages.map((m, i) => {
                                const isLastMessage = i === messages.length - 1;
                                const isThisMessageStreaming = isLastMessage && isCurrentlyStreaming && m.role === 'assistant';
                                return (
                                    <ChatMessage
                                        key={m.id || i}
                                        role={m.role}
                                        content={m.content}
                                        isStreaming={isThisMessageStreaming}
                                        isWaitingForResponse={m.isWaitingForResponse}
                                    />
                                );
                            })}
                        </>
                    )}
                </div>
                <div className="chat-input-area">
                    <input ref={inputRef} type="text" placeholder={isSeries ? "Ask about trends, comparisons..." : "Ask about findings..."} value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(); }}} disabled={isCurrentlyStreaming} className="chat-input" />
                    <button className="chat-send-btn" onClick={handleSendMessage} disabled={isCurrentlyStreaming || !inputValue.trim()}>
                        {isCurrentlyStreaming ? <div className="send-spinner" /> : <ArrowRightIcon />}
                    </button>
                </div>
            </div>
        );
    };

    // DEPRECATED: Replaced with FloatingActionButton (FAB) component
    // const renderChatBar = (title: string, isSeries: boolean = false) => {
    //     if (chatOpen) return null;
    //     const hasMessages = messages.length > 0;
    //     return (
    //         <div className="chat-bar-container">
    //             <div className="chat-bar" onClick={() => setChatOpen(true)}>
    //                 <div className="chat-bar-icon"><SparkleIcon /></div>
    //                 <div className="chat-bar-content">
    //                     <span className="chat-bar-title">{isSeries ? "Ask AI to compare across years" : "Ask AI about this report"}</span>
    //                     <span className="chat-bar-hint">{isSeries ? "Analyze trends, identify patterns" : "Get summaries, find data"}</span>
    //                 </div>
    //                 <div className="chat-bar-action">{hasMessages ? <span className="chat-bar-badge">{messages.length} messages</span> : <span className="chat-bar-cta">Start chat →</span>}</div>
    //             </div>
    //         </div>
    //     );
    // };

    // Doc Panel - Enhanced for Series
    const renderDocPanel = () => {
        if (view === 'series-chat' && selectedSeries) {
            const seriesReports = getSeriesReportDetails(selectedSeries);
            return (
                <div className="doc-panel-inner series-doc-panel">
                    <div className="series-header-prominent">
                        <div className="series-header-badge"><TrendingIcon /><span>TIME SERIES ANALYSIS</span></div>
                        <h2 className="series-title">{selectedSeries.name}</h2>
                        <p className="series-description">{selectedSeries.description}</p>
                        <button className="change-topic-btn" onClick={handleBackToTimeSeries}>Change Topic</button>
                    </div>
                    <div className="series-reports-info">
                        <div className="reports-info-header"><FileTextIcon /><span>Reports Covered</span></div>
                        <p className="reports-count">{seriesReports.length} reports spanning {selectedSeries.years_covered.length} financial years</p>
                    </div>
                    <div className="year-selector">
                        <span className="year-selector-label">Select Year:</span>
                        <div className="year-buttons">
                            {seriesReports.map(report => (
                                <button key={report.audit_year} className={`year-btn ${selectedSeriesYear === report.audit_year ? 'selected' : ''}`}
                                    onClick={() => handleSeriesYearSelect(report.audit_year)}>
                                    <CalendarIcon />{report.audit_year}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className="series-pdf-container">
                        {currentSeriesReport && (
                            <div className="series-pdf-header">
                                <span className="viewing-label">Viewing:</span>
                                <span className="viewing-year">{currentSeriesReport.audit_year}</span>
                                <span className="viewing-title" title={currentSeriesReport.report_title}>{truncateReportName(currentSeriesReport.report_title, 35)}</span>
                                <a href={currentSeriesPdfUrl || '#'} target="_blank" rel="noopener noreferrer" className="open-external" title="Open in new tab"><ExternalLinkIcon /></a>
                            </div>
                        )}
                        <PDFViewer url={currentSeriesPdfUrl} initialPage={currentSeriesPage} onPageChange={handleSeriesPageChange} />
                    </div>
                    {citationFeedback?.show && (
                        <div className={`citation-toast ${citationFeedback.switched ? 'year-switched' : ''}`}>
                            <LocationIcon />
                            <span>{citationFeedback.switched && <strong className="switched-text">Switched to {citationFeedback.auditYear}: </strong>}Navigated to <strong>{citationFeedback.section}</strong> — Page {citationFeedback.page}</span>
                        </div>
                    )}
                </div>
            );
        } else if (view === 'report' && selectedReport) {
            return (
                <div className="doc-panel-inner">
                    <div className="panel-header"><span>Document Viewer — {selectedReport.reportNumber}</span>
                        <div className="viewer-tools">{pdfUrl && <a href={pdfUrl} target="_blank" rel="noopener noreferrer" title="Open in new tab"><ExternalLinkIcon /></a>}</div>
                    </div>
                    <PDFViewer url={pdfUrl} />
                    {citationFeedback?.show && (
                        <div className="citation-toast"><LocationIcon /><span>Navigated to <strong>{citationFeedback.section}</strong> — Page {citationFeedback.page}{citationFeedback.auditYear && <span className="toast-year"> ({citationFeedback.auditYear})</span>}</span></div>
                    )}
                </div>
            );
        }
        return null;
    };

    const renderInteractivePanel = () => {
        if (view === 'series-chat' && selectedSeries) {
            return (
                <div className="interactive-panel-inner series-interactive-panel">
                    <div className="report-metadata-header series-chat-header">
                        <button className="back-link" onClick={handleBackToTimeSeries}><ChevronLeftIcon /> Back to Series List</button>
                        <div className="header-badge-row">
                            <span className="sector-pill series-pill"><TrendingIcon /> Cross-Year Analysis</span>
                            <span className="sector-pill">{selectedSeries.reports.length} Reports</span>
                        </div>
                    </div>
                    {!chatOpen && (
                        <div className="tab-content">
                            <div className="overview-tab series-overview">
                                <div className="series-quick-start">
                                    <h3>📊 Ready to Analyze</h3>
                                    <p>This series covers <strong>{selectedSeries.years_covered.join(', ')}</strong>. Ask questions to compare findings and track changes.</p>
                                    <div className="analysis-tips">
                                        <div className="tip"><span className="tip-icon">💡</span><span>Citations auto-switch the PDF to the relevant year</span></div>
                                        <div className="tip"><span className="tip-icon">📄</span><span>Page positions are remembered when switching years</span></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                    {renderAskAIBanner(true)}
                    {renderChatOverlay(selectedSeries.name, 'Series Analysis', true)}
                </div>
            );
        } else if (view === 'report' && selectedReport) {
            return (
                <div className="interactive-panel-inner">
                    <div className="report-metadata-header">
                        <button className="back-link" onClick={handleBackToLanding}><ChevronLeftIcon /> Return to Directory</button>
                        <div className="header-badge-row"><span className="sector-pill">{selectedReport.sector}</span><span className="sector-pill">{selectedReport.reportNumber}</span></div>
                        <h2 className="report-title-full" title={selectedReport.title}>{selectedReport.title}</h2>
                        <p className="subtitle">{selectedReport.ministry} • {selectedReport.year}</p>
                    </div>
                    {!chatOpen && (
                        <>
                            <div className="tab-navigation">
                                <button className={activeTab === 'overview' ? 'active' : ''} onClick={() => setActiveTab('overview')}>Overview</button>
                                <button className={activeTab === 'findings' ? 'active' : ''} onClick={() => setActiveTab('findings')}>Key Findings</button>
                                <button className={activeTab === 'recommendations' ? 'active' : ''} onClick={() => setActiveTab('recommendations')}>Recommendations</button>
                                <button className={activeTab === 'charts' ? 'active' : ''} onClick={() => setActiveTab('charts')}><ChartIcon /> Charts {chartsTotal > 0 && <span className="tab-count">{chartsTotal}</span>}</button>
                                <button className={activeTab === 'tables' ? 'active' : ''} onClick={() => setActiveTab('tables')}><TableIcon /> Tables {tablesTotal > 0 && <span className="tab-count">{tablesTotal}</span>}</button>
                                <button className={`${activeTab === 'summaries' ? 'active' : ''} summaries-tab-btn`} onClick={() => setActiveTab('summaries')}>
                                    <SparkleIcon /> Summaries
                                    {summariesAvailable && <span className="tab-badge new">AI</span>}
                                </button>
                            </div>
                            <div className="tab-content">
                                {activeTab === 'overview' && renderOverviewTab()}
                                {activeTab === 'findings' && (
                                    <div className="findings-tab">
                                        {selectedReport.findings?.length > 0 ? selectedReport.findings.map((f, i) => <div key={i} className="finding-item"><div className="finding-num">{i+1}</div><p>{f}</p></div>) : <p className="placeholder-text">Use AI assistant to explore.</p>}
                                    </div>
                                )}
                                {activeTab === 'recommendations' && (
                                    <div className="recommendations-tab">
                                        {selectedReport.recommendations?.length > 0 ? selectedReport.recommendations.map((r, i) => <div key={i} className="recommendation-item"><CheckCircleIcon /><p>{r}</p></div>) : <p className="placeholder-text">Use AI assistant to explore.</p>}
                                    </div>
                                )}
                                {activeTab === 'charts' && renderChartsTab()}
                                {activeTab === 'tables' && renderTablesTab()}
                                {activeTab === 'summaries' && renderSummariesTab()}
                            </div>
                        </>
                    )}
                    {renderAskAIBanner(false)}
                    {renderChatOverlay(selectedReport.title, selectedReport.reportNumber)}
                </div>
            );
        }
        return null;
    };

    // Main Render
    return (
        <div className="cag-app">
            <header className="cag-header">
                <div className="cag-header-left"><div className="cag-logo" onClick={handleBackToLanding}><FileTextIcon /><span>CAG GATEWAY</span></div></div>
                <nav className="cag-nav">
                    <button onClick={handleBackToLanding} className={view === 'landing' ? 'active' : ''}>Report Directory</button>
                    <button onClick={() => setView('time-series')} className={view === 'time-series' || view === 'series-chat' ? 'active' : ''}>Time Series Analysis</button>
                    <button onClick={() => setView('how-it-works')} className={view === 'how-it-works' ? 'active' : ''}>How It Works</button>
                </nav>
                <div className="cag-header-right"><div className="user-profile"><span className="user-role">Senior Auditor</span><div className="user-avatar">SA</div></div></div>
            </header>

            {view === 'landing' && (
                <main className="landing-view">
                    <div className="hero-section">
                        <h1>Comptroller and Auditor General of India</h1>
                        <p className="hero-subtitle">Established by Article 148 of the Constitution, the CAG is the Supreme Audit Institution of India.</p>
                        <div className="hero-mission-container">
                            <p className="hero-mission"><strong>Project Mission:</strong> Transform static audit reports into interactive data experiences.</p>
                            <p className="hero-disclaimer"><strong>Disclaimer:</strong> Independent initiative, not affiliated with CAG of India.</p>
                        </div>
                    </div>
                    <div className="stats-bar">
                        <div className="stat-item"><span className="stat-value">{reportsLoading ? '...' : stats.totalReports}</span><span className="stat-label">Active Reports</span></div>
                        <div className="stat-item"><span className="stat-value">{reportsLoading ? '...' : `${stats.totalFindings}+`}</span><span className="stat-label">Total Findings</span></div>
                        <div className="stat-item"><span className="stat-value">{reportsLoading ? '...' : stats.totalImpact}</span><span className="stat-label">Monetary Impact</span></div>
                        <div className="stat-item"><span className="stat-value">{reportsLoading ? '...' : stats.ministryCount}</span><span className="stat-label">Ministries</span></div>
                    </div>
                    <div className="filter-controls">
                        <div className="search-box"><SearchIcon /><input type="text" placeholder="Search..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} /></div>
                        <div className="dropdown-group"><label><FilterIcon /> Sector:</label><select value={filterSector} onChange={(e) => setFilterSector(e.target.value)}>{sectors.map(s => <option key={s} value={s}>{s}</option>)}</select></div>
                        <div className="view-toggle">
                            <button
                                className={viewMode === 'grid' ? 'active' : ''}
                                onClick={() => setViewMode('grid')}
                                title="Grid view"
                            >
                                <LayoutGridIcon />
                            </button>
                            <button
                                className={viewMode === 'list' ? 'active' : ''}
                                onClick={() => setViewMode('list')}
                                title="List view"
                            >
                                <ListIcon />
                            </button>
                        </div>
                    </div>
                    {reportsLoading && <div className="loading-spinner">Loading reports...</div>}
                    {!reportsLoading && (
                        <div className={`report-grid ${viewMode === 'list' ? 'list-view' : ''}`}>
                            {filteredReports.map(report => (
                                <ReportCard
                                    key={report.id}
                                    report={report}
                                    viewMode={viewMode}
                                    onClick={() => handleReportClick(report)}
                                />
                            ))}
                        </div>
                    )}
                </main>
            )}

            {view === 'time-series' && (
                <main className="landing-view">
                    <div className="hero-section"><h1>Time Series Analysis</h1><p className="hero-subtitle">Analyze trends across multiple financial years.</p></div>
                    {seriesLoading && <div className="loading-spinner">Loading time series...</div>}
                    {seriesError && <div className="tab-error" style={{margin:'40px auto',maxWidth:'600px'}}><p>Failed to load: {seriesError}</p></div>}
                    {!seriesLoading && !seriesError && allSeries.length === 0 && <div className="placeholder-text" style={{textAlign:'center',padding:'60px'}}><p>No time series available.</p></div>}
                    {!seriesLoading && !seriesError && allSeries.length > 0 && (
                        <div className="report-grid">
                            {allSeries.map(series => (
                                <div key={series.series_id} className="report-card series-card" onClick={() => handleSeriesClick(series)}>
                                    <div className="card-top"><span className="report-num">{series.reports.length} Reports</span><span className="status-badge compliant">Longitudinal Data</span></div>
                                    <h3>{series.name}</h3>
                                    <p className="series-desc">{series.description}</p>
                                    <div className="series-timeline-preview">{series.years_covered.map(year => <div key={year} className="timeline-dot"><span className="year">{year}</span><span className="dot"></span></div>)}</div>
                                    <div className="card-footer"><span>Cross-Report Intelligence</span><div className="action-link">Start Analysis <ArrowRightIcon /></div></div>
                                </div>
                            ))}
                        </div>
                    )}
                </main>
            )}

            {(view === 'report' || view === 'series-chat') && (
                <div className="report-view-container" ref={splitContainerRef}>
                    <div className="panel-container" style={{width:`${splitRatio}%`}}><div className="left-panel-content">{isSwapped ? renderInteractivePanel() : renderDocPanel()}</div></div>
                    <div className="resizer" onMouseDown={startDrag}><button className="swap-btn" onClick={() => setIsSwapped(!isSwapped)} title="Swap Panes"><SwapIcon /></button></div>
                    <div className="panel-container" style={{width:`${100-splitRatio}%`}}><div className="right-panel-content">{isSwapped ? renderDocPanel() : renderInteractivePanel()}</div></div>
                </div>
            )}

            {view === 'how-it-works' && (
                <main className="how-it-works-main">
                    <HowItWorks />
                </main>
            )}

            {(view === 'landing' || view === 'time-series' || view === 'how-it-works') && (
                <footer className="cag-footer"><div className="footer-content"><p>© 2025 CAG Gateway</p><div className="footer-links"><button>Privacy</button><button>Terms</button></div></div></footer>
            )}
        </div>
    );
}

// Initialize PostHog analytics
initPostHog();

// Wrapper component for access gate
function AppWithGate() {
    const [granted, setGranted] = useState(
        () => sessionStorage.getItem('cag_access_granted') === 'true'
    );

    const handleGranted = (accessCode: string) => {
        sessionStorage.setItem('cag_access_granted', 'true');
        sessionStorage.setItem('cag_access_code', accessCode);

        // Identify user in PostHog by their access code
        // This links all their events to this identifier
        import('./lib/posthog').then(({ posthog }) => {
            posthog.identify(accessCode);
        });

        setGranted(true);
    };

    // Re-identify user if they already have access (e.g., page refresh)
    React.useEffect(() => {
        const storedCode = sessionStorage.getItem('cag_access_code');
        if (granted && storedCode) {
            import('./lib/posthog').then(({ posthog }) => {
                posthog.identify(storedCode);
            });
        }
    }, [granted]);

    if (!granted) {
        return <AccessGate onGranted={handleGranted} />;
    }

    return <App />;
}

const rootElement = document.getElementById('root');
if (rootElement) {
    const root = ReactDOM.createRoot(rootElement);
    root.render(<React.StrictMode><AppWithGate /></React.StrictMode>);
}
