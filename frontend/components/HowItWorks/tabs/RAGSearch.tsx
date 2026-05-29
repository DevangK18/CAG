import React from 'react';
import { DocSection } from '../shared/DocSection';
import { DiagramCard } from '../shared/DiagramCard';
import { CalloutBox } from '../shared/CalloutBox';
import { CodeBlock } from '../shared/CodeBlock';
import { MermaidDiagram } from '../shared/MermaidDiagram';

/* ─── inline helper components (local to this page) ─── */

const Stat: React.FC<{ value: string; label: string; accent?: string }> = ({
    value,
    label,
    accent = '#1a365d',
}) => (
    <div className="stat-card">
        <div className="stat-value" style={{ color: accent }}>{value}</div>
        <div className="stat-label">{label}</div>
    </div>
);

const StageLabel: React.FC<{ number: string; title: string; color?: string }> = ({
    number,
    title,
    color = '#1a365d',
}) => (
    <div style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '10px',
        marginBottom: '12px',
    }}>
        <span style={{
            background: color,
            color: '#fff',
            fontSize: '12px',
            fontWeight: 700,
            padding: '3px 10px',
            borderRadius: '4px',
            letterSpacing: '0.04em',
            whiteSpace: 'nowrap',
        }}>
            STAGE {number}
        </span>
        <span style={{ fontSize: '15px', fontWeight: 600, color: '#334155' }}>{title}</span>
    </div>
);

const InlineStat: React.FC<{ value: string; label?: string }> = ({ value, label }) => (
    <span style={{
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: '4px',
        background: '#eff6ff',
        border: '1px solid #bfdbfe',
        padding: '2px 8px',
        borderRadius: '4px',
        fontSize: '13px',
        fontWeight: 600,
        color: '#1d4ed8',
        whiteSpace: 'nowrap',
    }}>
        {value}{label && <span style={{ fontWeight: 400, color: '#1a365d' }}> {label}</span>}
    </span>
);

const ProblemSolution: React.FC<{
    problem: string;
    solution: string;
    detail?: string;
}> = ({ problem, solution, detail }) => (
    <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '0',
        border: '1px solid #e2e8f0',
        borderRadius: '10px',
        overflow: 'hidden',
        margin: '14px 0',
    }}>
        <div style={{
            padding: '16px 20px',
            background: '#fef2f2',
            borderRight: '1px solid #e2e8f0',
        }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#dc2626', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>Problem</div>
            <div style={{ fontSize: '14px', lineHeight: 1.6, color: '#991b1b' }}>{problem}</div>
        </div>
        <div style={{ padding: '16px 20px', background: '#f0fdf4' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#16a34a', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>Solution</div>
            <div style={{ fontSize: '14px', lineHeight: 1.6, color: '#166534' }}>{solution}</div>
            {detail && <div style={{ fontSize: '13px', lineHeight: 1.5, color: '#4ade80', marginTop: '6px', fontStyle: 'italic' }}>{detail}</div>}
        </div>
    </div>
);

const DecisionCard: React.FC<{
    question: string;
    answer: string;
    tradeoff?: string;
}> = ({ question, answer, tradeoff }) => (
    <div style={{
        padding: '16px 20px',
        background: '#fefce8',
        border: '1px solid #fde68a',
        borderLeft: '4px solid #f59e0b',
        borderRadius: '0 8px 8px 0',
        margin: '14px 0',
    }}>
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#92400e', marginBottom: '6px' }}>{question}</div>
        <div style={{ fontSize: '14px', color: '#78350f', lineHeight: 1.6 }}>{answer}</div>
        {tradeoff && <div style={{ fontSize: '13px', color: '#a16207', marginTop: '8px', fontStyle: 'italic', lineHeight: 1.5 }}>Tradeoff: {tradeoff}</div>}
    </div>
);

const LatencyBar: React.FC<{
    label: string;
    time: string;
    widthPercent: number;
    color: string;
}> = ({ label, time, widthPercent, color }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
        <div style={{ width: '200px', fontSize: '13px', color: '#475569', textAlign: 'right', flexShrink: 0 }}>{label}</div>
        <div style={{ flex: 1, background: '#f1f5f9', borderRadius: '4px', height: '24px', position: 'relative', overflow: 'hidden' }}>
            <div style={{
                width: `${widthPercent}%`,
                height: '100%',
                background: color,
                borderRadius: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                paddingRight: '8px',
            }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#fff' }}>{time}</span>
            </div>
        </div>
    </div>
);

const ResponseStyleCard: React.FC<{
    name: string;
    audience: string;
    wordRange: string;
    color: string;
}> = ({ name, audience, wordRange, color }) => (
    <div style={{
        padding: '12px 16px',
        background: '#ffffff',
        border: '1px solid #e2e8f0',
        borderLeft: `4px solid ${color}`,
        borderRadius: '0 8px 8px 0',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
    }}>
        <div>
            <span style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>{name}</span>
            <span style={{ fontSize: '13px', color: '#64748b', marginLeft: '10px' }}>{audience}</span>
        </div>
        <span style={{ fontSize: '12px', color: '#64748b', background: '#f1f5f9', padding: '2px 8px', borderRadius: '4px', whiteSpace: 'nowrap' }}>{wordRange}</span>
    </div>
);

const PathCard: React.FC<{
    title: string;
    subtitle: string;
    latency: string;
    cost: string;
    color: string;
    bgColor: string;
    borderColor: string;
    children: React.ReactNode;
}> = ({ title, subtitle, latency, cost, color, bgColor, borderColor, children }) => (
    <div style={{ padding: '20px', background: bgColor, border: `1px solid ${borderColor}`, borderRadius: '10px' }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>{subtitle}</div>
        <div style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '10px' }}>{title}</div>
        <div style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6, marginBottom: '12px' }}>{children}</div>
        <div style={{ display: 'flex', gap: '16px', fontSize: '13px' }}>
            <div><span style={{ fontWeight: 700, color }}>Latency:</span> <span style={{ color: '#475569' }}>{latency}</span></div>
            <div><span style={{ fontWeight: 700, color }}>Cost:</span> <span style={{ color: '#475569' }}>{cost}</span></div>
        </div>
    </div>
);

