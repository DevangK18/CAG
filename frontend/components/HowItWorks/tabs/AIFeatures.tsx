import React from 'react';
import { DocSection } from '../shared/DocSection';
import { DiagramCard } from '../shared/DiagramCard';
import { CalloutBox } from '../shared/CalloutBox';
import { CodeBlock } from '../shared/CodeBlock';
import { MermaidDiagram } from '../shared/MermaidDiagram';
import { TabbedPrompt } from '../shared/TabbedPrompt';

/* ─── inline helper components ─── */

const Stat: React.FC<{ value: string; label: string; accent?: string }> = ({
    value, label, accent = '#1a365d',
}) => (
    <div className="stat-card">
        <div className="stat-value" style={{ color: accent }}>{value}</div>
        <div className="stat-label">{label}</div>
    </div>
);

const InlineStat: React.FC<{ value: string; label?: string }> = ({ value, label }) => (
    <span style={{
        display: 'inline-flex', alignItems: 'baseline', gap: '4px',
        background: '#eff6ff', border: '1px solid #bfdbfe',
        padding: '2px 8px', borderRadius: '4px',
        fontSize: '13px', fontWeight: 600, color: '#1d4ed8', whiteSpace: 'nowrap',
    }}>
        {value}{label && <span style={{ fontWeight: 400, color: '#1a365d' }}> {label}</span>}
    </span>
);

const DecisionCard: React.FC<{
    question: string; answer: string; tradeoff?: string;
}> = ({ question, answer, tradeoff }) => (
    <div style={{
        padding: '16px 20px', background: '#fefce8',
        border: '1px solid #fde68a', borderLeft: '4px solid #f59e0b',
        borderRadius: '0 8px 8px 0', margin: '14px 0',
    }}>
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#92400e', marginBottom: '6px' }}>{question}</div>
        <div style={{ fontSize: '14px', color: '#78350f', lineHeight: 1.6 }}>{answer}</div>
        {tradeoff && <div style={{ fontSize: '13px', color: '#a16207', marginTop: '8px', fontStyle: 'italic', lineHeight: 1.5 }}>Tradeoff: {tradeoff}</div>}
    </div>
);

const ModelCard: React.FC<{
    name: string; provider: string; tasks: string;
    cost: string; color: string; why: string;
}> = ({ name, provider, tasks, cost, color, why }) => (
    <div style={{
        padding: '16px 20px', background: '#ffffff',
        border: '1px solid #e2e8f0', borderLeft: `4px solid ${color}`,
        borderRadius: '0 10px 10px 0',
    }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b' }}>{name}</span>
            <span style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', background: '#f1f5f9', padding: '2px 8px', borderRadius: '4px' }}>{provider}</span>
        </div>
        <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6, marginBottom: '8px' }}>{tasks}</div>
        <div style={{ display: 'flex', gap: '16px', fontSize: '12px' }}>
            <span><span style={{ fontWeight: 700, color }}>Cost:</span> <span style={{ color: '#475569' }}>{cost}</span></span>
        </div>
        <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '6px', fontStyle: 'italic' }}>{why}</div>
    </div>
);

const PatternCard: React.FC<{
    title: string; description: string; techniques: string[];
}> = ({ title, description, techniques }) => (
    <div style={{
        padding: '16px 20px', background: '#f8fafc',
        border: '1px solid #e2e8f0', borderRadius: '10px',
    }}>
        <div style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b', marginBottom: '4px' }}>{title}</div>
        <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.5, marginBottom: '8px' }}>{description}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {techniques.map((t) => (
                <span key={t} style={{
                    fontSize: '11px', fontWeight: 600, color: '#6366f1',
                    background: '#eef2ff', padding: '2px 8px', borderRadius: '4px',
                }}>{t}</span>
            ))}
        </div>
    </div>
);

/* ─── main component ─── */

