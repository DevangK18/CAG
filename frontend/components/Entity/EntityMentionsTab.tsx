/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Mentions Tab Component
 * Phase D: Shows individual mentions of the entity across reports
 * Grouped by report with clickable mentions that open PDF viewer
 */

import React, { useState, useEffect, useMemo } from 'react';
import { getEntityMentions } from '../../lib/api';
import { formatReportSlug, formatAuditCategory } from '../../utils';
import { useAppStore } from '../../stores/appStore';

interface EntityMentionsTabProps {
  entityId: number;
}

interface Mention {
  report_id: string;
  report_title?: string;
  page?: number;
  context_snippet?: string;
  snippet?: string;
  audit_year?: string;
  audit_category?: string;
  finding_type?: string;
  section?: string;
}

interface ReportGroup {
  report_id: string;
  report_title: string;
  audit_year: string;
  audit_category?: string;
  mentions: Mention[];
}

/**
 * Check if text is likely an OCR artifact from table content
 * Looks for excessive pipe characters (|) which indicate table formatting
 */
function isOCRArtifact(text: string): boolean {
  if (!text) return false;
  const pipeCount = (text.match(/\|/g) || []).length;
  return pipeCount > 5;
}

/**
 * Extract year from report_id (first 4 characters)
 */
function extractYear(reportId: string): string {
  if (!reportId) return '';
  const match = reportId.match(/^(\d{4})/);
  return match ? match[1] : '';
}

/**
 * Single report group card with expandable mentions
 */
