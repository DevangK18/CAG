/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * PDFViewer Component - v6
 * 
 * Updates:
 * - Added initialPage prop for series view
 * - Added onPageChange callback for page tracking
 * - Supports both store-based and prop-based page control
 */

import React, { useState, useEffect, useRef } from 'react';
import { useAppStore } from '../stores/appStore';

interface PDFViewerProps {
  url: string | null;
  /** Optional initial page (overrides store if provided) */
  initialPage?: number;
  /** Callback when page changes (for series page memory) */
  onPageChange?: (page: number) => void;
}

export function PDFViewer({ url, initialPage, onPageChange }: PDFViewerProps) {
  const { pdfPage: storePdfPage, pdfHighlight } = useAppStore();
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [key, setKey] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Use initialPage prop if provided, otherwise use store
  const currentPage = initialPage !== undefined ? initialPage : storePdfPage;
  
  // Track previous page to detect changes
  const prevPageRef = useRef(currentPage);

  useEffect(() => {
    if (url) {
      setIsLoading(true);
      setHasError(false);
    }
  }, [url]);

  // Re-render iframe when page changes
  useEffect(() => {
    if (url && currentPage && currentPage !== prevPageRef.current) {
      setKey(prev => prev + 1);
      prevPageRef.current = currentPage;
      
      // Notify parent of page change
      if (onPageChange) {
        onPageChange(currentPage);
      }
    }
  }, [currentPage, url, onPageChange]);

  // Also trigger on URL change (for series switching)
  useEffect(() => {
    if (url && initialPage) {
      setKey(prev => prev + 1);
    }
  }, [url, initialPage]);

  // Observe container resize
  useEffect(() => {
    if (!containerRef.current) return;
    
    let resizeTimeout: NodeJS.Timeout;
    
    const resizeObserver = new ResizeObserver(() => {
      // Debounced refresh on resize
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        setKey(prev => prev + 1);
      }, 200);
    });
    
    resizeObserver.observe(containerRef.current);
    
    return () => {
      resizeObserver.disconnect();
      clearTimeout(resizeTimeout);
    };
  }, []);

  const handleIframeLoad = () => {
    setIsLoading(false);
  };

  const handleIframeError = () => {
    setIsLoading(false);
    setHasError(true);
  };

  if (!url) {
    return (
      <div className="pdf-viewer-container" ref={containerRef}>
        <div className="pdf-empty-state">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>
            <path d="M14 2v4a2 2 0 0 0 2 2h4"/>
            <path d="M10 9H8"/>
            <path d="M16 13H8"/>
            <path d="M16 17H8"/>
          </svg>
          <p>Select a report to view the PDF document</p>
        </div>
      </div>
    );
  }

  // Build URL with page parameter
  const pdfUrlWithPage = `${url}#page=${currentPage}&toolbar=1&navpanes=0&scrollbar=1&view=FitH`;

  return (
    <div className="pdf-viewer-container" ref={containerRef}>
      {/* Toolbar */}
      <div className="pdf-toolbar">
        <div className="pdf-toolbar-left">
          <span className="pdf-status">
            {isLoading ? 'Loading...' : `Page ${currentPage}`}
          </span>
        </div>
        <div className="pdf-toolbar-right">
          <a 
            href={url} 
            target="_blank" 
            rel="noopener noreferrer"
            className="pdf-toolbar-btn"
            title="Open in new tab"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
              <polyline points="15 3 21 3 21 9"/>
              <line x1="10" y1="14" x2="21" y2="3"/>
            </svg>
            Open in new tab
          </a>
          <a 
            href={url} 
            download
            className="pdf-toolbar-btn"
            title="Download PDF"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            Download
          </a>
        </div>
      </div>

      {/* PDF Display */}
      <div className="pdf-frame-container">
        {isLoading && (
          <div className="pdf-loading-overlay">
            <div className="pdf-spinner"></div>
            <p>Loading PDF document...</p>
          </div>
        )}

        {/* Highlight Overlay */}
        {pdfHighlight && pdfHighlight.page === currentPage && !isLoading && !hasError && (
          <div className="pdf-highlight-overlay">
            {pdfHighlight.bbox ? (
              // Bbox-based highlight
              <div
                className={`pdf-highlight-box ${pdfHighlight.type}`}
                style={{
                  left: `${pdfHighlight.bbox.x}%`,
                  top: `${pdfHighlight.bbox.y}%`,
                  width: `${pdfHighlight.bbox.width}%`,
                  height: `${pdfHighlight.bbox.height}%`,
                }}
              />
            ) : (
              // Banner fallback
              <div className={`pdf-highlight-banner ${pdfHighlight.type}`}>
                <span className="highlight-icon">
                  {pdfHighlight.type === 'chart' && '📊'}
                  {pdfHighlight.type === 'table' && '📋'}
                  {pdfHighlight.type === 'citation' && '📄'}
                </span>
                <span className="highlight-label">
                  {pdfHighlight.label} — Page {pdfHighlight.page}
                </span>
                <button
                  className="highlight-dismiss"
                  onClick={() => useAppStore.getState().setPdfHighlight(null)}
                  aria-label="Dismiss highlight"
                >
                  ✕
                </button>
              </div>
            )}
          </div>
        )}

        {hasError ? (
          <div className="pdf-error-state">
            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <p>Unable to load PDF in viewer</p>
            <a href={url} target="_blank" rel="noopener noreferrer" className="pdf-open-external">
              Open PDF in new tab →
            </a>
          </div>
        ) : (
          <iframe
            key={`${url}-${key}`}
            src={pdfUrlWithPage}
            className="pdf-iframe"
            onLoad={handleIframeLoad}
            onError={handleIframeError}
            title="PDF Document Viewer"
          />
        )}
      </div>
    </div>
  );
}

export default PDFViewer;
