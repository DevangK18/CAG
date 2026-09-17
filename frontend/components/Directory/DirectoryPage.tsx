/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * DirectoryPage Component
 * Extracted from index.tsx for Phase 0 refactor
 * Renders the report directory view (formerly 'landing' view)
 */

import React from 'react';
import { AuditReport, ViewState } from '../../types';
import { TierSelector } from '../TierSelector';
import { ReportCard } from '../ReportCard';
import { SearchIcon, FilterIcon, LayoutGridIcon, ListIcon } from '../Icons';
import { GovernmentTier } from '../../constants';

interface DirectoryPageProps {
    // Tier state
    activeTier: GovernmentTier;
    setActiveTier: (tier: GovernmentTier) => void;
    selectedState: string | null;
    setSelectedState: (state: string | null) => void;
    tierCounts: { union: number; state: number; local: number };
    availableStates: string[];

    // Stats
    enhancedStats: {
        totalReports: number;
        totalFindings: number;
        monetaryDisplay: string;
        ministryCount: number;
        stateCount: number;
        sectorCount: number;
        yearSpan: string;
    } | null;
    reportsLoading: boolean;

    // Filter state
    searchTerm: string;
    setSearchTerm: (term: string) => void;
    sectors: string[];
    filterSector: string;
    setFilterSector: (sector: string) => void;
    ministries: string[];
    filterMinistry: string;
    setFilterMinistry: (ministry: string) => void;
    years: string[];
    filterYear: string;
    setFilterYear: (year: string) => void;
    filterAuditType: Set<string>;
    toggleAuditType: (type: string) => void;
    auditTypes: { value: string; label: string }[];

    // View mode
    viewMode: 'grid' | 'list';
    setViewMode: (mode: 'grid' | 'list') => void;

    // Computed values
    activeFilterCount: number;
    filteredReports: AuditReport[];
    currentReports: { type: 'union' | 'state' | 'local'; data: AuditReport[] };
    reports: AuditReport[]; // Full reports array for filter count display
    hasActiveFilters: boolean;
    clearAllFilters: () => void;

    // Handlers
    handleReportClick: (report: AuditReport) => void;
    setView: (view: ViewState) => void;
}

