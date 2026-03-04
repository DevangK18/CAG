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

export function ReportCard({ report, viewMode, onClick }: ReportCardProps) {
  const sectorColor = getSectorColor(report.sector);
  const sanitizedTitle = sanitizeReportTitle(report.title);

  // Extract report number from "Report X of YYYY" format
  const reportNumMatch = report.reportNumber.match(/Report\s+(\d+)\s+of\s+(\d+)/i);
  const reportNum = reportNumMatch ? reportNumMatch[1] : report.reportNumber;
  const reportYear = reportNumMatch ? reportNumMatch[2] : report.year.toString();

  // Truncate long sector strings
  const truncateSector = (sector: string) => {
    if (sector.length <= 30) return sector;
    const firstSector = sector.split(',')[0].trim();
    const sectorCount = sector.split(',').length;
    return sectorCount > 1 ? `${firstSector} +${sectorCount - 1} more` : firstSector;
  };

  if (viewMode === 'list') {
    return (
      <div className="report-card-list" onClick={onClick}>
        <div className={`sector-dot ${sectorColor.bg}`} />
        <span className="report-num-bold font-semibold text-slate-800">{report.reportNumber}</span>
        {report.reportType && (
          <span className="report-type-badge-list bg-slate-100 text-slate-600 rounded px-1.5 py-0.5 text-xs">
            {getReportType(report.reportType)}
          </span>
        )}
        <h3 className="report-title-list" title={report.title}>{sanitizedTitle}</h3>
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
        <span className="report-num font-semibold text-slate-800">
          Report <strong className="report-num-highlight">{reportNum}</strong> of {reportYear}
        </span>
        {report.reportType && (
          <span className="report-type-badge bg-slate-100 text-slate-600 rounded px-2 py-0.5 text-xs ml-2">
            {getReportType(report.reportType)}
          </span>
        )}
      </div>
      <h3 className="card-title" title={report.title}>{sanitizedTitle}</h3>
      <p className="ministry">{report.ministry}</p>
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
}
