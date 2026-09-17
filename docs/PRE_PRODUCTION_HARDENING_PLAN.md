# CAG-GATEWAY: Pre-Production Hardening Plan

Three features to add before deploying to testers.
Run these as separate Claude Code tasks in order.

---

## Task 1: Rate Limiting on Chat Endpoints

### Goal
Prevent API bill spikes by limiting Claude API-hitting endpoints per IP.

### Instructions for Claude Code

```
Add rate limiting to the FastAPI backend using slowapi.

1. Install slowapi: add "slowapi==0.1.9" to services/api/requirements.txt

2. In services/api/main.py:
   - Import and initialize slowapi's Limiter with get_remote_address as key_func
   - Add SlowAPIMiddleware to the app
   - Add a custom 429 exception handler that returns JSON: {"error": "Rate limit exceeded. Please wait before sending more messages.", "retry_after": 60}

3. Apply rate limits to these routes ONLY (not all routes):
   - services/api/routes/chat.py: all endpoints → "30/hour"
   - services/api/routes/series.py: chat-related endpoints → "30/hour"

4. Do NOT rate limit: /health, /api/reports, /api/summaries, /api/overview,
   /api/assets, /api/tables, /api/charts — these serve static data and are cheap.

5. The limiter should use in-memory storage (default). No Redis needed.

6. Make the rate limit configurable via environment variable RATE_LIMIT_PER_HOUR
   with default "30/hour".
```


---

## Task 2: PostHog Analytics



### Instructions for Claude Code

```
Add PostHog analytics to the frontend using PostHog's official React SDK.

The PostHog project API key is: phc_xxxx.... (actual key)
The PostHog API host is: https://us.i.posthog.com (or eu if EU signup)

1. Install packages: run this in the frontend/ directory:
   npm install posthog-js @posthog/react

2. In the root mount file (frontend/index.tsx or main.tsx — wherever createRoot is called):
   - Import PostHogProvider from '@posthog/react'
   - Wrap the entire App component with PostHogProvider:

     import { PostHogProvider } from '@posthog/react'

     const posthogKey = import.meta.env.VITE_PUBLIC_POSTHOG_KEY
     const posthogOptions = {
       api_host: import.meta.env.VITE_PUBLIC_POSTHOG_HOST,
       defaults: '2026-01-30',
     }

     createRoot(document.getElementById('root')!).render(
       <PostHogProvider apiKey={posthogKey} options={posthogOptions}>
         <App />
       </PostHogProvider>
     )

   - If VITE_PUBLIC_POSTHOG_KEY is not set, still wrap with PostHogProvider —
     PostHog handles missing keys gracefully and won't crash the app.

3. Add custom tracking events using the usePostHog hook in these components:

   import { usePostHog } from '@posthog/react'

   Add these capture calls in the relevant components:
   - When a report is opened: posthog.capture('report_viewed', { report_id })
   - When a chat message is sent: posthog.capture('chat_message_sent', { report_id })
   - When a summary tab is viewed: posthog.capture('summary_viewed', { report_id, summary_type })
   - When series/cross-report chat is used: posthog.capture('series_chat_sent', {})
   - When a chart or table is viewed: posthog.capture('artifact_viewed', { type: 'chart'|'table', report_id })

   For any tracking in non-React utility code (e.g., inside lib/api.ts), import posthog directly:
   import posthog from 'posthog-js'
   posthog.capture('event_name', { ... })

4. Add these to .env.production.template:
   VITE_PUBLIC_POSTHOG_KEY=phc_COhdhdVucFZOd8nDx8RJKKynG2qHjqkdAYfPtcUah5F
   VITE_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com

5. Do NOT add PostHog to any backend code — frontend only.
```

### What you get for free (no code needed)
PostHog autocapture automatically tracks: page views, clicks on buttons/links, session duration, scroll depth, referrer, device/browser info. Session recording lets you replay what users did. You don't need to code any of this.


---

## Task 3: Access Gate

### Goal
A simple code-entry screen. Testers enter a shared access code to unlock the app.
Not auth — just a gate to keep randoms out.

### Instructions for Claude Code

```
Add a simple access code gate to the frontend. This is NOT authentication —
it's a lightweight screen that asks for an access code before showing the app.

1. Create frontend/components/AccessGate.tsx:
   - A centered card with:
     - Title: "CAG Audit Gateway" (or whatever the app title is)
     - Subtitle: "Enter access code to continue"
     - A single text input (type="password" so it's masked)
     - A "Continue" button
     - On submit: compare input against the access code
     - If correct: store a flag in sessionStorage (key: 'cag_access_granted', value: 'true')
       and update React state to show the app
     - If wrong: show inline error "Invalid access code", shake animation optional
   - Style it consistently with the existing app theme (check DottedGlowBackground.tsx
     and existing component styles for the dark theme / design language)

2. The access code should come from VITE_ACCESS_CODE env var.
   Default: "cag-test-2025" if not set.
   
   IMPORTANT: Yes, the code is visible in the JS bundle. This is intentional.
   It's not security — it's a gate. Anyone with DevTools can bypass it.
   That's fine for a 100-person invited test.

3. In the main app entry point (likely frontend/index.tsx or the root App component):
   - Check sessionStorage for 'cag_access_granted'
   - If not granted: render AccessGate instead of the main app
   - If granted: render the app normally
   - This means refreshing the page within the same tab keeps you logged in,
     but opening a new tab/window requires re-entering the code

4. Add VITE_ACCESS_CODE to .env.production.template

5. Do NOT add any backend validation for this. It's purely frontend.
```

---

## Environment Variables Summary

After all three tasks, your .env.production.template should include:

```env
# Existing
ANTHROPIC_API_KEY=sk-ant-xxxxx
QDRANT_URL=https://your-cluster.cloud.qdrant.io
QDRANT_API_KEY=your-qdrant-api-key
DATA_DIR=/app/data
ENVIRONMENT=production

# NEW: Rate limiting
RATE_LIMIT_PER_HOUR=30

# NEW: PostHog (frontend, baked into build)
VITE_PUBLIC_POSTHOG_KEY=phc_XXXXXXXXXXXX
VITE_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com

# NEW: Access gate (frontend, baked into build)
VITE_ACCESS_CODE=cag-test-2025
```

Note: VITE_ prefixed vars are baked into the frontend at build time.
Non-VITE vars are read by FastAPI at runtime.

---

## Execution Order

1. **Rate limiting** (backend only — no frontend changes, no rebuild needed)
2. **PostHog** (after you sign up and get the key)
3. **Access gate** (frontend only)
4. **Test locally**: `npm run dev` + `uvicorn` to verify all three work

Each task is independent — if one breaks, the others still work.