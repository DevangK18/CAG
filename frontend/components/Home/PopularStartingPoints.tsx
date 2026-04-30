/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Popular Starting Points - Phase B
 * 10 deterministic items per day (server-seeded)
 */

import React from 'react';
import { useHomeFeatured } from '../../hooks';
import { isValidMinistry } from '../../utils';
import type { FeaturedMinistry, FeaturedEntity } from '../../types';

const getIcon = (item: FeaturedMinistry | FeaturedEntity): string => {
    if ('entity_type' in item) {
        // It's a FeaturedEntity
        const t = item.entity_type.toLowerCase();
        if (t.includes('psu')) return '🏢';
        if (t.includes('scheme')) return '📋';
        if (t.includes('ministry')) return '🏛️';
        return '🔷';
    }
    // It's a FeaturedMinistry
    return '🏛️';
};

const getName = (item: FeaturedMinistry | FeaturedEntity): string => {
    return item.canonical_name;
};

const getStats = (item: FeaturedMinistry | FeaturedEntity): string => {
    if ('entity_type' in item) {
        // FeaturedEntity
        return `${item.mention_count} mentions · ${item.finding_count} findings`;
    }
    // FeaturedMinistry
    return `${item.report_count} reports · ${item.mention_count} mentions`;
};

interface PopularStartingPointsProps {
    onItemClick?: (entityId: number) => void;
}

export const PopularStartingPoints: React.FC<PopularStartingPointsProps> = ({ onItemClick }) => {
    const { featured, isLoading } = useHomeFeatured();

    if (isLoading) {
        return (
            <div className="home-rail">
                <h2 className="home-rail-title">Popular Starting Points</h2>
                <div className="home-popular-grid">
                    {[1, 2, 3, 4, 5, 6].map((i) => (
                        <div key={i} className="home-skeleton-card" />
                    ))}
                </div>
            </div>
        );
    }

    // Filter out "Unknown Ministry" entries
    const items = (featured?.popular_starts || []).filter((item) => {
        const name = getName(item);
        return isValidMinistry(name);
    });

    if (items.length === 0) {
        return null;
    }

    return (
        <div className="home-rail">
            <h2 className="home-rail-title">Popular Starting Points</h2>
            <div className="home-popular-grid">
                {items.map((item) => (
                    <div
                        key={item.entity_id}
                        className="home-popular-tile"
                        onClick={() => onItemClick?.(item.entity_id)}
                    >
                        <div className="home-popular-icon">{getIcon(item)}</div>
                        <div className="home-popular-name">{getName(item)}</div>
                        <div className="home-popular-stats">{getStats(item)}</div>
                    </div>
                ))}
            </div>
        </div>
    );
};
