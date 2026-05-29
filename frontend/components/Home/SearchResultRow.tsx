/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Search Result Row - Phase C
 * Conditional rendering by result.kind discriminant
 *
 * Row types:
 * - Reports: title, ministry (if valid), audit_year, findings_count
 * - Ministries: canonical_name, report_count, mention_count
 * - Entities: canonical_name, entity_type, mention_count
 * - Findings: snippet, report_id, section, page, severity
 * - Glossary: term (bold), abbreviation, definition (first 80 chars)
 */

import React from 'react';
import { isValidMinistry } from '../../utils';
import type {
    SearchResultRow as SearchResultRowType,
    SearchResultReport,
    SearchResultMinistry,
    SearchResultEntity,
    SearchResultFinding,
    SearchResultGlossary,
} from '../../types';

interface SearchResultRowProps {
    result: SearchResultRowType;
    isSelected: boolean;
    onClick: () => void;
    extraCount?: number; // For glossary "+N more" affordance
}

export const SearchResultRow: React.FC<SearchResultRowProps> = ({
    result,
    isSelected,
    onClick,
    extraCount,
}) => {
    const className = `home-search-result-row ${isSelected ? 'selected' : ''}`;

    switch (result.kind) {
        case 'report':
            return <ReportRow result={result} className={className} onClick={onClick} />;
        case 'ministry':
            return <MinistryRow result={result} className={className} onClick={onClick} />;
        case 'entity':
            return <EntityRow result={result} className={className} onClick={onClick} />;
        case 'finding':
            return <FindingRow result={result} className={className} onClick={onClick} />;
        case 'glossary':
            return <GlossaryRow result={result} className={className} onClick={onClick} extraCount={extraCount} />;
        default:
            return null;
    }
};

// Icon components
const ReportIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
    </svg>
);

const MinistryIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 21h18"/>
        <path d="M9 8h1"/>
        <path d="M14 8h1"/>
        <path d="M9 12h1"/>
        <path d="M14 12h1"/>
        <path d="M9 16h1"/>
        <path d="M14 16h1"/>
        <path d="M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16"/>
    </svg>
);

const EntityIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <path d="M7 7h.01"/>
        <path d="M17 7h.01"/>
        <path d="M7 17h.01"/>
        <path d="M17 17h.01"/>
        <path d="M12 12h.01"/>
    </svg>
);

const FindingIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/>
        <line x1="12" y1="17" x2="12.01" y2="17"/>
    </svg>
);

const GlossaryIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
    </svg>
);

