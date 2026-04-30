/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Featured Reports Rail - Phase B
 * Recently added reports, sorted by report_year DESC (server-sorted)
 */

import React from 'react';
import { useHomeFeatured } from '../../hooks';
import { isValidMinistry } from '../../utils';
import type { AuditReport, ReportSummary } from '../../types';

// Convert API ReportSummary to AuditReport for ReportCard
const convertToAuditReport = (r: ReportSummary): AuditReport => ({
    id: r.id,
    reportNumber: r.report_no,
    title: r.title,
    ministry: r.ministry,
    sector: r.sector,
    year: r.year,
    findingsCount: r.findings_count,
    impact: r.monetary_impact || '',
    reportType: r.report_type || undefined,
    pdfFilename: r.filename,
    government_body_type: r.government_body_type as 'union' | 'state' | 'local_body',
    state_name: r.state_name || null,
    department: r.department || null,
    audit_category: r.audit_category as 'compliance' | 'performance' | 'financial' | 'revenue' | 'commercial' | 'atir',
});

interface FeaturedReportsRailProps {
    onReportClick?: (reportId: string) => void;
}

export const FeaturedReportsRail: React.FC<FeaturedReportsRailProps> = ({ onReportClick }) => {
    const { featured, isLoading } = useHomeFeatured();

    if (isLoading) {
        return (
            <div className="home-rail">
                <h2 className="home-rail-title">Recently Added Reports</h2>
                <div className="home-rail-scroll">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="home-skeleton-card" />
                    ))}
                </div>
            </div>
        );
    }

    const reports = featured?.recent_reports || [];

    if (reports.length === 0) {
        return null;
    }

    return (
        <div className="home-rail">
            <h2 className="home-rail-title">Recently Added Reports</h2>
            <div className="home-rail-scroll">
                {reports.map((report) => {
                    const showMinistry = isValidMinistry(report.ministry);
                    return (
                        <div
                            key={report.id}
                            className="home-report-card"
                            onClick={() => onReportClick?.(report.id)}
                        >
                            <div className="home-report-year">{report.year}</div>
                            <div className="home-report-title">{report.title}</div>
                            {showMinistry && (
                                <div className="home-report-ministry">{report.ministry}</div>
                            )}
                            <div className="home-report-stats">
                                {report.findings_count} findings
                                {report.monetary_impact && ` · ${report.monetary_impact}`}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};
