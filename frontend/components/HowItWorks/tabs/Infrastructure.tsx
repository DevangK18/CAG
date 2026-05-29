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
                Two databases (Qdrant for vectors, PostgreSQL for entity graph), multi-provider LLM orchestration,
                feature flag system, and Docker deployment with Caddy reverse proxy.
            </p>

            {/* Database Architecture */}
            <DocSection
                title="Database Architecture"
                description="Two databases: Qdrant for vector search, PostgreSQL for the entity graph and query logs."
            >
                <div style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px',
                }}>
                    {/* Qdrant */}
                    <div style={{ padding: '20px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '10px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                            <span style={{ fontSize: '16px', fontWeight: 700, color: '#166534' }}>Qdrant</span>
                            <span style={{ fontSize: '11px', fontWeight: 600, color: '#15803d', background: '#dcfce7', padding: '2px 8px', borderRadius: '4px' }}>Vector DB</span>
                        </div>
                        <div style={{ fontSize: '13px', color: '#15803d', lineHeight: 1.6, marginBottom: '12px' }}>
                            <strong>Two collections:</strong>
                            <ul style={{ paddingLeft: '16px', marginTop: '6px' }}>
                                <li><code>cag_child_chunks</code> — 15,669 chunks with hybrid vectors (dense 1536-dim + BM25 sparse)</li>
                                <li><code>cag_parent_chunks</code> — 2,792 parent sections (metadata-only, no vectors)</li>
                            </ul>
                        </div>
                        <div style={{ fontSize: '13px', color: '#15803d', lineHeight: 1.6 }}>
                            <strong>Payload indexes:</strong> report_id, government_body_type, state_name, audit_year, audit_category, finding_types, severity
                        </div>
                    </div>

                    {/* PostgreSQL */}
                    <div style={{ padding: '20px', background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: '10px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                            <span style={{ fontSize: '16px', fontWeight: 700, color: '#0c4a6e' }}>PostgreSQL</span>
                            <span style={{ fontSize: '11px', fontWeight: 600, color: '#0284c7', background: '#e0f2fe', padding: '2px 8px', borderRadius: '4px' }}>Entity Graph</span>
                        </div>
                        <div style={{ fontSize: '13px', color: '#0c4a6e', lineHeight: 1.6, marginBottom: '12px' }}>
                            <strong>Database:</strong> <code>cag_entity_graph</code>
                            <ul style={{ paddingLeft: '16px', marginTop: '6px' }}>
                                <li><code>entities</code> — 390 canonical entities with aliases</li>
                                <li><code>entity_mentions</code> — 24,865 indexed mentions</li>
                                <li><code>entity_relations</code> — Cross-entity relationships</li>
                                <li><code>query_logs</code> — 50-column observability log</li>
                            </ul>
                        </div>
                        <div style={{ fontSize: '13px', color: '#0c4a6e', lineHeight: 1.6 }}>
                            <strong>Two-DSN pattern:</strong> Docker uses <code>postgres:5432</code>, Mac development uses <code>localhost:5432</code>
                        </div>
                    </div>
                </div>

                <CalloutBox type="info">
                    <strong>Why two databases?</strong> Qdrant excels at high-dimensional vector search with payload filtering —
                    perfect for RAG retrieval. PostgreSQL handles relational data (entities with aliases, mention-to-chunk mappings)
                    and provides full SQL for complex observability queries.
                </CalloutBox>
            </DocSection>

            {/* LLM Provider Architecture */}
            <DocSection
                title="LLM Provider Architecture"
                description="Multi-provider support with provider-specific fallbacks. OpenAI is required regardless of main provider."
            >
                <div style={{
                    border: '1px solid #e2e8f0', borderRadius: '10px', overflow: 'hidden', marginBottom: '20px',
                }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                        <thead>
                            <tr style={{ background: '#f8fafc', borderBottom: '2px solid #cbd5e1' }}>
                                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>Task</th>
                                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>Primary Provider</th>
                                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>Fallback</th>
                                <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>Notes</th>
                            </tr>
                        </thead>
                        <tbody>
                            {[
                                ['RAG Generation', 'LLM_PROVIDER setting', 'GPT-4o-mini', 'Claude, GPT-4, or Gemini based on env'],
                                ['Embeddings', 'OpenAI', 'None', 'text-embedding-3-large (required)'],
                                ['Query Enhancement', 'OpenAI', 'None', 'gpt-4o-mini (required)'],
                                ['Agentic Planner', 'OpenAI', 'None', 'gpt-4o-mini (required for agentic)'],
                                ['Groundedness', 'OpenAI', 'None', 'gpt-4o-mini (required)'],
                                ['Reranking', 'Cohere', 'BGE Local', 'rerank-english-v3.0 → bge-reranker-v2-m3'],
                                ['Batch Summaries', 'Anthropic', 'OpenAI', 'Claude Opus/Sonnet via Batch API'],
                                ['Visual Extraction', 'Google', 'None', 'Gemini 2.5 Flash'],
                            ].map(([task, primary, fallback, notes]) => (
                                <tr key={task} style={{ borderBottom: '1px solid #e2e8f0' }}>
                                    <td style={{ padding: '12px', fontWeight: 600, color: '#1e293b' }}>{task}</td>
                                    <td style={{ padding: '12px', color: '#475569' }}>{primary}</td>
                                    <td style={{ padding: '12px', color: '#64748b' }}>{fallback}</td>
                                    <td style={{ padding: '12px', color: '#64748b', fontSize: '13px' }}>{notes}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <CalloutBox type="warning">
                    <strong>OPENAI_API_KEY is required</strong> even if you set <code>LLM_PROVIDER=anthropic</code> or <code>google</code>.
                    Embeddings, query enhancement, agentic planner, and groundedness verification all use OpenAI models
                    because they offer the best cost/latency for these specific tasks.
                </CalloutBox>
            </DocSection>

            {/* Feature Flag System */}
            <DocSection
                title="Feature Flag System"
                description="All advanced features are independently toggleable. Enable/disable via environment variables."
            >
                <div style={{
                    border: '1px solid #e2e8f0', borderRadius: '10px', overflow: 'hidden', marginBottom: '20px',
                }}>
                    <div style={{ padding: '14px 18px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0', fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>
                        Feature Flag Matrix
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                        <thead>
                            <tr style={{ borderBottom: '2px solid #cbd5e1' }}>
                                {['Feature', 'Env Variable', 'Default', 'Description'].map((h) => (
                                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 700, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {[
                                ['Agentic Mode', 'ENABLE_AGENTIC', 'true', 'Query decomposition for multi-hop queries'],
                                ['Groundedness', 'ENABLE_GROUNDEDNESS', 'true', 'Post-generation claim verification'],
                                ['Auto-filter', 'ENABLE_AUTO_FILTER', 'true', 'Extract filters from query text'],
                                ['Entity Narrowing', 'ENABLE_ENTITY_NARROWING', 'true', 'Use entity graph for comparative queries'],
                                ['Query Logging', 'ENABLE_QUERY_LOG', 'true', 'Write to query_logs table'],
                                ['Dev Mode Logging', 'QUERY_LOG_DEV_MODE', 'false', 'Include full prompts in logs'],
                                ['Reranking', 'ENABLE_RERANKING', 'true', 'Cohere/BGE cross-encoder reranking'],
                                ['BGE Fallback', 'ENABLE_BGE_FALLBACK', 'true', 'Fall back to local BGE if Cohere fails'],
                            ].map(([feature, envVar, defaultVal, desc]) => (
                                <tr key={envVar} style={{ borderBottom: '1px solid #e2e8f0' }}>
                                    <td style={{ padding: '10px 14px', fontWeight: 600, color: '#1e293b' }}>{feature}</td>
                                    <td style={{ padding: '10px 14px' }}>
                                        <code style={{ fontSize: '12px', background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>{envVar}</code>
                                    </td>
                                    <td style={{ padding: '10px 14px' }}>
                                        <span style={{
                                            fontSize: '11px', fontWeight: 600, padding: '2px 8px', borderRadius: '4px',
                                            background: defaultVal === 'true' ? '#dcfce7' : '#fef2f2',
                                            color: defaultVal === 'true' ? '#166534' : '#991b1b',
                                        }}>{defaultVal}</span>
                                    </td>
                                    <td style={{ padding: '10px 14px', color: '#475569' }}>{desc}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <CodeBlock title="Feature Toggle Example">
{`# Disable agentic mode for simpler deployments
ENABLE_AGENTIC=false

# Enable verbose logging for debugging
QUERY_LOG_DEV_MODE=true

# Disable groundedness to reduce latency
ENABLE_GROUNDEDNESS=false`}
                </CodeBlock>
            </DocSection>

            {/* Docker Setup */}
            <DocSection
                title="Docker Setup"
                description="Production deployment with docker-compose.prod.yml and Caddy reverse proxy"
            >
                <DiagramCard title="Docker Compose Architecture">
                    <MermaidDiagram
                        chart={dockerSetup}
                        caption="Three services: FastAPI (port 8000), Qdrant (port 6333), and React dev server (port 5173). All networked via Docker Compose."
                    />
                </DiagramCard>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Development vs Production</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                        <div style={{ padding: '16px', background: '#fefce8', border: '1px solid #fde68a', borderRadius: '8px' }}>
                            <div style={{ fontSize: '13px', fontWeight: 700, color: '#92400e', marginBottom: '8px' }}>Development</div>
                            <CodeBlock>
{`# Just Qdrant + PostgreSQL in Docker
docker run -p 6333:6333 qdrant/qdrant
docker run -p 5432:5432 postgres

# FastAPI + React run locally
uvicorn src.api.main:app --reload
npm run dev`}
                            </CodeBlock>
                        </div>
                        <div style={{ padding: '16px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '8px' }}>
                            <div style={{ fontSize: '13px', fontWeight: 700, color: '#166534', marginBottom: '8px' }}>Production</div>
                            <CodeBlock>
{`# Full stack via docker-compose.prod.yml
docker compose --env-file .env.production \\
  -f docker-compose.prod.yml build --no-cache

docker compose --env-file .env.production \\
  -f docker-compose.prod.yml up -d`}
                            </CodeBlock>
                        </div>
                    </div>

                    <CalloutBox type="info">
                        <strong>Production stack:</strong> Caddy (reverse proxy + auto-TLS) → FastAPI (Gunicorn + Uvicorn workers) → Qdrant + PostgreSQL.
                        Frontend is pre-built and served by Caddy.
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
                                <td style={{ padding: '12px' }}>Send query, receive streaming response (standard path)</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#fff7ed', padding: '2px 6px', borderRadius: '4px', border: '1px solid #fed7aa' }}>/api/chat/agentic/stream</code></td>
                                <td style={{ padding: '12px' }}>POST</td>
                                <td style={{ padding: '12px' }}>Agentic query with decomposition (Phase 11)</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/series</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>List all time series</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>/api/series/:id/chat</code></td>
                                <td style={{ padding: '12px' }}>POST</td>
                                <td style={{ padding: '12px' }}>Query time series, streaming response</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f0f9ff', padding: '2px 6px', borderRadius: '4px', border: '1px solid #bae6fd' }}>/api/entities</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>List canonical entities with filters (Phase 12)</td>
                            </tr>
                            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f0f9ff', padding: '2px 6px', borderRadius: '4px', border: '1px solid #bae6fd' }}>/api/entities/:id</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>Get entity details, aliases, mentions, related reports</td>
                            </tr>
                            <tr>
                                <td style={{ padding: '12px' }}><code style={{ background: '#f0f9ff', padding: '2px 6px', borderRadius: '4px', border: '1px solid #bae6fd' }}>/api/entities/:id/findings</code></td>
                                <td style={{ padding: '12px' }}>GET</td>
                                <td style={{ padding: '12px' }}>Get all findings mentioning this entity</td>
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
                    <CodeBlock title="Environment Variables (Full Reference)">
{`# ═══════════════════════════════════════════════════════════
# API KEYS (Required)
# ═══════════════════════════════════════════════════════════
OPENAI_API_KEY=sk-...          # Embeddings, enhancement, agentic, groundedness
ANTHROPIC_API_KEY=sk-ant-...   # Claude RAG generation + Batch API
COHERE_API_KEY=...             # Reranking (fallback to BGE if missing)
GOOGLE_API_KEY=...             # Gemini visual extraction

# ═══════════════════════════════════════════════════════════
# SERVICES
# ═══════════════════════════════════════════════════════════
QDRANT_URL=http://localhost:6333
DATABASE_URL=postgresql://user:pass@localhost:5432/cag_entity_graph

# ═══════════════════════════════════════════════════════════
# LLM PROVIDER SELECTION
# ═══════════════════════════════════════════════════════════
LLM_PROVIDER=anthropic         # anthropic | openai | google

# ═══════════════════════════════════════════════════════════
# FEATURE FLAGS
# ═══════════════════════════════════════════════════════════
ENABLE_AGENTIC=true            # Query decomposition for complex queries
ENABLE_GROUNDEDNESS=true       # Post-generation verification
ENABLE_AUTO_FILTER=true        # Extract filters from query text
ENABLE_ENTITY_NARROWING=true   # Entity graph for comparative queries
ENABLE_QUERY_LOG=true          # Write to query_logs table
QUERY_LOG_DEV_MODE=false       # Include full prompts in logs

# ═══════════════════════════════════════════════════════════
# RATE LIMITING & SECURITY
# ═══════════════════════════════════════════════════════════
RATE_LIMIT_CHAT=30/hour        # Chat endpoint rate limit
VITE_ACCESS_CODE=code1,code2   # Access gate codes (comma-separated)

# ═══════════════════════════════════════════════════════════
# ANALYTICS (Optional)
# ═══════════════════════════════════════════════════════════
VITE_PUBLIC_POSTHOG_KEY=phc_...`}
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
