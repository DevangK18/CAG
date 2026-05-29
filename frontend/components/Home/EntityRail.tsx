/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Rail - Phase B
 * Horizontal scrollable entity cards
 */

import React, { useEffect } from 'react';
import { useHomeFeatured } from '../../hooks';
import { formatEntityType } from '../../utils';

const getEntityIcon = (type: string): string => {
    const t = type.toLowerCase();
    if (t.includes('psu')) return '🏢';
    if (t.includes('scheme')) return '📋';
    if (t.includes('ministry')) return '🏛️';
    return '🔷';
};

interface EntityRailProps {
    onEntityClick?: (entityId: number) => void;
}

export const EntityRail: React.FC<EntityRailProps> = ({ onEntityClick }) => {
    const { featured, isLoading } = useHomeFeatured();

    const entities = featured?.top_entities || [];

    if (isLoading) {
        return (
            <div className="home-rail">
                <h2 className="home-rail-title">Top-Mentioned PSUs & Schemes</h2>
                <div className="home-rail-scroll">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="home-skeleton-card" />
                    ))}
                </div>
            </div>
        );
    }

    if (entities.length === 0) {
        return null;
    }

    return (
        <div className="home-rail">
            <h2 className="home-rail-title">Top-Mentioned PSUs & Schemes</h2>
            <div className="home-rail-scroll">
                {entities.map((entity) => (
                    <div
                        key={entity.entity_id}
                        className="home-entity-card"
                        onClick={() => onEntityClick?.(entity.entity_id)}
                    >
                        <div className="home-entity-icon">{getEntityIcon(entity.entity_type)}</div>
                        <div className="home-entity-name">{entity.canonical_name}</div>
                        <div className="home-entity-type">{formatEntityType(entity.entity_type)}</div>
                        <div className="home-entity-stats">
                            {entity.mention_count} mentions · {entity.finding_count} findings
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};
