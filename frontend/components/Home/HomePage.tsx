/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Home Page - Phase A
 * Top-level composer with hardcoded data and loading placeholders
 */

import React from 'react';
import { ViewState } from '../../types';
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
    setChatMode: (mode: 'regular' | 'agentic') => void;
    openChatDrawer: () => void;
}

export const HomePage: React.FC<HomePageProps> = ({ setView, setChatMode, openChatDrawer }) => {
    return (
        <div className="home-page">
            <HomeHero />

            <FacetChips />

            <div className="home-section">
                <CTACards
                    setView={setView}
                    setChatMode={setChatMode}
                    openChatDrawer={openChatDrawer}
                />
            </div>

            <div className="home-section">
                <PopularStartingPoints />
                <MinistryRail />
                <EntityRail />
                <FeaturedReportsRail />
                <DeepDivesRail />
                <TrendingSearches />
            </div>

            <ToolsGrid />

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
                    © 2025 CAG Gateway
                </div>
            </footer>
        </div>
    );
};
