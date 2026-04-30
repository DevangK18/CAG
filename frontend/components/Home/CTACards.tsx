/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * CTA Cards Component
 * Three cards: Browse Reports, Compare Over Time, Ask the Corpus
 */

import React from 'react';
import { ViewState } from '../../types';

interface CTACardsProps {
    setView: (view: ViewState) => void;
    setChatMode: (mode: 'regular' | 'agentic') => void;
    openChatDrawer: () => void;
}

const GridIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7"/>
        <rect x="14" y="3" width="7" height="7"/>
        <rect x="14" y="14" width="7" height="7"/>
        <rect x="3" y="14" width="7" height="7"/>
    </svg>
);

const TrendingIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>
        <polyline points="17 6 23 6 23 12"/>
    </svg>
);

const ChatIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
);

export const CTACards: React.FC<CTACardsProps> = ({ setView, setChatMode, openChatDrawer }) => {
    const handleAskCorpus = () => {
        setChatMode('agentic');
        openChatDrawer();
    };

    const cards = [
        {
            icon: <GridIcon />,
            title: 'Browse Reports',
            description: 'Explore the full directory of CAG audit reports',
            onClick: () => setView('directory'),
        },
        {
            icon: <TrendingIcon />,
            title: 'Compare Over Time',
            description: 'Analyze trends across multiple audit years',
            onClick: () => setView('time-series'),
        },
        {
            icon: <ChatIcon />,
            title: 'Ask the Corpus',
            description: 'Search across all reports with AI-powered chat',
            onClick: handleAskCorpus,
        },
    ];

    return (
        <div className="home-cta-cards">
            {cards.map((card, index) => (
                <div key={index} className="home-cta-card" onClick={card.onClick}>
                    <div className="home-cta-card-icon">{card.icon}</div>
                    <div className="home-cta-card-title">{card.title}</div>
                    <div className="home-cta-card-desc">{card.description}</div>
                </div>
            ))}
        </div>
    );
};
