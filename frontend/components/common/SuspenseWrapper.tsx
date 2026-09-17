/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Reusable Suspense wrapper with loading fallback
 */

import React, { Suspense, ReactNode } from 'react';

interface SuspenseWrapperProps {
  children: ReactNode;
  fallback?: ReactNode;
}

const DefaultFallback = () => (
  <div className="suspense-loading">
    <div className="suspense-spinner"></div>
    <span>Loading...</span>
  </div>
);

export const SuspenseWrapper: React.FC<SuspenseWrapperProps> = ({
  children,
  fallback = <DefaultFallback />
}) => {
  return <Suspense fallback={fallback}>{children}</Suspense>;
};
