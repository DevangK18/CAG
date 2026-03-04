import posthog from 'posthog-js'

const posthogKey = import.meta.env.VITE_PUBLIC_POSTHOG_KEY
const posthogHost = import.meta.env.VITE_PUBLIC_POSTHOG_HOST

export function initPostHog() {
  if (posthogKey) {
    posthog.init(posthogKey, {
      api_host: posthogHost || 'https://us.i.posthog.com',
      autocapture: true,           // tracks clicks, pageviews automatically
      capture_pageview: true,       // automatic page view tracking
      capture_pageleave: true,      // track when users leave
      persistence: 'memory',        // don't use localStorage (not available in artifacts)
    })

    // Expose posthog globally for debugging in console
    if (typeof window !== 'undefined') {
      (window as any).posthog = posthog
    }

    console.log('[PostHog] Initialized successfully')
  } else {
    console.warn('[PostHog] VITE_PUBLIC_POSTHOG_KEY not set, analytics disabled')
  }
}

export function trackEvent(event: string, properties?: Record<string, any>) {
  if (posthogKey) {
    posthog.capture(event, properties)
  }
}

export { posthog }
