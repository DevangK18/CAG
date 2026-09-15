import React from 'react';
import { DocSection } from '../shared/DocSection';
import { TechBadge } from '../shared/TechBadge';
import { DiagramCard } from '../shared/DiagramCard';
import { CalloutBox } from '../shared/CalloutBox';
import { MermaidDiagram } from '../shared/MermaidDiagram';

/* ─── inline helper components ─── */

const ImpactStat: React.FC<{ value: string; label: string; sublabel?: string; accent?: string }> = ({
    value, label, sublabel, accent = '#1a365d',
}) => (
    <div className="stat-card" style={{ textAlign: 'center' }}>
        <div className="stat-value" style={{ color: accent }}>{value}</div>
        <div className="stat-label">{label}</div>
        {sublabel && <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px', lineHeight: 1.3 }}>{sublabel}</div>}
    </div>
);

const ProblemPoint: React.FC<{ stat: string; text: string }> = ({ stat, text }) => (
    <div style={{
        display: 'flex', gap: '14px', alignItems: 'flex-start',
        padding: '14px 18px', background: '#fef2f2',
        border: '1px solid #fecaca', borderRadius: '8px',
    }}>
        <span style={{
            fontSize: '20px', fontWeight: 800, color: '#dc2626',
            minWidth: '60px', textAlign: 'right', lineHeight: 1.2,
        }}>{stat}</span>
        <span style={{ fontSize: '14px', color: '#991b1b', lineHeight: 1.6 }}>{text}</span>
    </div>
);

const CapabilityCard: React.FC<{ title: string; description: string; accent: string }> = ({ title, description, accent }) => (
    <div style={{
        padding: '16px 20px', background: '#fff',
        border: '1px solid #e2e8f0', borderLeft: `4px solid ${accent}`,
        borderRadius: '0 8px 8px 0',
    }}>
        <div style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b', marginBottom: '6px' }}>{title}</div>
        <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6 }}>{description}</div>
    </div>
);

/* ─── main component ─── */

