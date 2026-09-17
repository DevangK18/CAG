# Claude Code Prompt: Build "How It Works" Section

## Task
Add a full "How It Works" documentation section to the CAG Gateway frontend. This is a tabbed, multi-page documentation area showcasing the project's architecture, technology, and implementation details.

## Requirements

### 1. Routing & Navigation

- Add a **"How It Works"** link to the main top navbar (between "Time Series Analysis" and the user avatar)
- Create route `/how-it-works` with nested child routes:
  - `/how-it-works/overview` (default — redirect `/how-it-works` here)
  - `/how-it-works/data-pipeline`
  - `/how-it-works/rag-search`
  - `/how-it-works/ai-features`
  - `/how-it-works/frontend`
  - `/how-it-works/infrastructure`

### 2. Layout Component: `HowItWorks.tsx`

- A **horizontal tab bar** sitting directly below the main navbar, visually distinct (e.g., `bg-slate-50` with bottom border, or white with a stronger bottom-border separator)
- Tab items are `<NavLink>` elements in a flex row, horizontally scrollable on mobile
- **Active tab** gets: bottom border highlight (2-3px, primary color), bolder text or color change
- **Inactive tabs**: muted text, no bottom border
- Below the tab bar: `<Outlet />` renders the active tab's content
- Content area should have a max-width container (e.g., `max-w-4xl mx-auto`) with comfortable padding for readability — like a docs page, not a full-bleed dashboard

### 3. Tab Content Components

Create these files under a `HowItWorks/` directory (or `pages/HowItWorks/tabs/`):

#### Tab 1: Overview (`Overview.tsx`)
Content to include:
- **Project Mission**: "CAG Gateway transforms static audit reports from India's Comptroller & Auditor General into interactive, searchable data experiences."
- **Disclaimer**: Independent initiative, not affiliated with CAG of India
- **Key Stats**: 19 reports, 1022+ findings, 5 ministries (pull from API if possible, or hardcode)
- **Architecture Diagram** (Mermaid): High-level system diagram showing:
  ```
  PDF Reports → Docling Parser → Chunking Engine → Qdrant Vector DB
                                                          ↓
  User → React Frontend → FastAPI Backend → Claude API (Haiku/Sonnet)
                                    ↓
                              Qdrant Search → Context Assembly → Streaming Response
  ```
- **Tech Stack Section**: Display ALL technologies as a visual grid/badges grouped by category:
  - **Language**: Python 3.11+
  - **Backend**: FastAPI, Pydantic, Uvicorn
  - **Frontend**: React, TypeScript, Vite, Tailwind CSS, Recharts
  - **AI/LLM**: Claude API (Sonnet, Haiku), Anthropic Batch API, Extended Thinking
  - **Vector DB**: Qdrant (self-hosted via Docker)
  - **Document Parsing**: Docling (IBM), PyMuPDF
  - **Data Processing**: Pandas, NumPy
  - **Infrastructure**: Docker, Docker Compose
  - **Other**: Server-Sent Events (SSE) for streaming, Mermaid.js for diagrams
  
  For the tech stack, render each technology as a small card/badge with the tech name. Group them under category headers. Make it visually appealing — not just a list.

#### Tab 2: Data Pipeline (`DataPipeline.tsx`)
Content to include:
- **Mermaid Flowchart**: End-to-end pipeline from raw PDF to indexed vectors
  ```
  Raw PDF → Docling (IBM) → Structured Text Extraction
    → Section Detection (chapters, paragraphs, annexures)
    → Chunking Engine (semantic chunking with overlap)
    → Metadata Enrichment (report year, ministry, audit type, page numbers)
    → Embedding Generation
    → Qdrant Indexing
  ```
- **PDF Parsing with Docling**: Explain how Docling handles complex government PDFs — tables, multi-column layouts, headers/footers
- **Charts & Tables Extraction**: How charts and tables are detected, extracted, and stored separately for the Charts/Tables navigation feature
- **Chunking Strategy**: Explain semantic chunking — chunk sizes, overlap, how section boundaries are respected
- **Metadata Enrichment**: What metadata gets attached to each chunk (report_id, page, section, chapter, audit_type, ministry, year)
- **Batch Processing Pipeline**: How Claude Batch API is used for bulk enrichment — diagram showing job submission → polling → result collection
- **Mermaid Diagram**: Show the data folder structure and how processed JSONs relate to each other

