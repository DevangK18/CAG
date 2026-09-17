/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Search Dropdown - Phase C
 * Renders grouped search results with loading states
 *
 * Features:
 * - Channel groupings: REPORTS, MINISTRIES, ENTITIES, FINDINGS, GLOSSARY
 * - Channels with zero results are hidden
 * - Per-channel loading spinner while loading
 * - "Try searching for..." example chips when empty
 * - No-results state with helpful message
 * - Glossary grouping: same term from multiple reports → "+N more"
 */

import React, { useMemo } from 'react';
import { SearchResultRow } from './SearchResultRow';
import { isValidMinistry } from '../../utils';
import type {
    GroupedSearchResults,
    SearchChannel,
    SearchResultRow as SearchResultRowType,
    SearchResultMinistry,
    SearchResultGlossary,
} from '../../types';

interface SearchDropdownProps {
    query: string;
    results: GroupedSearchResults | null;
    isLoading: boolean;
    isLoadingByChannel: Record<SearchChannel, boolean>;
    error: string | null;
    selectedIndex: number;
    onResultClick: (result: SearchResultRowType) => void;
    onExampleClick: (example: string) => void;
}

const EXAMPLE_QUERIES = [
    'railway safety',
    'NHAI',
    'Maharashtra 2023',
    'GST compliance',
    'revenue loss',
    'Ministry of Finance',
];

const Spinner = () => (
    <svg className="home-search-spinner" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
    </svg>
);

