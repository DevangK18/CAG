/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Debug Logging Utility
 * Provides development-only logging that is stripped in production builds.
 */

/**
 * Check if we're in development mode.
 * Uses Vite's import.meta.env.DEV which is true in dev, false in production.
 */
const IS_DEV = import.meta.env.DEV;

/**
 * Debug logger that only outputs in development mode.
 * All calls are no-ops in production for zero overhead.
 *
 * @example
 * import { debug } from './lib/debug';
 *
 * debug.log('Citation lookup:', citationText);
 * debug.warn('Low relevance score');
 * debug.error('Failed to parse:', error);
 * debug.group('Search Results');
 * debug.groupEnd();
 */
export const debug = {
  /**
   * Log informational messages (development only)
   */
  log: (...args: unknown[]): void => {
    if (IS_DEV) {
      console.log(...args);
    }
  },

  /**
   * Log warning messages (development only)
   */
  warn: (...args: unknown[]): void => {
    if (IS_DEV) {
      console.warn(...args);
    }
  },

  /**
   * Log error messages (development only)
   * Note: For actual error handling, throw errors or use error boundaries instead.
   */
  error: (...args: unknown[]): void => {
    if (IS_DEV) {
      console.error(...args);
    }
  },

  /**
   * Start a console group (development only)
   */
  group: (label: string): void => {
    if (IS_DEV) {
      console.group(label);
    }
  },

  /**
   * Start a collapsed console group (development only)
   */
  groupCollapsed: (label: string): void => {
    if (IS_DEV) {
      console.groupCollapsed(label);
    }
  },

  /**
   * End a console group (development only)
   */
  groupEnd: (): void => {
    if (IS_DEV) {
      console.groupEnd();
    }
  },

  /**
   * Log with a specific prefix/tag for filtering (development only)
   *
   * @example
   * debug.tagged('Citations', 'Looking up:', key);
   * // Output: [Citations] Looking up: Section 2.3, p. 45
   */
  tagged: (tag: string, ...args: unknown[]): void => {
    if (IS_DEV) {
      console.log(`[${tag}]`, ...args);
    }
  },

  /**
   * Log a table (development only)
   */
  table: (data: unknown, columns?: string[]): void => {
    if (IS_DEV) {
      console.table(data, columns);
    }
  },

  /**
   * Time a synchronous operation (development only)
   *
   * @example
   * debug.time('Parse citations');
   * // ... operation ...
   * debug.timeEnd('Parse citations'); // Logs: Parse citations: 12.34ms
   */
  time: (label: string): void => {
    if (IS_DEV) {
      console.time(label);
    }
  },

  timeEnd: (label: string): void => {
    if (IS_DEV) {
      console.timeEnd(label);
    }
  },

  /**
   * Assert a condition (development only)
   * Will throw in development if condition is false.
   */
  assert: (condition: boolean, message?: string): void => {
    if (IS_DEV && !condition) {
      console.assert(condition, message);
    }
  },
};

/**
 * Create a namespaced debug logger for a specific module.
 * All logs will be prefixed with the namespace.
 *
 * @example
 * const log = createDebugLogger('SmartSearch');
 * log.log('Query received:', query); // [SmartSearch] Query received: ...
 */
export function createDebugLogger(namespace: string) {
  return {
    log: (...args: unknown[]) => debug.tagged(namespace, ...args),
    warn: (...args: unknown[]) => {
      if (IS_DEV) console.warn(`[${namespace}]`, ...args);
    },
    error: (...args: unknown[]) => {
      if (IS_DEV) console.error(`[${namespace}]`, ...args);
    },
  };
}

export default debug;