export const Overview: React.FC = () => {

    const architectureDiagram = `
graph TB
    subgraph "Offline · Document Processing"
        PDF[PDF Reports<br/>Union · State · Local Body] --> Parse[10-Phase Pipeline<br/>OCR · Tables · Structure]
        Parse --> Enrich[Semantic Enrichment<br/>Findings · Entities · Severity]
        Enrich --> Index[Hybrid Indexing<br/>Dense + BM25 Sparse]
        Index --> Qdrant[(Qdrant Vector DB<br/>15,000+ chunks)]
        Parse --> Batch[Batch AI Processing<br/>Overviews · Summaries]
        Batch --> Store[(Processed JSON<br/>per report)]
        Batch --> EG[Entity Extraction<br/>Normalization]
        EG --> PG[(PostgreSQL<br/>Entity Graph)]
    end

    subgraph "Online · User Query"
        User[User Question] --> QE[Query Enhancement<br/>Expansion + Auto-filter]
        QE --> Router{Query<br/>Complexity}
        Router -->|simple| Hybrid[Hybrid Search<br/>Vector + BM25 + RRF]
        Router -->|multi-hop| Agent[Agentic Loop<br/>Decompose · Iterate]
        Agent --> Hybrid
        Hybrid --> Qdrant
        PG --> Entity[Entity Narrowing<br/>for Comparative]
        Entity --> Hybrid
        Qdrant --> Rerank[Cohere Reranking<br/>+ Context Assembly]
        Rerank --> LLM[LLM Generation<br/>with Source Citations]
        LLM --> Ground[Groundedness Check<br/>Claim Verification]
        Ground --> Stream[Streaming Response<br/>+ Clickable Citations]
    end

    style PDF fill:#fef3c7,stroke:#f59e0b
    style Qdrant fill:#dcfce7,stroke:#22c55e
    style PG fill:#e0f2fe,stroke:#0ea5e9
    style LLM fill:#fae8ff,stroke:#d946ef
    style User fill:#e0e7ff,stroke:#6366f1
    style Stream fill:#e0e7ff,stroke:#6366f1
    style Agent fill:#fff7ed,stroke:#ea580c
    style Ground fill:#f0fdf4,stroke:#22c55e
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">How CAG Gateway Works</h1>

            {/* ══════════════════════════════════════════════
                THE PROBLEM
            ══════════════════════════════════════════════ */}
            <DocSection
                title="The Problem"
                description="India's government accountability data exists — but it's locked in a format nobody can use."
            >
                <div style={{ display: 'grid', gap: '10px', marginTop: '12px', marginBottom: '16px' }}>
                    <ProblemPoint
                        stat="100+"
                        text="audit reports published every year by India's Comptroller & Auditor General — covering Union, State, and Local Body governments. Each one documents how public money was spent, misused, or lost."
                    />
                    <ProblemPoint
                        stat="200–400"
                        text="pages per report. Dense paragraphs, nested financial tables, audit jargon, cross-references. Designed for auditors, not citizens."
                    />
                    <ProblemPoint
                        stat="~0"
                        text="tools that let a journalist, researcher, or ordinary citizen search these reports, ask questions, or compare findings across years. The information is technically public — but practically inaccessible."
                    />
                </div>

                <CalloutBox type="note">
                    <strong>Why this matters:</strong> The CAG is a constitutional body (Articles 148–151 of the Indian Constitution)
                    whose mandate is to audit every rupee of government spending. These audit reports are the primary mechanism for
                    government financial accountability in the world's largest democracy. When citizens can't access them,
                    the accountability chain breaks at the last mile.
                </CalloutBox>
            </DocSection>

            {/* ══════════════════════════════════════════════
                THE SOLUTION
            ══════════════════════════════════════════════ */}
            <DocSection
                title="The Solution"
                description="CAG Gateway uses AI to turn inaccessible audit PDFs into a searchable, conversational knowledge base — with every answer traceable back to the original document."
            >
                <div style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginTop: '12px',
                }}>
                    <div style={{
                        padding: '18px 20px', background: '#f0fdf4',
                        border: '1px solid #bbf7d0', borderRadius: '10px',
                    }}>
                        <div style={{ fontSize: '14px', fontWeight: 700, color: '#166534', marginBottom: '8px' }}>Ask questions in plain language</div>
                        <div style={{ fontSize: '13px', color: '#15803d', lineHeight: 1.6 }}>
                            "What were the major financial irregularities in railway procurement?" — and get a real answer,
                            drawn from the actual audit report, with source citations you can click to verify.
                        </div>
                    </div>
                    <div style={{
                        padding: '18px 20px', background: '#f0fdf4',
                        border: '1px solid #bbf7d0', borderRadius: '10px',
                    }}>
                        <div style={{ fontSize: '14px', fontWeight: 700, color: '#166534', marginBottom: '8px' }}>Every answer is verifiable</div>
                        <div style={{ fontSize: '13px', color: '#15803d', lineHeight: 1.6 }}>
                            The original PDF sits alongside every AI response. Click a citation and the document scrolls
                            to the exact page. The source of truth and the intelligence to understand it — side by side.
                        </div>
                    </div>
                    <div style={{
                        padding: '18px 20px', background: '#f0fdf4',
                        border: '1px solid #bbf7d0', borderRadius: '10px',
                    }}>
                        <div style={{ fontSize: '14px', fontWeight: 700, color: '#166534', marginBottom: '8px' }}>Structured intelligence from unstructured PDFs</div>
                        <div style={{ fontSize: '13px', color: '#15803d', lineHeight: 1.6 }}>
                            Findings automatically classified by type and severity. Tables extracted and made interactive.
                            Summaries generated for five different audiences. What took hours of reading now takes seconds.
                        </div>
                    </div>
                    <div style={{
                        padding: '18px 20px', background: '#f0fdf4',
                        border: '1px solid #bbf7d0', borderRadius: '10px',
                    }}>
                        <div style={{ fontSize: '14px', fontWeight: 700, color: '#166534', marginBottom: '8px' }}>All three tiers of Indian government</div>
                        <div style={{ fontSize: '13px', color: '#15803d', lineHeight: 1.6 }}>
                            Union (central government), State (28 states), and Local Bodies (districts and municipalities).
                            The same pipeline processes all tiers with zero code changes — validated at 92–96% accuracy on unseen reports.
                        </div>
                    </div>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                FOUR QUERY PATHS
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Four Ways to Query"
                description="Different query paths optimized for different use cases — from focused single-report questions to complex cross-corpus research."
            >
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginTop: '12px' }}>
                    <CapabilityCard
                        title="Directory Chat"
                        description="Ask questions about a single report. The PDF sits alongside the chat, and citations link directly to source pages. Best for deep-diving into a specific audit."
                        accent="#3b82f6"
                    />
                    <CapabilityCard
                        title="Time Series"
                        description="Compare findings across multiple years of the same audit type. Track trends, identify recurring issues, and see how ministry performance changes over time."
                        accent="#8b5cf6"
                    />
                    <CapabilityCard
                        title="Home Page Chat"
                        description="Open-ended questions across the entire corpus. Auto-filtering detects years, states, and topics from your query to narrow results automatically."
                        accent="#10b981"
                    />
                    <CapabilityCard
                        title="Agentic Mode"
                        description="Complex multi-hop questions get decomposed into sub-queries. The system retrieves iteratively, reformulating when needed, then synthesizes a unified answer."
                        accent="#f59e0b"
                    />
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                IMPACT NUMBERS
            ══════════════════════════════════════════════ */}
            <DocSection title="Current Scale">
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                    gap: '14px', marginTop: '14px',
                }}>
                    <ImpactStat value="37" label="Reports Indexed" sublabel="19 Union · 12 State · 6 Local Body" />
                    <ImpactStat value="390" label="Canonical Entities" sublabel="Ministries · PSUs · Schemes" accent="#0ea5e9" />
                    <ImpactStat value="25k" label="Entity Mentions" sublabel="Cross-report links indexed" accent="#8b5cf6" />
                    <ImpactStat value="185" label="AI Summaries" sublabel="5 variants × 37 reports" accent="#7c3aed" />
                    <ImpactStat value="3" label="Government Tiers" sublabel="Union · State · Local Bodies" accent="#059669" />
                    <ImpactStat value="1,297" label="Target Scale" sublabel="Full CAG corpus" accent="#64748b" />
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                ARCHITECTURE
            ══════════════════════════════════════════════ */}
            <DocSection
                title="System Architecture"
                description="Two pipelines: offline document processing (runs once per report) and online query serving (runs per user question)."
            >
                <DiagramCard title="End-to-End Data Flow">
                    <MermaidDiagram
                        chart={architectureDiagram}
                        caption="Reports are parsed through a 10-phase pipeline, semantically enriched, and indexed into a hybrid vector database with entity graph. User queries go through enhancement, hybrid search (with optional agentic decomposition), neural reranking, LLM generation with groundedness verification, and streaming response with citations."
                    />
                </DiagramCard>

                <CalloutBox type="info" style={{ marginTop: '16px' }}>
                    <strong>Design principle:</strong> The core parsing pipeline is purely algorithmic — zero API cost.
                    AI models are used only where they add irreplaceable value: overview extraction, summary generation,
                    entity canonicalization, query enhancement, answer generation, and groundedness verification.
                </CalloutBox>
            </DocSection>

            {/* ══════════════════════════════════════════════
                KEY CAPABILITIES
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Key Capabilities"
                description="Production features beyond basic RAG — built for reliability and accuracy at scale."
            >
                <div style={{ display: 'grid', gap: '12px', marginTop: '12px' }}>
                    <CapabilityCard
                        title="Hybrid + Hierarchical Search"
                        description="Dense vector embeddings + BM25 sparse vectors with CAG-specific pattern boosting. RAPTOR-style hierarchical retrieval for multi-level context. Query routing directs simple vs. complex queries to appropriate paths."
                        accent="#3b82f6"
                    />
                    <CapabilityCard
                        title="Agentic Retrieval"
                        description="Complex queries are decomposed into sub-queries with Self-RAG (iterative sufficiency checks) and Corrective RAG (failure detection). Reformulates and retries up to 3x per sub-query. Simple queries short-circuit to the standard path."
                        accent="#f59e0b"
                    />
                    <CapabilityCard
                        title="Entity Graph"
                        description="390 canonical entities (ministries, PSUs, schemes) with 25k mentions across reports. Enables cross-report entity reasoning — find all NHAI findings even when the name varies across years."
                        accent="#0ea5e9"
                    />
                    <CapabilityCard
                        title="Groundedness Verification"
                        description="Every LLM answer is verified claim-by-claim against retrieved context. Per-claim grounding scores help identify potential hallucinations. Fail-open design: verification errors don't block answers."
                        accent="#22c55e"
                    />
                    <CapabilityCard
                        title="Auto-filtering"
                        description="Queries mentioning years, states, or audit categories automatically get filtered without user intervention. Short ambiguous aliases (UP, MP, TN) require context confirmation to avoid false positives."
                        accent="#8b5cf6"
                    />
                    <CapabilityCard
                        title="Full Observability"
                        description="50-column query log captures every query with latency breakdown, retrieval stats, groundedness scores, and cost estimates. Dev mode includes full prompts for debugging."
                        accent="#64748b"
                    />
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                THREE TECHNICAL SECTIONS
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Deep Dive"
                description="The system is documented across three sections. Each one covers a different layer of the platform."
            >
                <div style={{ display: 'grid', gap: '14px', marginTop: '12px' }}>
                    <div style={{
                        padding: '20px 24px', background: '#fff',
                        border: '1px solid #e2e8f0', borderLeft: '4px solid #1a365d',
                        borderRadius: '0 10px 10px 0',
                    }}>
                        <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '6px' }}>Data Pipeline</div>
                        <div style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6 }}>
                            How raw PDF reports become structured, enriched data. 10 processing phases (with 2 sub-phases for TOC) covering ingestion,
                            OCR, 3-layer TOC validation, layout analysis, 3-tier table extraction strategy,
                            hierarchical chunking, semantic enrichment, and batch AI processing. <strong>Entity Graph pipeline:</strong> per-report
                            normalization → cross-corpus canonicalization → mention indexing with Aho-Corasick scanning.
                        </div>
                    </div>

                    <div style={{
                        padding: '20px 24px', background: '#fff',
                        border: '1px solid #e2e8f0', borderLeft: '4px solid #d946ef',
                        borderRadius: '0 10px 10px 0',
                    }}>
                        <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '6px' }}>RAG & Search</div>
                        <div style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6 }}>
                            How questions become answers. Hybrid retrieval combining dense vector search with
                            custom BM25 built for audit documents. <strong>SOTA features:</strong> Hierarchical (RAPTOR) retrieval,
                            Query Routing, Self-RAG, Corrective RAG. Cohere neural reranking. <strong>Agentic path</strong> for complex multi-hop queries.
                            <strong> Groundedness verification</strong> for answer accuracy. End-to-end latency: 2–3s standard, 5–12s agentic.
                        </div>
                    </div>

                    <div style={{
                        padding: '20px 24px', background: '#fff',
                        border: '1px solid #e2e8f0', borderLeft: '4px solid #f59e0b',
                        borderRadius: '0 10px 10px 0',
                    }}>
                        <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '6px' }}>AI Features</div>
                        <div style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6 }}>
                            GCP-native AI with Gemini 3.5 Flash as primary model and Vertex AI embeddings.
                            Claude/GPT-4 as optional batch providers. 6 response styles. <strong>Agentic retrieval</strong> with query decomposition and iterative refinement.
                            <strong> Entity graph</strong> for cross-report reasoning. <strong>Groundedness verification</strong> for
                            hallucination detection. Auto-filtering and full query observability.
                        </div>
                    </div>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                TECH STACK (compact)
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Technology Stack"
            >
                <div style={{ display: 'grid', gap: '12px', marginTop: '12px' }}>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', width: '100px' }}>Backend</span>
                        <TechBadge name="Python 3.11+" category="language" />
                        <TechBadge name="FastAPI" category="backend" />
                        <TechBadge name="Pydantic" category="backend" />
                        <TechBadge name="SQLAlchemy" category="backend" />
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', width: '100px' }}>Frontend</span>
                        <TechBadge name="React" category="frontend" />
                        <TechBadge name="TypeScript" category="frontend" />
                        <TechBadge name="Vite" category="frontend" />
                        <TechBadge name="Zustand" category="frontend" />
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', width: '100px' }}>AI / LLM</span>
                        <TechBadge name="Gemini 3.5 Flash" category="ai" />
                        <TechBadge name="Vertex AI Embeddings" category="ai" />
                        <TechBadge name="Claude (Batch)" category="ai" />
                        <TechBadge name="Cohere Rerank" category="ai" />
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', width: '100px' }}>Databases</span>
                        <TechBadge name="Qdrant" category="database" />
                        <TechBadge name="PostgreSQL" category="database" />
                        <TechBadge name="Custom BM25" category="database" />
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', width: '100px' }}>Parsing</span>
                        <TechBadge name="Docling (IBM)" category="parsing" />
                        <TechBadge name="pdfplumber" category="parsing" />
                        <TechBadge name="Tesseract OCR" category="parsing" />
                        <TechBadge name="PyMuPDF" category="parsing" />
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', width: '100px' }}>Infrastructure</span>
                        <TechBadge name="GCP Cloud Run" category="infrastructure" />
                        <TechBadge name="Cloud Storage" category="infrastructure" />
                        <TechBadge name="Docker" category="infrastructure" />
                        <TechBadge name="Terraform" category="infrastructure" />
                    </div>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                MISSION + DISCLAIMER
            ══════════════════════════════════════════════ */}
            <DocSection title="About This Project">
                <div style={{
                    padding: '20px 24px', background: '#f8fafc',
                    border: '1px solid #e2e8f0', borderRadius: '10px',
                    marginTop: '12px',
                }}>
                    <p style={{ fontSize: '14px', color: '#334155', lineHeight: 1.7, marginBottom: '14px' }}>
                        CAG Gateway is an independent civic technology project built by a single developer. It is not affiliated
                        with the Comptroller & Auditor General of India or any government body. The platform processes publicly
                        available government documents under Section 52(1)(q) of the Indian Copyright Act, 1957.
                    </p>
                    <p style={{ fontSize: '14px', color: '#334155', lineHeight: 1.7, marginBottom: '14px' }}>
                        The mission is straightforward: use AI to make government accountability information accessible to everyone —
                        journalists, researchers, RTI activists, and ordinary citizens. Not behind a paywall. Not for specialists.
                        For everyone.
                    </p>
                    <p style={{ fontSize: '14px', color: '#334155', lineHeight: 1.7, margin: 0 }}>
                        India's CAG audits the spending of 1.4 billion people's tax money. The findings should be as easy to access
                        as the headlines they sometimes become — but rarely are. That's the gap this project exists to close.
                    </p>
                </div>
            </DocSection>
        </div>
    );
};