export const DirectoryPage: React.FC<DirectoryPageProps> = ({
    activeTier,
    setActiveTier,
    selectedState,
    setSelectedState,
    tierCounts,
    availableStates,
    enhancedStats,
    reportsLoading,
    searchTerm,
    setSearchTerm,
    sectors,
    filterSector,
    setFilterSector,
    ministries,
    filterMinistry,
    setFilterMinistry,
    years,
    filterYear,
    setFilterYear,
    filterAuditType,
    toggleAuditType,
    auditTypes,
    viewMode,
    setViewMode,
    activeFilterCount,
    filteredReports,
    currentReports,
    reports,
    hasActiveFilters,
    clearAllFilters,
    handleReportClick,
    setView,
}) => {
    return (
        <main className="landing-view">
            <div className="hero-section">
                <h1>CAG Gateway</h1>
                <p className="hero-subtitle">An intelligent audit report analysis platform</p>
                <div className="hero-body">
                    <p>
                        India's Comptroller and Auditor General ({' '}
                        <a href="https://cag.gov.in" target="_blank" rel="noopener noreferrer" className="hero-link">
                            CAG
                        </a>
                        ) is the supreme audit institution for Union and State government accounts, established under Article 148 of the Constitution.
                        Each year, the CAG publishes hundreds of audit reports covering everything from defence procurement and railway safety to
                        tax administration and public sector enterprise performance. These reports contain critical findings on government
                        accountability — but they're published as dense, lengthy PDFs that are difficult to search, compare, or extract insights from at scale.
                    </p>
                    <p>
                        CAG Gateway addresses this by transforming these static documents into an interactive research platform.
                        Reports are parsed and semantically chunked through a custom multi-tier extraction pipeline, then indexed into a hybrid
                        search system combining dense vector embeddings with BM25 retrieval and Cohere reranking. Users can explore any report
                        through AI-powered chat with streaming source citations, navigate extracted charts and tables with PDF cross-referencing,
                        read AI-generated summaries in multiple formats, and perform cross-report time series analysis to track how audit findings
                        evolve across financial years. To learn how this system works under the hood, visit the{' '}
                        <button className="hero-link-btn" onClick={() => setView('how-it-works')}>How It Works</button> section.
                    </p>
                </div>
                <div className="hero-disclaimer">
                    <p>
                        <strong>Disclaimer:</strong> This is an independent research project and is not affiliated with or endorsed by the CAG of India.
                        All audit reports used are public documents published by the CAG. Their non-commercial use is protected under
                        Section 52(1)(q) of the Indian Copyright Act, 1957, which permits the reproduction of public documents for informational purposes.
                    </p>
                </div>
            </div>
            <TierSelector
                activeTier={activeTier}
                onTierChange={(tier) => {
                    setActiveTier(tier);
                    setSelectedState(null); // Clear state filter when changing tier
                }}
                counts={tierCounts}
            />
            {/* Tier-aware stats bar - shows dynamic data based on selected tier */}
            <div className="stats-bar">
                <div className="stat-item">
                    <span className="stat-value">{reportsLoading ? '–' : enhancedStats?.totalReports ?? '–'}</span>
                    <span className="stat-label">Active Reports</span>
                </div>
                <div className="stat-item">
                    <span className="stat-value">{reportsLoading ? '–' : enhancedStats ? `${enhancedStats.totalFindings}+` : '–'}</span>
                    <span className="stat-label">Total Findings</span>
                </div>
                <div className="stat-item">
                    <span className="stat-value">{reportsLoading ? '–' : enhancedStats?.monetaryDisplay ?? 'N/A'}</span>
                    <span className="stat-label">Monetary Impact</span>
                </div>
                <div className="stat-item">
                    <span className="stat-value">
                        {reportsLoading ? '–' : (
                            activeTier === 'union'
                                ? (enhancedStats?.ministryCount ?? '–')
                                : (enhancedStats?.stateCount ?? '–')
                        )}
                    </span>
                    <span className="stat-label">{activeTier === 'union' ? 'Ministries' : 'States'}</span>
                </div>
                <div className="stat-item">
                    <span className="stat-value">{reportsLoading ? '–' : enhancedStats?.sectorCount ?? '–'}</span>
                    <span className="stat-label">Sectors</span>
                </div>
                <div className="stat-item">
                    <span className="stat-value">{reportsLoading ? '–' : enhancedStats?.yearSpan ?? '–'}</span>
                    <span className="stat-label">Year Span</span>
                </div>
            </div>
            {/* State filter dropdown for State and Local Body tiers */}
            {(activeTier === 'state' || activeTier === 'local') && availableStates.length > 0 && (
                <div className="state-filter-row" style={{ padding: '12px 24px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                    <div className="dropdown-group">
                        <label style={{ fontWeight: 500, color: '#475569', marginRight: '8px' }}>State:</label>
                        <select
                            value={selectedState || 'all'}
                            onChange={(e) => setSelectedState(e.target.value === 'all' ? null : e.target.value)}
                            style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #cbd5e1', background: 'white' }}
                        >
                            <option value="all">All States</option>
                            {availableStates.map(state => (
                                <option key={state} value={state}>{state}</option>
                            ))}
                        </select>
                    </div>
                </div>
            )}
            <div className="filter-block">
                <div className="filter-row-primary">
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
                <div className="filter-row-secondary">
                    <div className="secondary-filters-left">
                        <div className="dropdown-group">
                            <label>Ministry:</label>
                            <select value={filterMinistry} onChange={(e) => setFilterMinistry(e.target.value)}>
                                {ministries.map(m => <option key={m} value={m}>{m}</option>)}
                            </select>
                        </div>
                        <div className="dropdown-group">
                            <label>Year:</label>
                            <select value={filterYear} onChange={(e) => setFilterYear(e.target.value)}>
                                {years.map(y => <option key={y} value={y}>{y}</option>)}
                            </select>
                        </div>
                        <div className="filter-divider" />
                        <div className="audit-type-pills">
                            {auditTypes.map(type => (
                                <button
                                    key={type.value}
                                    className={`audit-type-pill ${filterAuditType.has(type.value) ? 'active' : ''}`}
                                    onClick={() => toggleAuditType(type.value)}
                                >
                                    {type.label}
                                </button>
                            ))}
                        </div>
                    </div>
                    {activeFilterCount > 0 && (
                        <div className="filter-status">
                            <span className="filter-count">{filteredReports.length} of {reports.length} reports</span>
                            <button className="clear-filters-btn" onClick={clearAllFilters}>Clear all</button>
                        </div>
                    )}
                </div>
            </div>
            {reportsLoading && <div className="loading-spinner">Loading reports...</div>}
            {!reportsLoading && filteredReports.length === 0 && (
                <div className="no-results">
                    <p>No reports match your current filters.</p>
                    {hasActiveFilters && (
                        <button className="clear-filters-link" onClick={clearAllFilters}>Clear all filters</button>
                    )}
                </div>
            )}
            {!reportsLoading && currentReports.data.length > 0 && (
                <div className={`report-grid ${viewMode === 'list' ? 'list-view' : ''}`}>
                    {currentReports.data.map(report => (
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
    );
};