function ReportGroupCard({ group }: { group: ReportGroup }) {
  const [expanded, setExpanded] = useState(false);
  const openHomePdf = useAppStore((state) => state.openHomePdf);

  const displayTitle = group.report_title || formatReportSlug(group.report_id);
  const mentionCount = group.mentions.length;
  const showExpand = mentionCount > 3;
  const visibleMentions = expanded ? group.mentions : group.mentions.slice(0, 3);
  const hiddenCount = mentionCount - 3;

  const handleMentionClick = (mention: Mention) => {
    if (mention.report_id && mention.page !== undefined) {
      openHomePdf(mention.report_id, mention.page);
    }
  };

  return (
    <div
      style={{
        border: '1px solid #e5e7eb',
        borderRadius: '0.5rem',
        backgroundColor: '#ffffff',
        overflow: 'hidden',
      }}
    >
      {/* Report Header */}
      <div
        style={{
          padding: '0.875rem 1rem',
          backgroundColor: '#f9fafb',
          borderBottom: '1px solid #e5e7eb',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '0.5rem',
          }}
        >
          <span style={{ fontSize: '1rem', flexShrink: 0 }}>📄</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontWeight: 500,
                color: '#111827',
                fontSize: '0.875rem',
                lineHeight: 1.4,
                wordBreak: 'break-word',
              }}
            >
              {displayTitle}
            </div>
            <div
              style={{
                display: 'flex',
                gap: '0.5rem',
                flexWrap: 'wrap',
                marginTop: '0.25rem',
                fontSize: '0.75rem',
                color: '#6b7280',
              }}
            >
              {group.audit_year && <span>{group.audit_year}</span>}
              {group.audit_year && group.audit_category && <span>·</span>}
              {group.audit_category && (
                <span>{formatAuditCategory(group.audit_category)}</span>
              )}
              <span>·</span>
              <span>
                {mentionCount} mention{mentionCount !== 1 ? 's' : ''}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Mention Rows */}
      <div>
        {visibleMentions.map((mention, idx) => (
          <div
            key={idx}
            onClick={() => handleMentionClick(mention)}
            style={{
              display: 'flex',
              gap: '0.75rem',
              padding: '0.75rem 1rem',
              borderBottom:
                idx < visibleMentions.length - 1 || showExpand
                  ? '1px solid #f3f4f6'
                  : 'none',
              cursor: mention.page !== undefined ? 'pointer' : 'default',
              transition: 'background-color 0.15s',
            }}
            onMouseEnter={(e) => {
              if (mention.page !== undefined) {
                e.currentTarget.style.backgroundColor = '#eff6ff';
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            {/* Page number */}
            <div
              style={{
                flexShrink: 0,
                width: '2.5rem',
                fontSize: '0.75rem',
                fontWeight: 500,
                color: '#6b7280',
                paddingTop: '0.125rem',
              }}
            >
              {mention.page !== undefined ? `p.${mention.page}` : ''}
            </div>

            {/* Context snippet */}
            <div
              style={{
                flex: 1,
                fontSize: '0.8125rem',
                color: '#374151',
                lineHeight: 1.5,
                overflow: 'hidden',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
              }}
            >
              "{mention.context_snippet || mention.snippet || 'No context available'}"
            </div>
          </div>
        ))}

        {/* Show more toggle */}
        {showExpand && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            style={{
              width: '100%',
              padding: '0.5rem 1rem',
              backgroundColor: 'transparent',
              border: 'none',
              borderTop: '1px solid #f3f4f6',
              color: '#3b82f6',
              fontSize: '0.75rem',
              fontWeight: 500,
              cursor: 'pointer',
              textAlign: 'left',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = '#f9fafb';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            + {hiddenCount} more mention{hiddenCount !== 1 ? 's' : ''} [Show]
          </button>
        )}

        {showExpand && expanded && (
          <button
            onClick={() => setExpanded(false)}
            style={{
              width: '100%',
              padding: '0.5rem 1rem',
              backgroundColor: 'transparent',
              border: 'none',
              borderTop: '1px solid #f3f4f6',
              color: '#6b7280',
              fontSize: '0.75rem',
              fontWeight: 500,
              cursor: 'pointer',
              textAlign: 'left',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = '#f9fafb';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            Show less
          </button>
        )}
      </div>
    </div>
  );
}

export function EntityMentionsTab({ entityId }: EntityMentionsTabProps) {
  const [mentions, setMentions] = useState<Mention[]>([]);
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

  // Group mentions by report, filter OCR artifacts, and sort
  const groupedReports = useMemo(() => {
    // Filter out OCR artifacts
    const cleanMentions = mentions.filter(
      (m) => !isOCRArtifact(m.context_snippet || m.snippet || '')
    );

    // Group by report_id
    const grouped: Record<string, ReportGroup> = {};
    for (const mention of cleanMentions) {
      const key = mention.report_id || 'unknown';
      if (!grouped[key]) {
        grouped[key] = {
          report_id: key,
          report_title: mention.report_title || '',
          audit_year: mention.audit_year || extractYear(key),
          audit_category: mention.audit_category,
          mentions: [],
        };
      }
      grouped[key].mentions.push(mention);
    }

    // Convert to array and sort by mention count (descending)
    const groups = Object.values(grouped);
    groups.sort((a, b) => b.mentions.length - a.mentions.length);

    // Sort mentions within each group by page number
    for (const group of groups) {
      group.mentions.sort((a, b) => (a.page ?? 0) - (b.page ?? 0));
    }

    return groups;
  }, [mentions]);

  const totalMentions = groupedReports.reduce((sum, g) => sum + g.mentions.length, 0);

  if (isLoading) {
    return <div style={{ padding: '1rem', color: '#6b7280' }}>Loading mentions...</div>;
  }

  if (error) {
    return <div style={{ padding: '1rem', color: '#ef4444' }}>{error}</div>;
  }

  if (groupedReports.length === 0) {
    return (
      <div style={{ padding: '1rem', color: '#6b7280' }}>
        No mentions found for this entity.
      </div>
    );
  }

  return (
    <div className="entity-mentions-tab">
      <div style={{ marginBottom: '1rem', color: '#6b7280', fontSize: '0.875rem' }}>
        {totalMentions} mention{totalMentions !== 1 ? 's' : ''} across{' '}
        {groupedReports.length} report{groupedReports.length !== 1 ? 's' : ''}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {groupedReports.map((group) => (
          <ReportGroupCard key={group.report_id} group={group} />
        ))}
      </div>
    </div>
  );
}

export default EntityMentionsTab;
