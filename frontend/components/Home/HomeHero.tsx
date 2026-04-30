/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Home Hero Component - Phase C
 * Title, channel tabs, search bar, surprise me, explainer with live stats, stats tiles
 */

import React from 'react';
import { useHomeStats } from '../../hooks';
import { formatStat } from '../../utils';
import { EntityChannelTabs } from './EntityChannelTabs';
import { SmartSearchBar } from './SmartSearchBar';
import { SurpriseMeButton } from './SurpriseMeButton';
import { StatsTiles } from './StatsTiles';
import type { SearchChannel, SearchResultRow, GroupedSearchResults } from '../../types';

interface HomeHeroProps {
    activeChannel: SearchChannel;
    onChannelChange: (channel: SearchChannel) => void;
    searchQuery: string;
    onQueryChange: (query: string) => void;
    onSmartEnter: (topHit: SearchResultRow | null, query: string, results: GroupedSearchResults | null) => void;
    onResultSelect: (result: SearchResultRow) => void;
}

export const HomeHero: React.FC<HomeHeroProps> = ({
    activeChannel,
    onChannelChange,
    searchQuery,
    onQueryChange,
    onSmartEnter,
    onResultSelect,
}) => {
    const { stats } = useHomeStats();

    // Build explainer with live numbers
    const explainer = stats
        ? `Search ${stats.total_reports} CAG audit reports — ${stats.total_entities} entities, ${formatStat(stats.total_mentions)} mentions, ${formatStat(stats.total_findings)} findings. Free, no signup.`
        : 'Search — CAG audit reports — — entities, — mentions, — findings. Free, no signup.';

    return (
        <div className="home-hero">
            <h1 className="home-hero-title">AUDIT INTELLIGENCE</h1>

            <EntityChannelTabs
                activeChannel={activeChannel}
                onChannelChange={onChannelChange}
            />
            <SmartSearchBar
                activeChannel={activeChannel}
                onQueryChange={onQueryChange}
                onSmartEnter={onSmartEnter}
                onResultSelect={onResultSelect}
                externalQuery={searchQuery}
            />
            <SurpriseMeButton variant="report" inline />

            <p className="home-hero-explainer">
                {explainer}
            </p>

            <StatsTiles />
        </div>
    );
};
