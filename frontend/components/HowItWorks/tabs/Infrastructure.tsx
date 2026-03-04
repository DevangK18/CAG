import React from 'react';
import { DocSection } from '../shared/DocSection';
import { DiagramCard } from '../shared/DiagramCard';
import { CalloutBox } from '../shared/CalloutBox';
import { CodeBlock } from '../shared/CodeBlock';
import { MermaidDiagram } from '../shared/MermaidDiagram';

export const Infrastructure: React.FC = () => {
    const dockerSetup = `
graph TB
    Compose[Docker Compose]

    Compose --> FastAPI[FastAPI Service<br/>:8000]
    Compose --> Qdrant[Qdrant Service<br/>:6333]
    Compose --> React[React Dev Server<br/>:5173]

    FastAPI --> API[API Endpoints]
    FastAPI --> Models[Pydantic Models]

    Qdrant --> Collections[Vector Collections]
    Qdrant --> Index[HNSW Index]

    React --> Components[React Components]
    React --> Hooks[Custom Hooks]

    style Compose fill:#f3f4f6
    style FastAPI fill:#dbeafe
    style Qdrant fill:#dcfce7
    style React fill:#e0e7ff
`;

    const repoStructure = `
graph TB
    Root[cag-gateway/]

    Root --> Src[src/]
    Root --> Frontend[frontend/]
    Root --> Data[data/]
    Root --> Docker[docker-compose.yml]

    Src --> API[api/]
    Src --> Parsing[parsing_pipeline/]
    Src --> RAG[rag_pipeline/]
    Src --> Batch[batch_pipeline/]

    Frontend --> Components[components/]
    Frontend --> Hooks[hooks/]
    Frontend --> IndexTsx[index.tsx]

    Data --> Raw[raw/]
    Data --> Processed[processed/]
    Data --> Extraction[extraction_images/]

    style Root fill:#f3f4f6
    style Src fill:#dbeafe
    style Frontend fill:#e0e7ff
    style Data fill:#dcfce7
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">Infrastructure</h1>
            <p className="page-subtitle">
                Docker setup, repository structure, and deployment architecture
            </p>

            {/* Docker Setup */}
            <DocSection
                title="Docker Setup"
                description="Containerized services with Docker Compose"
            >
                <DiagramCard title="Docker Compose Architecture">
                    <MermaidDiagram
                        chart={dockerSetup}
                        caption="Three services: FastAPI (port 8000), Qdrant (port 6333), and React dev server (port 5173). All networked via Docker Compose."
                    />
                </DiagramCard>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Starting the Services</h3>
                    <CodeBlock title="Docker Compose Commands">
{`# Start Qdrant only (for development)
docker run -p 6333:6333 qdrant/qdrant

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down

# Rebuild after code changes
docker-compose up --build`}
                    </CodeBlock>

                    <CalloutBox type="info">
                        <strong>Development Mode:</strong> In development, FastAPI and React run locally (not in Docker) for faster iteration. Only Qdrant runs in Docker.
                    </CalloutBox>
                </div>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Service Configuration</h3>
                    <CalloutBox type="success">
                        <strong>FastAPI:</strong> Runs with --reload flag for auto-restart. Mounted volumes for hot reloading. Exposed on port 8000.
                    </CalloutBox>
                    <CalloutBox type="warning">
                        <strong>Qdrant:</strong> Self-hosted vector DB. Data persisted in Docker volume. Exposed on port 6333 (HTTP) and 6334 (gRPC).
                    </CalloutBox>
                    <CalloutBox type="note">
                        <strong>React:</strong> Vite dev server with HMR. Proxy configured to forward /api requests to FastAPI. Exposed on port 5173.
                    </CalloutBox>
                </div>
            </DocSection>

            {/* Repository Structure */}
            <DocSection
                title="Repository Structure"
                description="Key directories and what lives where"
            >
                <DiagramCard title="Repository Organization">
                    <MermaidDiagram
                        chart={repoStructure}
                        caption="Python backend in src/, React frontend in frontend/, processed data in data/. Docker Compose at root."
                    />
                </DiagramCard>

                <div style={{ marginTop: '24px' }}>
                    <CodeBlock title="Detailed Directory Tree">
{`cag-gateway/
├── src/                              # Python backend
│   ├── api/                          # FastAPI application
│   │   ├── main.py                   # App entry point
│   │   ├── routes/                   # API endpoints
│   │   │   ├── reports.py            # /api/reports
│   │   │   ├── chat.py               # /api/chat
│   │   │   └── series.py             # /api/series
│   │   └── models.py                 # Pydantic models
│   ├── parsing_pipeline/             # 10-phase processing
│   │   ├── main.py                   # Orchestrator
│   │   ├── modules/                  # Phase services
│   │   └── extractors/               # Table/text/visual
│   ├── rag_pipeline/                 # Embedding & retrieval
│   │   ├── indexer.py                # Qdrant indexing
│   │   ├── retriever.py              # Hybrid search
│   │   └── cli.py                    # Interactive CLI
│   ├── batch_pipeline/               # Batch API jobs
│   │   ├── submit_jobs.py            # Job submission
│   │   ├── check_status.py           # Status polling
│   │   └── process_results.py        # Result processing
│   └── core/
│       ├── config.py                 # Central config
│       ├── data_contracts.py         # Pydantic models
│       └── table_contracts.py        # Structured tables
│
├── frontend/                         # React + TypeScript
│   ├── index.tsx                     # Main app component
│   ├── components/                   # Reusable components
│   │   ├── PDFViewer.tsx
│   │   ├── ReportCard.tsx
│   │   └── HowItWorks/               # Documentation
│   ├── hooks/                        # Custom hooks
│   │   ├── useReports.ts
│   │   ├── useChat.ts
│   │   └── useChatStream.ts
│   ├── stores/                       # Zustand stores
│   │   └── appStore.ts
│   ├── lib/                          # Utilities
│   │   ├── api.ts                    # API client
│   │   └── citationUtils.ts          # Citation parsing
│   ├── index.css                     # Global styles
│   ├── package.json
│   └── vite.config.ts
│
├── data/                             # Data files
│   ├── raw/                          # Downloaded PDFs
│   ├── processed/                    # Structured JSONs
│   │   ├── {report_id}_chunks.json
│   │   ├── ocred/                    # OCR-processed PDFs
│   │   └── manifest.json             # Report registry
│   ├── extraction_images/            # Saved images for Gemini
│   └── batch_jobs/                   # Batch API tracking
│
├── tests/                            # Pytest suite
├── scripts/                          # Utility scripts
│   └── run_pipeline_quick.py         # Quick runner
├── docker-compose.yml
├── pyproject.toml                    # Poetry dependencies
├── CLAUDE.md                         # Project instructions
└── README.md`}
                    </CodeBlock>
                </div>
            </DocSection>

            {/* API Endpoint Map */}
            <DocSection
                title="API Endpoint Map"
                description="Key endpoints, methods, and what they do"
            >
                <div style={{ overflowX: 'auto', marginTop: '16px' }}>
                    <table style={{
                        width: '100%',
                        borderCollapse: 'collapse',
                        fontSize: '14px',
                        border: '1px solid #e2e8f0'
                    }}>
                        <thead>
                            <tr style={{ background: '#f8fafc', borderBottom: '2px solid #cbd5e1' }}>
                                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600 }}>Endpoint</th>
                                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600 }}>Method</th>
                                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600 }}>Description</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/reports</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>List all reports with metadata, stats</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/reports/:id</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>Get single report details, PDF URL</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/reports/:id/overview</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>Get enhanced overview (scope, objectives, topics)</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/reports/:id/summaries</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>List AI summary variants</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/reports/:id/summaries/:variant</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>Get specific summary variant content</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/reports/:id/charts</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>Get all charts for a report</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/reports/:id/tables</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>Get all tables for a report</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/chat</code></td>
                                <td style={{ padding: '12px' }}>POST</td>
                                <td style={{ padding: '12px' }}>Send query, receive streaming response</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/series</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>List all time series</td>
                            </tr>
                            <tr>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/series/:id/chat</code></td>
                                <td style={{ padding: '12px' }}>POST</td>
                                <td style={{ padding: '12px' }}>Query time series, streaming response</td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <CalloutBox type="info" style={{ marginTop: '16px' }}>
                    <strong>API Base URL:</strong> http://localhost:8000 (dev) or configured production URL. All endpoints return JSON except chat endpoints which use SSE.
                </CalloutBox>
            </DocSection>

            {/* Report ID Convention */}
            <DocSection
                title="Report ID Convention"
                description="How reports are uniquely identified"
            >
                <div style={{ lineHeight: '1.7', color: '#475569' }}>
                    <p>
                        Report IDs follow the pattern: <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>{'{'} year {'}_{'} number {'}_{'} title_slug {'}'}</code>
                    </p>

                    <CodeBlock title="Example Report IDs">
{`2023_19_CAG_Performance_Audit_of_Implementation_of_PhaseI_of_Bharatmala_Pariyojana
2025_20_Performance_Audit_on_on_Skill_Development_under_Pradhan_Mantri_Kaushal_Vikas_Yoj
2024_13_Compliance_Audit_on_Direct_taxes_for_period_202122_for_the_Union_Government_Depa

Components:
- Year: 2023, 2024, 2025
- Number: 19, 20, 13 (report number within that year)
- Title Slug: Underscored, sanitized title`}
                    </CodeBlock>

                    <p style={{ marginTop: '16px' }}>
                        This convention ensures:
                    </p>
                    <ul style={{ paddingLeft: '24px', marginTop: '8px', lineHeight: '1.8' }}>
                        <li>Unique identification across all reports</li>
                        <li>Year-based sorting and filtering</li>
                        <li>Human-readable report discovery</li>
                        <li>File system compatibility (no spaces, special chars)</li>
                    </ul>
                </div>
            </DocSection>

            {/* Data File Organization */}
            <DocSection
                title="Data File Organization"
                description="How processed JSONs, batch outputs, and vector data relate"
            >
                <div style={{ lineHeight: '1.7', color: '#475569' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Data Flow</h3>

                    <CalloutBox type="success">
                        <strong>1. Raw PDFs:</strong> Downloaded to <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>data/raw/</code>. Named using report ID convention.
                    </CalloutBox>

                    <CalloutBox type="info">
                        <strong>2. Processing:</strong> Pipeline reads PDFs, processes through 10 phases, outputs to <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>data/processed/</code>.
                    </CalloutBox>

                    <CalloutBox type="warning">
                        <strong>3. Structured JSONs:</strong> <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>{'{report_id}_chunks.json'}</code> contains all chunks, metadata, findings, recommendations.
                    </CalloutBox>

                    <CalloutBox type="note">
                        <strong>4. Indexing:</strong> Indexer reads JSONs, embeds chunks, uploads to Qdrant. Vector data stored in Qdrant (not on disk).
                    </CalloutBox>

                    <CalloutBox type="success">
                        <strong>5. Manifest:</strong> <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>data/processed/manifest.json</code> is the single source of truth for report registry.
                    </CalloutBox>
                </div>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Batch Outputs</h3>
                    <CodeBlock>
{`data/batch_jobs/
├── summaries/
│   ├── {batch_id}_requests.jsonl       # Batch request file
│   ├── {batch_id}_results.jsonl        # Batch results
│   └── {batch_id}_mapping.json         # Request ID mapping
├── overviews/
│   └── {report_id}_overview.json       # Enhanced overview
└── gemini/
    └── {report_id}_visuals.json        # Gemini extractions`}
                    </CodeBlock>

                    <p style={{ marginTop: '16px' }}>
                        Batch jobs create intermediate files for tracking. Results are merged into <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>{'{report_id}_chunks.json'}</code> after processing.
                    </p>
                </div>
            </DocSection>

            {/* Deployment */}
            <DocSection title="Deployment">
                <CalloutBox type="info">
                    <strong>Requirements:</strong> Python 3.11+, Node 18+, Docker, ≥16GB RAM (for vision models), API keys (OpenAI, Anthropic, Google, Cohere).
                </CalloutBox>

                <div style={{ marginTop: '16px' }}>
                    <CodeBlock title="Environment Variables">
{`# API Keys
OPENAI_API_KEY=sk-...          # Embeddings + Batch API
ANTHROPIC_API_KEY=sk-ant-...   # Claude LLM + Batch API
COHERE_API_KEY=...             # Reranking
GOOGLE_API_KEY=...             # Gemini visual extraction

# Services
QDRANT_URL=http://localhost:6333

# Optional
ANTHROPIC_API_KEY=...          # Phase 5.7 TOC validation (optional)`}
                    </CodeBlock>
                </div>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Production Considerations</h3>
                    <ul style={{ paddingLeft: '24px', lineHeight: '1.8', color: '#475569' }}>
                        <li>Use Nginx or Caddy as reverse proxy for FastAPI + React</li>
                        <li>Consider Qdrant Cloud for managed vector DB (easier scaling)</li>
                        <li>Set up CI/CD for automatic deployments (GitHub Actions, GitLab CI)</li>
                        <li>Monitor costs: OpenAI embeddings, Claude API, Gemini API</li>
                        <li>Implement rate limiting and caching for API endpoints</li>
                        <li>Use environment-specific configs (dev, staging, prod)</li>
                    </ul>
                </div>
            </DocSection>
        </div>
    );
};
