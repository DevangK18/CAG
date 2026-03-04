/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * FloatingActionButton (FAB) Component
 * Replaces the sticky chat banner with a non-intrusive floating button
 */

import React, { useState, useEffect } from 'react';

// Sparkle icon for AI
const SparkleIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/>
  </svg>
);

interface FABProps {
  onClick: () => void;
  label?: string;
  hasMessages?: number | boolean;
}

export function FloatingActionButton({ onClick, label = "Ask AI", hasMessages = false }: FABProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showTooltip, setShowTooltip] = useState(false);
  const [shouldPulse, setShouldPulse] = useState(false);

  // First-visit tooltip logic
  useEffect(() => {
    const hasSeenFAB = sessionStorage.getItem('fab-tooltip-seen');
    if (!hasSeenFAB) {
      setShowTooltip(true);
      setShouldPulse(true);

      // Stop pulsing after 3 cycles (~4.5 seconds)
      const pulseTimer = setTimeout(() => setShouldPulse(false), 4500);

      // Auto-dismiss tooltip after 4 seconds
      const tooltipTimer = setTimeout(() => {
        setShowTooltip(false);
        sessionStorage.setItem('fab-tooltip-seen', 'true');
      }, 4000);

      return () => {
        clearTimeout(pulseTimer);
        clearTimeout(tooltipTimer);
      };
    }
  }, []);

  return (
    <>
      <button
        className={`fab ${shouldPulse ? 'pulse' : ''} ${isExpanded ? 'expanded' : ''}`}
        onMouseEnter={() => setIsExpanded(true)}
        onMouseLeave={() => setIsExpanded(false)}
        onClick={onClick}
        aria-label={label}
      >
        <span className="fab-icon">
          <SparkleIcon />
        </span>
        {isExpanded && (
          <span className="fab-label">
            {label} {typeof hasMessages === 'number' && hasMessages > 0 && `(${hasMessages})`} →
          </span>
        )}
      </button>

      {showTooltip && (
        <div className="fab-tooltip">
          <p>Ask AI about this report</p>
          <span className="fab-tooltip-arrow" />
        </div>
      )}
    </>
  );
}
