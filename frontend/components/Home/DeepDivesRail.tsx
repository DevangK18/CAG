/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Deep Dives Rail - Phase B
 * Time series collections for multi-year analysis
 */

import React from 'react';
import { useHomeFeatured } from '../../hooks';

interface DeepDivesRailProps {
    onSeriesClick?: (seriesId: string) => void;
}

export const DeepDivesRail: React.FC<DeepDivesRailProps> = ({ onSeriesClick }) => {
    const { featured, isLoading } = useHomeFeatured();

    if (isLoading) {
        return (
            <div className="home-rail">
                <h2 className="home-rail-title">Deep Dive Collections</h2>
                <div className="home-deep-dive-cards-grid">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="home-skeleton-card" />
                    ))}
                </div>
            </div>
        );
    }

    const series = featured?.deep_dives || [];

    if (series.length === 0) {
        return null;
    }

    return (
        <div className="home-rail">
            <h2 className="home-rail-title">Deep Dive Collections</h2>
            <div className="home-deep-dive-cards-grid">
                {series.map((item) => (
                    <div
                        key={item.series_id}
                        className="home-series-card"
                        onClick={() => onSeriesClick?.(item.series_id)}
                    >
                        <div className="home-series-icon">📊</div>
                        <div className="home-series-name">{item.name}</div>
                        <div className="home-series-description">{item.description}</div>
                        <div className="home-series-stats">
                            {item.reports.length} reports · {item.years_covered.length} years
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};
