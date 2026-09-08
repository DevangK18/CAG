/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * useSmartSearch - Phase C
 * Debounced multi-channel search with AbortController cancellation
 *
 * Behaviors:
 * - 150ms debounce on query changes
 * - AbortController cancels in-flight requests on new keystrokes
 * - Findings channel only fires when query.length >= 3 AND 300ms idle
 * - Per-channel loading tracked independently
 * - topHit derived from server's top_hit_channel + top_hit_score
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { smartSearch } from '../lib/api';
import type {
    GroupedSearchResults,
    SearchChannel,
    SearchResultRow,
} from '../types';

interface UseSmartSearchReturn {
    results: GroupedSearchResults | null;
    isLoading: boolean;
    isLoadingByChannel: Record<SearchChannel, boolean>;
    error: string | null;
    topHit: SearchResultRow | null;
}

const DEBOUNCE_MS = 150;
const FINDINGS_DEBOUNCE_MS = 300;
const FINDINGS_MIN_CHARS = 3;

const emptyLoadingState: Record<SearchChannel, boolean> = {
    all: false,
    reports: false,
    ministries: false,
    entities: false,
    findings: false,
    glossary: false,
};

export function useSmartSearch(
    query: string,
    activeChannel: SearchChannel
): UseSmartSearchReturn {
    const [results, setResults] = useState<GroupedSearchResults | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [isLoadingByChannel, setIsLoadingByChannel] = useState<Record<SearchChannel, boolean>>(emptyLoadingState);
    const [error, setError] = useState<string | null>(null);

    // Refs for debounce timers and separate abort controllers
    // Using separate controllers prevents race condition where findings fetch
    // accidentally aborts the main search
    const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const findingsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const mainAbortRef = useRef<AbortController | null>(null);
    const findingsAbortRef = useRef<AbortController | null>(null);

    // Track if findings have been fetched for current query
    const findingsFetchedRef = useRef<string | null>(null);

    const trimmedQuery = query.trim();

    // Derive topHit from results
    const topHit = useMemo((): SearchResultRow | null => {
        if (!results || !results.top_hit_channel || results.top_hit_channel === 'all') {
            return null;
        }

        const channel = results.top_hit_channel;
        let hitList: SearchResultRow[] = [];

        switch (channel) {
            case 'reports':
                hitList = results.reports;
                break;
            case 'ministries':
                hitList = results.ministries;
                break;
            case 'entities':
                hitList = results.entities;
                break;
            case 'findings':
                hitList = results.findings;
                break;
            case 'glossary':
                hitList = results.glossary;
                break;
        }

        return hitList.length > 0 ? hitList[0] : null;
    }, [results]);

    // Filter results by active channel (client-side filtering on already-fetched data)
    const filteredResults = useMemo((): GroupedSearchResults | null => {
        if (!results) return null;
        if (activeChannel === 'all') return results;

        // Return only the selected channel, zero out others
        return {
            reports: activeChannel === 'reports' ? results.reports : [],
            ministries: activeChannel === 'ministries' ? results.ministries : [],
            entities: activeChannel === 'entities' ? results.entities : [],
            findings: activeChannel === 'findings' ? results.findings : [],
            glossary: activeChannel === 'glossary' ? results.glossary : [],
            top_hit_channel: results.top_hit_channel,
            top_hit_score: results.top_hit_score,
        };
    }, [results, activeChannel]);

    // Fetch search results (lexical channels only initially)
    const fetchSearch = useCallback(async (q: string, includeFindingsOnly: boolean = false) => {
        if (!q) {
            setResults(null);
            setError(null);
            setIsLoading(false);
            setIsLoadingByChannel(emptyLoadingState);
            return;
        }

        // Abort previous main search request before starting new one
        if (mainAbortRef.current) {
            mainAbortRef.current.abort();
        }
        const controller = new AbortController();
        mainAbortRef.current = controller;

        try {
            if (includeFindingsOnly) {
                // Only updating findings channel
                setIsLoadingByChannel(prev => ({ ...prev, findings: true }));
            } else {
                setIsLoading(true);
                setError(null);
                // Mark lexical channels as loading
                setIsLoadingByChannel({
                    all: true,
                    reports: true,
                    ministries: true,
                    entities: true,
                    findings: false, // Findings handled separately
                    glossary: true,
                });
            }

            const data = await smartSearch(
                {
                    q,
                    // Don't pass type to always fetch all channels
                    limit: 10,
                },
                controller.signal
            );

            // Check if aborted
            if (controller.signal.aborted) {
                return;
            }

            if (data === null) {
                // Request was aborted - don't update state
                return;
            }

            if (includeFindingsOnly) {
                // Merge findings into existing results
                setResults(prev => prev ? {
                    ...prev,
                    findings: data.findings,
                    top_hit_channel: data.top_hit_channel,
                    top_hit_score: data.top_hit_score,
                } : data);
                setIsLoadingByChannel(prev => ({ ...prev, findings: false }));
            } else {
                setResults(data);
                setIsLoading(false);
                setIsLoadingByChannel({
                    all: false,
                    reports: false,
                    ministries: false,
                    entities: false,
                    findings: false, // Will be set to true when findings fetch starts
                    glossary: false,
                });
            }

            findingsFetchedRef.current = q;
        } catch (err) {
            if (controller.signal.aborted) {
                // Aborted - ignore
                return;
            }

            setError(err instanceof Error ? err.message : 'Search failed');
            setIsLoading(false);
            setIsLoadingByChannel(emptyLoadingState);
        }
    }, []);

    // Handle findings separately with longer debounce
    const fetchFindings = useCallback(async (q: string) => {
        if (q.length < FINDINGS_MIN_CHARS) {
            return;
        }

        // Abort previous findings request only (don't affect main search)
        if (findingsAbortRef.current) {
            findingsAbortRef.current.abort();
        }
        const controller = new AbortController();
        findingsAbortRef.current = controller;

        setIsLoadingByChannel(prev => ({ ...prev, findings: true }));

        try {
            const data = await smartSearch(
                { q, limit: 10 },
                controller.signal
            );

            if (controller.signal.aborted || data === null) {
                return;
            }

            // Merge findings into existing results
            setResults(prev => prev ? {
                ...prev,
                findings: data.findings,
                // Update top hit if findings channel has the top score
                top_hit_channel: data.top_hit_channel ?? prev.top_hit_channel,
                top_hit_score: data.top_hit_score ?? prev.top_hit_score,
            } : data);

            setIsLoadingByChannel(prev => ({ ...prev, findings: false }));
            findingsFetchedRef.current = q;
        } catch (err) {
            if (!controller.signal.aborted) {
                setIsLoadingByChannel(prev => ({ ...prev, findings: false }));
            }
        }
    }, []);

    // Effect: debounce search
    useEffect(() => {
        // Clear timers
        if (debounceTimerRef.current) {
            clearTimeout(debounceTimerRef.current);
        }
        if (findingsTimerRef.current) {
            clearTimeout(findingsTimerRef.current);
        }

        // Reset state on empty query
        if (!trimmedQuery) {
            // Abort both main search and findings requests
            if (mainAbortRef.current) {
                mainAbortRef.current.abort();
            }
            if (findingsAbortRef.current) {
                findingsAbortRef.current.abort();
            }
            setResults(null);
            setError(null);
            setIsLoading(false);
            setIsLoadingByChannel(emptyLoadingState);
            findingsFetchedRef.current = null;
            return;
        }

        // Debounce the main search (lexical channels)
        debounceTimerRef.current = setTimeout(() => {
            fetchSearch(trimmedQuery);
        }, DEBOUNCE_MS);

        // Separate debounce for findings (longer delay, min chars)
        if (trimmedQuery.length >= FINDINGS_MIN_CHARS) {
            findingsTimerRef.current = setTimeout(() => {
                // Only fetch findings if they haven't been fetched for this query yet
                if (findingsFetchedRef.current !== trimmedQuery) {
                    fetchFindings(trimmedQuery);
                }
            }, FINDINGS_DEBOUNCE_MS);
        }

        // Cleanup
        return () => {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current);
            }
            if (findingsTimerRef.current) {
                clearTimeout(findingsTimerRef.current);
            }
        };
    }, [trimmedQuery, fetchSearch, fetchFindings]);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            // Abort both controllers
            if (mainAbortRef.current) {
                mainAbortRef.current.abort();
            }
            if (findingsAbortRef.current) {
                findingsAbortRef.current.abort();
            }
            // Clear timers
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current);
            }
            if (findingsTimerRef.current) {
                clearTimeout(findingsTimerRef.current);
            }
        };
    }, []);

    return {
        results: filteredResults,
        isLoading,
        isLoadingByChannel,
        error,
        topHit,
    };
}
