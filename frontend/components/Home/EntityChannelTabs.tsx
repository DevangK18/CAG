/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Channel Tabs - Phase A (Static)
 * All · Reports · Ministries · Entities · Findings · Glossary
 */

import React, { useState } from 'react';

export const EntityChannelTabs: React.FC = () => {
    const [activeChannel, setActiveChannel] = useState<string>('all');

    const channels = [
        { id: 'all', label: 'All' },
        { id: 'reports', label: 'Reports' },
        { id: 'ministries', label: 'Ministries' },
        { id: 'entities', label: 'Entities' },
        { id: 'findings', label: 'Findings' },
        { id: 'glossary', label: 'Glossary' },
    ];

    return (
        <div className="home-channel-tabs">
            {channels.map((channel) => (
                <button
                    key={channel.id}
                    className={`home-channel-tab ${activeChannel === channel.id ? 'active' : ''}`}
                    onClick={() => setActiveChannel(channel.id)}
                >
                    {channel.label}
                </button>
            ))}
        </div>
    );
};
