/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Home Page - Phase C
 * Top-level composer with smart search wiring and navigation routing
 */

import React, { useState, useCallback } from 'react';
import { ViewState, SearchChannel, SearchResultRow, GroupedSearchResults } from '../../types';
import { useHomeStats, useHomeFacets, useHomeFeatured } from '../../hooks';
import { useAppStore } from '../../stores/appStore';
import { HomeHero } from './HomeHero';
import { FacetChips } from './FacetChips';
import { CTACards } from './CTACards';
import { PopularStartingPoints } from './PopularStartingPoints';
import { MinistryRail } from './MinistryRail';
import { EntityRail } from './EntityRail';
import { FeaturedReportsRail } from './FeaturedReportsRail';
import { DeepDivesRail } from './DeepDivesRail';
import { TrendingSearches } from './TrendingSearches';
import { ToolsGrid } from './ToolsGrid';
import './home.css';

interface HomePageProps {
    setView: (view: ViewState) => void;
    setCurrentSeriesId: (id: string) => void;
    openChatDrawer: () => void;
}

export const HomePage: React.FC<HomePageProps> = ({
    setView,
    setCurrentSeriesId,
    openChatDrawer,
}) => {
    const { setChatMode, setCurrentEntityId, setCurrentReportId } = useAppStore();

    // Smart search state
    const [activeChannel, setActiveChannel] = useState<SearchChannel>('all');
    const [searchQuery, setSearchQuery] = useState('');

    // Fire all three fetches in parallel on mount (§19.1)
    useHomeStats();
    useHomeFacets();
    useHomeFeatured();

    // Navigation handlers
    const handleReportClick = useCallback((reportId: string) => {
        setCurrentReportId(reportId);
        setView('report');
    }, [setCurrentReportId, setView]);

    const handleEntityClick = useCallback((entityId: number) => {
        console.log('[HomePage] navigating to entity:', entityId, 'setting previousView to home');
        setCurrentEntityId(entityId);
        setView('entity');
    }, [setCurrentEntityId, setView]);

    const handleSeriesClick = useCallback((seriesId: string) => {
        setCurrentSeriesId(seriesId);
        setView('time-series');
    }, [setCurrentSeriesId, setView]);

    // Smart search result selection - navigate to the appropriate destination
    const handleResultSelect = useCallback((result: SearchResultRow) => {
        switch (result.kind) {
            case 'report':
                handleReportClick(result.report_id);
                break;
            case 'ministry':
            case 'entity':
                handleEntityClick(result.entity_id);
                break;
            case 'finding':
                // Open chat drawer pre-populated with the finding context
                setChatMode('agentic');
                openChatDrawer();
                break;
            case 'glossary':
                // Navigate to the report containing the glossary term
                handleReportClick(result.report_id);
                break;
        }
    }, [handleReportClick, handleEntityClick, setChatMode, openChatDrawer]);

    // Smart Enter routing (§8.4)
    const handleSmartEnter = useCallback((
        topHit: SearchResultRow | null,
        query: string,
        results: GroupedSearchResults | null
    ) => {
        if (!query.trim()) return;

        // If there's a clear top hit, navigate to it
        if (topHit) {
            handleResultSelect(topHit);
            return;
        }

        // Mixed results or no clear top hit → navigate to directory with query as filter
        // Show "Ask the corpus" CTA at the top
        setView('directory');
        // TODO: Pass query filter to directory page
    }, [handleResultSelect, setView]);

    // Trending search click → pre-fill search bar
    const handleTrendingQueryClick = useCallback((query: string) => {
        setSearchQuery(query);
    }, []);

    // Tools grid handlers
    const handleOpenChat = useCallback(() => {
        setChatMode('agentic');
        openChatDrawer();
    }, [setChatMode, openChatDrawer]);

    const handleFocusSearch = useCallback((channel: SearchChannel) => {
        setActiveChannel(channel);
        // User can then click into the search bar
    }, []);

    return (
        <div className="home-page">
            <HomeHero
                activeChannel={activeChannel}
                onChannelChange={setActiveChannel}
                searchQuery={searchQuery}
                onQueryChange={setSearchQuery}
                onSmartEnter={handleSmartEnter}
                onResultSelect={handleResultSelect}
            />

            <FacetChips setView={setView} />

            <div className="home-section">
                <CTACards
                    setView={setView}
                    setChatMode={setChatMode}
                    openChatDrawer={openChatDrawer}
                />
            </div>

            <div className="home-section">
                <PopularStartingPoints onItemClick={handleEntityClick} />
                <MinistryRail onMinistryClick={handleEntityClick} />
                <EntityRail onEntityClick={handleEntityClick} />
                <FeaturedReportsRail onReportClick={handleReportClick} />
                <DeepDivesRail onSeriesClick={handleSeriesClick} />
                <TrendingSearches onQueryClick={handleTrendingQueryClick} />
            </div>

            <ToolsGrid
                onNavigate={setView}
                onOpenChat={handleOpenChat}
                onFocusSearch={handleFocusSearch}
            />

            <footer className="home-footer">
                <div className="home-footer-links">
                    <a
                        href="#"
                        className="home-footer-link"
                        onClick={(e) => {
                            e.preventDefault();
                            setView('directory');
                            // TODO: Scroll to disclaimer section on directory page
                        }}
                    >
                        Disclaimer
                    </a>
                    <span className="home-footer-link">Privacy</span>
                    <span className="home-footer-link">Terms</span>
                </div>
                <div className="home-footer-copyright">
                    © {new Date().getFullYear()} CAG Gateway
                </div>
            </footer>
        </div>
    );
};
