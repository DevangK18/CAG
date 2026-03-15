/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * TierSelector Component - Government Tier Tab Navigation
 * Allows switching between Union, State, and Local Body reports
 */

import React from 'react';
import { GovernmentTier } from '../constants';

interface TierSelectorProps {
  activeTier: GovernmentTier;
  onTierChange: (tier: GovernmentTier) => void;
  counts: { union: number; state: number; local: number };
}

const TIERS: { id: GovernmentTier; label: string }[] = [
  { id: 'union', label: 'Union' },
  { id: 'state', label: 'State' },
  { id: 'local', label: 'Local Bodies' },
];

export function TierSelector({ activeTier, onTierChange, counts }: TierSelectorProps) {
  return (
    <div className="tier-selector">
      <div className="tier-tabs">
        {TIERS.map((tier) => {
          const isActive = activeTier === tier.id;
          const count = counts[tier.id];

          return (
            <button
              key={tier.id}
              className={`tier-tab ${isActive ? 'active' : ''}`}
              onClick={() => onTierChange(tier.id)}
              aria-selected={isActive}
              role="tab"
            >
              <span className="tier-label">{tier.label}</span>
              <span className="tier-count">({count})</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