/* ─── main component ─── */

export const RAGSearch: React.FC = () => {

    const architectureDiagram = `
graph TB
    subgraph "Offline: Indexing Pipeline"
        A[JSON Files<br/>from Parsing] --> B[EmbeddingService]
        B --> C1[Dense Vectors<br/>OpenAI 1536-dim]
        B --> C2[Sparse Vectors<br/>Custom BM25]
        B --> C3[Table Summaries<br/>GPT-4o-mini]
        B --> C4[Semantic Payloads<br/>Findings · Severity]
        C1 --> D[(Qdrant)]
        C2 --> D
        C3 --> D
        C4 --> D
    end

    subgraph "Online: Query Pipeline"
        E[User Question] --> QE[Query Enhancement<br/>Expansion + Classification]
        QE --> AF[Auto-filter<br/>Year · State · Tier]
        AF --> Router{Complexity<br/>Check}
        Router -->|simple| H
        Router -->|multi-hop| AG[Agentic Loop]
        AG --> H[Hybrid Search<br/>RRF Fusion]
        D --> H
        H --> I[Reranking<br/>Cohere / BGE]
        I --> J[O1 Neighbor<br/>Expansion]
        J --> SC[Sufficiency Check<br/>+ Passage Reorder]
        SC --> K[Parent Grouping<br/>+ Context Assembly]
        L[ReportRegistry] --> K
        K --> TC[Tier Context<br/>Injection]
        TC --> M[LLM Generation<br/>Claude / GPT-4]
        M --> GND[Groundedness<br/>Verification]
        GND --> N[RAGResponse<br/>Answer + Citations]
    end

    style D fill:#e1f5ff,stroke:#0ea5e9
    style N fill:#dcfce7,stroke:#22c55e
    style H fill:#fef3c7,stroke:#f59e0b
    style I fill:#fae8ff,stroke:#d946ef
    style AG fill:#fff7ed,stroke:#ea580c
    style GND fill:#f0fdf4,stroke:#22c55e
    style QE fill:#eff6ff,stroke:#3b82f6
    style AF fill:#fdf4ff,stroke:#a855f7
`;

    const agenticDiagram = `
graph TB
    Q[User Question] --> PL[Planner<br/>gpt-4o-mini]
    PL -->|simple| SC[Short-Circuit<br/>to Standard Path]
    PL -->|multi-hop| DQ[Decompose into<br/>2-4 Sub-queries]

    DQ --> SQ1[Sub-query 1]
    DQ --> SQ2[Sub-query 2]
    DQ --> SQN[Sub-query N]

    subgraph "Per Sub-query Loop (max 3 iterations)"
        SQ1 --> AF1[Auto-filter]
        AF1 --> RET1[Retrieve]
        RET1 --> SUF1{Sufficient?}
        SUF1 -->|no| REF1[Reformulate]
        REF1 --> RET1
        SUF1 -->|yes| RES1[Results]
    end

    SQ2 --> RES2[Results]
    SQN --> RESN[Results]

    RES1 --> MRG[Merge Results<br/>Dedupe · Score]
    RES2 --> MRG
    RESN --> MRG

    MRG --> SYN[Synthesize Answer<br/>with Citations]
    SYN --> GND[Groundedness<br/>Check]
    GND --> RESP[Final Response]

    style PL fill:#fef3c7,stroke:#f59e0b
    style SC fill:#dcfce7,stroke:#22c55e
    style MRG fill:#e0f2fe,stroke:#0ea5e9
    style GND fill:#f0fdf4,stroke:#22c55e
`;

    const hybridSearchDiagram = `
graph LR
    Q[Query] --> DE[Dense Embedding<br/>1536-dim]
    Q --> SE[Sparse Encoding<br/>BM25 + Boosts]

    DE --> DS[Dense Search<br/>Top 50]
    SE --> SS[Sparse Search<br/>Top 50]

    DS --> RRF[RRF Fusion<br/>k=60]
    SS --> RRF

    RRF --> RR[Reranking<br/>Top 10]
    RR --> NE[Neighbor<br/>Expansion ±1]
    NE --> PG[Parent<br/>Grouping]

    style Q fill:#e0e7ff,stroke:#6366f1
    style DS fill:#dcfce7,stroke:#22c55e
    style SS fill:#fef3c7,stroke:#f59e0b
    style RRF fill:#fee2e2,stroke:#ef4444
    style RR fill:#fae8ff,stroke:#d946ef
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">RAG & Search</h1>
            <p className="page-subtitle">
                A hybrid search pipeline with agentic retrieval for complex queries, groundedness verification for accuracy,
                and auto-filtering for intelligent query interpretation. Two query paths — standard (2-3s) and agentic (5-12s).
            </p>

            {/* ── Hero Stats ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '14px', margin: '0 0 56px 0' }}>
                <Stat value="15,669" label="Chunks Indexed" />
                <Stat value="2,792" label="Parent Sections" accent="#7c3aed" />
                <Stat value="2-3s" label="Standard Latency" accent="#059669" />
                <Stat value="5-12s" label="Agentic Latency" accent="#f59e0b" />
                <Stat value="6" label="Response Styles" accent="#dc2626" />
                <Stat value="$0.005" label="Avg Query Cost" accent="#0ea5e9" />
            </div>

            {/* ══════════════════════════════════════════════
                SECTION 1: Two Query Paths
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Two Query Paths"
                description="Simple questions take the standard path (~70-80% of queries). Complex multi-hop questions get decomposed and processed through the agentic loop."
            >
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '16px',
                    marginBottom: '20px',
                }}>
                    <PathCard
                        title="Standard Path"
                        subtitle="Simple Queries"
                        latency="~2-3s"
                        cost="~$0.004-0.009"
                        color="#15803d"
                        bgColor="#f0fdf4"
                        borderColor="#bbf7d0"
                    >
                        Query enhancement → hybrid search → reranking → neighbor expansion →
                        context assembly → LLM generation → groundedness verification.
                        Handles factual questions, list queries, and single-report analysis.
                    </PathCard>

                    <PathCard
                        title="Agentic Path"
                        subtitle="Multi-hop Queries"
                        latency="~5-12s"
                        cost="~$0.01-0.03"
                        color="#ea580c"
                        bgColor="#fff7ed"
                        borderColor="#fed7aa"
                    >
                        Planner decomposes query into 2-4 sub-queries. Each sub-query: retrieve →
                        check sufficiency → reformulate if needed (up to 3x). Merge results →
                        synthesize unified answer. For cross-report and comparative questions.
                    </PathCard>
                </div>

                <DiagramCard title="Full Query Pipeline">
                    <MermaidDiagram
                        chart={architectureDiagram}
                        caption="User questions flow through enhancement and auto-filtering before routing. Simple queries short-circuit to standard retrieval; complex queries enter the agentic loop. All paths end with groundedness verification."
                    />
                </DiagramCard>

                <CalloutBox type="info" style={{ marginTop: '16px' }}>
                    <strong>Composition over extension:</strong> The agentic path doesn't replace the standard path — it
                    wraps it. Each sub-query uses the same <code style={{ background: '#e2e8f0', padding: '2px 6px', borderRadius: '4px' }}>RetrievalService</code> as
                    standard queries. Simple queries (70-80% of traffic) see zero regression.
                </CalloutBox>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 2: Query Enhancement & Auto-filter
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Query Enhancement & Auto-filter"
                description="Before retrieval, the system enhances the query with LLM-powered expansion and extracts implicit filters from the query text."
            >
                {/* Query Enhancement */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="1" title="Query Enhancement" color="#3b82f6" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        A single LLM call (gpt-4o-mini) provides query intelligence before retrieval:
                    </p>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(3, 1fr)',
                        gap: '12px',
                        marginBottom: '16px',
                    }}>
                        {[
                            { title: 'Question Classification', desc: 'factual, list, aggregation, comparison, explanation', color: '#1a365d' },
                            { title: 'Query Expansion', desc: 'Original + 2 alternative phrasings for multi-query retrieval', color: '#059669' },
                            { title: 'Suggested Filters', desc: 'Inferred finding_type, severity, etc. from query intent', color: '#7c3aed' },
                        ].map(item => (
                            <div key={item.title} style={{
                                padding: '14px 16px', background: '#f8fafc',
                                border: '1px solid #e2e8f0', borderRadius: '8px',
                            }}>
                                <div style={{ fontSize: '14px', fontWeight: 700, color: item.color, marginBottom: '6px' }}>{item.title}</div>
                                <div style={{ fontSize: '13px', color: '#64748b', lineHeight: 1.5 }}>{item.desc}</div>
                            </div>
                        ))}
                    </div>

                    <CodeBlock title="Query Enhancement Example">
{`Input: "What went wrong with toll collection?"

Output:
  question_type: "explanation"
  expanded_queries: [
    "What went wrong with toll collection?",
    "toll revenue loss audit findings NHAI fee collection",
    "electronic toll collection ETC compliance shortfall"
  ]
  suggested_filters: {"finding_type": "loss_of_revenue"}
  top_k: 12
  recommended_style: "explanatory"`}
                    </CodeBlock>

                    <p style={{ lineHeight: 1.7, color: '#475569', marginTop: '14px' }}>
                        Cost: <InlineStat value="~$0.0002" label="per query" />. Latency: <InlineStat value="~100ms" />.
                        The expanded queries enable multi-query retrieval with RRF fusion — different phrasings
                        capture different relevant chunks.
                    </p>
                </div>

                {/* Auto-filter */}
                <div style={{ marginBottom: '8px' }}>
                    <StageLabel number="2" title="Auto-filter Extraction" color="#a855f7" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        When no explicit filters are set (home page chat, agentic sub-queries), the system extracts
                        implicit filters from query text using rule-based patterns — no LLM call required.
                    </p>

                    <div style={{
                        border: '1px solid #e2e8f0', borderRadius: '10px', overflow: 'hidden', marginBottom: '16px',
                    }}>
                        <div style={{
                            display: 'grid', gridTemplateColumns: '120px 1fr 1fr',
                            borderBottom: '2px solid #cbd5e1', fontSize: '12px', fontWeight: 700,
                            textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b',
                        }}>
                            <div style={{ padding: '10px 14px', background: '#f8fafc' }}>Filter Type</div>
                            <div style={{ padding: '10px 14px' }}>Detection Pattern</div>
                            <div style={{ padding: '10px 14px' }}>Example</div>
                        </div>
                        {[
                            { type: 'Years', pattern: '\\b(20\\d{2})\\b', example: '"findings from 2023" → audit_year: 2023', color: '#1a365d' },
                            { type: 'States', pattern: 'Substring match against 28 states + 8 UTs', example: '"Gujarat audit" → state_name: "Gujarat"', color: '#059669' },
                            { type: 'Tiers', pattern: '"Central", "GoI", "panchayat", "ULB", "ATIR"', example: '"local body issues" → tier: local_body', color: '#7c3aed' },
                            { type: 'Categories', pattern: 'performance, compliance, financial, revenue', example: '"compliance failures" → audit_category: compliance', color: '#f59e0b' },
                        ].map(row => (
                            <div key={row.type} style={{
                                display: 'grid', gridTemplateColumns: '120px 1fr 1fr',
                                borderBottom: '1px solid #e2e8f0', fontSize: '14px',
                            }}>
                                <div style={{ padding: '10px 14px', fontWeight: 700, color: row.color, background: '#fafafa' }}>{row.type}</div>
                                <div style={{ padding: '10px 14px', color: '#475569', fontFamily: 'monospace', fontSize: '12px' }}>{row.pattern}</div>
                                <div style={{ padding: '10px 14px', color: '#475569', fontSize: '13px' }}>{row.example}</div>
                            </div>
                        ))}
                    </div>

                    <CalloutBox type="warning">
                        <strong>Short alias guard:</strong> Ambiguous 2-letter state codes (UP, MP, TN, HP, WB, JK) require
                        ≥2 occurrences OR explicit context cues to avoid false positives. "Audit process <strong>up</strong> to 2023"
                        won't silently filter to Uttar Pradesh.
                    </CalloutBox>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 3: Agentic Retrieval (Phase 11)
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Agentic Retrieval"
                description="Complex multi-hop queries are decomposed, retrieved iteratively, and synthesized into unified answers. Simple queries short-circuit to the standard path."
            >
                <DiagramCard title="Agentic Loop Architecture">
                    <MermaidDiagram
                        chart={agenticDiagram}
                        caption="The planner classifies complexity and decomposes multi-hop queries. Each sub-query runs through retrieval with sufficiency checks and optional reformulation. Results are merged and deduplicated before synthesis."
                    />
                </DiagramCard>

                <div style={{ marginTop: '24px', marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>How It Works</h3>

                    <div style={{ display: 'grid', gap: '12px', marginBottom: '16px' }}>
                        {[
                            { step: '1', title: 'Complexity Classification', desc: 'Planner LLM call classifies query as simple (factual, single-report) or multi-hop (comparative, cross-report, requires reasoning across sources).', color: '#1a365d' },
                            { step: '2', title: 'Query Decomposition', desc: 'Multi-hop queries are broken into 2-4 sub-queries. Each targets a specific aspect of the original question.', color: '#059669' },
                            { step: '3', title: 'Iterative Retrieval', desc: 'Each sub-query: retrieve → check sufficiency → reformulate if insufficient (up to 3 iterations). Auto-filter applies to each sub-query.', color: '#f59e0b' },
                            { step: '4', title: 'Result Merging', desc: 'All sub-query results are merged and deduplicated by chunk ID. Scores are preserved for ranking.', color: '#7c3aed' },
                            { step: '5', title: 'Synthesis', desc: 'Single LLM call generates unified answer with citations from all sub-queries. Groundedness verification runs on the final answer.', color: '#0ea5e9' },
                        ].map(item => (
                            <div key={item.step} style={{
                                display: 'grid', gridTemplateColumns: '40px 1fr',
                                gap: '14px', padding: '14px 18px',
                                background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '8px',
                            }}>
                                <div style={{
                                    width: '32px', height: '32px', borderRadius: '50%',
                                    background: item.color, color: '#fff',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    fontSize: '14px', fontWeight: 700,
                                }}>{item.step}</div>
                                <div>
                                    <div style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b', marginBottom: '4px' }}>{item.title}</div>
                                    <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.5 }}>{item.desc}</div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Hard Limits</h3>
                    <div style={{
                        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px',
                    }}>
                        {[
                            { value: '4', label: 'Max sub-queries', desc: 'From decomposition' },
                            { value: '3', label: 'Max iterations', desc: 'Per sub-query' },
                            { value: '30k', label: 'Token budget', desc: 'Total across all' },
                            { value: '20s', label: 'Wall-clock', desc: 'Hard timeout' },
                        ].map(item => (
                            <div key={item.label} style={{
                                padding: '16px', background: '#fff7ed',
                                border: '1px solid #fed7aa', borderRadius: '8px', textAlign: 'center',
                            }}>
                                <div style={{ fontSize: '24px', fontWeight: 800, color: '#ea580c' }}>{item.value}</div>
                                <div style={{ fontSize: '13px', fontWeight: 600, color: '#1e293b', marginTop: '4px' }}>{item.label}</div>
                                <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>{item.desc}</div>
                            </div>
                        ))}
                    </div>
                </div>

                <DecisionCard
                    question="Why is the planner hard-wired to OpenAI (gpt-4o-mini)?"
                    answer="The planner requires fast, reliable JSON output for complexity classification. gpt-4o-mini has the best cost/latency ratio for this narrow task. Even if your main LLM is Claude or Gemini, agentic mode requires OPENAI_API_KEY."
                    tradeoff="Dependency on OpenAI for agentic queries. Simple queries (70-80%) don't use the planner at all."
                />

                <CalloutBox type="success">
                    <strong>Endpoint:</strong> <code style={{ background: '#e2e8f0', padding: '2px 6px', borderRadius: '4px' }}>POST /api/chat/agentic/stream</code> —
                    SSE streaming with agentic-specific events (planning, sub_query, iteration, reformulation, synthesizing).
                </CalloutBox>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 4: Hybrid Search
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Hybrid Search & Retrieval"
                description="The core retrieval pipeline: dense + sparse vectors, RRF fusion, cross-encoder reranking, neighbor expansion, and passage reordering."
            >
                <DiagramCard title="Hybrid Search Pipeline">
                    <MermaidDiagram
                        chart={hybridSearchDiagram}
                        caption="The query is encoded into both dense and sparse vectors. Two independent searches are fused via RRF, reranked by a cross-encoder, expanded with neighbors, and grouped by parent section."
                    />
                </DiagramCard>

                {/* Why Hybrid */}
                <div style={{ marginTop: '24px', marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Why Hybrid Search?</h3>
                    <ProblemSolution
                        problem="Dense-only search misses exact pattern matches. A query for 'Section 143(3) violations' might return chunks about violations in general, not the specific statutory reference."
                        solution="BM25 sparse vectors ensure exact lexical matches rank high. The 3× boost on legal references like 'section_143' makes statutory queries precise."
                    />
                    <ProblemSolution
                        problem="Sparse-only search misses paraphrased queries. 'Revenue shortfall' and 'loss of revenue' are the same concept but share few keywords."
                        solution="Dense embeddings capture semantic similarity — both phrases map to nearby vectors. Hybrid search gets the best of both worlds."
                    />
                </div>

                {/* BM25 Boosts */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="1" title="CAG-Specific BM25 Boosts" color="#f59e0b" />
                    <div style={{
                        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '16px',
                    }}>
                        {[
                            { pattern: 'Legal References', examples: 'section_143, rule_86b, form_26as', boost: '3.0×', color: '#dc2626', bg: '#fef2f2', border: '#fecaca' },
                            { pattern: 'Entity Acronyms', examples: 'acronym_NHAI, acronym_PMJAY', boost: '2.5×', color: '#7c3aed', bg: '#faf5ff', border: '#e9d5ff' },
                            { pattern: 'State/Local Terms', examples: 'state_exchequer, gram_panchayat', boost: '2.0×', color: '#059669', bg: '#f0fdf4', border: '#bbf7d0' },
                            { pattern: 'Monetary / Temporal', examples: 'money_crore, year_2023-24', boost: '1.5×', color: '#0369a1', bg: '#f0f9ff', border: '#bae6fd' },
                        ].map((item) => (
                            <div key={item.pattern} style={{
                                padding: '14px 16px', background: item.bg,
                                border: `1px solid ${item.border}`, borderRadius: '8px',
                            }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                                    <span style={{ fontSize: '13px', fontWeight: 700, color: '#1e293b' }}>{item.pattern}</span>
                                    <span style={{ fontSize: '13px', fontWeight: 700, color: item.color }}>{item.boost}</span>
                                </div>
                                <div style={{ fontSize: '11px', color: '#64748b', fontFamily: 'monospace' }}>{item.examples}</div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Reranking */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="2" title="Cross-Encoder Reranking" color="#d946ef" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Initial search (top 50) optimizes for <strong>recall</strong>. Reranking (to top 10) optimizes for <strong>precision</strong>.
                        Cross-encoders see the full query-document pair jointly, giving stronger relevance judgment than bi-encoder similarity.
                    </p>

                    <div style={{
                        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '14px',
                    }}>
                        <div style={{ padding: '16px 20px', background: '#faf5ff', border: '1px solid #e9d5ff', borderRadius: '8px' }}>
                            <div style={{ fontSize: '14px', fontWeight: 700, color: '#6b21a8', marginBottom: '6px' }}>Cohere (Primary)</div>
                            <div style={{ fontSize: '13px', color: '#581c87', lineHeight: 1.6 }}>
                                Model: <code style={{ fontSize: '12px' }}>rerank-english-v3.0</code><br />
                                ~8-12% better precision@10 on CAG benchmarks.
                            </div>
                        </div>
                        <div style={{ padding: '16px 20px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px' }}>
                            <div style={{ fontSize: '14px', fontWeight: 700, color: '#475569', marginBottom: '6px' }}>BGE (Fallback)</div>
                            <div style={{ fontSize: '13px', color: '#64748b', lineHeight: 1.6 }}>
                                Model: <code style={{ fontSize: '12px' }}>BAAI/bge-reranker-v2-m3</code><br />
                                Local, zero API cost. Within ~5% of Cohere.
                            </div>
                        </div>
                    </div>
                </div>

                {/* Neighbor Expansion + Passage Reordering */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="3" title="Neighbor Expansion + Passage Reordering" color="#059669" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        <strong>O(1) Neighbor Lookup:</strong> Deterministic chunk ID format enables direct ID prediction for ±1 neighbors.
                        <InlineStat value="~20ms" label="for 10 chunks" /> vs ~2,000ms with vector search.
                    </p>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        <strong>Lost-in-the-Middle Mitigation:</strong> LLMs attend most to content at the beginning and end of context.
                        Passage reordering interleaves parents by relevance score: best → worst → second-best → second-worst.
                        This places the most relevant content at attention-optimal positions.
                    </p>
                </div>

                {/* Context Sufficiency */}
                <div style={{ marginBottom: '8px' }}>
                    <StageLabel number="4" title="Context Sufficiency Check" color="#0284c7" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Before generation, the system checks if the top reranker score exceeds <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>min_rerank_score</code> (default: 0.25).
                        <strong> Tier-adjusted threshold:</strong> State/Local Body reports use a 30% lower threshold (0.175) because the Cohere reranker
                        was calibrated for Union report vocabulary.
                    </p>
                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        If context is insufficient, a caveat is prepended to the answer:
                        <em style={{ color: '#b45309' }}> "The available reports may not contain specific information to fully answer this question."</em>
                    </p>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 5: Groundedness Verification (Phase 13)
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Groundedness Verification"
                description="Post-generation LLM call verifies each factual claim against retrieved context. Catches hallucinations without blocking the response."
            >
                <div style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '20px',
                }}>
                    <div style={{ padding: '20px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#166534', marginBottom: '12px' }}>How It Works</h3>
                        <ol style={{ paddingLeft: '20px', margin: 0, lineHeight: 1.8, color: '#15803d', fontSize: '14px' }}>
                            <li>After LLM generates answer, extract factual claims</li>
                            <li>For each claim, verify against retrieved context</li>
                            <li>Return per-claim grounding score + confidence</li>
                            <li>Calculate overall grounded/ungrounded ratio</li>
                            <li>Stream as final event before "done"</li>
                        </ol>
                    </div>
                    <div style={{ padding: '20px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Key Properties</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['Model', 'gpt-4o-mini'],
                                ['Cost', '~$0.0005/query'],
                                ['Latency', '+200-400ms (thread-pooled)'],
                                ['Fail mode', 'Fail-open (errors don\'t block)'],
                            ].map(([key, val]) => (
                                <div key={key} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#64748b' }}>{key}</span>
                                    <span style={{ fontWeight: 600, color: '#1e293b' }}>{val}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                <CodeBlock title="Groundedness Response Schema">
{`{
  "verified": true,
  "overall_score": 0.85,
  "num_claims": 7,
  "num_grounded": 6,
  "num_ungrounded": 1,
  "claims": [
    {
      "claim_text": "₹124.18 crore loss at Nathavalasa toll plaza",
      "cited_source": "Section 3.2.1, p.36",
      "grounded": true,
      "confidence": 0.95,
      "reason": "Exact figure appears in cited source"
    },
    {
      "claim_text": "ETC equipment was non-functional for 18 months",
      "cited_source": "Section 3.2.1, p.37",
      "grounded": false,
      "confidence": 0.70,
      "reason": "Context mentions 'extended period' but not specific duration"
    }
  ]
}`}
                </CodeBlock>

                <CalloutBox type="note" style={{ marginTop: '16px' }}>
                    <strong>Design decision:</strong> Groundedness runs in a thread pool and doesn't block token streaming.
                    Users see the answer stream in real-time, and the groundedness report arrives as the final event.
                    If verification errors, the answer still ships — we log the error for observability but don't degrade UX.
                </CalloutBox>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 6: Generation & Response Styles
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Generation & Response Styles"
                description="Style-adaptive generation with tier-aware context injection and strict citation rules."
            >
                {/* Tier Context Injection */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Tier Context Injection</h3>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        State and Local Body reports use different administrative vocabulary than Union reports.
                        A context header is prepended to help the LLM understand tier-specific terminology:
                    </p>

                    <div style={{
                        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px',
                    }}>
                        <CodeBlock title="State Report Context">
{`REPORT CONTEXT: State audit from Odisha.
Department: Rural Development
Audit type: Compliance Audit

State terminology: 'State AG', 'State Exchequer',
'State Consolidated Fund', 'SPSE' (State PSE)`}
                        </CodeBlock>
                        <CodeBlock title="Local Body Context">
{`REPORT CONTEXT: Local Body audit from Maharashtra.

Terminology: 'PRI' (Panchayati Raj),
'ULB' (Urban Local Body), 'GP' (Gram Panchayat),
'ZP' (Zila Parishad), 'ATIR', 'PRIASoft'`}
                        </CodeBlock>
                    </div>
                </div>

                {/* Response Styles */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>6 Response Styles</h3>
                    <div style={{ display: 'grid', gap: '8px' }}>
                        <ResponseStyleCard name="Concise" audience="Quick answers, mobile" wordRange="50–100 words" color="#1a365d" />
                        <ResponseStyleCard name="Executive" audience="Decision-makers, bottom-line first" wordRange="150–250 words" color="#059669" />
                        <ResponseStyleCard name="Detailed" audience="Comprehensive analysis" wordRange="300–500 words" color="#7c3aed" />
                        <ResponseStyleCard name="Technical" audience="Deep-dive for analysts" wordRange="400–600 words" color="#0891b2" />
                        <ResponseStyleCard name="Comparative" audience="Theme-based multi-year trends" wordRange="300–500 words" color="#f59e0b" />
                        <ResponseStyleCard name="Adaptive" audience="Auto-detects question type" wordRange="Varies" color="#64748b" />
                    </div>
                </div>

                {/* Citation Rules */}
                <div style={{ marginBottom: '8px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Citation Rules</h3>
                    <div style={{
                        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px',
                    }}>
                        <div style={{ padding: '16px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '8px' }}>
                            <div style={{ fontSize: '13px', fontWeight: 700, color: '#166534', marginBottom: '8px' }}>Correct</div>
                            <div style={{ fontSize: '14px', color: '#15803d', lineHeight: 1.6 }}>
                                "Revenue loss was ₹64.60 crore. <strong>[Section 3.2.1, p.36]</strong>"
                            </div>
                            <div style={{ fontSize: '12px', color: '#059669', marginTop: '8px' }}>Citation at END of sentence.</div>
                        </div>
                        <div style={{ padding: '16px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px' }}>
                            <div style={{ fontSize: '13px', fontWeight: 700, color: '#dc2626', marginBottom: '8px' }}>Wrong</div>
                            <div style={{ fontSize: '14px', color: '#991b1b', lineHeight: 1.6 }}>
                                "Revenue loss was ₹64.60 crore <strong>[Section 3.2.1, p.36]</strong> due to..."
                            </div>
                            <div style={{ fontSize: '12px', color: '#dc2626', marginTop: '8px' }}>Mid-sentence citation breaks parsing.</div>
                        </div>
                    </div>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 7: Streaming Events
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Streaming Events"
                description="SSE event sequences for standard and agentic paths. The frontend handles each event type differently."
            >
                <div style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px',
                }}>
                    <div>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Standard Path Events</h3>
                        <div style={{
                            border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden',
                        }}>
                            {[
                                { event: 'citation_map', when: 'After retrieval', payload: 'Citation metadata for linking' },
                                { event: 'token', when: 'Each LLM token', payload: 'String token' },
                                { event: 'groundedness', when: 'After token stream', payload: 'Grounding report' },
                                { event: 'done', when: 'End of stream', payload: 'null' },
                            ].map((row, i) => (
                                <div key={row.event} style={{
                                    display: 'grid', gridTemplateColumns: '100px 1fr',
                                    borderBottom: i < 3 ? '1px solid #e2e8f0' : 'none', fontSize: '13px',
                                }}>
                                    <div style={{ padding: '10px 12px', background: '#f8fafc', fontWeight: 600, color: '#059669', fontFamily: 'monospace' }}>{row.event}</div>
                                    <div style={{ padding: '10px 12px', color: '#475569' }}>{row.when} — {row.payload}</div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Agentic Path Events</h3>
                        <div style={{
                            border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden',
                        }}>
                            {[
                                { event: 'planning', when: 'After decomposition', payload: 'complexity, sub_queries' },
                                { event: 'sub_query', when: 'Before each sub-query', payload: 'index, query, total' },
                                { event: 'iteration', when: 'After each loop', payload: 'sufficient, num_chunks' },
                                { event: 'reformulation', when: 'When query rewritten', payload: 'new_query' },
                                { event: 'synthesizing', when: 'Before generation', payload: 'null' },
                                { event: 'token', when: 'Each LLM token', payload: 'String token' },
                                { event: 'groundedness', when: 'After token stream', payload: 'Grounding report' },
                                { event: 'agentic_trace', when: 'Before done', payload: 'Full execution trace' },
                                { event: 'done', when: 'End of stream', payload: 'null' },
                            ].map((row, i) => (
                                <div key={row.event} style={{
                                    display: 'grid', gridTemplateColumns: '100px 1fr',
                                    borderBottom: i < 8 ? '1px solid #e2e8f0' : 'none', fontSize: '12px',
                                }}>
                                    <div style={{ padding: '8px 10px', background: '#fff7ed', fontWeight: 600, color: '#ea580c', fontFamily: 'monospace' }}>{row.event}</div>
                                    <div style={{ padding: '8px 10px', color: '#475569' }}>{row.payload}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 8: Performance & Cost
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Performance & Cost"
                description="Latency breakdowns for both paths and per-query cost analysis."
            >
                {/* Latency Breakdown */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '16px' }}>Standard Path Latency</h3>
                    <div style={{
                        padding: '20px 24px', background: '#ffffff',
                        border: '1px solid #e2e8f0', borderRadius: '12px',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                    }}>
                        <LatencyBar label="Query enhancement" time="~100ms" widthPercent={5} color="#3b82f6" />
                        <LatencyBar label="Query embedding" time="~100ms" widthPercent={5} color="#1a365d" />
                        <LatencyBar label="Hybrid search + RRF" time="~50ms" widthPercent={2.5} color="#f59e0b" />
                        <LatencyBar label="Cohere reranking" time="~200ms" widthPercent={10} color="#d946ef" />
                        <LatencyBar label="Neighbor expansion" time="~20ms" widthPercent={1} color="#059669" />
                        <LatencyBar label="Context assembly" time="~15ms" widthPercent={0.75} color="#64748b" />
                        <LatencyBar label="LLM generation" time="~1.5-2s" widthPercent={75} color="#ef4444" />
                        <LatencyBar label="Groundedness" time="~300ms" widthPercent={15} color="#22c55e" />
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '12px', paddingTop: '12px', borderTop: '2px solid #e2e8f0' }}>
                            <div style={{ width: '200px', fontSize: '14px', fontWeight: 700, color: '#1e293b', textAlign: 'right' }}>Total end-to-end</div>
                            <div style={{ fontSize: '16px', fontWeight: 700, color: '#1a365d' }}>~2-3 seconds</div>
                        </div>
                    </div>
                </div>

                {/* Agentic Latency */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Agentic Path Latency</h3>
                    <div style={{
                        padding: '16px 20px', background: '#fff7ed',
                        border: '1px solid #fed7aa', borderRadius: '10px',
                    }}>
                        <div style={{ display: 'grid', gap: '6px', fontSize: '14px', color: '#78350f' }}>
                            <div>Planning / decomposition: <strong>~100ms</strong></div>
                            <div>Per sub-query (2-4x): retrieval + sufficiency: <strong>~500-1500ms each</strong></div>
                            <div>Reformulation retries (if needed): <strong>+500ms each</strong></div>
                            <div>Result merging: <strong>~10ms</strong></div>
                            <div>Synthesis LLM generation: <strong>~2000-3000ms</strong></div>
                            <div>Groundedness verification: <strong>+200-400ms</strong></div>
                            <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid #fed7aa', fontWeight: 700, color: '#ea580c' }}>
                                Total end-to-end: ~5-12 seconds
                            </div>
                        </div>
                    </div>
                </div>

                {/* Cost Breakdown */}
                <div style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px',
                }}>
                    <div style={{ padding: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '14px' }}>Standard Query Cost</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['Query enhancement (gpt-4o-mini)', '~$0.0002'],
                                ['Query embedding', '~$0.0001'],
                                ['Cohere reranking', '~$0.001'],
                                ['LLM generation (gpt-4o-mini)', '~$0.002-0.005'],
                                ['Groundedness verification', '~$0.0005'],
                            ].map(([item, cost]) => (
                                <div key={item} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569' }}>{item}</span>
                                    <span style={{ fontWeight: 600, color: '#1e293b' }}>{cost}</span>
                                </div>
                            ))}
                            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderTop: '2px solid #e2e8f0', marginTop: '4px' }}>
                                <span style={{ fontWeight: 700, color: '#1e293b' }}>Total per query</span>
                                <span style={{ fontWeight: 700, color: '#059669' }}>~$0.004-0.009</span>
                            </div>
                        </div>
                    </div>

                    <div style={{ padding: '20px', background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#92400e', marginBottom: '14px' }}>Agentic Query Cost</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['Planner LLM call', '~$0.0002'],
                                ['Per sub-query (2-4x): embed + retrieve + rerank', '~$0.002-0.004 each'],
                                ['Synthesis LLM call', '~$0.005-0.01'],
                                ['Groundedness verification', '~$0.0005'],
                            ].map(([item, cost]) => (
                                <div key={item} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #fde68a' }}>
                                    <span style={{ color: '#78350f' }}>{item}</span>
                                    <span style={{ fontWeight: 600, color: '#92400e' }}>{cost}</span>
                                </div>
                            ))}
                            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderTop: '2px solid #f59e0b', marginTop: '4px' }}>
                                <span style={{ fontWeight: 700, color: '#92400e' }}>Total per query</span>
                                <span style={{ fontWeight: 700, color: '#ea580c' }}>~$0.01-0.03</span>
                            </div>
                        </div>
                    </div>
                </div>

                <CalloutBox type="success" style={{ marginTop: '20px' }}>
                    <strong>Entity Graph cost:</strong> $0 per query (DB lookup only). Canonicalization is a one-time cost:
                    ~$0.50-1.00 for 37 reports, ~$10-15 for 700+ reports.
                </CalloutBox>
            </DocSection>
        </div>
    );
};