export const SearchDropdown: React.FC<SearchDropdownProps> = ({
    query,
    results,
    isLoading,
    isLoadingByChannel,
    error,
    selectedIndex,
    onResultClick,
    onExampleClick,
}) => {
    // Filter ministries to exclude invalid ones
    const filteredMinistries = useMemo(() => {
        if (!results) return [];
        return results.ministries.filter(m => isValidMinistry(m.canonical_name));
    }, [results]);

    // Group glossary terms - same term from different reports get "+N more"
    const groupedGlossary = useMemo(() => {
        if (!results) return [];

        const termMap = new Map<string, { first: SearchResultGlossary; count: number }>();

        for (const item of results.glossary) {
            const key = item.term.toLowerCase();
            const existing = termMap.get(key);
            if (existing) {
                existing.count++;
            } else {
                termMap.set(key, { first: item, count: 0 });
            }
        }

        return Array.from(termMap.values());
    }, [results]);

    // Calculate flat index offsets for arrow navigation
    const getGlobalIndex = useMemo(() => {
        if (!results) return () => -1;

        const reports = results.reports;
        const ministries = filteredMinistries;
        const entities = results.entities;
        const findings = results.findings;

        const reportsOffset = 0;
        const ministriesOffset = reports.length;
        const entitiesOffset = ministriesOffset + ministries.length;
        const findingsOffset = entitiesOffset + entities.length;
        const glossaryOffset = findingsOffset + findings.length;

        return (channel: SearchChannel, index: number): number => {
            switch (channel) {
                case 'reports':
                    return reportsOffset + index;
                case 'ministries':
                    return ministriesOffset + index;
                case 'entities':
                    return entitiesOffset + index;
                case 'findings':
                    return findingsOffset + index;
                case 'glossary':
                    return glossaryOffset + index;
                default:
                    return -1;
            }
        };
    }, [results, filteredMinistries]);

    // Show example chips when query is empty
    if (!query.trim()) {
        return (
            <div className="home-search-dropdown">
                <div className="home-search-dropdown-header">
                    Try searching for...
                </div>
                <div className="home-search-examples">
                    {EXAMPLE_QUERIES.map((example) => (
                        <button
                            key={example}
                            className="home-search-example-chip"
                            onClick={() => onExampleClick(example)}
                        >
                            {example}
                        </button>
                    ))}
                </div>
            </div>
        );
    }

    // Error state
    if (error) {
        return (
            <div className="home-search-dropdown">
                <div className="home-search-dropdown-error">
                    Search failed. Please try again.
                </div>
            </div>
        );
    }

    // Loading state (initial load only)
    if (isLoading && !results) {
        return (
            <div className="home-search-dropdown">
                <div className="home-search-dropdown-loading">
                    <Spinner /> Searching...
                </div>
            </div>
        );
    }

    // No results state
    const hasResults = results && (
        results.reports.length > 0 ||
        filteredMinistries.length > 0 ||
        results.entities.length > 0 ||
        results.findings.length > 0 ||
        results.glossary.length > 0
    );

    if (!hasResults && !isLoading) {
        return (
            <div className="home-search-dropdown">
                <div className="home-search-dropdown-empty">
                    No matches for "{query}".
                    <br />
                    <span className="home-search-dropdown-hint">
                        Try entity names like NHAI or topics like railway safety.
                    </span>
                </div>
            </div>
        );
    }

    // Results rendering
    return (
        <div className="home-search-dropdown">
            {/* Reports Channel */}
            {(results?.reports.length ?? 0) > 0 && (
                <div className="home-search-channel">
                    <div className="home-search-channel-header">
                        <span>REPORTS ({results!.reports.length})</span>
                        {isLoadingByChannel.reports && <Spinner />}
                    </div>
                    {results!.reports.map((result, idx) => (
                        <SearchResultRow
                            key={`report-${result.report_id}`}
                            result={result}
                            isSelected={selectedIndex === getGlobalIndex('reports', idx)}
                            onClick={() => onResultClick(result)}
                        />
                    ))}
                </div>
            )}

            {/* Ministries Channel */}
            {filteredMinistries.length > 0 && (
                <div className="home-search-channel">
                    <div className="home-search-channel-header">
                        <span>MINISTRIES ({filteredMinistries.length})</span>
                        {isLoadingByChannel.ministries && <Spinner />}
                    </div>
                    {filteredMinistries.map((result, idx) => (
                        <SearchResultRow
                            key={`ministry-${result.entity_id}`}
                            result={result}
                            isSelected={selectedIndex === getGlobalIndex('ministries', idx)}
                            onClick={() => onResultClick(result)}
                        />
                    ))}
                </div>
            )}

            {/* Entities Channel */}
            {(results?.entities.length ?? 0) > 0 && (
                <div className="home-search-channel">
                    <div className="home-search-channel-header">
                        <span>ENTITIES ({results!.entities.length})</span>
                        {isLoadingByChannel.entities && <Spinner />}
                    </div>
                    {results!.entities.map((result, idx) => (
                        <SearchResultRow
                            key={`entity-${result.entity_id}`}
                            result={result}
                            isSelected={selectedIndex === getGlobalIndex('entities', idx)}
                            onClick={() => onResultClick(result)}
                        />
                    ))}
                </div>
            )}

            {/* Findings Channel - only show if query >= 3 chars */}
            {query.trim().length >= 3 && (
                <>
                    {isLoadingByChannel.findings && (results?.findings.length ?? 0) === 0 && (
                        <div className="home-search-channel">
                            <div className="home-search-channel-header">
                                <span>FINDINGS</span>
                                <Spinner />
                            </div>
                        </div>
                    )}
                    {(results?.findings.length ?? 0) > 0 && (
                        <div className="home-search-channel">
                            <div className="home-search-channel-header">
                                <span>FINDINGS ({results!.findings.length})</span>
                                {isLoadingByChannel.findings && <Spinner />}
                            </div>
                            {results!.findings.map((result, idx) => (
                                <SearchResultRow
                                    key={`finding-${result.chunk_id}`}
                                    result={result}
                                    isSelected={selectedIndex === getGlobalIndex('findings', idx)}
                                    onClick={() => onResultClick(result)}
                                />
                            ))}
                        </div>
                    )}
                </>
            )}

            {/* Glossary Channel */}
            {groupedGlossary.length > 0 && (
                <div className="home-search-channel">
                    <div className="home-search-channel-header">
                        <span>GLOSSARY ({groupedGlossary.length})</span>
                        {isLoadingByChannel.glossary && <Spinner />}
                    </div>
                    {groupedGlossary.map(({ first, count }, idx) => (
                        <SearchResultRow
                            key={`glossary-${first.term}-${first.report_id}`}
                            result={first}
                            isSelected={selectedIndex === getGlobalIndex('glossary', idx)}
                            onClick={() => onResultClick(first)}
                            extraCount={count}
                        />
                    ))}
                </div>
            )}
        </div>
    );
};
