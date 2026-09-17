/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tools Grid Component
 * 6 static tiles showing capabilities
 */

import React from 'react';
import { ViewState, SearchChannel } from '../../types';

interface ToolsGridProps {
    onNavigate: (view: ViewState) => void;
    onOpenChat?: () => void;
    onFocusSearch?: (channel: SearchChannel) => void;
}

export const ToolsGrid: React.FC<ToolsGridProps> = ({ onNavigate, onOpenChat, onFocusSearch }) => {
    const tools = [
        {
            icon: '💬',
            label: 'Chat',
            onClick: () => onNavigate('corpus-chat'),
        },
        {
            icon: '📊',
            label: 'Charts',
            onClick: () => onNavigate('directory'),
        },
        {
            icon: '📋',
            label: 'Tables',
            onClick: () => onNavigate('directory'),
        },
        {
            icon: '📖',
            label: 'Glossary',
            onClick: () => onFocusSearch?.('glossary'),
        },
        {
            icon: '📈',
            label: 'Time Series',
            onClick: () => onNavigate('time-series'),
        },
        {
            icon: '📝',
            label: 'Summaries',
            onClick: () => onNavigate('directory'),
        },
    ];

    return (
        <div className="home-section">
            <h2 className="home-section-title">Explore Our Tools</h2>
            <div className="home-tools-grid">
                {tools.map((tool, index) => (
                    <div
                        key={index}
                        className="home-tool-tile"
                        onClick={tool.onClick}
                        style={{ cursor: 'pointer' }}
                    >
                        <div className="home-tool-icon">{tool.icon}</div>
                        <div className="home-tool-label">{tool.label}</div>
                    </div>
                ))}
            </div>
        </div>
    );
};
