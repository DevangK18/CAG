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

/* ─── main component ─── */

export const Overview: React.FC = () => {

    const architectureDiagram = `
graph TB
    subgraph "Offline · Document Processing"
        PDF[PDF Reports<br/>Native + Scanned] --> Parse[12-Phase Pipeline<br/>OCR · Tables · Structure]
        Parse --> Enrich[Semantic Enrichment<br/>Findings · Entities · Severity]
        Enrich --> Index[Hybrid Indexing<br/>Dense + BM25 Sparse]
        Index --> Qdrant[(Qdrant Vector DB<br/>15,000+ chunks)]
        Parse --> Batch[Batch AI Processing<br/>Overviews · Summaries]
        Batch --> Store[(Processed JSON<br/>per report)]
    end

    subgraph "Online · User Query"
        User[User Question] --> QE[Query Enhancement<br/>Expansion + Filters]
        QE --> Hybrid[Hybrid Search<br/>Vector + BM25 + RRF]
        Hybrid --> Qdrant
        Qdrant --> Rerank[Cohere Reranking<br/>+ Context Assembly]
        Rerank --> LLM[LLM Generation<br/>with Source Citations]
        LLM --> Stream[Streaming Response<br/>+ Clickable Citations]
    end

    style PDF fill:#fef3c7,stroke:#f59e0b
    style Qdrant fill:#dcfce7,stroke:#22c55e
    style LLM fill:#fae8ff,stroke:#d946ef
    style User fill:#e0e7ff,stroke:#6366f1
    style Stream fill:#e0e7ff,stroke:#6366f1
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
                IMPACT NUMBERS
            ══════════════════════════════════════════════ */}
            <DocSection title="Current Coverage">
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                    gap: '14px', marginTop: '14px',
                }}>
                    <ImpactStat value="28" label="Reports Indexed" sublabel="19 Union · 5 State · 4 Local Body" />
                    <ImpactStat value="1,022+" label="Findings Extracted" sublabel="Classified by type and severity" accent="#dc2626" />
                    <ImpactStat value="20,000+" label="Table Cells" sublabel="Freed from PDF and made searchable" accent="#f59e0b" />
                    <ImpactStat value="140" label="AI Summaries" sublabel="5 variants × 28 reports" accent="#7c3aed" />
                    <ImpactStat value="3" label="Government Tiers" sublabel="Union · State · Local Bodies" accent="#059669" />
                    <ImpactStat value="$0.39" label="Indexing Cost" sublabel="Total for all 28 reports" accent="#0284c7" />
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
                        caption="Reports are parsed through a 12-phase pipeline, semantically enriched, and indexed into a hybrid vector database. User queries go through expansion, hybrid search (dense + sparse), neural reranking, and LLM generation with source citations streamed back in real time."
                    />
                </DiagramCard>

                <CalloutBox type="info" style={{ marginTop: '16px' }}>
                    <strong>Design principle:</strong> The core parsing pipeline (Phases 1_9) is purely algorithmic — zero API cost.
                    AI models are used only where they add irreplaceable value: overview extraction, summary generation, 
                    and real-time query answering. This keeps the system sustainable on minimal resources.
                </CalloutBox>
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
                            How raw PDF reports become structured, enriched data. 12 processing phases covering ingestion, 
                            OCR, layout analysis, table extraction (3-tier strategy for native and scanned PDFs), 
                            document structuring, semantic enrichment (15+ finding types, entity extraction, monetary normalization), 
                            and batch AI processing for overviews and summaries. Cost: ~$1.10–1.80 per report.
                        </div>
                    </div>

                    <div style={{
                        padding: '20px 24px', background: '#fff',
                        border: '1px solid #e2e8f0', borderLeft: '4px solid #d946ef',
                        borderRadius: '0 10px 10px 0',
                    }}>
                        <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '6px' }}>RAG & Search</div>
                        <div style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6 }}>
                            How questions become answers. Hybrid retrieval combining dense vector search (OpenAI embeddings) 
                            with a custom BM25 implementation built for audit documents — understanding section references like 
                            "Para 2.3.1" and monetary amounts in "₹ crore" format. Reciprocal Rank Fusion, Cohere neural reranking, 
                            parent-child chunk expansion, and LLM generation with inline source citations. End-to-end latency: 2–3 seconds. 
                            Cost: ~$0.003–0.007 per query.
                        </div>
                    </div>

                    <div style={{
                        padding: '20px 24px', background: '#fff',
                        border: '1px solid #e2e8f0', borderLeft: '4px solid #f59e0b',
                        borderRadius: '0 10px 10px 0',
                    }}>
                        <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '6px' }}>AI Features</div>
                        <div style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6 }}>
                            6 AI models orchestrated across offline and real-time workloads. Claude Opus for deep analysis, 
                            Claude Sonnet for RAG generation and summaries, Claude Haiku for structured extraction, 
                            Gemini Flash for visual extraction, GPT-4o-mini for commodity tasks and query enhancement, 
                            OpenAI embeddings for vector search. 8 response styles for different user needs. 
                            Anti-hallucination safeguards at every layer. Total corpus setup cost: under $30.
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
                        <TechBadge name="Claude (Opus/Sonnet/Haiku)" category="ai" />
                        <TechBadge name="GPT-4o-mini" category="ai" />
                        <TechBadge name="Gemini 2.5 Flash" category="ai" />
                        <TechBadge name="OpenAI Embeddings" category="ai" />
                        <TechBadge name="Cohere Rerank" category="ai" />
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', width: '100px' }}>Search</span>
                        <TechBadge name="Qdrant Cloud" category="database" />
                        <TechBadge name="Custom BM25" category="database" />
                        <TechBadge name="RRF Fusion" category="database" />
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
                        <TechBadge name="Docker" category="infrastructure" />
                        <TechBadge name="Hetzner Cloud" category="infrastructure" />
                        <TechBadge name="Caddy" category="infrastructure" />
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