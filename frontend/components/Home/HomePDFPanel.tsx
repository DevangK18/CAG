/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * HomePDFPanel - Slide-over PDF viewer panel for home page
 *
 * Slides in from the right when clicking on findings, citations, or any element
 * that should show a PDF page. Uses the existing PDFViewer component.
 */

import React, { useEffect, useRef } from 'react';
import { useAppStore } from '../../stores/appStore';
import { useReport } from '../../hooks/useReport';
import { PDFViewer } from '../PDFViewer';

export function HomePDFPanel() {
  const { homePdfPanel, closeHomePdf, setView, setCurrentReportId } = useAppStore();
  const panelRef = useRef<HTMLDivElement>(null);

  // Fetch report details to get filename and title
  const { report, pdfUrl, isLoading, error } = useReport(homePdfPanel?.reportId ?? null);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && homePdfPanel) {
        closeHomePdf();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [homePdfPanel, closeHomePdf]);

  // Prevent body scroll when panel is open
  useEffect(() => {
    if (homePdfPanel) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [homePdfPanel]);

  if (!homePdfPanel) {
    return null;
  }

  const handleOpenFullReport = () => {
    // Set the report ID
    setCurrentReportId(homePdfPanel.reportId);

    // Preserve the current page so the report view opens to the same page
    if (homePdfPanel.page) {
      useAppStore.getState().setPdfPage(homePdfPanel.page);
    }

    // Navigate to the report view
    setView('report');

    // Close the panel
    closeHomePdf();
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      closeHomePdf();
    }
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="home-pdf-panel-backdrop"
        onClick={handleBackdropClick}
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.4)',
          zIndex: 999,
          animation: 'fadeIn 0.2s ease-out',
        }}
      />

      {/* Panel */}
      <div
        ref={panelRef}
        className="home-pdf-panel"
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          height: '100vh',
          width: '55vw',
          minWidth: '500px',
          maxWidth: '900px',
          backgroundColor: '#fff',
          boxShadow: '-4px 0 24px rgba(0, 0, 0, 0.15)',
          zIndex: 1000,
          display: 'flex',
          flexDirection: 'column',
          animation: 'slideInFromRight 0.25s ease-out',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 16px',
            borderBottom: '1px solid #e2e8f0',
            backgroundColor: '#f8fafc',
            gap: '12px',
          }}
        >
          {/* Title */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {isLoading ? (
              <span style={{ color: '#64748b', fontSize: '0.9rem' }}>Loading...</span>
            ) : error ? (
              <span style={{ color: '#ef4444', fontSize: '0.9rem' }}>Error loading report</span>
            ) : (
              <h3
                style={{
                  margin: 0,
                  fontSize: '0.95rem',
                  fontWeight: 600,
                  color: '#1e293b',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                title={report?.title}
              >
                {report?.title || 'Report'}
              </h3>
            )}
            {homePdfPanel.page && (
              <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
                Page {homePdfPanel.page}
              </span>
            )}
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={handleOpenFullReport}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 12px',
                fontSize: '0.85rem',
                color: '#0369a1',
                backgroundColor: '#e0f2fe',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              Open full report
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M5 12h14" />
                <path d="m12 5 7 7-7 7" />
              </svg>
            </button>

            <button
              onClick={closeHomePdf}
              aria-label="Close panel"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '32px',
                height: '32px',
                padding: 0,
                backgroundColor: 'transparent',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                cursor: 'pointer',
                color: '#64748b',
              }}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* PDF Viewer Body */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          {pdfUrl ? (
            <PDFViewer url={pdfUrl} initialPage={homePdfPanel.page || 1} />
          ) : isLoading ? (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: '#64748b',
              }}
            >
              <div style={{ textAlign: 'center' }}>
                <div className="home-pdf-panel-spinner" />
                <p style={{ marginTop: '12px' }}>Loading PDF...</p>
              </div>
            </div>
          ) : (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: '#94a3b8',
              }}
            >
              <div style={{ textAlign: 'center' }}>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="48"
                  height="48"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <p style={{ marginTop: '12px' }}>Unable to load PDF</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Inline styles for animations */}
      <style>{`
        @keyframes slideInFromRight {
          from {
            transform: translateX(100%);
          }
          to {
            transform: translateX(0);
          }
        }

        @keyframes fadeIn {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }

        .home-pdf-panel-spinner {
          width: 32px;
          height: 32px;
          border: 3px solid #e2e8f0;
          border-top-color: #0ea5e9;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </>
  );
}

export default HomePDFPanel;
