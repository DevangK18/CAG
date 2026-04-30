/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Facet Chips - Phase A (Static buttons)
 * Multi-select facets: Tier, State, Year, Ministry, Entity, Audit Type
 */

import React from 'react';

const ChevronDownIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="6 9 12 15 18 9"/>
    </svg>
);

export const FacetChips: React.FC = () => {
    const facets = [
        { id: 'tier', label: 'Tier' },
        { id: 'state', label: 'State' },
        { id: 'year', label: 'Year' },
        { id: 'ministry', label: 'Ministry' },
        { id: 'entity', label: 'Entity' },
        { id: 'audit_type', label: 'Audit Type' },
    ];

    return (
        <div className="home-facet-chips">
            {facets.map((facet) => (
                <button
                    key={facet.id}
                    className="home-facet-chip"
                    // Phase A: No click handler
                >
                    {facet.label}
                    <ChevronDownIcon />
                </button>
            ))}
        </div>
    );
};