export const AIFeatures: React.FC = () => {

    const batchDiagram = `
graph LR
    Prep[Prepare Prompts<br/>5 variants × N reports] --> Submit[Submit to<br/>Batch API]
    Submit --> Track[Job Tracker<br/>custom_id mapping]
    Track --> Poll[Poll Status<br/>1-2 hours]
    Poll --> Download[Download<br/>Results]
    Download --> Parse[Parse JSON<br/>+ Validate]
    Parse --> Merge[Merge with<br/>Algorithmic Data]
    Merge --> Store[Store as<br/>Final JSON]

    style Prep fill:#e0e7ff,stroke:#6366f1
    style Submit fill:#fae8ff,stroke:#d946ef
    style Track fill:#fefce8,stroke:#f59e0b
    style Store fill:#dcfce7,stroke:#22c55e
`;

    const modelOrchestrationDiagram = `
graph TB
    subgraph "Offline · Batch Processing"
        A[Phase 5.7<br/>TOC Validation] --> H4[Claude Haiku 4.5]
        B[Phase 10a<br/>Overviews] --> S4[Claude Sonnet 4]
        C[Phase 10a<br/>Summaries 3/5] --> S4
        D[Phase 10a<br/>Summaries 2/5] --> O4[Claude Opus 4]
        E[Phase 10b<br/>Visual Extraction] --> GF[Gemini 2.5 Flash]
        F[Indexing<br/>Table Summaries] --> GM[GPT-4o-mini]
    end

    subgraph "Online · Per-Query"
        G[Query Enhancement] --> GM
        I[RAG Generation] --> S4
        J[Dense Embeddings] --> TE[text-embedding-3-large]
    end

    style H4 fill:#dbeafe,stroke:#1a365d
    style S4 fill:#fae8ff,stroke:#d946ef
    style O4 fill:#fef2f2,stroke:#ef4444
    style GF fill:#fff7ed,stroke:#f97316
    style GM fill:#dcfce7,stroke:#22c55e
    style TE fill:#f1f5f9,stroke:#94a3b8
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">AI Features</h1>
            <p className="page-subtitle">
                6 AI models orchestrated across offline batch processing and real-time serving.
                Each model is chosen for a specific cost/quality tradeoff — Claude Opus for
                long-form analysis, Haiku for structured extraction, Gemini for vision, GPT-4o-mini
                for commodity tasks. Total corpus setup: under $30.
            </p>

            {/* ── Hero Stats ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '14px', margin: '0 0 56px 0' }}>
                <Stat value="6" label="AI Models" />
                <Stat value="28" label="Distinct Prompts" accent="#7c3aed" />
                <Stat value="50%" label="Batch API Savings" accent="#059669" />
                <Stat value="~$0.50" label="Per Report Cost" accent="#d97706" />
                <Stat value="8" label="Response Styles" accent="#dc2626" />
            </div>

            {/* ══════════════════════════════════════════════
                SECTION 1: Multi-Model Strategy
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Multi-Model Strategy"
                description="Using one model for everything is simpler but wasteful. Table summarization doesn't need Claude Opus. TOC validation doesn't need vision. Each model earns its place through a specific capability at a specific price point."
            >
                <DiagramCard title="Model-to-Task Mapping">
                    <MermaidDiagram
                        chart={modelOrchestrationDiagram}
                        caption="Offline tasks use batch APIs for 50% savings. Online tasks prioritize latency. Opus handles only the 2 summary variants where quality justifies 5× the cost."
                    />
                </DiagramCard>

                <div style={{ display: 'grid', gap: '12px', marginTop: '20px' }}>
                    <ModelCard
                        name="Claude Opus 4"
                        provider="Anthropic"
                        tasks="Deep Dive & Journalist summaries — the two variants requiring creative writing and deep analytical reasoning over 100+ page reports."
                        cost="$15/$75 per 1M tokens (batch: 50% off)"
                        color="#ef4444"
                        why="Only used for 2 of 5 summary variants. Extended Thinking budget: 12K-16K tokens."
                    />
                    <ModelCard
                        name="Claude Sonnet 4"
                        provider="Anthropic"
                        tasks="Overview extraction, 3 summary variants (Executive, Simple, Policy), RAG chat generation. The workhorse model."
                        cost="$3/$15 per 1M tokens (batch: 50% off)"
                        color="#d946ef"
                        why="Best cost/quality balance for tasks requiring reasoning. Handles most offline and all online generation."
                    />
                    <ModelCard
                        name="Claude Haiku 4.5"
                        provider="Anthropic"
                        tasks="TOC validation (Phase 5.7) — fires only for ~15% of reports where heuristic TOC quality is below 50."
                        cost="$0.25/$1.25 per 1M tokens"
                        color="#1a365d"
                        why="Fastest, cheapest Claude. Structured extraction from semi-structured text doesn't need reasoning depth."
                    />
                    <ModelCard
                        name="GPT-4o-mini"
                        provider="OpenAI"
                        tasks="Table summaries during indexing, query enhancement per search, fallback RAG generation."
                        cost="$0.15/$0.60 per 1M tokens"
                        color="#22c55e"
                        why="20× cheaper than Sonnet. Table summarization and query rewriting are simple tasks that don't benefit from stronger models."
                    />
                    <ModelCard
                        name="Gemini 2.5 Flash"
                        provider="Google"
                        tasks="Tier 3 visual extraction — tables and charts that failed structural extraction. Reads cropped PNG images from PDFs."
                        cost="~$0.075/$0.30 per 1M tokens"
                        color="#f97316"
                        why="Best vision model for structured data extraction from document images. Generous rate limits for batch processing."
                    />
                    <ModelCard
                        name="text-embedding-3-large"
                        provider="OpenAI"
                        tasks="Dense embeddings for all 15,669 chunks at 1,536 dimensions (reduced from 3,072)."
                        cost="$0.13 per 1M tokens"
                        color="#94a3b8"
                        why="High-quality embeddings. Dimension reduction cuts storage 50% with <1% quality loss."
                    />
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 2: Batch Processing Architecture
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Batch Processing Architecture"
                description="All offline AI processing runs through batch APIs — Anthropic and OpenAI both offer 50% cost reduction for asynchronous jobs. The pipeline submits prompts, tracks job IDs, polls for completion, and hydrates results back to reports."
            >
                <DiagramCard title="Batch Job Lifecycle">
                    <MermaidDiagram
                        chart={batchDiagram}
                        caption="Prompts are prepared for all reports, submitted with custom_id mappings, polled for 1-2 hours, then results are parsed and merged with algorithmic data."
                    />
                </DiagramCard>

                <div style={{ marginTop: '20px', marginBottom: '20px' }}>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '16px' }}>
                        Each batch request carries a <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>custom_id</code> (max 64 chars)
                        that encodes the report ID and variant type. A mapping file persists the relationship between
                        custom IDs and source reports, enabling reliable result hydration even if jobs are retried.
                    </p>

                    <CodeBlock title="Batch ID Mapping">
{`custom_id format:  {prefix}_{hash}_{truncated_report_id}

Examples:
  "ov_a1b2c3d4_CAG_Railways_2023"       → Overview extraction
  "sm_ex_a1b2c3d4_CAG_Railways_2023"    → Executive summary
  "sm_jo_a1b2c3d4_CAG_Railways_2023"    → Journalist summary
  "sm_dd_a1b2c3d4_CAG_Railways_2023"    → Deep Dive summary

Mapping stored in job_*_mapping.json:
{
  "sm_ex_a1b2c3d4_CAG_Railways_2023": {
    "report_id": "CAG_Railways_Performance_2023_24",
    "variant": "executive"
  }
}`}
                    </CodeBlock>
                </div>

                {/* Extended Thinking Table */}
                <div style={{
                    border: '1px solid #e2e8f0', borderRadius: '10px',
                    overflow: 'hidden', marginBottom: '20px',
                }}>
                    <div style={{
                        padding: '12px 18px', background: '#faf5ff',
                        borderBottom: '1px solid #e2e8f0',
                        fontSize: '14px', fontWeight: 700, color: '#6b21a8',
                    }}>
                        Extended Thinking Configuration
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                        <thead>
                            <tr style={{ background: '#f8fafc', borderBottom: '2px solid #cbd5e1' }}>
                                {['Variant', 'Model', 'Max Tokens', 'Thinking Budget'].map((h) => (
                                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 700, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {[
                                ['Overview', 'Sonnet 4', '16,000', '5,000'],
                                ['Executive Brief', 'Sonnet 4', '16,000', '8,000'],
                                ['Journalist\'s Take', 'Opus 4', '20,000', '12,000'],
                                ['Deep Dive', 'Opus 4', '24,000', '16,000'],
                                ['Simple Explainer', 'Sonnet 4', '12,000', '6,000'],
                                ['Policy Brief', 'Sonnet 4', '16,000', '10,000'],
                            ].map(([variant, model, max, thinking]) => (
                                <tr key={variant} style={{ borderBottom: '1px solid #e2e8f0' }}>
                                    <td style={{ padding: '10px 14px', fontWeight: 600, color: '#1e293b' }}>{variant}</td>
                                    <td style={{ padding: '10px 14px', color: '#475569' }}>{model}</td>
                                    <td style={{ padding: '10px 14px', color: '#475569' }}>{max}</td>
                                    <td style={{ padding: '10px 14px', color: '#7c3aed', fontWeight: 600 }}>{thinking}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <DecisionCard
                    question="Why Extended Thinking, and why different budgets per variant?"
                    answer="Without Extended Thinking, summaries of 100+ page reports front-load early chapters and thin out toward the end. Thinking lets the model plan coverage across the entire document before writing. Deep Dive gets 16K thinking tokens because it's 4,000 words of analytical writing. Simple Explainer gets 6K because it's shorter and less analytical."
                    tradeoff="Thinking tokens are billed but never shown to the user. At batch pricing, it's ~$0.002 per 1K thinking tokens for Sonnet — a small premium for significantly better coverage."
                />
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 3: Summary Generation
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Summary Generation"
                description="5 summary variants per report, each with a distinct audience, structure, and tone. The prompts are the engineering — they define section structure, word allocations, style rules, and anti-patterns. Click through the tabs to see the actual prompts."
            >
                <div style={{ marginBottom: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>
                        Input Strategy: JSON Chunks, Not Raw PDFs
                    </h3>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        The summary prompts receive the output of the parsing pipeline — structured JSON chunks
                        with clean text, TOC hierarchy, and metadata — not the raw PDF text. This is a deliberate
                        cost and quality decision. A 120-page CAG report's raw PDF text includes repeated headers
                        and footers on every page, page numbers, OCR artifacts, table borders rendered as pipes
                        and dashes, and formatting noise. The parsed JSON has none of this.
                    </p>
                    <div style={{
                        display: 'grid', gridTemplateColumns: '1fr auto 1fr',
                        gap: '0', alignItems: 'stretch',
                        border: '1px solid #e2e8f0', borderRadius: '10px',
                        overflow: 'hidden', marginBottom: '16px',
                    }}>
                        <div style={{ padding: '16px 20px', background: '#fef2f2' }}>
                            <div style={{ fontSize: '12px', fontWeight: 700, color: '#dc2626', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                                Raw PDF Text (120 pages)
                            </div>
                            <div style={{ fontSize: '24px', fontWeight: 700, color: '#991b1b', marginBottom: '6px' }}>~70K tokens</div>
                            <div style={{ fontSize: '13px', color: '#b91c1c', lineHeight: 1.5 }}>
                                Repeated headers/footers, page numbers, OCR noise,
                                formatting artifacts, table borders as text, boilerplate disclaimers
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', padding: '0 12px', fontSize: '20px', color: '#94a3b8', background: '#f8fafc' }}>→</div>
                        <div style={{ padding: '16px 20px', background: '#f0fdf4' }}>
                            <div style={{ fontSize: '12px', fontWeight: 700, color: '#16a34a', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                                Parsed JSON Chunks
                            </div>
                            <div style={{ fontSize: '24px', fontWeight: 700, color: '#166534', marginBottom: '6px' }}>~30K tokens</div>
                            <div style={{ fontSize: '13px', color: '#15803d', lineHeight: 1.5 }}>
                                Clean content, structured hierarchy, tables as markdown,
                                semantic enrichment attached, no noise
                            </div>
                        </div>
                    </div>

                    <DecisionCard
                        question="Why not send the raw PDF directly to Claude (which supports PDF input)?"
                        answer="Three reasons. First, cost: ~40-50% fewer input tokens means ~40-50% lower API cost per summary — and this stacks with the 50% Batch API discount for a combined ~70-75% savings vs. naive 'upload PDF to Claude.' Second, quality: the LLM processes structured content with hierarchy context instead of fighting formatting noise. Third, consistency: every report goes through the same parsing pipeline, so summaries are generated from a uniform data format regardless of how messy the original PDF was."
                        tradeoff="Summaries can only reference content that survived the parsing pipeline. If parsing missed a section (rare, but possible), the summary won't cover it. We accept this because the quality-gated parsing pipeline captures 97%+ of report content."
                    />
                </div>

                <TabbedPrompt
                    title="Summary Prompt Variants"
                    description="Each variant uses Claude Batch API with Extended Thinking. Opus handles Journalist and Deep Dive; Sonnet handles the rest."
                    tabs={[
                        {
                            label: 'Executive Brief',
                            subtitle: 'Claude Sonnet 4 · 8K thinking · 2,200-2,500 words · Ministry secretaries, policymakers',
                            color: '#1a365d',
                            meta: 'src/batch_pipeline/prompts/summary_variants.py',
                            content: `You are creating an Executive Brief summary of this CAG audit report for senior government officials.

## Target Audience
- Ministry secretaries and joint secretaries
- Department heads
- Decision-makers who need to understand key issues quickly
- People preparing for parliamentary committee meetings

## Required Sections

### 1. Context & Scope (200-250 words)
- What entity/area was audited and why it matters
- Time period covered
- Type of audit (Performance/Compliance/Financial)
- Scale of operations examined

### 2. Critical Findings (800-1000 words)
- Present the TOP 7-10 most significant findings
- Order by monetary impact (highest first)
- For each finding include:
  - Clear statement of the issue
  - Specific amount in ₹ Crores
  - Reference to section/paragraph
  - Brief implication
- Use sub-headers to group related findings

### 3. Financial Impact Summary (300-400 words)
- Total monetary impact across all findings
- Breakdown by category (non-compliance, revenue loss, irregular expenditure, etc.)
- Breakdown by severity (critical, high, medium)

### 4. Key Recommendations (400-500 words)
- Summarize the main recommendations from the report
- Group by theme/area
- Indicate which require immediate attention

### 5. Action Items (200-250 words)
- Immediate steps required (0-3 months)
- Short-term actions (3-12 months)
- Key accountability points

## Style Guidelines
- Formal, professional tone suitable for government communication
- Always include specific numbers (₹X.XX Crore)
- Reference source sections (Section 3.4, Para 2.5.1)
- NO meta-commentary like "This report discusses..." — start directly with content`,
                        },
                        {
                            label: "Journalist's Take",
                            subtitle: 'Claude Opus 4 · 12K thinking · 2,000-2,200 words · News media, general public',
                            color: '#059669',
                            meta: 'src/batch_pipeline/prompts/summary_variants.py · Opus for creative writing quality',
                            content: `You are a senior investigative journalist at a major national newspaper
(like The Hindu, Indian Express, or Times of India) writing about this CAG audit report.

## Your Mission
Transform this government audit into a compelling news story that:
- Leads with the most dramatic yet accurate finding
- Makes complex government issues accessible to the general public
- Serves the public interest by highlighting accountability gaps
- Could actually run in tomorrow's paper

## Required Sections

### 1. The Headlines (5-7 options)
Write potential news headlines that could run in major papers:
- One main headline (dramatic but 100% accurate)
- 4-6 alternative angles for different editorial choices
- Style examples:
  - "₹3.5 Lakh Crore Gap: CAG Audit Exposes Tax Collection Failures"
  - "Railway Safety Funds Unspent as Accidents Continue, Reveals CAG"

### 2. The Lead Paragraph (150 words)
Classic inverted pyramid — most important facts first.

### 3. The Full Story (800-1000 words)
Write as a complete news article.

### 4. By The Numbers
8-12 key statistics as a "fast facts" sidebar.

### 5. The Context (200-250 words)
Background information and historical context.

### 6. What Happens Next (150-200 words)
Expected government responses and accountability timeline.

### 7. Quotable Findings
5-7 findings suitable for pull-quotes or social media posts.

## Style Guidelines
- Active voice: "The ministry failed to..." not "Failures were observed..."
- Short paragraphs (2-3 sentences max)
- Explain jargon: "AO (Assessing Officer)"
- Make amounts relatable: "₹12,000 Crore—enough to build 2,400 government schools"
- Be dramatic but NEVER exaggerate beyond what the data supports
- Write with controlled outrage appropriate for public interest journalism`,
                        },
                        {
                            label: 'Deep Dive',
                            subtitle: 'Claude Opus 4 · 16K thinking · 3,500-4,000 words · Researchers, academics, think tanks',
                            color: '#7c3aed',
                            meta: 'src/batch_pipeline/prompts/summary_variants.py · Highest thinking budget (16K)',
                            content: `You are creating a comprehensive academic analysis of this CAG audit report
for researchers, policy analysts, and serious students of governance.

## Target Audience
- Academic researchers studying Indian governance
- Policy analysts at think tanks (CPR, ORF, PRS, etc.)
- PhD students in public administration, economics, or political science
- International organizations studying audit systems
- Parliamentary research staff

## Required Sections

### 1. Audit Framework & Institutional Context (400-500 words)
- Legal basis (CAG Act, Constitution Article 151)
- Type of audit and its significance
- Audit standards applied (SAI standards, international benchmarks)
- Institutional relationship between CAG, PAC, and audited entity

### 2. Methodology Analysis (500-600 words)
- Scope, coverage, sampling methodology
- Time period and rationale for selection
- Data sources (records, field visits, third-party data)
- Analytical methods employed
- Limitations acknowledged by CAG

### 3. Findings Analysis by Theme (1500-2000 words)
For EACH major thematic area:
- Key findings with exact paragraph/section references
- Quantitative data and statistical patterns
- Cross-case patterns and variations
- Severity distribution within theme
- Causal analysis where provided

### 4. Quantitative Summary (400-500 words)
- Complete statistical breakdown of findings
- Cross-tabulations (severity × type, ministry × amount)

### 5. Systemic Issues Identified (400-500 words)
- Root causes identified by the audit
- Structural/institutional problems
- Regulatory and policy gaps

### 6. Recommendations Analysis (400-500 words)
- Classification by type: policy, process, system, capacity, legal
- Feasibility assessment based on past implementation

### 7. Research Implications (300-400 words)
- Questions for further academic research
- Data gaps and comparative possibilities

### 8. Technical Appendix
- Section list, glossary, Acts referenced, key entities

## Style Guidelines
- Academic tone, formal citation style: (Section 3.4.2, p. 45)
- Present data in tabular format where appropriate
- Maintain analytical objectivity
- Acknowledge limitations and alternative interpretations`,
                        },
                        {
                            label: 'Simple Explainer',
                            subtitle: 'Claude Sonnet 4 · 6K thinking · 1,200-1,500 words · Students, non-experts, citizens',
                            color: '#f59e0b',
                            meta: 'src/batch_pipeline/prompts/summary_variants.py',
                            content: `You are explaining this government audit report to regular citizens who have
no background in finance, accounting, or government procedures.

## Your Goal
Make this completely understandable to:
- A college student who doesn't study economics
- A small shop owner or farmer
- A retired person reading the newspaper
- Anyone who pays taxes but doesn't understand government jargon
- Someone who has 10 minutes to understand what happened

## Required Sections (Use Q&A Format with Simple Headers)

### What Is This Report About?
- Explain like you're telling a neighbor over tea
- NO jargon whatsoever (or explain it immediately)
- Why should ordinary people care?

### What Did They Find Wrong?
- Top 5-7 problems in plain, everyday language
- Use relatable analogies:
  "It's like if you gave money to a contractor to build your house,
   but they used cheaper materials and kept the difference..."
- Make amounts relatable:
  - "₹12,000 Crore—that's enough money to give ₹1,000 to 12 crore families"
  - "This is like losing ₹90 from every ₹100 collected"

### Why Should I Care?
- How does this directly affect regular people?
- What services might be worse because of this?
- What happens to "your tax money"?

### Who Is Responsible?
- Which government department or officials
- Keep it factual, don't be preachy or political

### What Should Happen Now?
- Simple action items anyone can understand

### The Bottom Line (5-6 bullets)
- Most important takeaways in one sentence each

## Style Guidelines
- Very short sentences (under 15-20 words)
- Use "you" and "your taxes" and "your money"
- ZERO jargon without explanation:
  - AO → "the tax officer"
  - FY → "financial year (April to March)"
  - Non-compliance → "not following the rules"
- Treat readers as smart people who just need translation`,
                        },
                        {
                            label: 'Policy Brief',
                            subtitle: 'Claude Sonnet 4 · 10K thinking · 2,200-2,500 words · Government officials, legislators',
                            color: '#dc2626',
                            meta: 'src/batch_pipeline/prompts/summary_variants.py',
                            content: `You are creating a Policy Brief for government officials who need to prepare
formal responses to this CAG audit and implement corrective actions.

## Target Audience
- Ministry officials preparing Action Taken Notes
- Department heads implementing reforms
- Policy advisors drafting compliance responses
- Parliamentary committee members reviewing audit findings

## Required Sections

### 1. Policy & Regulatory Context (300-350 words)
- Relevant laws, rules, and regulations
- Policy framework under which the entity operates
- Recent policy changes that may be relevant

### 2. Compliance Gaps Identified (500-600 words)
A. Regulatory Non-Compliance
  - Specific statutory provisions violated (cite Act/Rule/Section)
B. Process & Procedural Failures
  - SOPs not followed, documentation gaps
C. System & Monitoring Weaknesses
  - IT deficiencies, MIS failures

### 3. Financial Implications (300-350 words)
- Total revenue loss or potential recovery amount
- Breakdown by category of irregularity
- Recurring versus one-time financial impact

### 4. Prioritized Action Plan (600-700 words)
IMMEDIATE ACTIONS (0-3 months):
  - Quick fixes, policy clarifications, circulars to issue
SHORT-TERM ACTIONS (3-12 months):
  - Process re-engineering, training, system modifications
MEDIUM-TERM ACTIONS (1-2 years):
  - Legislative amendments, structural reforms

### 5. Implementation Framework (300-350 words)
- Responsible officers/departments for each action
- Monitoring mechanisms, review frequency, KPIs

### 6. Risk Assessment (200-250 words)
- Consequences if issues continue unaddressed
- PAC proceedings, court cases, reputational risks

### 7. Draft Response Template
Outline for the ministry's formal Action Taken Note:
- Para-wise response structure
- Points to accept vs. clarify
- Timeline commitments

## Style Guidelines
- Government/bureaucratic terminology appropriately used
- Reference relevant GFR/CVC/DoPT guidelines
- Format for easy tracking of action items`,
                        },
                    ]}
                    maxHeight={520}
                />

                <DecisionCard
                    question="Why Opus for Journalist and Deep Dive, but Sonnet for the other three?"
                    answer="Journalist's Take requires genuine creative writing — compelling ledes, headline options, controlled outrage. Deep Dive requires sustained analytical reasoning across 4,000 words. Both need Opus's stronger reasoning and writing. Executive, Simple, and Policy follow more structured templates where Sonnet's quality is sufficient."
                    tradeoff="Opus costs 5× more than Sonnet. Using it for only 2 of 5 variants keeps per-report cost at ~$0.50 instead of ~$1.50."
                />
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 4: Overview Extraction & Merge
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Overview Extraction & Merge"
                description="Each report's overview page combines algorithmic extraction (TOC, findings, entities — already computed in the parsing pipeline) with LLM-extracted fields that heuristics can't parse: audit scope, objectives, topic mappings, and glossary terms."
            >
                <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '16px' }}>
                    The parsing pipeline already extracts structured data — TOC hierarchy, findings with severity and monetary amounts,
                    recommendations, entity lists. But some metadata requires understanding context:
                    "This audit covers the period 2017-18 to 2021-22 across 28 states" isn't a pattern a regex can reliably capture
                    from inconsistently formatted reports. Claude Sonnet extracts these fields from the introduction, scope,
                    and objectives sections, then the merge script combines both sources into a
                    unified <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>{'{report_id}'}_overview.json</code>.
                </p>

                <div style={{
                    display: 'grid', gridTemplateColumns: '1fr auto 1fr',
                    gap: '0', alignItems: 'stretch',
                    border: '1px solid #e2e8f0', borderRadius: '10px',
                    overflow: 'hidden', marginBottom: '20px',
                }}>
                    <div style={{ padding: '16px 20px', background: '#f0f9ff' }}>
                        <div style={{ fontSize: '12px', fontWeight: 700, color: '#0369a1', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>Algorithmic (Free)</div>
                        <div style={{ fontSize: '13px', color: '#0c4a6e', lineHeight: 1.6 }}>
                            Report metadata (title, ministry, year)<br />
                            TOC structure with page ranges<br />
                            Findings summaries + severity<br />
                            Monetary aggregates<br />
                            Entity lists<br />
                            Recommendations
                        </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', padding: '0 12px', fontSize: '18px', color: '#94a3b8', background: '#f8fafc' }}>+</div>
                    <div style={{ padding: '16px 20px', background: '#faf5ff' }}>
                        <div style={{ fontSize: '12px', fontWeight: 700, color: '#7c3aed', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>LLM-Extracted (~$0.035/report)</div>
                        <div style={{ fontSize: '13px', color: '#581c87', lineHeight: 1.6 }}>
                            Audit scope (period, geography, sample size)<br />
                            Audit objectives (verbatim from report)<br />
                            Topics covered (neutral names + page ranges)<br />
                            Glossary & abbreviations with definitions<br />
                            Entity categorization
                        </div>
                    </div>
                </div>

                <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '16px' }}>
                    The overview extraction prompt enforces a critical rule for topics: <strong>use neutral descriptive names</strong>,
                    not finding-based names. "Tax Assessment Procedures" instead of "Assessment Errors."
                    "Revenue Collection Mechanisms" instead of "Revenue Loss." This makes topics useful for navigation —
                    a user browsing the report wants to find sections by subject area, not by what went wrong.
                </p>

                <CalloutBox type="note">
                    <strong>Prompt Architecture Note:</strong> The overview prompt explicitly lists what's already been extracted
                    ("Report metadata ✓, Findings with severity ✓, Recommendations ✓") and instructs Claude
                    to extract ONLY the 4 missing fields. This prevents duplication and keeps the LLM focused on
                    what heuristics can't do.
                </CalloutBox>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 5: Extraction & Enrichment Prompts
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Extraction & Enrichment Prompts"
                description="Beyond summaries and overviews, AI is used for structural extraction (TOC validation, visual table/chart parsing), semantic enrichment (finding and entity extraction), and query-time enhancement."
            >
                <TabbedPrompt
                    title="Offline Extraction Prompts"
                    description="These prompts run during batch processing. Each is optimized for its specific extraction task."
                    tabs={[
                        {
                            label: 'TOC Validation',
                            subtitle: 'Claude Haiku 4.5 · Phase 5.7 · Only fires when TOC quality < 50 (~15% of reports)',
                            color: '#ec4899',
                            meta: 'src/parsing_pipeline/modules/toc_llm_validator.py',
                            content: `SYSTEM:
You are a document structure analyzer specializing in Indian government
audit reports (CAG reports).

Your task: Extract or validate the Table of Contents from the provided text.

Rules:
1. Each TOC entry has: level (1=chapter, 2=section, 3=subsection), title, page
2. Common Level 1: Preface, Executive Summary, Chapter I/II/III, Annexure
3. Common Level 2: numbered sections like 1.1, 2.3, or lettered like A. Karnataka
4. Common Level 3: sub-sections like 1.1.1, 2.3.2
5. Page numbers refer to PRINTED page numbers (not PDF page numbers)
6. Ignore table captions, figure numbers, headers/footers

USER:
Here is text from the first pages of a CAG audit report.
{existing_toc_section}
Extract the complete Table of Contents. Return ONLY a JSON array:
[level, "title", page_number]

Example:
[
  [1, "Preface", 1],
  [1, "Executive Summary", 3],
  [1, "Chapter I Introduction", 7],
  [2, "1.1 Background", 8],
  [2, "1.2 Audit Objectives", 10],
  [1, "Chapter II Compliance Audit", 15],
  [2, "2.1 Tax Assessment Issues", 16],
  [3, "2.1.1 Short Levy of Tax", 17]
]

Document text (first ~15 pages):
---
{document_text}
---

Return ONLY the JSON array, no explanations.`,
                        },
                        {
                            label: 'Gemini Tables',
                            subtitle: 'Gemini 2.5 Flash · Phase 10b · Tier 3 fallback for tables that failed pdfplumber + Docling',
                            color: '#f97316',
                            meta: 'src/batch_pipeline/enrichment/gemini_visual_extractor.py',
                            content: `You are an expert at extracting structured data from Indian government
audit report tables.

Analyze this table image and extract ALL data into a clean markdown table.

CRITICAL RULES:
1. Preserve EVERY row and column — do not skip or summarize
2. Indian number formats: use commas as-is (e.g., 1,23,456.78)
3. Fiscal years: preserve format exactly (e.g., 2021-22)
4. Currency: preserve units (crore, lakh) if shown in headers
5. Merged cells: repeat the value in each spanned cell
6. Multi-level headers: flatten into single header row with combined labels
7. "(continued)" markers: this is a continuation table, include all data
8. Empty cells: leave blank (don't write "N/A" unless that's what's printed)

OUTPUT FORMAT — respond with ONLY a JSON object, no markdown fences:
{
  "title": "Table title if visible, or null",
  "markdown": "| Header1 | Header2 |\\n| --- | --- |\\n| data | data |",
  "monetary_unit": "crore/lakh/null",
  "extraction_notes": ["any issues encountered"],
  "row_count": 10,
  "col_count": 5
}`,
                        },
                        {
                            label: 'Gemini Charts',
                            subtitle: 'Gemini 2.5 Flash · Phase 10b · Extracts data points from chart images',
                            color: '#84cc16',
                            meta: 'src/batch_pipeline/enrichment/gemini_visual_extractor.py',
                            content: `You are an expert at extracting structured data from charts in Indian
government audit reports.

Analyze this chart image and extract ALL visible data points.

CRITICAL RULES:
1. Read EVERY data point — use axis gridlines to estimate values
2. Indian number formats: preserve commas (1,23,456)
3. Fiscal years: preserve format (2021-22, FY2023)
4. Percentage values: include % symbol
5. For bar/line charts: read each bar/point against the Y-axis
6. For pie charts: extract label + percentage/value for each slice
7. Multi-series: identify each series by its legend label

OUTPUT FORMAT — respond with ONLY a JSON object:
{
  "title": "Chart title",
  "chart_type": "bar|line|pie|scatter|area|combo|unknown",
  "x_axis_label": "X axis label",
  "y_axis_label": "Y axis label",
  "monetary_unit": "crore/lakh/null",
  "series": [
    {
      "name": "Series name from legend",
      "data_points": [
        {"category": "2021-22", "value": 1234.56},
        {"category": "2022-23", "value": 2345.67}
      ]
    }
  ],
  "description": "One-sentence summary of what the chart shows"
}`,
                        },
                        {
                            label: 'Finding Extraction',
                            subtitle: 'GPT-4o-mini / Claude Sonnet · Batch enrichment · Extracts structured findings per chunk',
                            color: '#ef4444',
                            meta: 'src/batch_pipeline/prompts/finding_extraction.py',
                            content: `You are analyzing a chunk from a CAG audit report.

TASK: Extract all audit findings from this text.

For each finding, provide:
1. finding_type: One of:
   - irregular_expenditure (unauthorized or improper spending)
   - loss_of_revenue (revenue not collected/recovered)
   - wasteful_expenditure (unnecessary or unproductive spending)
   - non_compliance (violation of rules/regulations)
   - system_deficiency (weaknesses in processes/controls)
   - performance_shortfall (targets/objectives not met)
   - fraud_misappropriation (deliberate misuse of funds)
   - procedural_lapse (failure to follow procedures)

2. summary: One sentence summary (max 150 chars)
3. monetary_amount: Numeric value (null if no amount)
4. currency_unit: "crore" / "lakh" / "thousand" / null
5. severity: Based on monetary value and impact:
   - critical: >₹100 crore OR systemic fraud/failure
   - high: ₹10-100 crore OR significant non-compliance
   - medium: ₹1-10 crore OR moderate issues
   - low: <₹1 crore OR minor procedural lapses
6. entities: Specific entities mentioned (ministries, schemes, PSUs)
7. evidence_refs: Table/para/annexure references

IMPORTANT:
- Only extract findings explicitly stated as audit observations
- Handle Indian number formats (crore/lakh)
- Parenthetical amounts are negative: "(₹50 crore)" = -50
- If no findings exist, return {"findings": []}`,
                        },
                        {
                            label: 'Query Enhancement',
                            subtitle: 'GPT-4o-mini · Online · Runs per user query to expand search terms and detect question type',
                            color: '#06b6d4',
                            meta: 'src/rag_pipeline/query_enhancer.py',
                            content: `You analyze questions about Indian CAG audit reports.

Return ONLY valid JSON with this schema:
{
  "question_type": "factual|list|aggregation|comparison|explanation|procedural",
  "expanded_queries": ["original reworded for search", "alternative with domain terms"],
  "suggested_filters": {},
  "retrieval_params": {"top_k": 10, "initial_candidates": 50, "max_context_chars": 15000},
  "recommended_style": "concise|detailed|executive|technical|comparative|explanatory"
}

Rules for expanded_queries:
- Generate exactly 2 alternative queries
- Rephrase using CAG/audit vocabulary
  (e.g., "money lost" → "revenue loss quantified in crore")
- Include specific terms likely in audit reports
  (findings, observations, recommendations, compliance)
- If entity mentioned, include full name AND acronym in different queries

Rules for suggested_filters:
- Only include filters you're confident about. Empty {} is fine.
- Valid keys: "finding_type" (loss_of_revenue|non_compliance|fraud|...),
  "severity" (critical|high|medium|low)

Rules for retrieval_params (scale to complexity):
- factual:     {"top_k": 8,  "initial_candidates": 30, "max_context_chars": 10000}
- list:        {"top_k": 18, "initial_candidates": 80, "max_context_chars": 25000}
- comparison:  {"top_k": 15, "initial_candidates": 60, "max_context_chars": 22000}
- explanation: {"top_k": 12, "initial_candidates": 50, "max_context_chars": 18000}`,
                        },
                        {
                            label: 'Table Summary',
                            subtitle: 'GPT-4o-mini · Indexing · ~$0.0001 per table · Generates natural language for embedding',
                            color: '#64748b',
                            meta: 'src/rag_pipeline/embedding_service.py · TableSummaryService',
                            content: `Summarize this table from a CAG (Comptroller and Auditor General) audit
report in 1-2 sentences. Focus on: what data it shows, time period
covered, key totals or trends.

Context: {context}

Table:
{table_text}

Summary (1-2 sentences, be specific about numbers and entities):

---

Example input:
  Context: "Chapter 2 > Revenue Collection > Tax Assessment"
  Table: | State | Revenue (₹ crore) | Growth (%) |
         | Maharashtra | 12,450 | 8.3 |
         | Tamil Nadu | 8,920 | 6.1 |
         | ...

Example output:
  "Table showing state-wise revenue collection for FY 2022-23,
   with Maharashtra contributing ₹12,450 crore (highest) and
   total of ₹45,230 crore across 8 states."

---

Why this exists:
Markdown tables embed poorly — a 15-row table produces a vector
that says "pipes and dashes" more than "state-wise revenue."
This summary is prepended to the table before embedding, making
tables findable via semantic queries like "revenue by state."

Fallback: If LLM fails, rule-based extraction grabs header row
+ row count as a minimal summary.`,
                        },
                    ]}
                    maxHeight={480}
                />
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 6: RAG Chat Prompt Architecture
            ══════════════════════════════════════════════ */}
            <DocSection
                title="RAG Chat Prompt Architecture"
                description="The chat system uses a layered prompt: a shared base (domain expertise + anti-hallucination rules + citation format) combined with a style-specific layer. The base ensures correctness; the style layer controls format and tone."
            >
                {/* Base + Citation shown inline */}
                <div style={{ marginBottom: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Shared Prompt Layers (included in every style)</h3>
                    <div style={{
                        display: 'grid', gap: '10px', marginBottom: '16px',
                    }}>
                        {[
                            {
                                layer: 'Base Expertise',
                                desc: 'CAG domain knowledge. CRITICAL RULES: only state facts in context, never invent amounts, never extrapolate. If info isn\'t in context, say so explicitly.',
                                bg: '#f8fafc', border: '#e2e8f0', color: '#1e293b',
                            },
                            {
                                layer: 'Anti-Pattern Rules',
                                desc: 'FORBIDDEN: "The question is asking...", "Based on the context...", "Let me analyze...", "Here\'s what I found...". REQUIRED: Start directly with the answer. Use proper markdown headers and bullet points.',
                                bg: '#fef2f2', border: '#fecaca', color: '#991b1b',
                            },
                            {
                                layer: 'Citation Rules',
                                desc: 'Copy the EXACT [Source: ...] label from context passages. Place at END of sentence, never mid-sentence. Every amount and every finding must be cited. Group related facts, cite once.',
                                bg: '#eff6ff', border: '#bfdbfe', color: '#1e40af',
                            },
                        ].map((item) => (
                            <div key={item.layer} style={{
                                padding: '14px 18px', background: item.bg,
                                border: `1px solid ${item.border}`, borderRadius: '8px',
                                display: 'grid', gridTemplateColumns: '160px 1fr',
                                gap: '14px', alignItems: 'start',
                            }}>
                                <div style={{ fontSize: '13px', fontWeight: 700, color: item.color }}>{item.layer}</div>
                                <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6 }}>{item.desc}</div>
                            </div>
                        ))}
                    </div>

                    <DecisionCard
                        question="Why source-label citation instead of letting the LLM generate section references?"
                        answer="The backend adds [Source: Section Name, p.XX] labels above each context passage. The LLM is told to copy these labels exactly. This achieves ~95% citation accuracy because the model doesn't need to infer section numbers — it just copies what it sees."
                        tradeoff="Requires consistent source labeling in context assembly. But eliminates the class of errors where the LLM invents section numbers like '[Section 1, p.11]' when the actual source was '[Executive Summary, p.11]'."
                    />
                </div>

                {/* Style Prompts in Tabs */}
                <TabbedPrompt
                    title="Response Style Prompts"
                    description="Each style adds its own structure, word count, and formatting rules on top of the shared base. The frontend exposes 6 styles; 2 more are available programmatically."
                    tabs={[
                        {
                            label: 'Concise',
                            subtitle: '50-100 words · Quick answers, mobile users',
                            color: '#1a365d',
                            meta: 'rag_service.py · CONCISE',
                            content: `## RESPONSE STYLE: Concise

### What to deliver:
A focused, direct answer in 3-5 sentences. No headers, no bullet points.

### Structure:
1. Lead with the key finding/answer
2. Include the main amount (₹ crore)
3. Add 1-2 supporting details
4. End with citation(s)

### Word count: 50-100 words

### Example:
The audit identified revenue loss of ₹64.60 crore due to delayed toll
collection at NHAI projects. Non-functional electronic equipment at 12
toll plazas was the primary cause, representing a 23% increase from the
previous year. The Ministry has acknowledged these findings.
[Section 3.2.1, p.36]`,
                        },
                        {
                            label: 'Executive',
                            subtitle: '150-250 words · Bottom-line first for decision-makers',
                            color: '#059669',
                            meta: 'rag_service.py · EXECUTIVE',
                            content: `## RESPONSE STYLE: Executive Summary

### What to deliver:
Business-focused summary with bottom line first, then key supporting points.

### Structure:
### Key Finding
[One sentence: Main finding + primary amount + citation]

### Summary
- **[Category 1]**: Amount and finding. [Citation]
- **[Category 2]**: Amount and finding. [Citation]
- **[Category 3]**: Amount and finding. [Citation]

### Action Required
[One sentence on implications or recommended action]

### Requirements:
- Bottom line FIRST (most important finding)
- 3-5 bullet points maximum
- Each bullet: specific amount + finding + citation
- End with implication/action
- No lengthy explanations

### Word count: 150-250 words`,
                        },
                        {
                            label: 'Detailed',
                            subtitle: '300-500 words · Comprehensive analysis with all relevant context',
                            color: '#7c3aed',
                            meta: 'rag_service.py · DETAILED',
                            content: `## RESPONSE STYLE: Detailed

### What to deliver:
Comprehensive, well-structured response covering all relevant aspects.

### Structure:
### Overview
[2-3 sentences introducing the topic and key takeaway]

### Key Findings
[Main findings with amounts and citations — bullets if 3+ items]

### Context & Background
[Additional relevant details, causes, or circumstances]

### Implications
[Significance, impact, or recommendations if mentioned]

### Requirements:
- Cover ALL relevant information from context
- Use headers to organize (###)
- Include specific amounts with citations
- Provide context and implications
- Every major claim needs a citation

### Word count: 300-500 words`,
                        },
                        {
                            label: 'Technical',
                            subtitle: '400-600 words · Deep analysis with data tables and root causes',
                            color: '#0891b2',
                            meta: 'rag_service.py · TECHNICAL',
                            content: `## RESPONSE STYLE: Technical Analysis

### What to deliver:
Deep, analytical examination with technical detail, data analysis,
and systemic insights.

### Structure:
### Executive Summary
[2-3 sentences with key metrics and overall assessment]

### Detailed Analysis
#### [Theme/Category 1]
[Technical analysis with specific data points, percentages, trends]
[Multiple citations throughout]

#### [Theme/Category 2]
[Technical analysis with data points]

### Data Highlights
| Metric | Value | Reference |
|--------|-------|-----------|
| [Metric 1] | ₹XX crore | [Citation] |
| [Metric 2] | XX% | [Citation] |

### Systemic Issues
[Analysis of root causes, patterns, structural problems]

### Technical Recommendations
[Specific technical/procedural recommendations from audit]

### Requirements:
- Include ALL relevant numerical data
- Show calculations or breakdowns where available
- Analyze patterns and root causes
- Use tables for comparative data
- Every data point cited

### Word count: 400-600 words`,
                        },
                        {
                            label: 'Comparative',
                            subtitle: '300-500 words · Theme-based cross-year analysis with trend indicators',
                            color: '#f59e0b',
                            meta: 'rag_service.py · COMPARATIVE',
                            content: `## RESPONSE STYLE: Comparative Analysis

### What to deliver:
Cross-year or cross-report analysis organized by THEME (not chronologically).

### Structure:
### Overview
[1-2 sentences on scope and key trend]

### [Theme 1: e.g., Fiscal Deficit]
**Trend**: [↑ Improving / ↓ Worsening / → Stable]

- **[Year 1]**: [Value/Finding]. [Year - Section, p.XX]
- **[Year 2]**: [Value/Finding]. [Year - Section, p.XX]
- **[Year 3]**: [Value/Finding]. [Year - Section, p.XX]

[1-2 sentences analyzing this theme's trend]

### [Theme 2: e.g., Revenue Collection]
**Trend**: [↑/↓/→]
...

### Key Patterns
[2-3 sentences on recurring issues or notable changes]

### Requirements:
- Organize by THEME, not by year
- Show trend direction (↑ ↓ →)
- MUST include year in citations: [2022-23 - Section 3.2, p.54]
- Highlight improvements AND deteriorations
- Note persistent/recurring issues

### Word count: 300-500 words`,
                        },
                        {
                            label: 'Adaptive',
                            subtitle: 'Variable · Auto-detects question type and adjusts format accordingly',
                            color: '#64748b',
                            meta: 'rag_service.py · ADAPTIVE',
                            content: `## RESPONSE STYLE: Adaptive

Analyze the question and respond with the appropriate format:

### For FACTUAL questions ("What was X?", "How much was Y?")
→ Direct answer in 2-4 sentences
→ Key finding first, then supporting detail
→ 50-100 words

### For LIST questions ("List all...", "What are the...", "Name the...")
→ Proper bullet format:
  - **Item 1**: Description. [Citation]
  - **Item 2**: Description. [Citation]
→ Include ALL items from context
→ 100-300 words

### For AGGREGATION ("What was total...", "How much overall...")
→ State the total if explicitly in context
→ If no total stated: "Components include: [list them]"
→ NEVER calculate totals yourself
→ 50-150 words

### For COMPARISON ("Compare...", "How has X changed...", "Trend...")
→ Organize by THEME, not by year
→ Use trend indicators (↑ ↓ →)
→ Include year in citations
→ 200-400 words

### For EXPLANATION ("Why...", "Explain...", "What caused...")
→ Structure: Finding → Causes → Factors → Consequences
→ Connect cause to effect clearly
→ 200-350 words

### Always:
- Start DIRECTLY with the answer
- Include citations for all facts
- Use exact amounts from context`,
                        },
                        {
                            label: 'Explanatory',
                            subtitle: '250-400 words · Cause → effect analysis with evidence chains',
                            color: '#a855f7',
                            meta: 'rag_service.py · EXPLANATORY (backend-only)',
                            content: `## RESPONSE STYLE: Explanatory

### What to deliver:
Clear explanation of causes, reasons, and mechanisms behind findings.

### Structure:
### The Finding
[What happened — the fact being explained]

### Root Causes
[Primary reasons/causes with evidence]

### Contributing Factors
[Secondary factors that contributed]

### Consequences
[Impact or implications of the finding]

### Requirements:
- Clearly connect cause to effect
- Provide evidence for each causal claim
- Distinguish primary from secondary causes
- Explain mechanisms, not just list facts
- Use logical flow

### Word count: 250-400 words`,
                        },
                        {
                            label: 'Report',
                            subtitle: '500-800 words · Formal document structure with numbered sections and tables',
                            color: '#1e293b',
                            meta: 'rag_service.py · REPORT (backend-only)',
                            content: `## RESPONSE STYLE: Formal Report

### What to deliver:
A structured, formal document suitable for official use.

### Structure:
### 1. Introduction
[Scope, period, and audit mandate]

### 2. Key Findings
#### 2.1 [Finding Category 1]
[Detailed finding with amounts and citations]
#### 2.2 [Finding Category 2]
[Detailed finding with amounts and citations]

### 3. Financial Impact
| Category | Amount (₹ crore) | Reference |
|----------|------------------|-----------|
| [Type 1] | [Amount] | [Citation] |
| [Type 2] | [Amount] | [Citation] |
| **Total** | **[Sum]** | - |

### 4. Audit Recommendations
[Key recommendations from the audit]

### 5. Ministry Response
[Response/acceptance status if mentioned]

### 6. Conclusion
[Summary assessment]

### Requirements:
- Use numbered sections
- Formal, objective tone
- Include all relevant amounts
- Use tables for financial data
- CAG terminology
- Every claim cited

### Word count: 500-800 words`,
                        },
                    ]}
                    maxHeight={460}
                />
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 7: Prompt Engineering Patterns
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Prompt Engineering Patterns"
                description="Cross-cutting techniques used across multiple prompts. These patterns emerged from iteration — each solves a specific failure mode we observed during development."
            >
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px' }}>
                    <PatternCard
                        title="JSON Output Enforcement"
                        description="All structured extraction prompts need reliable JSON output. We layer 4 techniques for near-100% parse success."
                        techniques={['Explicit schema in prompt', 'Output guards ("ONLY valid JSON")', 'OpenAI response_format', 'Fallback fence-stripping']}
                    />
                    <PatternCard
                        title="Anti-Hallucination"
                        description="RAG prompts must prevent fabricated amounts and invented section references. Three layers of defense."
                        techniques={['CRITICAL RULES block', '"NEVER invent amounts"', 'Source-label citations', '"Not available in context"']}
                    />
                    <PatternCard
                        title="Audience Adaptation"
                        description="Summary variants demonstrate 5 distinct audience models — from 'ministry secretary' to 'shop owner telling a neighbor over tea.'"
                        techniques={['Target audience lists', 'Tone calibration', 'Jargon translation rules', 'Relatable comparisons']}
                    />
                    <PatternCard
                        title="Word Count Control"
                        description="Each prompt specifies both total target and per-section allocations. This prevents front-loading and ensures coverage."
                        techniques={['Total word target', 'Per-section allocations', 'Structure templates', 'Example outputs']}
                    />
                    <PatternCard
                        title="Missing Data Handling"
                        description="Time series prompts explicitly instruct: state missing data, don't hallucinate, don't skip years silently."
                        techniques={['"Data not available for [YEAR]"', 'Never estimate or guess', 'Year in every citation', 'Explicit gap statements']}
                    />
                    <PatternCard
                        title="Domain Vocabulary"
                        description="CAG-specific terminology is embedded in prompts: 'short levy', 'infructuous expenditure', 'revenue foregone', fiscal year formats."
                        techniques={['CAG terminology glossary', 'Indian number formats', 'Fiscal year patterns', 'Entity naming conventions']}
                    />
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 8: Cost Architecture
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Cost Architecture"
                description="Every model choice has a cost rationale. The system is designed so the most expensive model (Opus) is used for the fewest tasks, and the cheapest (GPT-4o-mini) handles the highest-volume work."
            >
                <div style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '20px',
                }}>
                    {/* Per-Report */}
                    <div style={{ padding: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '14px' }}>Per-Report Processing Cost</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['TOC Validation (15% of reports)', '~$0.015', '#1a365d'],
                                ['Overview Extraction', '~$0.035', '#d946ef'],
                                ['Executive + Simple + Policy summaries', '~$0.11', '#d946ef'],
                                ['Journalist + Deep Dive summaries', '~$0.35', '#ef4444'],
                                ['Visual Extraction (avg 5 items)', '~$0.01', '#f97316'],
                                ['Table Summaries (avg 10 tables)', '~$0.001', '#22c55e'],
                                ['Dense Embeddings (avg 100 chunks)', '~$0.002', '#94a3b8'],
                            ].map(([item, cost, color]) => (
                                <div key={item} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569' }}>{item}</span>
                                    <span style={{ fontWeight: 600, color: color as string }}>{cost}</span>
                                </div>
                            ))}
                            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderTop: '2px solid #e2e8f0', marginTop: '4px' }}>
                                <span style={{ fontWeight: 700, color: '#1e293b' }}>Total per report</span>
                                <span style={{ fontWeight: 700, color: '#1a365d' }}>~$0.50-0.55</span>
                            </div>
                        </div>
                        <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '10px' }}>
                            Without Opus summaries: ~$0.15-0.20/report
                            JSON chunks save ~40-50% on input tokens vs. raw PDF — stacking with 50% batch discount for ~70-75% total savings.
                        </div>
                    </div>

                    {/* Per-Query */}
                    <div style={{ padding: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '14px' }}>Per-Query Cost</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['Query Enhancement (GPT-4o-mini)', '~$0.0002'],
                                ['Query Embedding', '~$0.0001'],
                                ['Cohere Reranking', '~$0.002'],
                                ['RAG Generation (Claude Sonnet)', '~$0.005-0.01'],
                            ].map(([item, cost]) => (
                                <div key={item} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569' }}>{item}</span>
                                    <span style={{ fontWeight: 600, color: '#1e293b' }}>{cost}</span>
                                </div>
                            ))}
                            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderTop: '2px solid #e2e8f0', marginTop: '4px' }}>
                                <span style={{ fontWeight: 700, color: '#1e293b' }}>Total per query (Claude)</span>
                                <span style={{ fontWeight: 700, color: '#1a365d' }}>~$0.008-0.015</span>
                            </div>
                        </div>
                        <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '10px' }}>
                            With GPT-4o-mini RAG: ~$0.003-0.006/query
                        </div>
                    </div>
                </div>

                {/* Monthly Projections */}
                <div style={{
                    border: '1px solid #e2e8f0', borderRadius: '10px',
                    overflow: 'hidden', marginBottom: '20px',
                }}>
                    <div style={{ padding: '12px 18px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0', fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>
                        Monthly Query Cost Projections
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                        <thead>
                            <tr style={{ borderBottom: '2px solid #cbd5e1' }}>
                                {['Query Volume', 'Claude RAG', 'GPT-4o-mini RAG'].map((h) => (
                                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 700, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {[
                                ['1,000/month', '~$10-15', '~$4-6'],
                                ['10,000/month', '~$100-150', '~$40-60'],
                                ['100,000/month', '~$1,000-1,500', '~$400-600'],
                            ].map(([vol, claude, gpt]) => (
                                <tr key={vol} style={{ borderBottom: '1px solid #e2e8f0' }}>
                                    <td style={{ padding: '10px 14px', fontWeight: 600, color: '#1e293b' }}>{vol}</td>
                                    <td style={{ padding: '10px 14px', color: '#d946ef', fontWeight: 600 }}>{claude}</td>
                                    <td style={{ padding: '10px 14px', color: '#22c55e', fontWeight: 600 }}>{gpt}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <CalloutBox type="success">
                    <strong>8 cost optimization strategies:</strong> JSON chunks as input (~40-50% fewer tokens than raw PDF),
                    Batch API (50% off), model tiering (Opus only for 2/5 summaries),
                    Haiku for validation ($0.015 vs $0.04 with Sonnet), GPT-4o-mini for commodity tasks (20× cheaper),
                    built-in BM25 (zero-cost sparse vectors), dimensionality reduction (1536 vs 3072),
                    and query enhancement caching (cached per session). JSON chunks + batch discount stack for ~70-75% total savings vs. naive PDF-to-Claude approach.
                </CalloutBox>
            </DocSection>
        </div>
    );
};