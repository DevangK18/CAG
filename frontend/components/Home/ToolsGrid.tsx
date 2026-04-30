/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tools Grid Component
 * 6 static tiles showing capabilities
 */

import React from 'react';

export const ToolsGrid: React.FC = () => {
    const tools = [
        { icon: '💬', label: 'Chat' },
        { icon: '📊', label: 'Charts' },
        { icon: '📋', label: 'Tables' },
        { icon: '📖', label: 'Glossary' },
        { icon: '📈', label: 'Time Series' },
        { icon: '📝', label: 'Summaries' },
    ];

    return (
        <div className="home-section">
            <h2 className="home-section-title">Explore Our Tools</h2>
            <div className="home-tools-grid">
                {tools.map((tool, index) => (
                    <div key={index} className="home-tool-tile">
                        <div className="home-tool-icon">{tool.icon}</div>
                        <div className="home-tool-label">{tool.label}</div>
                    </div>
                ))}
            </div>
        </div>
    );
};
