/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Header Component
 * Phase D: Shows entity name, type, aliases, and stats
 */

import React from 'react';
import { EntityDetail } from '../../types';

interface EntityHeaderProps {
  entity: EntityDetail;
  onBack: () => void;
}

function formatNumber(num: number): string {
  if (num >= 1000) {
    return `${(num / 1000).toFixed(1)}K`;
  }
  return num.toString();
}

export function EntityHeader({ entity, onBack }: EntityHeaderProps) {
  return (
    <div className="entity-header">
      {/* Back Button */}
      <button
        onClick={onBack}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          padding: '0.5rem 1rem',
          backgroundColor: '#f3f4f6',
          border: '1px solid #d1d5db',
          borderRadius: '0.375rem',
          cursor: 'pointer',
          marginBottom: '1.5rem',
          fontSize: '0.875rem',
          color: '#374151',
        }}
      >
        ← Back
      </button>

      {/* Entity Name */}
      <h1
        style={{
          fontSize: '2rem',
          fontWeight: '700',
          color: '#111827',
          marginBottom: '0.5rem',
        }}
      >
        {entity.canonical_name}
      </h1>

      {/* Entity Type & Tier */}
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          alignItems: 'center',
          marginBottom: '0.75rem',
        }}
      >
        <span
          style={{
            padding: '0.25rem 0.75rem',
            backgroundColor: '#dbeafe',
            color: '#1e40af',
            borderRadius: '0.375rem',
            fontSize: '0.875rem',
            fontWeight: '500',
          }}
        >
          {entity.entity_type}
        </span>
        <span style={{ color: '#6b7280', fontSize: '0.875rem' }}>·</span>
        <span style={{ color: '#6b7280', fontSize: '0.875rem', textTransform: 'capitalize' }}>
          {entity.primary_tier} tier
        </span>
      </div>

      {/* Aliases */}
      {entity.aliases && entity.aliases.length > 0 && (
        <div style={{ marginBottom: '1rem', color: '#6b7280', fontSize: '0.875rem' }}>
          <span style={{ fontWeight: '500' }}>Aliases: </span>
          {entity.aliases.join(', ')}
        </div>
      )}

      {/* Stats Row */}
      <div
        style={{
          display: 'flex',
          gap: '2rem',
          padding: '1rem',
          backgroundColor: '#f9fafb',
          borderRadius: '0.5rem',
          border: '1px solid #e5e7eb',
        }}
      >
        <div>
          <div style={{ fontSize: '1.5rem', fontWeight: '700', color: '#111827' }}>
            {entity.report_count}
          </div>
          <div style={{ fontSize: '0.75rem', color: '#6b7280', textTransform: 'uppercase' }}>
            Reports
          </div>
        </div>
        <div>
          <div style={{ fontSize: '1.5rem', fontWeight: '700', color: '#111827' }}>
            {formatNumber(entity.mention_count)}
          </div>
          <div style={{ fontSize: '0.75rem', color: '#6b7280', textTransform: 'uppercase' }}>
            Mentions
          </div>
        </div>
        <div>
          <div style={{ fontSize: '1.5rem', fontWeight: '700', color: '#111827' }}>
            {entity.finding_count}
          </div>
          <div style={{ fontSize: '0.75rem', color: '#6b7280', textTransform: 'uppercase' }}>
            Findings
          </div>
        </div>
        {entity.first_seen_year && entity.last_seen_year && (
          <div>
            <div style={{ fontSize: '1.5rem', fontWeight: '700', color: '#111827' }}>
              {entity.first_seen_year}–{entity.last_seen_year}
            </div>
            <div style={{ fontSize: '0.75rem', color: '#6b7280', textTransform: 'uppercase' }}>
              Years
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default EntityHeader;
