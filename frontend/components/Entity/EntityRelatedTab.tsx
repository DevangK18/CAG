/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Related Tab Component
 * Phase D: Shows related entities (co-mentioned entities)
 */

import React, { useState, useEffect } from 'react';
import { getEntityRelated } from '../../lib/api';
import { useAppStore } from '../../stores/appStore';

interface EntityRelatedTabProps {
  entityId: number;
}

export function EntityRelatedTab({ entityId }: EntityRelatedTabProps) {
  const [relatedEntities, setRelatedEntities] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { setCurrentEntityId, setView } = useAppStore();

  useEffect(() => {
    let cancelled = false;

    const fetchRelated = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const data = await getEntityRelated(entityId, 50);
        if (!cancelled) {
          setRelatedEntities(data);
          setIsLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load related entities');
          setIsLoading(false);
        }
      }
    };

    fetchRelated();

    return () => {
      cancelled = true;
    };
  }, [entityId]);

  const handleEntityClick = (relatedEntityId: number) => {
    setCurrentEntityId(relatedEntityId);
    setView('entity');
  };

  if (isLoading) {
    return <div style={{ padding: '1rem', color: '#6b7280' }}>Loading related entities...</div>;
  }

  if (error) {
    return <div style={{ padding: '1rem', color: '#ef4444' }}>{error}</div>;
  }

  if (relatedEntities.length === 0) {
    return (
      <div style={{ padding: '1rem', color: '#6b7280' }}>
        No related entities found.
      </div>
    );
  }

  return (
    <div className="entity-related-tab">
      <div style={{ marginBottom: '1rem', color: '#6b7280', fontSize: '0.875rem' }}>
        {relatedEntities.length} related entit{relatedEntities.length !== 1 ? 'ies' : 'y'} found
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))',
          gap: '1rem',
        }}
      >
        {relatedEntities.map((entity, idx) => (
          <div
            key={entity.id || idx}
            onClick={() => handleEntityClick(entity.id)}
            style={{
              padding: '1rem',
              border: '1px solid #e5e7eb',
              borderRadius: '0.5rem',
              backgroundColor: '#ffffff',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1)';
              e.currentTarget.style.transform = 'translateY(-2px)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = 'none';
              e.currentTarget.style.transform = 'translateY(0)';
            }}
          >
            {/* Entity Name */}
            <div
              style={{
                fontWeight: '600',
                color: '#111827',
                marginBottom: '0.5rem',
                fontSize: '0.875rem',
              }}
            >
              {entity.canonical_name || entity.name}
            </div>

            {/* Entity Type */}
            {entity.entity_type && (
              <div style={{ marginBottom: '0.5rem' }}>
                <span
                  style={{
                    padding: '0.25rem 0.5rem',
                    fontSize: '0.75rem',
                    borderRadius: '0.25rem',
                    backgroundColor: '#dbeafe',
                    color: '#1e40af',
                  }}
                >
                  {entity.entity_type}
                </span>
              </div>
            )}

            {/* Stats */}
            <div
              style={{
                fontSize: '0.75rem',
                color: '#6b7280',
                display: 'flex',
                flexWrap: 'wrap',
                gap: '0.75rem',
              }}
            >
              {entity.co_occurrence_count !== undefined && (
                <span>{entity.co_occurrence_count} co-mentions</span>
              )}
              {entity.mention_count !== undefined && (
                <span>{entity.mention_count} mentions</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default EntityRelatedTab;
