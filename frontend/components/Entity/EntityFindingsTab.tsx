/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Findings Tab Component
 * Phase D: Shows findings related to an entity
 */

import React, { useState, useEffect } from 'react';
import { getEntityFindings } from '../../lib/api';
import { formatAmountCrore, formatReportSlug } from '../../utils';
import { useAppStore } from '../../stores/appStore';

interface EntityFindingsTabProps {
  entityId: number;
}

export function EntityFindingsTab({ entityId }: EntityFindingsTabProps) {
  const [findings, setFindings] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { openHomePdf } = useAppStore();

  useEffect(() => {
    // Guard: ensure entityId is valid
    if (!entityId || typeof entityId !== 'number') {
      console.error(`[EntityFindingsTab] Invalid entityId:`, entityId);
      setError('Invalid entity ID');
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    const fetchFindings = async () => {
      console.log(`[EntityFindingsTab] Fetching findings for entityId=${entityId}`);
      setIsLoading(true);
      setError(null);
      // Clear stale findings
      setFindings([]);

      try {
        const data = await getEntityFindings(entityId, { limit: 100 });
        console.log(`[EntityFindingsTab] entityId=${entityId} received ${data.length} findings`);
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
        {findings.map((finding, idx) => {
          const reportTitle = finding.report_title || formatReportSlug(finding.report_id);
          const yearBadge = finding.report_id ? finding.report_id.substring(0, 4) : null;
          const auditType = finding.audit_category || finding.government_body_type;

          return (
            <div
              key={idx}
              onClick={() => {
                if (finding.report_id) {
                  openHomePdf(finding.report_id, finding.page);
                }
              }}
              style={{
                border: '1px solid #e5e7eb',
                borderRadius: '0.5rem',
                backgroundColor: '#ffffff',
                cursor: finding.report_id ? 'pointer' : 'default',
                transition: 'border-color 0.2s ease',
              }}
              onMouseEnter={(e) => {
                if (finding.report_id) {
                  e.currentTarget.style.borderColor = '#3b82f6';
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = '#e5e7eb';
              }}
            >
              {/* Report Header Bar */}
              <div
                style={{
                  padding: '0.75rem 1rem',
                  backgroundColor: '#f8fafc',
                  borderBottom: '1px solid #e5e7eb',
                  borderTopLeftRadius: '0.5rem',
                  borderTopRightRadius: '0.5rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  flexWrap: 'wrap',
                }}
              >
                <span style={{ fontSize: '0.875rem', fontWeight: '500', color: '#111827', flex: 1 }}>
                  {reportTitle}
                </span>
                {yearBadge && (
                  <span
                    style={{
                      padding: '0.125rem 0.5rem',
                      fontSize: '0.75rem',
                      borderRadius: '0.25rem',
                      backgroundColor: '#dbeafe',
                      color: '#1e40af',
                      fontWeight: '500',
                    }}
                  >
                    {yearBadge}
                  </span>
                )}
                {auditType && (
                  <span
                    style={{
                      padding: '0.125rem 0.5rem',
                      fontSize: '0.75rem',
                      borderRadius: '0.25rem',
                      backgroundColor: '#e0e7ff',
                      color: '#4338ca',
                    }}
                  >
                    {auditType}
                  </span>
                )}
              </div>

              {/* Card Content */}
              <div style={{ padding: '1rem' }}>
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
                  {finding.finding_type && finding.finding_type !== 'other' && (
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
                  {finding.description || finding.snippet || finding.text || 'No description available'}
                </div>

                {/* Metadata */}
                <div
                  style={{
                    display: 'flex',
                    gap: '1rem',
                    fontSize: '0.875rem',
                    color: '#6b7280',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                  }}
                >
                  {finding.section && <span>Section: {finding.section}</span>}
                  {finding.page !== undefined && <span>Page: {finding.page}</span>}
                  {finding.amount_crore !== undefined &&
                    finding.amount_crore !== null &&
                    formatAmountCrore(finding.amount_crore) && (
                      <span style={{ fontWeight: '600', color: '#dc2626' }}>
                        {formatAmountCrore(finding.amount_crore)}
                      </span>
                    )}
                  {finding.report_id && (
                    <span
                      style={{
                        marginLeft: 'auto',
                        color: '#3b82f6',
                        fontSize: '0.875rem',
                        fontWeight: '500',
                      }}
                    >
                      View in PDF →
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default EntityFindingsTab;
