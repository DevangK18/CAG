/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Page Component
 * Phase D: Entity detail view with tabs
 */

import React, { useState } from 'react';
import { useAppStore } from '../../stores/appStore';
import { useEntity } from '../../hooks';
import { EntityHeader } from './EntityHeader';
import { EntityFindingsTab } from './EntityFindingsTab';
import { EntityReportsTab } from './EntityReportsTab';
import { EntityRelatedTab } from './EntityRelatedTab';
import { EntityMentionsTab } from './EntityMentionsTab';

type EntityTab = 'findings' | 'reports' | 'related' | 'mentions';

interface EntityPageProps {
  onNavigateToReport: (reportId: string) => void;
}

export function EntityPage({ onNavigateToReport }: EntityPageProps) {
  const { currentEntityId, goBack } = useAppStore();
  const { entity, isLoading, error } = useEntity(currentEntityId);
  const [activeTab, setActiveTab] = useState<EntityTab>('findings');

  // Guard: no entity ID set
  if (!currentEntityId) {
    console.warn('EntityPage: setView("entity") called without setCurrentEntityId');
    return (
      <div className="entity-page" style={{ padding: '2rem' }}>
        <div className="error-message" style={{ color: '#ef4444' }}>
          No entity selected. Please navigate from the home page.
        </div>
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="entity-page" style={{ padding: '2rem' }}>
        <div className="loading-message">Loading entity...</div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="entity-page" style={{ padding: '2rem' }}>
        <div className="error-message" style={{ color: '#ef4444' }}>
          {error}
        </div>
        <button
          onClick={() => goBack()}
          style={{
            marginTop: '1rem',
            padding: '0.5rem 1rem',
            backgroundColor: '#f3f4f6',
            border: '1px solid #d1d5db',
            borderRadius: '0.375rem',
            cursor: 'pointer',
          }}
        >
          ← Go Back
        </button>
      </div>
    );
  }

  // No entity found
  if (!entity) {
    return (
      <div className="entity-page" style={{ padding: '2rem' }}>
        <div className="error-message" style={{ color: '#ef4444' }}>
          Entity not found
        </div>
        <button
          onClick={() => goBack()}
          style={{
            marginTop: '1rem',
            padding: '0.5rem 1rem',
            backgroundColor: '#f3f4f6',
            border: '1px solid #d1d5db',
            borderRadius: '0.375rem',
            cursor: 'pointer',
          }}
        >
          ← Go Back
        </button>
      </div>
    );
  }

  return (
    <div className="entity-page" style={{ padding: '2rem', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Entity Header */}
      <EntityHeader entity={entity} onBack={() => goBack()} />

      {/* Tab Navigation */}
      <div
        className="entity-tabs"
        style={{
          display: 'flex',
          gap: '0.5rem',
          borderBottom: '2px solid #e5e7eb',
          marginTop: '2rem',
          marginBottom: '1.5rem',
        }}
      >
        {(['findings', 'reports', 'related', 'mentions'] as EntityTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: '0.75rem 1.5rem',
              border: 'none',
              background: 'none',
              borderBottom: activeTab === tab ? '2px solid #3b82f6' : '2px solid transparent',
              color: activeTab === tab ? '#3b82f6' : '#6b7280',
              fontWeight: activeTab === tab ? '600' : '400',
              cursor: 'pointer',
              marginBottom: '-2px',
              textTransform: 'capitalize',
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="entity-tab-content">
        {activeTab === 'findings' && <EntityFindingsTab entityId={entity.id} />}
        {activeTab === 'reports' && (
          <EntityReportsTab entityId={entity.id} onNavigateToReport={onNavigateToReport} />
        )}
        {activeTab === 'related' && <EntityRelatedTab entityId={entity.id} />}
        {activeTab === 'mentions' && <EntityMentionsTab entityId={entity.id} />}
      </div>
    </div>
  );
}

export default EntityPage;