#### Tab 3: RAG & Search (`RAGSearch.tsx`)
Content to include:
- **Query Flow Diagram** (Mermaid sequence diagram):
  ```
  User types question
    → Frontend sends to /api/chat
    → FastAPI receives query
    → Query embedded via model
    → Qdrant similarity search (top-k chunks)
    → Context assembly (chunks + metadata)
    → Claude API call with system prompt + context + user query
    → Streaming response via SSE
    → Frontend renders with inline citations
  ```
- **Vector Search**: How Qdrant is configured — collection schema, distance metric, indexing params
- **Context Assembly**: How retrieved chunks are ranked, deduplicated, and assembled into a coherent context window
- **Citation Mechanism**: How chunk metadata (page numbers, sections) maps back to source citations in the response
- **Streaming Architecture**: SSE implementation — how FastAPI streams tokens and how React consumes them in real-time
- **Prompt Engineering**: Overview of system prompts used — how Claude is instructed to cite sources, handle ambiguity, stay grounded in the audit report content

#### Tab 4: AI Features (`AIFeatures.tsx`)
Content to include:
- **AI Summaries** (Mermaid diagram showing the 5 variants):
  - Executive Brief, Key Findings, Detailed Analysis, Recommendations, Quick Take
  - How they're generated: Claude Batch API with Extended Thinking
  - Batch job lifecycle: submission → processing → result retrieval → storage
  ```
  Report Chunks → Prompt Variants (5 types)
    → Claude Batch API (with Extended Thinking)
    → Poll for completion
    → Parse results → Store as JSON
    → Serve via API → Frontend tabs
  ```
- **Enhanced Overview Generation**: How audit scope, objectives, topics, and glossary are extracted using LLM
- **Time Series Analysis**: How cross-report analysis works — identifying trends across multiple years of audit reports for the same ministry/topic
- **Diagram**: Show how different AI features connect to the same underlying chunk data but produce different outputs

#### Tab 5: Frontend Architecture (`FrontendArchitecture.tsx`)
Content to include:
- **Component Architecture** (Mermaid diagram): Show the main page components and how they nest
  ```
  App
  ├── ReportDirectory (grid/list of all reports)
  ├── ReportDetail
  │   ├── OverviewTab (stats, scope, AI summary tabs)
  │   ├── ChatTab (RAG chat with streaming + citations)
  │   ├── ChartsTab (extracted charts/tables viewer)
  │   └── TimeSeriesTab (cross-report trends)
  ├── TimeSeriesAnalysis (standalone cross-report page)
  └── HowItWorks (this documentation)
  ```
- **Streaming UI Pattern**: How the chat interface handles SSE — message state management, token-by-token rendering, citation highlighting
- **Search & Filtering**: How the report directory search, sector filter, and grid/list toggle work
- **Key Hooks**: Overview of custom hooks used (e.g., useChat, useReport, useSearch) and what they encapsulate
- **State Management**: How data flows — API calls via custom hooks, local state, etc.

#### Tab 6: Infrastructure (`Infrastructure.tsx`)
Content to include:
- **Docker Setup** (Mermaid diagram):
  ```
  Docker Compose
  ├── FastAPI Service (port 8000)
  ├── Qdrant Service (port 6333)
  └── React Dev Server / Nginx (port 5173/80)
  ```
- **Repository Structure**: Visual tree of the repo showing key directories and what lives where
  ```
  cag-gateway/
  ├── services/api/          # FastAPI backend
  │   ├── routes/            # API endpoints
  │   ├── models.py          # Pydantic models
  │   └── ...
  ├── frontend/              # React + TypeScript
  │   ├── src/pages/
  │   ├── src/hooks/
  │   └── src/lib/api.ts
  ├── data/
  │   ├── processed/         # Enriched report JSONs
  │   └── batch_jobs/        # Claude Batch API outputs
  └── docker-compose.yml
  ```
