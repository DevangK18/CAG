/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Entity Reports Tab Component
 * Phase D: Shows reports related to an entity using ReportCard
 */

import React, { useState, useEffect } from 'react';
import { getEntityReports, fetchReport } from '../../lib/api';
import { ReportCard } from '../ReportCard';

interface EntityReportsTabProps {
  entityId: number;
  onNavigateToReport: (reportId: string) => void;
}

export function EntityReportsTab({ entityId, onNavigateToReport }: EntityReportsTabProps) {
  const [reports, setReports] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchReports = async () => {
      setIsLoading(true);
      setError(null);

      try {
        // Step 1: Get report IDs
        const reportIds = await getEntityReports(entityId);

        if (!cancelled && reportIds.length > 0) {
          // Step 2: Fetch each report's details
          const reportPromises = reportIds.map((id) => fetchReport(id));
          const reportData = await Promise.all(reportPromises);

          if (!cancelled) {
            setReports(reportData);
            setIsLoading(false);
          }
        } else if (!cancelled) {
          setReports([]);
          setIsLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load reports');
          setIsLoading(false);
        }
      }
    };

    fetchReports();

    return () => {
      cancelled = true;
    };
  }, [entityId]);

  if (isLoading) {
    return <div style={{ padding: '1rem', color: '#6b7280' }}>Loading reports...</div>;
  }

  if (error) {
    return <div style={{ padding: '1rem', color: '#ef4444' }}>{error}</div>;
  }

  if (reports.length === 0) {
    return (
      <div style={{ padding: '1rem', color: '#6b7280' }}>
        No reports found for this entity.
      </div>
    );
  }

  return (
    <div className="entity-reports-tab">
      <div style={{ marginBottom: '1rem', color: '#6b7280', fontSize: '0.875rem' }}>
        {reports.length} report{reports.length !== 1 ? 's' : ''} found
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))',
          gap: '1.5rem',
        }}
      >
        {reports.map((report) => (
          <ReportCard
            key={report.id}
            report={report}
            onClick={() => onNavigateToReport(report.id)}
          />
        ))}
      </div>
    </div>
  );
}

export default EntityReportsTab;
