/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * ReportCard Component - Grid and List View Modes
 * Displays audit report cards with sector-based color coding
 */

import React from 'react';
import { AuditReport } from '../types';
import { getSectorColor, getReportType } from '../constants';
import { ArrowRightIcon } from './Icons';
import { sanitizeReportTitle } from '../utils';

interface ReportCardProps {
  report: AuditReport;
  viewMode: 'grid' | 'list';
  onClick: () => void;
}

export const ReportCard = React.memo<ReportCardProps>(function ReportCard({ report, viewMode, onClick }) {
  const sectorColor = getSectorColor(report.sector);
  const sanitizedTitle = sanitizeReportTitle(report.title);

  // Parse report number with fallback handling
  // Expected format from backend: "Report X of YYYY" or null
  let reportNum: string | null = null;
  let reportYear = report.year.toString();
  const hasReportNumber = report.reportNumber && report.reportNumber.trim();

  if (hasReportNumber) {
    // Try standard format: "Report X of YYYY"
    const standardMatch = report.reportNumber!.match(/Report\s+(\d+)\s+of\s+(\d+)/i);
    if (standardMatch) {
      reportNum = standardMatch[1];
      reportYear = standardMatch[2];
    } else {
      // Fallback: try to parse underscore format "num_year" (defense-in-depth)
      const underscoreMatch = report.reportNumber!.match(/(\d+)_(\d{4})/);
      if (underscoreMatch) {
        reportNum = String(parseInt(underscoreMatch[1], 10)); // Strip leading zeros
        reportYear = underscoreMatch[2];
      } else {
        // Last resort: use as-is if it looks like a number
        const numOnly = report.reportNumber!.replace(/\D/g, '');
        if (numOnly) {
          reportNum = numOnly;
        }
      }
    }
  }

  // Tier information
  const isNonUnion = report.government_body_type && report.government_body_type !== 'union';
  const tierLabel = report.government_body_type === 'state' ? 'State' : report.government_body_type === 'local_body' ? 'Local Body' : null;

  // Display department/ministry - hide if "Unknown", "N/A", or empty
  const isValidOrg = (val: string | null | undefined): boolean => {
    if (!val) return false;
    const lower = val.toLowerCase().trim();
    return lower !== 'unknown' && lower !== 'unknown ministry' && lower !== 'n/a' && lower !== '';
  };
  const organizationLabel = isValidOrg(report.department)
    ? report.department
    : isValidOrg(report.ministry)
      ? report.ministry
      : null;

  // Truncate long sector strings
  const truncateSector = (sector: string) => {
    if (sector.length <= 30) return sector;
    const firstSector = sector.split(',')[0].trim();
    const sectorCount = sector.split(',').length;
    return sectorCount > 1 ? `${firstSector} +${sectorCount - 1} more` : firstSector;
  };

  // Helper to truncate report type for badge display
  const truncateReportType = (type: string | undefined) => {
    if (!type) return null;
    const displayType = getReportType(type);
    // If contains comma (multiple types), show first + count
    if (displayType.includes(',')) {
      const types = displayType.split(',').map(t => t.trim());
      return { display: types[0], full: displayType, hasMore: types.length > 1 };
    }
    return { display: displayType, full: displayType, hasMore: false };
  };

  const reportTypeInfo = truncateReportType(report.reportType);

  if (viewMode === 'list') {
    // Build the report identifier for list view
    const listReportLabel = reportNum
      ? `Report ${reportNum} of ${reportYear}`
      : `${reportYear} Report`;

    return (
      <div className="report-card-list" onClick={onClick}>
        <div className={`sector-dot ${sectorColor.bg}`} />
        <span className="report-num-bold font-semibold text-slate-800">{listReportLabel}</span>
        {reportTypeInfo && (
          <span
            className="report-type-badge-list bg-slate-100 text-slate-600 rounded px-1.5 py-0.5 text-xs max-w-[120px] truncate"
            title={reportTypeInfo.full}
          >
            {reportTypeInfo.display}{reportTypeInfo.hasMore ? ' +' : ''}
          </span>
        )}
        <h3 className="report-title-list" title={report.title}>{sanitizedTitle}</h3>
        {isNonUnion && report.state_name ? (
          <span className="state-badge" style={{ fontSize: '11px', fontWeight: 600, color: '#1e40af', background: '#dbeafe', padding: '2px 8px', borderRadius: '4px', whiteSpace: 'nowrap' }}>{report.state_name}</span>
        ) : null}
        {isNonUnion && tierLabel ? (
          <span className="tier-badge" style={{ fontSize: '10px', fontWeight: 500, color: '#64748b', background: '#f1f5f9', padding: '2px 6px', borderRadius: '3px', whiteSpace: 'nowrap' }}>{tierLabel}</span>
        ) : null}
        <span className={`sector-pill-inline ${sectorColor.bg} ${sectorColor.text}`} title={report.sector}>
          {truncateSector(report.sector)}
        </span>
        <span className="report-year">{report.year}</span>
        <span className="findings-badge">{report.findingsCount} findings</span>
        <button className="action-link-list">
          Interact <ArrowRightIcon />
        </button>
      </div>
    );
  }

  // Grid mode
  return (
    <div className="report-card border border-slate-200 rounded-lg hover:shadow-md hover:border-slate-300 transition-all" onClick={onClick}>
      <div className="card-top">
        {reportNum ? (
          <span className="report-num font-semibold text-slate-800">
            Report <strong className="report-num-highlight">{reportNum}</strong> of {reportYear}
          </span>
        ) : (
          <span className="report-num font-semibold text-slate-800">
            {reportYear} Audit Report
          </span>
        )}
        {reportTypeInfo && (
          <span
            className="report-type-badge bg-slate-100 text-slate-600 rounded px-2 py-0.5 text-xs ml-2 max-w-[140px] truncate inline-block align-middle"
            title={reportTypeInfo.full}
          >
            {reportTypeInfo.display}{reportTypeInfo.hasMore ? ' +' : ''}
          </span>
        )}
      </div>
      <h3 className="card-title" title={report.title}>{sanitizedTitle}</h3>
      {isNonUnion && report.state_name ? (
        <div className="demo-location-row" style={{ marginBottom: '8px', display: 'flex', gap: '6px', alignItems: 'center' }}>
          <span className="state-badge" style={{ fontSize: '11px', fontWeight: 600, color: '#1e40af', background: '#dbeafe', padding: '2px 8px', borderRadius: '4px' }}>{report.state_name}</span>
          {tierLabel && <span className="tier-badge" style={{ fontSize: '10px', fontWeight: 500, color: '#64748b', background: '#f1f5f9', padding: '2px 6px', borderRadius: '3px' }}>{tierLabel}</span>}
        </div>
      ) : null}
      {organizationLabel && <p className="ministry">{organizationLabel}</p>}
      <div className="card-meta overflow-hidden">
        <span className={`sector-tag ${sectorColor.bg} ${sectorColor.text} truncate max-w-full`} title={report.sector}>
          {truncateSector(report.sector)}
        </span>
        <span className="meta-year">{report.year}</span>
        <span className="findings-count">{report.findingsCount} findings</span>
      </div>
      <div className="card-footer">
        <span className="impact">{report.impact !== 'N/A' ? report.impact : ''}</span>
        <div className="action-link">
          Interact <ArrowRightIcon />
        </div>
      </div>
    </div>
  );
});

ReportCard.displayName = 'ReportCard';
