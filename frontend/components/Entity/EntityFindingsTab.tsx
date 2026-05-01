/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Findings Tab Component
 * Phase D: Shows findings related to an entity
 */

import React, { useState, useEffect } from 'react';
import { getEntityFindings } from '../../lib/api';

interface EntityFindingsTabProps {
  entityId: number;
}

export function EntityFindingsTab({ entityId }: EntityFindingsTabProps) {
  const [findings, setFindings] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchFindings = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const data = await getEntityFindings(entityId, { limit: 100 });
        if (!cancelled) {
          setFindings(data);
          setIsLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load findings');
          setIsLoading(false);
        }
      }
    };

    fetchFindings();

    return () => {
      cancelled = true;
    };
  }, [entityId]);

  if (isLoading) {
    return <div style={{ padding: '1rem', color: '#6b7280' }}>Loading findings...</div>;
  }

  if (error) {
    return <div style={{ padding: '1rem', color: '#ef4444' }}>{error}</div>;
  }

  if (findings.length === 0) {
    return (
      <div style={{ padding: '1rem', color: '#6b7280' }}>
        No findings found for this entity.
      </div>
    );
  }

  return (
    <div className="entity-findings-tab">
      <div style={{ marginBottom: '1rem', color: '#6b7280', fontSize: '0.875rem' }}>
        {findings.length} finding{findings.length !== 1 ? 's' : ''} found
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {findings.map((finding, idx) => (
          <div
            key={idx}
            style={{
              padding: '1rem',
              border: '1px solid #e5e7eb',
              borderRadius: '0.5rem',
              backgroundColor: '#ffffff',
            }}
          >
            {/* Severity & Type */}
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
              {finding.severity && (
                <span
                  style={{
                    padding: '0.25rem 0.5rem',
                    fontSize: '0.75rem',
                    borderRadius: '0.25rem',
                    fontWeight: '500',
                    backgroundColor:
                      finding.severity === 'critical'
                        ? '#fef2f2'
                        : finding.severity === 'high'
                        ? '#fef3c7'
                        : '#f3f4f6',
                    color:
                      finding.severity === 'critical'
                        ? '#991b1b'
                        : finding.severity === 'high'
                        ? '#92400e'
                        : '#374151',
                  }}
                >
                  {finding.severity.toUpperCase()}
                </span>
              )}
              {finding.finding_type && (
                <span
                  style={{
                    padding: '0.25rem 0.5rem',
                    fontSize: '0.75rem',
                    borderRadius: '0.25rem',
                    backgroundColor: '#eff6ff',
                    color: '#1e40af',
                  }}
                >
                  {finding.finding_type.replace(/_/g, ' ')}
                </span>
              )}
            </div>

            {/* Finding Text */}
            <div style={{ marginBottom: '0.75rem', color: '#111827', lineHeight: '1.6' }}>
              {finding.snippet || finding.text || 'No description available'}
            </div>

            {/* Metadata */}
            <div
              style={{
                display: 'flex',
                gap: '1rem',
                fontSize: '0.875rem',
                color: '#6b7280',
              }}
            >
              {finding.report_id && (
                <span>Report: {finding.report_id}</span>
              )}
              {finding.section && (
                <span>Section: {finding.section}</span>
              )}
              {finding.page !== undefined && (
                <span>Page: {finding.page}</span>
              )}
              {finding.amount_crore !== undefined && finding.amount_crore !== null && (
                <span style={{ fontWeight: '600', color: '#dc2626' }}>
                  ₹{finding.amount_crore.toFixed(2)} cr
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default EntityFindingsTab;
