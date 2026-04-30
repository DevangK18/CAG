/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * TimeSeriesPage Component
 * Extracted from index.tsx for Phase 0 refactor
 * Renders the time series analysis view
 */

import React from 'react';
import { TimeSeriesInfo } from '../../lib/api';
import { ArrowRightIcon } from '../Icons';

interface TimeSeriesPageProps {
    allSeries: TimeSeriesInfo[];
    seriesLoading: boolean;
    seriesError: string | null;
    handleSeriesClick: (series: TimeSeriesInfo) => void;
}

export const TimeSeriesPage: React.FC<TimeSeriesPageProps> = ({
    allSeries,
    seriesLoading,
    seriesError,
    handleSeriesClick,
}) => {
    return (
        <main className="landing-view">
            <div className="hero-section">
                <h1>Time Series Analysis</h1>
                <p className="hero-subtitle">Analyze trends across multiple financial years.</p>
            </div>
            {seriesLoading && <div className="loading-spinner">Loading time series...</div>}
            {seriesError && (
                <div className="tab-error" style={{margin:'40px auto',maxWidth:'600px'}}>
                    <p>Failed to load: {seriesError}</p>
                </div>
            )}
            {!seriesLoading && !seriesError && allSeries.length === 0 && (
                <div className="placeholder-text" style={{textAlign:'center',padding:'60px'}}>
                    <p>No time series available.</p>
                </div>
            )}
            {!seriesLoading && !seriesError && allSeries.length > 0 && (
                <div className="report-grid">
                    {allSeries.map(series => (
                        <div key={series.series_id} className="report-card series-card" onClick={() => handleSeriesClick(series)}>
                            <div className="card-top">
                                <span className="report-num">{series.reports.length} Reports</span>
                                <span className="status-badge compliant">Longitudinal Data</span>
                            </div>
                            <h3>{series.name}</h3>
                            <p className="series-desc">{series.description}</p>
                            <div className="series-timeline-preview">
                                {series.years_covered.map(year => (
                                    <div key={year} className="timeline-dot">
                                        <span className="year">{year}</span>
                                        <span className="dot"></span>
                                    </div>
                                ))}
                            </div>
                            <div className="card-footer">
                                <span>Cross-Report Intelligence</span>
                                <div className="action-link">Start Analysis <ArrowRightIcon /></div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </main>
    );
};
