/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Smart Search Bar - Phase C
 * Full search functionality with keyboard shortcuts and dropdown
 *
 * Features:
 * - Rotating placeholder every 3s
 * - "/" keyboard shortcut to focus (when not in another input)
 * - Escape closes dropdown
 * - Arrow keys navigate results
 * - Enter triggers smart routing
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { SearchDropdown } from './SearchDropdown';
import { useSmartSearch } from '../../hooks/useSmartSearch';
import type { SearchChannel, SearchResultRow, GroupedSearchResults } from '../../types';

const SearchIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.35-4.35"/>
    </svg>
);

interface SmartSearchBarProps {
    activeChannel: SearchChannel;
    onQueryChange?: (query: string) => void;
    onSmartEnter?: (topHit: SearchResultRow | null, query: string, results: GroupedSearchResults | null) => void;
    onResultSelect?: (result: SearchResultRow) => void;
    externalQuery?: string;
}

export const SmartSearchBar: React.FC<SmartSearchBarProps> = ({
    activeChannel,
    onQueryChange,
    onSmartEnter,
    onResultSelect,
    externalQuery,
}) => {
    const placeholders = [
        'Try: railway safety findings',
        'Try: NHAI',
        'Try: Maharashtra 2023',
    ];

    const [query, setQuery] = useState(externalQuery ?? '');
    const [placeholderIndex, setPlaceholderIndex] = useState(0);
    const [isFocused, setIsFocused] = useState(false);
    const [selectedIndex, setSelectedIndex] = useState(-1);

    const inputRef = useRef<HTMLInputElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    const { results, isLoading, isLoadingByChannel, error, topHit } = useSmartSearch(query, activeChannel);

    // Sync external query (e.g., from trending searches click)
    useEffect(() => {
        if (externalQuery !== undefined && externalQuery !== query) {
            setQuery(externalQuery);
            // Focus the input when external query is set
            inputRef.current?.focus();
        }
    }, [externalQuery]);

    // Rotating placeholder
    useEffect(() => {
        const interval = setInterval(() => {
            setPlaceholderIndex((prev) => (prev + 1) % placeholders.length);
        }, 3000);
        return () => clearInterval(interval);
    }, []);

    // "/" keyboard shortcut - focus search when not in another input
    useEffect(() => {
        const handleGlobalKeydown = (e: KeyboardEvent) => {
            if (e.key === '/') {
                const activeEl = document.activeElement;
                // Check if we're in any input-type element
                if (
                    activeEl instanceof HTMLInputElement ||
                    activeEl instanceof HTMLTextAreaElement ||
                    activeEl instanceof HTMLSelectElement ||
                    activeEl?.getAttribute('contenteditable') === 'true'
                ) {
                    return;
                }
                e.preventDefault();
                inputRef.current?.focus();
            }
        };

        document.addEventListener('keydown', handleGlobalKeydown);
        return () => document.removeEventListener('keydown', handleGlobalKeydown);
    }, []);

    // Handle clicks outside to close dropdown
    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setIsFocused(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Build flat list of results for arrow navigation
    const getFlatResults = useCallback((): SearchResultRow[] => {
        if (!results) return [];
        return [
            ...results.reports,
            ...results.ministries,
            ...results.entities,
            ...results.findings,
            ...results.glossary,
        ];
    }, [results]);

    // Reset selection when results change
    useEffect(() => {
        setSelectedIndex(-1);
    }, [results]);

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const newQuery = e.target.value;
        setQuery(newQuery);
        onQueryChange?.(newQuery);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        const flatResults = getFlatResults();

        switch (e.key) {
            case 'Escape':
                setIsFocused(false);
                inputRef.current?.blur();
                break;

            case 'ArrowDown':
                e.preventDefault();
                if (flatResults.length > 0) {
                    setSelectedIndex(prev =>
                        prev < flatResults.length - 1 ? prev + 1 : prev
                    );
                }
                break;

            case 'ArrowUp':
                e.preventDefault();
                if (flatResults.length > 0) {
                    setSelectedIndex(prev => prev > 0 ? prev - 1 : -1);
                }
                break;

            case 'Enter':
                e.preventDefault();
                if (selectedIndex >= 0 && selectedIndex < flatResults.length) {
                    // Navigate to selected result
                    onResultSelect?.(flatResults[selectedIndex]);
                } else {
                    // Smart Enter routing with no selection
                    onSmartEnter?.(topHit, query, results);
                }
                setIsFocused(false);
                break;
        }
    };

    const handleResultClick = (result: SearchResultRow) => {
        onResultSelect?.(result);
        setIsFocused(false);
    };

    const handleExampleClick = (example: string) => {
        setQuery(example);
        onQueryChange?.(example);
        inputRef.current?.focus();
    };

    const showDropdown = isFocused && (query.length > 0 || isFocused);

    return (
        <div ref={containerRef} className="home-search-container">
            <div className="home-search-icon">
                <SearchIcon />
            </div>
            <input
                ref={inputRef}
                type="text"
                className="home-search-bar"
                placeholder={placeholders[placeholderIndex]}
                value={query}
                onChange={handleInputChange}
                onFocus={() => setIsFocused(true)}
                onKeyDown={handleKeyDown}
            />
            <div className="home-search-shortcut">/</div>

            {showDropdown && (
                <SearchDropdown
                    query={query}
                    results={results}
                    isLoading={isLoading}
                    isLoadingByChannel={isLoadingByChannel}
                    error={error}
                    selectedIndex={selectedIndex}
                    onResultClick={handleResultClick}
                    onExampleClick={handleExampleClick}
                />
            )}
        </div>
    );
};
