/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Surprise Me Button - Phase B
 * Fetches random report or entity on click
 */

import React, { useEffect } from 'react';
import { useSurpriseMe } from '../../hooks';
import type { APIReportSummary } from '../../lib/api';
import type { EntitySummary } from '../../types';

interface SurpriseMeButtonProps {
    variant?: 'report' | 'entity';
    inline?: boolean;
    onReportSelect?: (reportId: string) => void;
    onEntitySelect?: (entityId: number) => void;
}

const ShuffleIcon = ({ spinning }: { spinning: boolean }) => (
    <svg
        xmlns="http://www.w3.org/2000/svg"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={spinning ? 'home-shuffle-spin' : ''}
    >
        <polyline points="16 3 21 3 21 8"/>
        <line x1="4" y1="20" x2="21" y2="3"/>
        <polyline points="21 16 21 21 16 21"/>
        <line x1="15" y1="15" x2="21" y2="21"/>
        <line x1="4" y1="4" x2="9" y2="9"/>
    </svg>
);

export const SurpriseMeButton: React.FC<SurpriseMeButtonProps> = ({
    variant = 'report',
    inline = false,
    onReportSelect,
    onEntitySelect,
}) => {
    const { result, isLoading, trigger } = useSurpriseMe(variant);

    useEffect(() => {
        if (!result) return;

        if (variant === 'report' && onReportSelect) {
            const report = result as APIReportSummary;
            onReportSelect(report.id);
        } else if (variant === 'entity' && onEntitySelect) {
            const entity = result as EntitySummary;
            onEntitySelect(entity.id);
        }
    }, [result, variant, onReportSelect, onEntitySelect]);

    const handleClick = async () => {
        await trigger();
    };

    return (
        <button
            className="home-surprise-btn"
            onClick={handleClick}
            disabled={isLoading}
        >
            <ShuffleIcon spinning={isLoading} />
            <span>Surprise Me</span>
        </button>
    );
};
