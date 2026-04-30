/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Stats Tiles Component - Phase A (Hardcoded)
 * Big yellow numbers showing corpus stats
 */

import React from 'react';

export const StatsTiles: React.FC = () => {
    // Phase A: Hardcoded values
    const stats = [
        { number: '37', label: 'REPORTS' },
        { number: '390', label: 'ENTITIES' },
        { number: '25K', label: 'MENTIONS' },
        { number: '5K', label: 'FINDINGS' },
        { number: '10', label: 'STATES' },
    ];

    return (
        <div className="home-stats-tiles">
            {stats.map((stat, index) => (
                <div key={index} className="home-stat-tile">
                    <div className="home-stat-number">{stat.number}</div>
                    <div className="home-stat-label">{stat.label}</div>
                </div>
            ))}
        </div>
    );
};
