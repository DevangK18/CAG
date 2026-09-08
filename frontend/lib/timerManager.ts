/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Timer Manager Utility
 * Provides auto-cleanup timers that can be cancelled to prevent stale closures
 * and memory leaks from orphaned timeouts.
 */

import { useRef, useCallback, useEffect } from 'react';

/**
 * Module-level timer tracking for non-React contexts (like Zustand stores)
 * Maps a unique key to the timer ID
 */
const moduleTimers = new Map<string, ReturnType<typeof setTimeout>>();

/**
 * Set a timer that can be cancelled by key.
 * If a timer with the same key exists, it will be cancelled first.
 * Useful for Zustand stores where React hooks aren't available.
 *
 * @param key - Unique identifier for the timer
 * @param callback - Function to execute after delay
 * @param delay - Delay in milliseconds
 * @returns Cleanup function to cancel the timer
 */
export function setManagedTimeout(
  key: string,
  callback: () => void,
  delay: number
): () => void {
  // Cancel existing timer with this key
  const existing = moduleTimers.get(key);
  if (existing) {
    clearTimeout(existing);
    moduleTimers.delete(key);
  }

  // Set new timer
  const timerId = setTimeout(() => {
    moduleTimers.delete(key);
    callback();
  }, delay);

  moduleTimers.set(key, timerId);

  // Return cleanup function
  return () => {
    clearTimeout(timerId);
    moduleTimers.delete(key);
  };
}

/**
 * Cancel a managed timer by key
 *
 * @param key - The key used when setting the timer
 */
export function clearManagedTimeout(key: string): void {
  const timerId = moduleTimers.get(key);
  if (timerId) {
    clearTimeout(timerId);
    moduleTimers.delete(key);
  }
}

/**
 * Clear all managed timers.
 * Useful for cleanup during app shutdown or testing.
 */
export function clearAllManagedTimeouts(): void {
  moduleTimers.forEach((timerId) => clearTimeout(timerId));
  moduleTimers.clear();
}

/**
 * React hook for managing multiple timers with auto-cleanup on unmount.
 * Each timer is identified by a key and can be individually cancelled.
 *
 * @returns Object with setTimeout, clearTimeout, and clearAll methods
 *
 * @example
 * const timers = useTimerManager();
 *
 * // Set a timer (will auto-cleanup on unmount)
 * timers.setTimeout(() => console.log('fired'), 5000, 'myTimer');
 *
 * // Cancel a specific timer
 * timers.clearTimeout('myTimer');
 *
 * // Cancel all timers
 * timers.clearAll();
 */
export function useTimerManager() {
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // Clear all timers on unmount
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((timerId) => clearTimeout(timerId));
      timers.clear();
    };
  }, []);

  const setTimer = useCallback((
    callback: () => void,
    delay: number,
    key: string = `timer_${Date.now()}_${Math.random()}`
  ) => {
    // Cancel existing timer with this key
    const existing = timersRef.current.get(key);
    if (existing) {
      clearTimeout(existing);
    }

    // Set new timer
    const timerId = setTimeout(() => {
      timersRef.current.delete(key);
      callback();
    }, delay);

    timersRef.current.set(key, timerId);

    return key;
  }, []);

  const clearTimer = useCallback((key: string) => {
    const timerId = timersRef.current.get(key);
    if (timerId) {
      clearTimeout(timerId);
      timersRef.current.delete(key);
    }
  }, []);

  const clearAll = useCallback(() => {
    timersRef.current.forEach((timerId) => clearTimeout(timerId));
    timersRef.current.clear();
  }, []);

  return {
    setTimeout: setTimer,
    clearTimeout: clearTimer,
    clearAll,
  };
}

/**
 * Creates an auto-dismissing highlight timer that properly handles
 * rapid successive calls (cancels previous timer before setting new one).
 *
 * @param onDismiss - Callback when timer fires
 * @param delay - Delay in milliseconds (default: 5000)
 * @returns Object with trigger and cancel methods
 */
export function createHighlightTimer(
  onDismiss: () => void,
  delay: number = 5000
) {
  let timerId: ReturnType<typeof setTimeout> | null = null;

  return {
    trigger: () => {
      // Cancel previous timer
      if (timerId) {
        clearTimeout(timerId);
      }
      // Set new timer
      timerId = setTimeout(() => {
        timerId = null;
        onDismiss();
      }, delay);
    },
    cancel: () => {
      if (timerId) {
        clearTimeout(timerId);
        timerId = null;
      }
    },
  };
}

export default useTimerManager;
