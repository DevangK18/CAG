/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Home Hero Component
 * Title, search bar, explainer, stats tiles
 */

import React from 'react';
import { EntityChannelTabs } from './EntityChannelTabs';
import { SmartSearchBar } from './SmartSearchBar';
import { SurpriseMeButton } from './SurpriseMeButton';
import { StatsTiles } from './StatsTiles';

export const HomeHero: React.FC = () => {
    return (
        <div className="home-hero">
            <h1 className="home-hero-title">AUDIT INTELLIGENCE</h1>

            <EntityChannelTabs />
            <SmartSearchBar />
            <SurpriseMeButton variant="report" inline />

            <p className="home-hero-explainer">
                Search 37 CAG audit reports — 390 entities, 25K mentions, 5K findings. Free, no signup.
            </p>

            <StatsTiles />
        </div>
    );
};
