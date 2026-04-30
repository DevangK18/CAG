/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Smart Search Bar - Phase A (Non-functional)
 * Renders with rotating placeholder but no actual search yet
 */

import React, { useState, useEffect } from 'react';

const SearchIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.35-4.35"/>
    </svg>
);

export const SmartSearchBar: React.FC = () => {
    const placeholders = [
        'Try: railway safety findings',
        'Try: NHAI',
        'Try: Maharashtra 2023',
    ];

    const [placeholderIndex, setPlaceholderIndex] = useState(0);

    useEffect(() => {
        const interval = setInterval(() => {
            setPlaceholderIndex((prev) => (prev + 1) % placeholders.length);
        }, 3000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="home-search-container">
            <div className="home-search-icon">
                <SearchIcon />
            </div>
            <input
                type="text"
                className="home-search-bar"
                placeholder={placeholders[placeholderIndex]}
                // Phase A: Non-functional - no onChange handler
            />
            <div className="home-search-shortcut">/</div>
        </div>
    );
};
