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

// Row components for each type
const ReportRow: React.FC<{
    result: SearchResultReport;
    className: string;
    onClick: () => void;
}> = ({ result, className, onClick }) => {
    const showMinistry = result.ministry && isValidMinistry(result.ministry);

    return (
        <div className={className} onClick={onClick}>
            <div className="home-search-result-icon">
                <ReportIcon />
            </div>
            <div className="home-search-result-content">
                <div className="home-search-result-title">{result.title}</div>
                <div className="home-search-result-meta">
                    {showMinistry && <span>{result.ministry}</span>}
                    {showMinistry && result.audit_year && <span className="home-search-result-sep">·</span>}
                    {result.audit_year && <span>{result.audit_year}</span>}
                    {(showMinistry || result.audit_year) && <span className="home-search-result-sep">·</span>}
                    <span>{result.findings_count} findings</span>
                </div>
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
        <div className={className} onClick={onClick}>
            <div className="home-search-result-icon ministry">
                <MinistryIcon />
            </div>
            <div className="home-search-result-content">
                <div className="home-search-result-title">{result.canonical_name}</div>
                <div className="home-search-result-meta">
                    <span>{result.report_count} reports</span>
                    <span className="home-search-result-sep">·</span>
                    <span>{result.finding_count} findings</span>
                </div>
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
        <div className={className} onClick={onClick}>
            <div className="home-search-result-icon entity">
                <EntityIcon />
            </div>
            <div className="home-search-result-content">
                <div className="home-search-result-title">{result.canonical_name}</div>
                <div className="home-search-result-meta">
                    <span className="home-search-result-type">{result.entity_type}</span>
                    <span className="home-search-result-sep">·</span>
                    <span>{result.mention_count} mentions</span>
                </div>
            </div>
        </div>
    );
};

const FindingRow: React.FC<{
    result: SearchResultFinding;
    className: string;
    onClick: () => void;
}> = ({ result, className, onClick }) => {
    // Truncate snippet to ~120 chars
    const truncatedSnippet = result.snippet.length > 120
        ? result.snippet.slice(0, 117) + '...'
        : result.snippet;

    return (
        <div className={className} onClick={onClick}>
            <div className="home-search-result-icon finding">
                <FindingIcon />
            </div>
            <div className="home-search-result-content">
                <div className="home-search-result-snippet">"{truncatedSnippet}"</div>
                <div className="home-search-result-meta">
                    <span>{result.report_id}</span>
                    {result.section && (
                        <>
                            <span className="home-search-result-sep">·</span>
                            <span>{result.section}</span>
                        </>
                    )}
                    <span className="home-search-result-sep">·</span>
                    <span>p.{result.page}</span>
                    {result.severity && (
                        <>
                            <span className="home-search-result-sep">·</span>
                            <span className={`home-search-result-severity ${result.severity.toLowerCase()}`}>
                                {result.severity}
                            </span>
                        </>
                    )}
                </div>
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
    // Truncate definition to first 80 chars
    const truncatedDef = result.definition
        ? (result.definition.length > 80 ? result.definition.slice(0, 77) + '...' : result.definition)
        : null;

    return (
        <div className={className} onClick={onClick}>
            <div className="home-search-result-icon glossary">
                <GlossaryIcon />
            </div>
            <div className="home-search-result-content">
                <div className="home-search-result-title">
                    <strong>{result.term}</strong>
                    {result.abbreviation && (
                        <span className="home-search-result-abbr"> ({result.abbreviation})</span>
                    )}
                    {extraCount && extraCount > 0 && (
                        <span className="home-search-result-extra">+{extraCount} more</span>
                    )}
                </div>
                {truncatedDef && (
                    <div className="home-search-result-meta">{truncatedDef}</div>
                )}
            </div>
        </div>
    );
};
