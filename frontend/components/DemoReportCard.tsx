/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * DemoReportCard Component - Display-only card for State/Local reports
 * Non-interactive variant of ReportCard for demo data
 */

import React from 'react';
import { DemoReport, getReportType } from '../constants';
import { ArrowRightIcon } from './Icons';

interface DemoReportCardProps {
  report: DemoReport;
  viewMode: 'grid' | 'list';
  tier: 'state' | 'local';
}

export function DemoReportCard({ report, viewMode, tier }: DemoReportCardProps) {
  // Extract report number from format like "Report X of YYYY"
  const reportNumMatch = report.reportNumber.match(/Report\s+(\d+)\s+of\s+(\d+)/i);
  const reportNum = reportNumMatch ? reportNumMatch[1] : report.reportNumber;
  const reportYear = reportNumMatch ? reportNumMatch[2] : report.year.toString();

  // Format sectors for display
  const sectorDisplay = report.sectors.length > 1
    ? `${report.sectors[0]} +${report.sectors.length - 1} more`
    : report.sectors[0];

  // Tier badge text
  const tierLabel = tier === 'state' ? 'State' : 'Local Body';

  if (viewMode === 'list') {
    return (
      <div className="report-card-list demo-card">
        <div className="sector-dot bg-slate-100" />
        <span className="report-num-bold font-semibold text-slate-800">{report.reportNumber}</span>
        <span className="report-type-badge-list bg-slate-100 text-slate-600 rounded px-1.5 py-0.5 text-xs">
          {getReportType(report.auditType)}
        </span>
        <h3 className="report-title-list" title={report.title}>{report.title}</h3>
        <span className="state-badge">{report.state}</span>
        <span className="tier-badge">{tierLabel}</span>
        <span className="sector-pill-inline bg-slate-100 text-slate-600" title={report.sectors.join(', ')}>
          {sectorDisplay}
        </span>
        <span className="report-year">{report.year}</span>
        <span className="findings-badge">— findings</span>
        <div className="action-link-list">
          Interact <ArrowRightIcon />
        </div>
      </div>
    );
  }

  // Grid mode
  return (
    <div className="report-card demo-card border border-slate-200 rounded-lg">
      <div className="card-top">
        <span className="report-num font-semibold text-slate-800">
          {reportNumMatch ? (
            <>Report <strong className="report-num-highlight">{reportNum}</strong> of {reportYear}</>
          ) : (
            report.reportNumber
          )}
        </span>
        <span className="report-type-badge bg-slate-100 text-slate-600 rounded px-2 py-0.5 text-xs ml-2">
          {getReportType(report.auditType)}
        </span>
      </div>
      <h3 className="card-title" title={report.title}>{report.title}</h3>
      <div className="demo-location-row">
        <span className="state-badge">{report.state}</span>
        <span className="tier-badge">{tierLabel}</span>
        {report.bodyType && <span className="body-type-badge">{report.bodyType}</span>}
      </div>
      <div className="card-meta overflow-hidden">
        <span className="sector-tag bg-slate-100 text-slate-600 truncate max-w-full" title={report.sectors.join(', ')}>
          {sectorDisplay}
        </span>
        <span className="meta-year">{report.year}</span>
        <span className="findings-count">— findings</span>
      </div>
      <div className="card-footer">
        <span className="impact"></span>
        <div className="action-link">
          Interact <ArrowRightIcon />
        </div>
      </div>
    </div>
  );
}