// Row components for each type - Single horizontal line layout
const ReportRow: React.FC<{
    result: SearchResultReport;
    className: string;
    onClick: () => void;
}> = ({ result, className, onClick }) => {
    // Truncate title to ~60 chars
    const truncatedTitle = result.title.length > 60
        ? result.title.slice(0, 57) + '...'
        : result.title;

    return (
        <div
            className={className}
            onClick={onClick}
            style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                minHeight: '48px',
                padding: '8px 12px',
                cursor: 'pointer',
                gap: '12px',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                <div style={{
                    flexShrink: 0,
                    color: '#6b7280',
                    display: 'flex',
                    alignItems: 'center'
                }}>
                    📄
                </div>
                <div style={{
                    fontWeight: 500,
                    color: '#111827',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}
                    title={result.title}
                >
                    {truncatedTitle}
                </div>
            </div>
            <div style={{
                fontSize: '0.8rem',
                color: '#9ca3af',
                flexShrink: 0,
                whiteSpace: 'nowrap',
            }}>
                {result.audit_year}
            </div>
        </div>
    );
};

const MinistryRow: React.FC<{
    result: SearchResultMinistry;
    className: string;
    onClick: () => void;
}> = ({ result, className, onClick }) => {
    return (
        <div
            className={className}
            onClick={onClick}
            style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                minHeight: '48px',
                padding: '8px 12px',
                cursor: 'pointer',
                gap: '12px',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                <div style={{
                    flexShrink: 0,
                    fontSize: '1.2rem',
                    display: 'flex',
                    alignItems: 'center'
                }}>
                    🏛️
                </div>
                <div style={{
                    fontWeight: 500,
                    color: '#111827',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}
                    title={result.canonical_name}
                >
                    {result.canonical_name}
                </div>
            </div>
            <div style={{
                fontSize: '0.8rem',
                color: '#9ca3af',
                flexShrink: 0,
                whiteSpace: 'nowrap',
            }}>
                {result.report_count} reports · {result.finding_count} findings
            </div>
        </div>
    );
};

const EntityRow: React.FC<{
    result: SearchResultEntity;
    className: string;
    onClick: () => void;
}> = ({ result, className, onClick }) => {
    return (
        <div
            className={className}
            onClick={onClick}
            style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                minHeight: '48px',
                padding: '8px 12px',
                cursor: 'pointer',
                gap: '12px',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                <div style={{
                    flexShrink: 0,
                    fontSize: '1.2rem',
                    display: 'flex',
                    alignItems: 'center'
                }}>
                    🏛️
                </div>
                <div style={{
                    fontWeight: 500,
                    color: '#111827',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}
                    title={result.canonical_name}
                >
                    {result.canonical_name}
                </div>
            </div>
            <div style={{
                fontSize: '0.8rem',
                color: '#9ca3af',
                flexShrink: 0,
                whiteSpace: 'nowrap',
            }}>
                {result.entity_type} · {result.mention_count} mentions
            </div>
        </div>
    );
};

const FindingRow: React.FC<{
    result: SearchResultFinding;
    className: string;
    onClick: () => void;
}> = ({ result, className, onClick }) => {
    // Truncate snippet to ~60 chars
    const truncatedSnippet = result.snippet.length > 60
        ? result.snippet.slice(0, 57) + '...'
        : result.snippet;

    // Severity badge colors
    const severityColors: Record<string, { bg: string; text: string }> = {
        critical: { bg: '#fee2e2', text: '#991b1b' },
        high: { bg: '#fed7aa', text: '#9a3412' },
        medium: { bg: '#fef3c7', text: '#92400e' },
        low: { bg: '#dbeafe', text: '#1e40af' },
    };

    const severityColor = result.severity
        ? severityColors[result.severity.toLowerCase()] || { bg: '#f3f4f6', text: '#374151' }
        : { bg: '#f3f4f6', text: '#374151' };

    // Truncate report_id for display
    const truncatedReportId = result.report_id.length > 30
        ? result.report_id.slice(0, 27) + '...'
        : result.report_id;

    return (
        <div
            className={className}
            onClick={onClick}
            style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                minHeight: '48px',
                padding: '8px 12px',
                cursor: 'pointer',
                gap: '12px',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                {result.severity && (
                    <div style={{
                        flexShrink: 0,
                        fontSize: '0.65rem',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        padding: '3px 6px',
                        borderRadius: '3px',
                        backgroundColor: severityColor.bg,
                        color: severityColor.text,
                        letterSpacing: '0.5px',
                    }}>
                        {result.severity}
                    </div>
                )}
                <div style={{
                    fontWeight: 500,
                    color: '#111827',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}
                    title={result.snippet}
                >
                    {truncatedSnippet}
                </div>
            </div>
            <div style={{
                fontSize: '0.8rem',
                color: '#9ca3af',
                flexShrink: 0,
                whiteSpace: 'nowrap',
            }}
                title={result.report_id}
            >
                {truncatedReportId}, p.{result.page}
            </div>
        </div>
    );
};

const GlossaryRow: React.FC<{
    result: SearchResultGlossary;
    className: string;
    onClick: () => void;
    extraCount?: number;
}> = ({ result, className, onClick, extraCount }) => {
    // Truncate definition preview
    const truncatedDef = result.definition
        ? (result.definition.length > 80 ? result.definition.slice(0, 77) + '...' : result.definition)
        : 'No definition available';

    return (
        <div
            className={className}
            onClick={onClick}
            style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                minHeight: '48px',
                padding: '8px 12px',
                cursor: 'pointer',
                gap: '12px',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                <div style={{
                    flexShrink: 0,
                    fontSize: '1.2rem',
                    display: 'flex',
                    alignItems: 'center'
                }}>
                    📖
                </div>
                <div style={{
                    fontWeight: 500,
                    color: '#111827',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}>
                    {result.term}
                    {result.abbreviation && (
                        <span style={{ fontWeight: 400, color: '#6b7280' }}> ({result.abbreviation})</span>
                    )}
                    {extraCount && extraCount > 0 && (
                        <span style={{
                            marginLeft: '6px',
                            fontSize: '0.75rem',
                            color: '#6b7280',
                            fontWeight: 400,
                        }}>
                            +{extraCount} more
                        </span>
                    )}
                </div>
            </div>
            <div style={{
                fontSize: '0.8rem',
                color: '#9ca3af',
                flexShrink: 0,
                whiteSpace: 'nowrap',
                maxWidth: '300px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
            }}
                title={result.definition || undefined}
            >
                {truncatedDef}
            </div>
        </div>
    );
};
