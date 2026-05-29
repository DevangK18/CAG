/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Facet Chips - Phase B
 * Multi-select facets that navigate to directory with filters applied
 */

import React, { useState } from 'react';
import { useHomeFacets } from '../../hooks';
import { useAppStore } from '../../stores/appStore';
import { isValidMinistry } from '../../utils';
import { ViewState } from '../../types';

const ChevronDownIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="6 9 12 15 18 9"/>
    </svg>
);

interface FacetChipsProps {
    setView: (view: ViewState) => void;
}

export const FacetChips: React.FC<FacetChipsProps> = ({ setView }) => {
    const { facets, isLoading } = useHomeFacets();
    const { setSearchFilters, searchFilters } = useAppStore();
    const [openPopover, setOpenPopover] = useState<string | null>(null);

    const handleFacetClick = (facetId: string) => {
        // v1: Navigate to directory for filtering
        // Clicking chips takes you to the full directory where filters are available
        setView('directory');
    };

    if (isLoading || !facets) {
        return (
            <div className="home-facet-chips">
                {['Tier', 'State', 'Year', 'Ministry', 'Entity', 'Audit Type'].map((label, i) => (
                    <button key={i} className="home-facet-chip home-facet-chip-disabled" disabled>
                        {label}
                        <ChevronDownIcon />
                    </button>
                ))}
            </div>
        );
    }

    // Filter invalid ministries and entities
    const validMinistries = facets.ministries.filter((m) => isValidMinistry(m.label || m.value));
    const validEntities = facets.entities.filter((e) => e.count >= 5); // Low-signal threshold

    const facetList = [
        { id: 'tier', label: 'Tier', count: facets.tiers.length },
        { id: 'state', label: 'State', count: facets.states.length },
        { id: 'year', label: 'Year', count: facets.years.length },
        { id: 'ministry', label: 'Ministry', count: validMinistries.length },
        { id: 'entity', label: 'Entity', count: validEntities.length },
        { id: 'audit_type', label: 'Audit Type', count: facets.audit_categories.length },
    ];

    return (
        <div className="home-facet-chips">
            {facetList.map((facet) => (
                <button
                    key={facet.id}
                    className="home-facet-chip"
                    onClick={() => handleFacetClick(facet.id)}
                    title={`Browse reports by ${facet.label.toLowerCase()} — opens Report Directory`}
                >
                    {facet.label}
                    {facet.count > 0 && <span className="home-facet-count">({facet.count})</span>}
                    <ChevronDownIcon />
                </button>
            ))}
        </div>
    );
};
