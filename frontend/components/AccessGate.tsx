/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Access Gate - Lightweight access control for invite-only testing
 * Not authentication - just a simple password gate
 *
 * Supports multiple comma-separated access codes via VITE_ACCESS_CODE env var.
 * Tracks which code was used with PostHog for user identification.
 */

import React, { useState, useRef, useEffect } from 'react';
import { trackEvent } from '../lib/posthog';

interface AccessGateProps {
  onGranted: (accessCode: string) => void;
}

const FileTextIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <polyline points="14 2 14 8 20 8"/>
    <line x1="16" y1="13" x2="8" y2="13"/>
    <line x1="16" y1="17" x2="8" y2="17"/>
    <polyline points="10 9 9 9 8 9"/>
  </svg>
);

export function AccessGate({ onGranted }: AccessGateProps) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Support multiple comma-separated access codes
    const codesString = import.meta.env.VITE_ACCESS_CODE || 'cag-test-2025';
    const validCodes = codesString.split(',').map((c: string) => c.trim());

    if (validCodes.includes(code)) {
      setError('');

      // Track successful access with the code used (for user identification)
      trackEvent('access_granted', {
        access_code: code,
        timestamp: new Date().toISOString()
      });

      onGranted(code);
    } else {
      // Track failed attempt (without revealing the attempted code for security)
      trackEvent('access_denied', {
        timestamp: new Date().toISOString()
      });

      setError('Invalid access code');
      setCode('');
      inputRef.current?.focus();
    }
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      background: '#f8f9fa',
      fontFamily: 'Inter, sans-serif',
    }}>
      <div style={{
        background: '#ffffff',
        border: '1px solid #dee2e6',
        borderRadius: '8px',
        padding: '48px',
        width: '100%',
        maxWidth: '420px',
        boxShadow: '0 4px 16px rgba(0,0,0,0.04)',
      }}>
        {/* Logo */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '12px',
          marginBottom: '32px',
          color: '#1a365d',
        }}>
          <FileTextIcon />
          <span style={{
            fontSize: '1.5rem',
            fontWeight: 700,
            letterSpacing: '0.05em',
          }}>
            CAG GATEWAY
          </span>
        </div>

        {/* Title */}
        <h2 style={{
          fontSize: '1.25rem',
          fontWeight: 600,
          textAlign: 'center',
          marginBottom: '8px',
          color: '#1a1a1a',
        }}>
          Access Restricted
        </h2>

        {/* Subtitle */}
        <p style={{
          fontSize: '0.9rem',
          color: '#6c757d',
          textAlign: 'center',
          marginBottom: '32px',
        }}>
          Enter access code to continue
        </p>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="password"
            value={code}
            onChange={(e) => {
              setCode(e.target.value);
              setError('');
            }}
            placeholder="Access code"
            style={{
              width: '100%',
              padding: '12px 16px',
              fontSize: '0.95rem',
              border: error ? '1px solid #dc3545' : '1px solid #dee2e6',
              borderRadius: '4px',
              outline: 'none',
              fontFamily: 'inherit',
              marginBottom: '8px',
              transition: 'border-color 0.2s',
            }}
            onFocus={(e) => {
              if (!error) {
                e.target.style.borderColor = '#1a365d';
              }
            }}
            onBlur={(e) => {
              if (!error) {
                e.target.style.borderColor = '#dee2e6';
              }
            }}
          />

          {/* Error message */}
          {error && (
            <div style={{
              fontSize: '0.85rem',
              color: '#dc3545',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}>
              <span>⚠️</span>
              <span>{error}</span>
            </div>
          )}

          {/* Submit button */}
          <button
            type="submit"
            disabled={!code.trim()}
            style={{
              width: '100%',
              padding: '12px 24px',
              fontSize: '0.95rem',
              fontWeight: 600,
              color: '#ffffff',
              background: code.trim() ? '#1a365d' : '#6c757d',
              border: 'none',
              borderRadius: '4px',
              cursor: code.trim() ? 'pointer' : 'not-allowed',
              transition: 'all 0.2s',
              fontFamily: 'inherit',
            }}
            onMouseEnter={(e) => {
              if (code.trim()) {
                e.currentTarget.style.background = '#102a44';
              }
            }}
            onMouseLeave={(e) => {
              if (code.trim()) {
                e.currentTarget.style.background = '#1a365d';
              }
            }}
          >
            Continue
          </button>
        </form>

        {/* Footer hint */}
        <p style={{
          fontSize: '0.75rem',
          color: '#adb5bd',
          textAlign: 'center',
          marginTop: '24px',
        }}>
          This is an invite-only testing environment
        </p>
      </div>
    </div>
  );
}

export default AccessGate;
