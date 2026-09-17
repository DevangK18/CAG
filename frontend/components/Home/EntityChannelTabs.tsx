/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Channel Tabs - Phase C
 * All · Reports · Ministries · Entities · Findings · Glossary
 *
 * Tab click updates activeChannel in local state (no new API call).
 * Already-fetched results are filtered client-side.
 */

import React from 'react';
import type { SearchChannel } from '../../types';

interface EntityChannelTabsProps {
    activeChannel: SearchChannel;
    onChannelChange: (channel: SearchChannel) => void;
}

const CHANNELS: { id: SearchChannel; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'reports', label: 'Reports' },
    { id: 'ministries', label: 'Ministries' },
    { id: 'entities', label: 'Entities' },
    { id: 'findings', label: 'Findings' },
    { id: 'glossary', label: 'Glossary' },
];

export const EntityChannelTabs: React.FC<EntityChannelTabsProps> = ({
    activeChannel,
    onChannelChange,
}) => {
    return (
        <div className="home-channel-tabs">
            {CHANNELS.map((channel) => (
                <button
                    key={channel.id}
                    className={`home-channel-tab ${activeChannel === channel.id ? 'active' : ''}`}
                    onClick={() => onChannelChange(channel.id)}
                >
                    {channel.label}
                </button>
            ))}
        </div>
    );
};