- **API Endpoint Map**: Table showing key endpoints, methods, and what they do
- **Report ID Convention**: Explain the `{year}_{number}_{title_slug}` pattern
- **Data File Organization**: How processed JSONs, batch outputs, and vector data relate

### 4. Mermaid Diagram Rendering

- Use a Mermaid rendering approach that works with your existing setup. Options:
  - Install `mermaid` npm package and create a reusable `<MermaidDiagram>` component that takes a diagram string and renders it
  - Or use `react-mermaidjs` if you prefer a wrapper
- Create a **reusable `MermaidDiagram` component** at `components/MermaidDiagram.tsx` that:
  - Accepts a `chart` string prop
  - Renders the Mermaid diagram in a container
  - Has a light theme matching the docs aesthetic
  - Handles loading/error states gracefully

### 5. Shared Content Components

Create reusable components for the documentation pages:

- **`DocSection`**: A section with a title (h2), optional description, and children. Adds consistent spacing.
- **`TechBadge`**: A small styled badge/chip showing a technology name, optionally with a category color
- **`DiagramCard`**: A wrapper for Mermaid diagrams with an optional caption/title, light background, rounded corners
- **`CodeBlock`**: Styled code display for showing file paths, API contracts, folder structures (use a monospace font, light gray bg)
- **`CalloutBox`**: An info/note box (like Stripe's blue info boxes) for highlighting key points

### 6. Styling Guidelines

- The documentation pages should feel like a **polished docs site** — clean, lots of whitespace, excellent typography
- Use a readable line length (max-width ~65-75ch for prose)
- Mermaid diagrams should be centered with comfortable padding
- Use a consistent heading hierarchy: h1 for tab title, h2 for sections, h3 for subsections
- Code/file paths in inline `code` style
- Color-coded tech badges by category
- Responsive: tab bar scrolls horizontally on mobile, content stacks naturally

### 7. File Structure

```
frontend/src/
├── pages/
│   └── HowItWorks/
│       ├── HowItWorks.tsx          # Layout with tab bar + Outlet
│       ├── tabs/
│       │   ├── Overview.tsx
│       │   ├── DataPipeline.tsx
│       │   ├── RAGSearch.tsx
│       │   ├── AIFeatures.tsx
│       │   ├── FrontendArchitecture.tsx
│       │   └── Infrastructure.tsx
│       └── components/
│           ├── MermaidDiagram.tsx
│           ├── DocSection.tsx
│           ├── TechBadge.tsx
│           ├── DiagramCard.tsx
│           ├── CodeBlock.tsx
│           └── CalloutBox.tsx
```

### 8. Integration Checklist

- [ ] Add "How It Works" to main navbar component
- [ ] Add routes to the router config (wherever routes are defined — likely `App.tsx` or a routes file)
- [ ] Default redirect from `/how-it-works` → `/how-it-works/overview`
- [ ] Install `mermaid` package: `npm install mermaid`
- [ ] All 6 tab pages render with placeholder content + at least one Mermaid diagram each
- [ ] Tab bar highlights active tab correctly
- [ ] Navigation between tabs works without full page reload
- [ ] Responsive on mobile

### Important Notes

- This is a Python-based project showcase. Emphasize Python everywhere — the backend, parsing, data processing, batch jobs are ALL Python. The frontend is the only non-Python piece.
- Include ALL non-trivial technologies: Docling (IBM's document parser), Qdrant, Docker, Claude API Batch processing, Extended Thinking, SSE streaming, Pydantic, etc.
- Every tab should have at LEAST 2 Mermaid diagrams. Diagrams are a priority — they should be the visual anchors of each page.
- The content should read like a technical blog post / case study — informative but not dry. Write it as if explaining the project to a technically curious person who wants to understand HOW it all works.
- Use real details from the project (report ID patterns, actual API routes, actual component names) — not generic placeholder text.
