/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Surprise Me Button - Phase A (No-op)
 * Will fetch random report/entity in Phase B
 */

import React from 'react';

interface SurpriseMeButtonProps {
    variant?: 'report' | 'entity';
    inline?: boolean;
}

const ShuffleIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 3 21 3 21 8"/>
        <line x1="4" y1="20" x2="21" y2="3"/>
        <polyline points="21 16 21 21 16 21"/>
        <line x1="15" y1="15" x2="21" y2="21"/>
        <line x1="4" y1="4" x2="9" y2="9"/>
    </svg>
);

export const SurpriseMeButton: React.FC<SurpriseMeButtonProps> = ({ variant = 'report', inline = false }) => {
    const handleClick = () => {
        // Phase A: No-op
        console.log('Surprise Me clicked:', variant);
    };

    return (
        <button className="home-surprise-btn" onClick={handleClick}>
            <ShuffleIcon />
            <span>Surprise Me</span>
        </button>
    );
};
