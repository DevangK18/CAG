/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Mentions Tab Component
 * Phase D: Shows individual mentions of the entity across reports
 */

import React, { useState, useEffect } from 'react';
import { getEntityMentions } from '../../lib/api';

interface EntityMentionsTabProps {
  entityId: number;
}

export function EntityMentionsTab({ entityId }: EntityMentionsTabProps) {
  const [mentions, setMentions] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchMentions = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const data = await getEntityMentions(entityId, { limit: 200 });
        if (!cancelled) {
          setMentions(data);
          setIsLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load mentions');
          setIsLoading(false);
        }
      }
    };

    fetchMentions();

    return () => {
      cancelled = true;
    };
  }, [entityId]);

  if (isLoading) {
    return <div style={{ padding: '1rem', color: '#6b7280' }}>Loading mentions...</div>;
  }

  if (error) {
    return <div style={{ padding: '1rem', color: '#ef4444' }}>{error}</div>;
  }

  if (mentions.length === 0) {
    return (
      <div style={{ padding: '1rem', color: '#6b7280' }}>
        No mentions found for this entity.
      </div>
    );
  }

  return (
    <div className="entity-mentions-tab">
      <div style={{ marginBottom: '1rem', color: '#6b7280', fontSize: '0.875rem' }}>
        {mentions.length} mention{mentions.length !== 1 ? 's' : ''} found
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {mentions.map((mention, idx) => (
          <div
            key={idx}
            style={{
              padding: '1rem',
              border: '1px solid #e5e7eb',
              borderRadius: '0.5rem',
              backgroundColor: '#ffffff',
            }}
          >
            {/* Context Snippet */}
            <div
              style={{
                marginBottom: '0.75rem',
                color: '#374151',
                lineHeight: '1.6',
                fontSize: '0.875rem',
              }}
            >
              {mention.context_snippet || mention.snippet || 'No context available'}
            </div>

            {/* Metadata */}
            <div
              style={{
                display: 'flex',
                gap: '1rem',
                flexWrap: 'wrap',
                fontSize: '0.75rem',
                color: '#6b7280',
              }}
            >
              {mention.report_id && (
                <span>Report: {mention.report_id}</span>
              )}
              {mention.audit_year && (
                <span>Year: {mention.audit_year}</span>
              )}
              {mention.section && (
                <span>Section: {mention.section}</span>
              )}
              {mention.page !== undefined && (
                <span>Page: {mention.page}</span>
              )}
              {mention.finding_type && (
                <span
                  style={{
                    padding: '0.125rem 0.375rem',
                    borderRadius: '0.25rem',
                    backgroundColor: '#f3f4f6',
                  }}
                >
                  {mention.finding_type.replace(/_/g, ' ')}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default EntityMentionsTab;
