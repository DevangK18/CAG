/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Trending Searches - Phase B
 * Popular queries from query_logs, sanitized server-side
 */

import React, { useState, useEffect } from 'react';
import { getHomeTrending } from '../../lib/api';
import type { TrendingSearch } from '../../types';

interface TrendingSearchesProps {
    onQueryClick?: (query: string) => void;
}

export const TrendingSearches: React.FC<TrendingSearchesProps> = ({ onQueryClick }) => {
    const [trending, setTrending] = useState<TrendingSearch[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let isMounted = true;

        async function fetchTrending() {
            try {
                setIsLoading(true);
                setError(null);
                const data = await getHomeTrending();
                if (isMounted) {
                    setTrending(data);
                }
            } catch (err) {
                if (isMounted) {
                    setError(err instanceof Error ? err.message : 'Failed to fetch trending searches');
                }
            } finally {
                if (isMounted) {
                    setIsLoading(false);
                }
            }
        }

        fetchTrending();

        return () => {
            isMounted = false;
        };
    }, []);

    if (isLoading) {
        return (
            <div className="home-rail">
                <h2 className="home-rail-title">Popular This Week</h2>
                <div className="home-rail-scroll">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="home-skeleton-card" />
                    ))}
                </div>
            </div>
        );
    }

    if (error || trending.length === 0) {
        return null;
    }

    return (
        <div className="home-rail">
            <h2 className="home-rail-title">Popular This Week</h2>
            <div className="home-trending-list">
                {trending.map((item, index) => (
                    <div
                        key={index}
                        className="home-trending-item"
                        onClick={() => onQueryClick?.(item.query_text)}
                    >
                        <span className="home-trending-query">{item.query_text}</span>
                        <span className="home-trending-count">{item.hit_count} searches</span>
                    </div>
                ))}
            </div>
        </div>
    );
};
