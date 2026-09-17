/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Stats Tiles Component - Phase B
 * Big yellow numbers showing corpus stats from real API
 */

import React from 'react';
import { useHomeStats } from '../../hooks';
import { formatStat } from '../../utils';

export const StatsTiles: React.FC = () => {
    const { stats, isLoading } = useHomeStats();

    // Show placeholder "—" during loading
    const displayStats = [
        { number: stats ? stats.total_reports.toString() : '—', label: 'REPORTS' },
        { number: stats ? stats.total_entities.toString() : '—', label: 'ENTITIES' },
        { number: stats ? formatStat(stats.total_mentions) : '—', label: 'MENTIONS' },
        { number: stats ? formatStat(stats.total_findings) : '—', label: 'FINDINGS' },
        { number: stats ? stats.year_range[1] - stats.year_range[0] + 1 + ' YEARS' : '—', label: 'COVERED' },
    ];

    return (
        <div className="home-stats-tiles">
            {displayStats.map((stat, index) => (
                <div key={index} className="home-stat-tile">
                    <div className="home-stat-number">{stat.number}</div>
                    <div className="home-stat-label">{stat.label}</div>
                </div>
            ))}
        </div>
    );
};
