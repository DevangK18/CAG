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
    accent = '#2563eb',
}) => (
    <div className="stat-card">
        <div className="stat-value" style={{ color: accent }}>{value}</div>
        <div className="stat-label">{label}</div>
    </div>
);

const StageLabel: React.FC<{ number: string; title: string; color?: string }> = ({
    number,
    title,
    color = '#2563eb',
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
        {value}{label && <span style={{ fontWeight: 400, color: '#3b82f6' }}> {label}</span>}
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
        E[User Question] --> F[RAGService]
        F --> G[Query Embedding]
        G --> H[Hybrid Search<br/>RRF Fusion]
        D --> H
        H --> I[Reranking<br/>Cohere / BGE]
        I --> J[O1 Neighbor<br/>Expansion]
        J --> K[Parent Grouping<br/>+ Context Assembly]
        L[ReportRegistry] --> K
        K --> M[LLM Generation<br/>Claude / GPT-4]
        M --> N[RAGResponse<br/>Answer + Citations]
    end

    style D fill:#e1f5ff,stroke:#0ea5e9
    style N fill:#dcfce7,stroke:#22c55e
    style H fill:#fef3c7,stroke:#f59e0b
    style I fill:#fae8ff,stroke:#d946ef
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

    const contextAssemblyDiagram = `
graph TB
    Chunks[Retrieved Chunks<br/>with scores] --> Group[Group by<br/>Parent Section]
    Group --> Fetch[Fetch Parent<br/>Metadata]
    Fetch --> Hierarchy[Add Hierarchy<br/>Breadcrumbs]
    Hierarchy --> Semantic[Add Semantic<br/>Tags]
    Semantic --> Number[Number Chunks<br/>for Citation]
    Number --> Truncate[Truncate to<br/>15K chars]
    Truncate --> Context[Final Context<br/>String]

    style Chunks fill:#e0e7ff
    style Context fill:#dcfce7
    style Truncate fill:#fef3c7
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">RAG & Search</h1>
            <p className="page-subtitle">
                A hybrid search pipeline that retrieves relevant audit chunks using dense + sparse vectors,
                reranks with cross-encoders, and generates cited answers across 6 response styles.
                Two distinct pipelines — offline indexing at pennies per report, online querying under 3 seconds.
            </p>

            {/* ── Hero Stats ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '14px', margin: '0 0 56px 0' }}>
                <Stat value="15,669" label="Chunks Indexed" />
                <Stat value="2,792" label="Parent Sections" accent="#7c3aed" />
                <Stat value="~2.5s" label="End-to-End Latency" accent="#059669" />
                <Stat value="$0.39" label="Total Indexing Cost" accent="#d97706" />
                <Stat value="6" label="Response Styles" accent="#dc2626" />
            </div>

            {/* ══════════════════════════════════════════════
                SECTION 1: Two-Pipeline Architecture
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Two-Pipeline Architecture"
                description="The RAG system splits into two pipelines with fundamentally different runtime profiles. Indexing runs once per report and costs fractions of a cent. Querying runs per user interaction and optimizes for latency."
            >
                <DiagramCard title="Offline Indexing + Online Query Flow">
                    <MermaidDiagram
                        chart={architectureDiagram}
                        caption="The offline pipeline generates 4 types of data per chunk (dense vector, sparse vector, table summary, semantic payload). The online pipeline chains 5 retrieval stages before reaching the LLM. Yellow = fusion, purple = reranking."
                    />
                </DiagramCard>

                <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '16px',
                    marginTop: '20px',
                }}>
                    <div style={{ padding: '20px', background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: '10px' }}>
                        <div style={{ fontSize: '12px', fontWeight: 700, color: '#0369a1', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>Offline Pipeline</div>
                        <div style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '8px' }}>Indexing</div>
                        <p style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6, marginBottom: '10px' }}>
                            JSON → embeddings → Qdrant. Runs once per report.
                            Generates dense embeddings, BM25 sparse vectors, LLM table summaries, and semantic payloads.
                        </p>
                        <div style={{ display: 'flex', gap: '16px', fontSize: '13px' }}>
                            <div><span style={{ fontWeight: 700, color: '#0369a1' }}>Cost:</span> <span style={{ color: '#475569' }}>~$0.02/report</span></div>
                            <div><span style={{ fontWeight: 700, color: '#0369a1' }}>Speed:</span> <span style={{ color: '#475569' }}>~2 reports/sec</span></div>
                        </div>
                    </div>
                    <div style={{ padding: '20px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '10px' }}>
                        <div style={{ fontSize: '12px', fontWeight: 700, color: '#15803d', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>Online Pipeline</div>
                        <div style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '8px' }}>Querying</div>
                        <p style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6, marginBottom: '10px' }}>
                            Question → retrieval → generation → cited response. Runs per user query.
                            Chains hybrid search, reranking, neighbor expansion, and style-adaptive generation.
                        </p>
                        <div style={{ display: 'flex', gap: '16px', fontSize: '13px' }}>
                            <div><span style={{ fontWeight: 700, color: '#15803d' }}>Cost:</span> <span style={{ color: '#475569' }}>~$0.005/query</span></div>
                            <div><span style={{ fontWeight: 700, color: '#15803d' }}>Latency:</span> <span style={{ color: '#475569' }}>~2.5s e2e</span></div>
                        </div>
                    </div>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 2: Embedding & Indexing
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Embedding & Indexing"
                description="The offline pipeline generates 4 types of data per chunk. Each serves a different retrieval need — semantic similarity, keyword matching, table understanding, and structured filtering."
            >
                {/* Dense Embeddings */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="1" title="Dense Embeddings" color="#3b82f6" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Every child chunk is embedded using OpenAI's <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>text-embedding-3-large</code> at <InlineStat value="1536" label="dimensions" />,
                        batched in groups of 100 to stay within rate limits. Before embedding, each chunk's text is
                        prefixed with its TOC hierarchy breadcrumb — so a table in "Chapter II {'>'} 2.3 Revenue Collection"
                        carries that section context directly in the vector. This means queries about "revenue collection"
                        naturally boost chunks from the correct section.
                    </p>

                    <DecisionCard
                        question="Why 1536 dimensions, not the full 3072?"
                        answer="OpenAI's research shows <1% quality degradation for this reduction on typical retrieval tasks. We validated empirically on CAG queries and found no measurable recall impact."
                        tradeoff="50% reduction in storage and search costs. The entire corpus (15,669 vectors) fits comfortably in memory."
                    />

                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        Total dense embedding cost for all 19 reports: <InlineStat value="$0.28" />. That's less than 1.5 cents per report.
                    </p>
                </div>

                {/* Custom BM25 */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="2" title="Custom BM25 Sparse Vectors" color="#f59e0b" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Dense embeddings capture meaning but miss exact patterns. When a user asks about "Section 143(3) violations,"
                        semantic similarity alone might return chunks about violations in general. BM25 sparse vectors ensure
                        exact keyword matches rank high. The custom engine is built specifically for CAG documents with
                        domain-specific pattern boosting:
                    </p>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr 1fr',
                        gap: '12px',
                        marginBottom: '16px',
                    }}>
                        {[
                            { pattern: 'Legal References', examples: 'section_143, rule_86b, form_26as', boost: '3.0×', color: '#dc2626', bg: '#fef2f2', border: '#fecaca' },
                            { pattern: 'Entity Acronyms', examples: 'acronym_NHAI, acronym_PMJAY', boost: '2.5×', color: '#7c3aed', bg: '#faf5ff', border: '#e9d5ff' },
                            { pattern: 'Monetary / Temporal', examples: 'money_crore, year_2023-24', boost: '1.5×', color: '#0369a1', bg: '#f0f9ff', border: '#bae6fd' },
                        ].map((item) => (
                            <div key={item.pattern} style={{
                                padding: '14px 16px',
                                background: item.bg,
                                border: `1px solid ${item.border}`,
                                borderRadius: '8px',
                            }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                                    <span style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>{item.pattern}</span>
                                    <span style={{ fontSize: '13px', fontWeight: 700, color: item.color }}>{item.boost}</span>
                                </div>
                                <div style={{ fontSize: '12px', color: '#64748b', fontFamily: 'monospace' }}>{item.examples}</div>
                            </div>
                        ))}
                    </div>

                    <DecisionCard
                        question="Why build custom BM25 instead of using fastembed?"
                        answer="fastembed pulls in huggingface_hub, which creates version conflicts with Docling (our layout analysis engine in the parsing pipeline). Custom BM25 has zero external dependencies and enables the CAG-specific boosts above."
                        tradeoff="We maintain the BM25 engine ourselves, but the 3× boost on legal references significantly improves retrieval for the most common CAG query patterns."
                    />
                </div>

                {/* Table Summaries */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="3" title="LLM Table Summaries" color="#059669" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Markdown tables embed poorly — a 15-row revenue table produces a vector that says
                        "pipes and dashes" more than "state-wise revenue collection." The pipeline generates
                        a natural language summary for each table using <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>gpt-4o-mini</code> and
                        prepends it to the table content before embedding. This makes tables findable via semantic queries.
                    </p>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr auto 1fr',
                        gap: '0',
                        alignItems: 'center',
                        border: '1px solid #e2e8f0',
                        borderRadius: '10px',
                        overflow: 'hidden',
                        margin: '0 0 16px 0',
                    }}>
                        <div style={{ padding: '14px 18px', background: '#fef2f2' }}>
                            <div style={{ fontSize: '11px', fontWeight: 700, color: '#dc2626', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>Without Summary</div>
                            <div style={{ fontSize: '13px', color: '#991b1b', fontFamily: 'monospace', lineHeight: 1.5 }}>| State | Revenue | Growth |<br/>| --- | --- | --- |<br/>| Maharashtra | 12,450 | 8.3 |</div>
                        </div>
                        <div style={{ padding: '0 16px', fontSize: '20px', color: '#94a3b8' }}>→</div>
                        <div style={{ padding: '14px 18px', background: '#f0fdf4' }}>
                            <div style={{ fontSize: '11px', fontWeight: 700, color: '#16a34a', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>With Summary</div>
                            <div style={{ fontSize: '13px', color: '#166534', lineHeight: 1.5 }}>"Table showing state-wise revenue for FY 2022-23, Maharashtra at ₹12,450 crore (highest)."</div>
                        </div>
                    </div>

                    <DecisionCard
                        question="Why gpt-4o-mini instead of Claude for table summaries?"
                        answer="Table summarization is a simple task — identify headers, describe the data, note extremes. gpt-4o-mini is 5× cheaper than Claude and produces equivalent quality for this narrow task."
                        tradeoff="At ~$0.0001 per table, the entire corpus costs $0.12 for table summaries. Total table summary cost across 19 reports: $0.12."
                    />
                </div>

                {/* Semantic Payloads */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="4" title="Semantic Payloads" color="#7c3aed" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Every chunk arrives from the parsing pipeline with semantic enrichment — findings, recommendations,
                        monetary values, entities. The <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>SemanticPayloadExtractor</code> maps
                        this data into Qdrant payload fields: <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>finding_type</code>, <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>severity</code>,
                        {' '}<code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>total_amount_crore</code>, <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>is_recommendation</code>.
                        These fields are indexed in Qdrant for fast filtered queries.
                    </p>
                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        The result: users can ask "Show me all high-severity findings above ₹100 crore" and the system
                        applies <strong>both</strong> semantic search (via vectors) and structured filtering (via payload indexes)
                        in a single query. Without payload indexing, these filters would require scanning all 15,669 vectors — <InlineStat value="<50ms" label="indexed" /> vs <InlineStat value="~5000ms" label="unindexed" />.
                    </p>
                </div>

                {/* Qdrant Collections */}
                <div style={{ marginBottom: '8px' }}>
                    <StageLabel number="5" title="Qdrant Collection Architecture" color="#0891b2" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '16px' }}>
                        The vector database uses two collections — not one — to cleanly separate searchable content
                        from section metadata.
                    </p>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr',
                        gap: '14px',
                        marginBottom: '16px',
                    }}>
                        <div style={{ padding: '16px 20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                                <span style={{ background: '#dbeafe', color: '#1e40af', fontSize: '12px', fontWeight: 700, padding: '3px 8px', borderRadius: '4px' }}>CHILD</span>
                                <span style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>cag_child_chunks</span>
                            </div>
                            <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6 }}>
                                <strong>15,669 points</strong> — paragraphs, tables, charts.
                                Dense vectors (1536-dim, cosine) + sparse vectors (BM25 with IDF).
                                Full payload with semantic fields indexed for filtered search.
                            </div>
                        </div>
                        <div style={{ padding: '16px 20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                                <span style={{ background: '#fae8ff', color: '#7c3aed', fontSize: '12px', fontWeight: 700, padding: '3px 8px', borderRadius: '4px' }}>PARENT</span>
                                <span style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>cag_parent_chunks</span>
                            </div>
                            <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6 }}>
                                <strong>2,792 points</strong> — TOC sections, metadata-only.
                                Dummy 4-dim vector (Qdrant requires it).
                                Stores: toc_entry, hierarchy, page ranges.
                            </div>
                        </div>
                    </div>

                    <DecisionCard
                        question="Why two collections instead of one with filtering?"
                        answer="Parent chunks don't have searchable content — they're section titles and page ranges. Putting them in the same collection would pollute search results with irrelevant section-level entries. The parent collection serves purely as a metadata store for hierarchy and page range lookups during context assembly."
                    />
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 3: Hybrid Search
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Hybrid Search & Retrieval"
                description="The query pipeline chains 5 stages to go from a user question to a ranked, grouped, context-ready set of chunks. Every stage exists because the previous one alone isn't good enough."
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

                {/* RRF Fusion */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="1" title="RRF Fusion" color="#ef4444" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Reciprocal Rank Fusion combines the two result sets using a rank-based formula.
                        For each document, it sums <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>1 / (k + rank)</code> across
                        both searches, where <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>k=60</code> is the standard dampening constant.
                        Both dense and sparse results contribute <InlineStat value="50" label="candidates each" />,
                        and the fused set is trimmed to the final candidate pool.
                    </p>

                    <DecisionCard
                        question="Why RRF over linear combination?"
                        answer="Dense cosine similarity ranges [0,1] while BM25 scores can be arbitrarily large. Linear combination requires tuning weights per domain. RRF is rank-based — it normalizes score differences automatically. Research shows RRF consistently outperforms tuned linear combinations across domains."
                    />
                </div>

                {/* Reranking */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="2" title="Cross-Encoder Reranking" color="#d946ef" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Initial search (top 50) optimizes for <strong>recall</strong> — casting a wide net.
                        Reranking (to top 10) optimizes for <strong>precision</strong> — keeping only the most relevant.
                        Cross-encoders see the full query-document pair jointly (not just embeddings), giving them
                        much stronger relevance judgment than bi-encoder similarity.
                    </p>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Both rerankers prepend hierarchy breadcrumbs to each chunk before scoring:
                        {' '}<code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>[Chapter II &gt; 2.3 Revenue &gt; 2.3.1 Direct Taxes] {'{'}{'{'}chunk content{'}'}{'}'}</code>.
                        This gives the reranker section context — a chunk about "revenue" in the Revenue section
                        scores higher than an identical mention in an unrelated section.
                    </p>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr',
                        gap: '14px',
                        marginBottom: '14px',
                    }}>
                        <div style={{ padding: '16px 20px', background: '#faf5ff', border: '1px solid #e9d5ff', borderRadius: '8px' }}>
                            <div style={{ fontSize: '14px', fontWeight: 700, color: '#6b21a8', marginBottom: '6px' }}>Cohere (Primary)</div>
                            <div style={{ fontSize: '13px', color: '#581c87', lineHeight: 1.6 }}>
                                Model: <code style={{ fontSize: '12px' }}>rerank-english-v3.0</code><br />
                                API-based, state-of-art quality.<br />
                                ~8-12% better precision@10 on CAG benchmarks.
                            </div>
                        </div>
                        <div style={{ padding: '16px 20px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px' }}>
                            <div style={{ fontSize: '14px', fontWeight: 700, color: '#475569', marginBottom: '6px' }}>BGE (Fallback)</div>
                            <div style={{ fontSize: '13px', color: '#64748b', lineHeight: 1.6 }}>
                                Model: <code style={{ fontSize: '12px' }}>BAAI/bge-reranker-v2-m3</code><br />
                                Local cross-encoder, zero API cost.<br />
                                Within ~5% of Cohere quality.
                            </div>
                        </div>
                    </div>

                    <DecisionCard
                        question="Why 50 → 10 (5:1 ratio)?"
                        answer="50 initial candidates captures ~95% recall — enough to include most relevant chunks. More provides diminishing returns at increased reranking cost. Reranking to 10 ensures the final set is highly precise for context assembly."
                    />
                </div>

                {/* O(1) Neighbor Expansion */}
                <div style={{ marginBottom: '28px' }}>
                    <StageLabel number="3" title="O(1) Neighbor Expansion" color="#059669" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        A retrieved chunk about "revenue loss of ₹64.60 crore" often needs the preceding paragraph
                        (which sets the context) and the following paragraph (which adds detail). Traditional approaches
                        search for neighbors — 2 additional vector searches per chunk, multiplied by 10 chunks = 20 searches.
                    </p>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Our approach exploits the deterministic chunk ID format from the parsing pipeline:
                    </p>

                    <CodeBlock title="O(1) Neighbor Prediction">
{`Chunk ID format:
  {report_id}_child_p{page:03d}_{type}_{index:04d}

Example:
  Current: "2023_07_child_p045_paragraph_0123"
  Previous: "2023_07_child_p045_paragraph_0122"  ← index - 1
  Next:     "2023_07_child_p045_paragraph_0124"  ← index + 1

→ Direct Qdrant fetch by ID (no vector search)`}
                    </CodeBlock>

                    <p style={{ lineHeight: 1.7, color: '#475569', marginTop: '14px' }}>
                        Result: <InlineStat value="~20ms" label="for 10 chunks" /> vs ~2,000ms with vector search.
                        The tradeoff is a hard dependency on consistent chunk ID formatting from the parsing pipeline —
                        if chunk IDs change format, neighbor prediction breaks. We accept this coupling
                        because both pipelines are maintained together.
                    </p>
                </div>

                {/* Context Assembly */}
                <div style={{ marginBottom: '8px' }}>
                    <StageLabel number="4" title="Parent Grouping & Context Assembly" color="#0284c7" />

                    <DiagramCard title="Context Assembly Pipeline">
                        <MermaidDiagram
                            chart={contextAssemblyDiagram}
                            caption="Retrieved chunks are grouped by parent section, enriched with hierarchy and semantic metadata, numbered for citation reference, and truncated to the context limit."
                        />
                    </DiagramCard>

                    <p style={{ lineHeight: 1.7, color: '#475569', marginTop: '16px', marginBottom: '12px' }}>
                        Chunks are grouped by their <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>parent_chunk_id</code>,
                        and parent metadata (TOC entry, hierarchy, page range) is fetched from the parent collection.
                        The final context string is formatted as structured markdown:
                    </p>

                    <CodeBlock title="Context Output (sent to LLM)">
{`## Chapter II > 2.3 Revenue Collection (Pages 35-42)

[1] Revenue loss of ₹64.60 crore occurred at 12 toll plazas...
    Finding: loss_of_revenue | Severity: HIGH | Amount: ₹64.60 crore

[2] Non-functional ETC equipment was the primary cause...

## Chapter III > 3.1 Procurement (Pages 55-63)

[3] Irregular expenditure of ₹847.71 crore in procurement...
    Finding: irregular_expenditure | Severity: CRITICAL | Amount: ₹847.71 crore`}
                    </CodeBlock>

                    <p style={{ lineHeight: 1.7, color: '#475569', marginTop: '14px' }}>
                        Each chunk is numbered for citation reference. Semantic tags (finding type, severity, amount) are
                        included so the LLM can cite specific monetary values and severity levels. Context is truncated
                        to <InlineStat value="15,000" label="chars" /> (~3,750 tokens) — our experiments showed answer quality
                        plateaus past ~4,000 tokens. List and aggregation questions get 1.5× context since they benefit from more sources.
                    </p>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 4: Answer Generation
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Answer Generation"
                description="The generation layer adapts to question type and response style. It's built around strict citation rules, anti-hallucination guardrails, and a multi-style prompt architecture."
            >
                {/* Response Styles */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>6 Response Styles</h3>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Each style has its own system prompt with tailored structure and word count guidance.
                        The frontend exposes 6 styles; two more (<code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>EXPLANATORY</code>,
                        {' '}<code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>REPORT</code>) are available programmatically.
                    </p>
                    <div style={{ display: 'grid', gap: '8px' }}>
                        <ResponseStyleCard name="Concise" audience="Quick answers, mobile" wordRange="50–100 words" color="#3b82f6" />
                        <ResponseStyleCard name="Executive" audience="Decision-makers, bottom-line first" wordRange="150–250 words" color="#059669" />
                        <ResponseStyleCard name="Detailed" audience="Comprehensive analysis" wordRange="300–500 words" color="#7c3aed" />
                        <ResponseStyleCard name="Technical" audience="Deep-dive for analysts" wordRange="400–600 words" color="#0891b2" />
                        <ResponseStyleCard name="Comparative" audience="Theme-based multi-year trends" wordRange="300–500 words" color="#f59e0b" />
                        <ResponseStyleCard name="Adaptive" audience="Auto-detects question type" wordRange="Varies" color="#64748b" />
                    </div>
                </div>

                {/* Question Type Detection */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Question Type Detection</h3>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Before retrieval, the system classifies the question to adjust both retrieval parameters and
                        response formatting. This happens in the <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>_detect_question_type()</code> method:
                    </p>

                    <div style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: '10px',
                        overflow: 'hidden',
                        marginBottom: '16px',
                        background: '#ffffff',
                    }}>
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: '100px 1fr 1fr',
                            gap: '0',
                            borderBottom: '2px solid #cbd5e1',
                            fontSize: '12px',
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            letterSpacing: '0.05em',
                            color: '#64748b',
                        }}>
                            <div style={{ padding: '10px 14px', background: '#f8fafc' }}>Type</div>
                            <div style={{ padding: '10px 14px' }}>Trigger Patterns</div>
                            <div style={{ padding: '10px 14px' }}>Adjustments</div>
                        </div>
                        {[
                            { type: 'LIST', patterns: '"what are", "list all", "enumerate"', adjustments: 'top_k → 15, bullet format', color: '#3b82f6' },
                            { type: 'AGGREGATION', patterns: '"total", "sum", "overall"', adjustments: 'Context limit 1.5×, warn against calculation', color: '#059669' },
                            { type: 'COMPARISON', patterns: '"compare", "trend", "over years"', adjustments: 'Auto-select COMPARATIVE style', color: '#f59e0b' },
                            { type: 'EXPLANATION', patterns: '"why", "explain", "cause"', adjustments: 'Auto-select EXPLANATORY style', color: '#7c3aed' },
                            { type: 'FACTUAL', patterns: '(default)', adjustments: 'No adjustment', color: '#64748b' },
                        ].map((row) => (
                            <div key={row.type} style={{
                                display: 'grid',
                                gridTemplateColumns: '100px 1fr 1fr',
                                gap: '0',
                                borderBottom: '1px solid #e2e8f0',
                                fontSize: '14px',
                            }}>
                                <div style={{ padding: '10px 14px', fontWeight: 700, color: row.color, background: '#fafafa' }}>{row.type}</div>
                                <div style={{ padding: '10px 14px', color: '#475569', fontFamily: 'monospace', fontSize: '13px' }}>{row.patterns}</div>
                                <div style={{ padding: '10px 14px', color: '#475569' }}>{row.adjustments}</div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* System Prompt Architecture */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>System Prompt Architecture</h3>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        The prompt system is layered — a base expertise layer plus style-specific and question-type overlays:
                    </p>
                    <div style={{
                        display: 'grid',
                        gap: '10px',
                        marginBottom: '16px',
                    }}>
                        {[
                            { layer: 'Base Expertise', desc: 'CAG domain knowledge. Critical rules: ONLY state facts found in context, NEVER invent monetary amounts.', bg: '#f8fafc', border: '#e2e8f0', color: '#1e293b' },
                            { layer: 'Anti-Pattern Rules', desc: 'Forbidden phrases ("The question is asking...", "Based on the context..."). Required: start directly with the answer.', bg: '#fef2f2', border: '#fecaca', color: '#991b1b' },
                            { layer: 'Citation Rules', desc: 'Format: [Section Name, p.XX]. Placement: END of sentence, never mid-sentence. Every claim must be cited.', bg: '#eff6ff', border: '#bfdbfe', color: '#1e40af' },
                            { layer: 'Style-Specific', desc: 'Tailored structure and word count per style. E.g., CONCISE: lead finding → amount → 1-2 details → citation.', bg: '#f0fdf4', border: '#bbf7d0', color: '#166534' },
                            { layer: 'Question-Type Hints', desc: 'Dynamic suffix added per detected type. E.g., LIST → "Enumerate ALL items. Citation at end of each."', bg: '#fefce8', border: '#fde68a', color: '#854d0e' },
                        ].map((item) => (
                            <div key={item.layer} style={{
                                padding: '14px 18px',
                                background: item.bg,
                                border: `1px solid ${item.border}`,
                                borderRadius: '8px',
                                display: 'grid',
                                gridTemplateColumns: '160px 1fr',
                                gap: '14px',
                                alignItems: 'start',
                            }}>
                                <div style={{ fontSize: '13px', fontWeight: 700, color: item.color }}>{item.layer}</div>
                                <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6 }}>{item.desc}</div>
                            </div>
                        ))}
                    </div>

                    <DecisionCard
                        question="Why temperature 0.1 instead of 0?"
                        answer="Temperature 0 in OpenAI's API can produce repetitive outputs for similar queries — the same phrasing for every 'What is the revenue loss' question. Temperature 0.1 is near-deterministic but avoids the repetition trap."
                        tradeoff="We prioritize consistency over creativity for factual Q&A. Claude's temperature 0.1 produces reliable, non-repetitive answers."
                    />
                </div>

                {/* Time Series */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Time Series / Comparative Analysis</h3>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        The <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>ask_comparative()</code> method
                        retrieves from each report separately and constructs context with strong year boundaries.
                        Reports are grouped into series using regex patterns in the <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>ReportRegistry</code> —
                        for example, all FRBM compliance reports across years are matched
                        by <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px', fontSize: '12px' }}>/Fiscal.?Responsibility.*Budget.?Management|FRBM/</code>.
                    </p>

                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        The time series prompt system enforces three rules to prevent hallucination across years:
                    </p>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr 1fr',
                        gap: '12px',
                        marginBottom: '16px',
                    }}>
                        {[
                            { rule: 'Year in Citations', desc: 'Mandatory: [2022-23 - Section 3.1, p.45]. Without the year prefix, citations are ambiguous across reports.', bg: '#eff6ff', border: '#bfdbfe' },
                            { rule: 'Missing Data', desc: '"Data not available for 2021-22" — the LLM is explicitly instructed to state gaps rather than infer or hallucinate.', bg: '#fef2f2', border: '#fecaca' },
                            { rule: 'Theme Organization', desc: 'Group by theme (fiscal deficit, revenue), not chronologically. Trend indicators (↑ ↓ →) show directionality at a glance.', bg: '#f0fdf4', border: '#bbf7d0' },
                        ].map((item) => (
                            <div key={item.rule} style={{
                                padding: '14px 16px',
                                background: item.bg,
                                border: `1px solid ${item.border}`,
                                borderRadius: '8px',
                            }}>
                                <div style={{ fontSize: '13px', fontWeight: 700, color: '#1e293b', marginBottom: '6px' }}>{item.rule}</div>
                                <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.5 }}>{item.desc}</div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Citation Building */}
                <div style={{ marginBottom: '8px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Citation Pipeline</h3>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Citations aren't just text — they're structured objects enriched with full report metadata.
                        The <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>build_citations()</code> method
                        maps each retrieved chunk to a <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>Citation</code> that
                        includes the section name, physical page number (converted from 0-indexed to 1-indexed),
                        relevance score, finding type, severity, monetary amount, report title, filename, and audit year —
                        all pulled from the <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>ReportRegistry</code>.
                    </p>
                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        The frontend parses citation markers from the LLM response and renders them as clickable chips.
                        Clicking a citation navigates the PDF viewer to the exact page, highlights the source section,
                        and — for time series queries — auto-switches to the correct report year.
                    </p>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 5: Engineering Details
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Engineering Details"
                description="Design decisions and edge cases that surface when you build a RAG system for government audit documents with inconsistent formatting, legal references, and cross-year analysis."
            >
                <div style={{ display: 'grid', gap: '12px', marginBottom: '24px' }}>
                    <ProblemSolution
                        problem="Chunk IDs need to map to Qdrant integer point IDs. Simple sequential IDs don't work because reports are indexed independently and incrementally."
                        solution="MD5 hash of chunk_id, first 8 bytes as unsigned long. Deterministic, collision-resistant at our corpus size (~15K chunks). CRC32 was considered but has higher collision risk at scale."
                    />
                    <ProblemSolution
                        problem="The LLM sometimes places citations mid-sentence: 'Revenue was ₹64.60 crore [Section 3.2.1, p.36] due to...' This makes citations hard to parse and visually awkward."
                        solution="Strict citation placement rule in the system prompt: citations go at the END of sentences, never mid-sentence. The TECHNICAL style has the strongest enforcement since it generates the most citations."
                    />
                    <ProblemSolution
                        problem="Monetary values in different units (lakh, crore, INR) across reports make cross-report comparison unreliable."
                        solution="All monetary amounts are normalized to crore during semantic enrichment in the parsing pipeline. The RAG layer filters on total_amount_crore as a uniform field."
                    />
                    <ProblemSolution
                        problem="For aggregation queries ('total revenue loss'), the LLM might attempt to sum amounts from context — and get it wrong."
                        solution="AGGREGATION question type detection triggers a prompt warning: 'Do NOT calculate totals. Report individual amounts and let the user aggregate.' The context limit is also increased 1.5× to include more sources."
                    />
                    <ProblemSolution
                        problem="Table summaries generated at indexing time are cached in Qdrant payloads. But if re-indexing is needed, all summaries must be regenerated."
                        solution="Table summaries are stored in the payload alongside the raw table content. Re-indexing regenerates them, but at $0.0001 per table, re-generating 10,000 summaries costs $1 — negligible vs the alternative of a separate cache layer."
                    />
                </div>

                <CalloutBox type="note">
                    <strong>Semantic Filter Combinations:</strong> The payload indexing system supports compound filters —
                    for example, "high-severity findings above ₹100 crore in reports from 2023 onwards" combines
                    {' '}<code style={{ background: '#e2e8f0', padding: '2px 6px', borderRadius: '4px' }}>severity: "high"</code>,
                    {' '}<code style={{ background: '#e2e8f0', padding: '2px 6px', borderRadius: '4px' }}>total_amount_crore: {'{'}"gte": 100{'}'}</code>, and
                    {' '}<code style={{ background: '#e2e8f0', padding: '2px 6px', borderRadius: '4px' }}>report_year: {'{'}"gte": 2023{'}'}</code>.
                    All filter fields are indexed in Qdrant, keeping filtered search under 50ms regardless of combination complexity.
                </CalloutBox>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 6: Performance & Cost
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Performance & Cost"
                description="Where the time goes, where the money goes, and why the numbers are what they are."
            >
                {/* Latency Breakdown */}
                <div style={{ marginBottom: '28px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '16px' }}>Query Latency Breakdown</h3>
                    <div style={{
                        padding: '20px 24px',
                        background: '#ffffff',
                        border: '1px solid #e2e8f0',
                        borderRadius: '12px',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                    }}>
                        <LatencyBar label="Query embedding" time="~100ms" widthPercent={5} color="#3b82f6" />
                        <LatencyBar label="Hybrid search + RRF" time="~50ms" widthPercent={2.5} color="#f59e0b" />
                        <LatencyBar label="Cohere reranking" time="~200ms" widthPercent={10} color="#d946ef" />
                        <LatencyBar label="Neighbor expansion" time="~20ms" widthPercent={1} color="#059669" />
                        <LatencyBar label="Context assembly" time="~10ms" widthPercent={0.5} color="#64748b" />
                        <LatencyBar label="LLM generation" time="~1.5–2s" widthPercent={80} color="#ef4444" />
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '12px', paddingTop: '12px', borderTop: '2px solid #e2e8f0' }}>
                            <div style={{ width: '200px', fontSize: '14px', fontWeight: 700, color: '#1e293b', textAlign: 'right' }}>Total end-to-end</div>
                            <div style={{ fontSize: '16px', fontWeight: 700, color: '#2563eb' }}>~2–3 seconds</div>
                        </div>
                    </div>
                    <p style={{ fontSize: '13px', color: '#94a3b8', marginTop: '10px', lineHeight: 1.5 }}>
                        LLM generation dominates at 80% of total latency. The retrieval stack (embedding → search → reranking → expansion)
                        completes in ~380ms. SSE streaming masks generation latency — users see tokens appearing within 500ms.
                    </p>
                </div>

                {/* Cost Breakdown */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '20px',
                    marginBottom: '20px',
                }}>
                    {/* Per-Query Cost */}
                    <div style={{ padding: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '14px' }}>Per-Query Cost</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['Query embedding', '~$0.0001'],
                                ['Cohere reranking', '~$0.001'],
                                ['LLM generation (gpt-4o-mini)', '~$0.002–0.005'],
                            ].map(([item, cost]) => (
                                <div key={item} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569' }}>{item}</span>
                                    <span style={{ fontWeight: 600, color: '#1e293b' }}>{cost}</span>
                                </div>
                            ))}
                            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderTop: '2px solid #e2e8f0', marginTop: '4px' }}>
                                <span style={{ fontWeight: 700, color: '#1e293b' }}>Total per query</span>
                                <span style={{ fontWeight: 700, color: '#2563eb' }}>~$0.003–0.007</span>
                            </div>
                        </div>
                    </div>

                    {/* Indexing Cost */}
                    <div style={{ padding: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '14px' }}>Indexing Cost (19 reports)</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['Dense embeddings (15,669 chunks)', '$0.2754'],
                                ['Table summaries (gpt-4o-mini)', '$0.1168'],
                                ['Sparse vectors (built-in BM25)', '$0.00'],
                                ['Semantic payload extraction', '$0.00'],
                            ].map(([item, cost]) => (
                                <div key={item} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569' }}>{item}</span>
                                    <span style={{ fontWeight: 600, color: '#1e293b' }}>{cost}</span>
                                </div>
                            ))}
                            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderTop: '2px solid #e2e8f0', marginTop: '4px' }}>
                                <span style={{ fontWeight: 700, color: '#1e293b' }}>Total indexing</span>
                                <span style={{ fontWeight: 700, color: '#2563eb' }}>$0.3922</span>
                            </div>
                        </div>
                        <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '10px' }}>
                            ~$0.02 per report. BM25 and payload extraction are free (algorithmic).
                        </div>
                    </div>
                </div>

                <CalloutBox type="success">
                    <strong>Key cost insight:</strong> The retrieval stack is essentially free — hybrid search, neighbor expansion,
                    and context assembly have zero API cost. The only per-query costs are embedding the query (~$0.0001),
                    reranking (~$0.001), and LLM generation (~$0.003). Switching from Cohere to BGE eliminates the reranking
                    cost entirely, dropping per-query cost to ~$0.002–0.005. Indexing the entire 19-report corpus costs less
                    than a cup of coffee.
                </CalloutBox>
            </DocSection>
        </div>
    );
};