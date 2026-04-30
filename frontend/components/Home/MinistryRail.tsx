/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Ministry Rail - Phase B
 * Horizontal scrollable ministry cards
 */

import React from 'react';
import { useHomeFeatured } from '../../hooks';
import { isValidMinistry } from '../../utils';

interface MinistryRailProps {
    onMinistryClick?: (entityId: number) => void;
}

export const MinistryRail: React.FC<MinistryRailProps> = ({ onMinistryClick }) => {
    const { featured, isLoading } = useHomeFeatured();

    if (isLoading) {
        return (
            <div className="home-rail">
                <h2 className="home-rail-title">Most-Referenced Ministries</h2>
                <div className="home-rail-scroll">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="home-skeleton-card" />
                    ))}
                </div>
            </div>
        );
    }

    // Filter out "Unknown Ministry" and similar
    const validMinistries = (featured?.top_ministries || []).filter((m) =>
        isValidMinistry(m.canonical_name)
    );

    if (validMinistries.length === 0) {
        return null;
    }

    return (
        <div className="home-rail">
            <h2 className="home-rail-title">Most-Referenced Ministries</h2>
            <div className="home-rail-scroll">
                {validMinistries.map((ministry) => (
                    <div
                        key={ministry.entity_id}
                        className="home-ministry-card"
                        onClick={() => onMinistryClick?.(ministry.entity_id)}
                    >
                        <div className="home-ministry-icon">🏛️</div>
                        <div className="home-ministry-name">{ministry.canonical_name}</div>
                        <div className="home-ministry-stats">
                            {ministry.report_count} reports · {ministry.mention_count} mentions
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};
