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

const PhaseLabel: React.FC<{ number: string; title: string; color?: string }> = ({
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
            PHASE {number}
        </span>
        <span style={{ fontSize: '15px', fontWeight: 600, color: '#334155' }}>{title}</span>
    </div>
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

const TierRow: React.FC<{
    tier: string;
    tool: string;
    when: string;
    speed: string;
    qualityGate: string;
    color: string;
}> = ({ tier, tool, when, speed, qualityGate, color }) => (
    <div style={{
        display: 'grid',
        gridTemplateColumns: '80px 1fr 1fr 100px 1fr',
        gap: '0',
        borderBottom: '1px solid #e2e8f0',
        fontSize: '14px',
    }}>
        <div style={{ padding: '12px 14px', fontWeight: 700, color, background: '#fafafa' }}>{tier}</div>
        <div style={{ padding: '12px 14px', fontWeight: 600, color: '#1e293b' }}>{tool}</div>
        <div style={{ padding: '12px 14px', color: '#475569' }}>{when}</div>
        <div style={{ padding: '12px 14px', color: '#475569' }}>{speed}</div>
        <div style={{ padding: '12px 14px', color: '#475569' }}>{qualityGate}</div>
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

const SummaryVariantCard: React.FC<{
    name: string;
    audience: string;
    description: string;
    wordRange: string;
    color: string;
}> = ({ name, audience, description, wordRange, color }) => (
    <div style={{
        padding: '18px 20px',
        background: '#ffffff',
        border: '1px solid #e2e8f0',
        borderLeft: `4px solid ${color}`,
        borderRadius: '0 8px 8px 0',
    }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b' }}>{name}</span>
            <span style={{ fontSize: '12px', color: '#64748b', background: '#f1f5f9', padding: '2px 8px', borderRadius: '4px' }}>{wordRange}</span>
        </div>
        <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '4px' }}>{audience}</div>
        <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.5 }}>{description}</div>
    </div>
);

/* ─── main component ─── */

export const DataPipeline: React.FC = () => {

    const pipelineOverview = `
graph TB
    A[Excel Manifest] -->|Phase 1| B[Manifest Ingestion]
    B --> C[Document Triage]
    C --> D{Scanned?}
    D -->|Yes| E[Tesseract OCR]
    D -->|No| F[Document Scaffolding]
    E --> F
    F --> G[Docling Layout Analysis]
    G --> H[TOC Reconciliation]
    H --> I{Quality < 50?}
    I -->|Yes| J[Claude Haiku Validation]
    I -->|No| K[Content Extraction]
    J --> K
    K --> L[Hierarchical Chunking]
    L --> M[Document Assembly]
    M --> N[Semantic Enrichment]
    N --> O[Phase 10a: Overviews + Summaries]
    N --> P[Phase 10b: Gemini Visuals]
    O --> Q[Phase 10c: Post-Processing]
    P --> Q
    Q --> R[Final Corpus]

    style A fill:#e0e7ff,stroke:#6366f1
    style R fill:#dcfce7,stroke:#22c55e
    style D fill:#fef3c7,stroke:#f59e0b
    style I fill:#fef3c7,stroke:#f59e0b
    style E fill:#fee2e2,stroke:#ef4444
    style J fill:#fae8ff,stroke:#d946ef
    style O fill:#fae8ff,stroke:#d946ef
    style P fill:#fff7ed,stroke:#f97316
`;

    const tocCascade = `
graph LR
    P4[Phase 4: Heuristic TOC] -->|~90% accuracy| P55[Phase 5.5: Docling Reconciliation]
    P55 -->|~95% accuracy| Check{Quality < 50?}
    Check -->|Yes ~15%| P57[Phase 5.7: Claude Haiku]
    Check -->|No ~85%| Done[Final TOC]
    P57 -->|~97% accuracy| Done

    style P4 fill:#dbeafe,stroke:#1a365d
    style P55 fill:#e0e7ff,stroke:#6366f1
    style P57 fill:#fae8ff,stroke:#d946ef
    style Done fill:#dcfce7,stroke:#22c55e
    style Check fill:#fef3c7,stroke:#f59e0b
`;

    const chunkingDiagram = `
graph TB
    TOC[TOC Entries] --> Parents[Parent Chunks<br/>Section-level]
    Content[Extracted Content] --> Children[Child Chunks<br/>Paragraph-level]
    Parents --> Link{Assignment}
    Children --> Link
    Link --> Hierarchy[Full Hierarchy<br/>Inheritance]

    Hierarchy --> Assembly[Document Assembly]
    Assembly --> Temporal[Temporal Annotation]
    Assembly --> CrossRef[Cross-Reference Resolution]
    Assembly --> Footnotes[Footnote Indexing]
    Assembly --> Confidence[Confidence Scoring]

    Assembly --> Semantic[Semantic Enrichment]
    Semantic --> Findings[Findings Extraction]
    Semantic --> Recs[Recommendations]
    Semantic --> Entities[Entity Recognition]
    Semantic --> Money[Monetary Aggregation]

    style TOC fill:#e0e7ff
    style Content fill:#dbeafe
    style Semantic fill:#fae8ff
    style Link fill:#fef3c7
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">Data Pipeline</h1>
            <p className="page-subtitle">
                A 12-phase pipeline that transforms government audit PDFs — scanned, multi-column,
                inconsistently formatted — into structured, semantically enriched JSON.
                Built entirely in Python, orchestrated by a single <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px', fontSize: '16px' }}>DocumentTask</code> state
                object that accumulates metadata across every phase.
            </p>

            {/* ── Hero Stats ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '14px', margin: '0 0 56px 0' }}>
                <Stat value="12" label="Processing Phases" />
                <Stat value="3" label="AI Models Used" accent="#7c3aed" />
                <Stat value="97%" label="TOC Accuracy" accent="#059669" />
                <Stat value="~$1.50" label="Cost Per Report" accent="#d97706" />
                <Stat value="159" label="Reports in Corpus" />
            </div>

            {/* ── Pipeline at a Glance ── */}
            <DocSection
                title="Pipeline at a Glance"
                description="Each phase feeds its output into the next via a DocumentTask state object. Decision nodes route PDFs through different extraction strategies based on document type and quality signals."
            >
                <DiagramCard title="End-to-End Processing Flow">
                    <MermaidDiagram
                        chart={pipelineOverview}
                        caption="Yellow diamonds mark decision points. Purple nodes involve LLM calls. The pipeline never crashes — every phase has fallback paths that preserve partial results."
                    />
                </DiagramCard>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 1: Understanding the Document
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Understanding the Document"
                description="The hardest part of this pipeline isn't the AI — it's recovering structure from PDFs that were never designed to be machine-readable. CAG reports come in 7+ formats, mix native text with scanned pages, use inconsistent heading styles, and embed tables without borders. Phases 1–5.7 handle all of it."
            >
                {/* Phase 1–3: Ingestion */}
                <div style={{ marginBottom: '32px' }}>
                    <PhaseLabel number="1–3" title="Ingestion, Triage & OCR" color="#1a365d" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        The pipeline starts with an Excel manifest listing every audit report — title, ministry, sector, report number, and PDF download URL.
                        Each row becomes a <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>DocumentTask</code> object
                        that carries state through all 12 phases. PDFs are downloaded (with retry logic and local caching), then classified
                        by sampling the first 3 pages: if text density falls below <InlineStat value="50 chars/page" />,
                        the document is routed through Tesseract OCR at 300 DPI to produce a searchable PDF.
                    </p>
                    <ProblemSolution
                        problem="Cover pages and title pages often have minimal text, causing native PDFs to be misclassified as scanned."
                        solution="Multi-page sampling across the first 3 pages, not just page 1. If any sampled page exceeds the threshold, the document is classified as native."
                    />
                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        OCR is by far the slowest phase — <InlineStat value="10–30 min" label="per report" /> for scanned documents — but it's
                        skipped entirely for native PDFs, which account for the majority of the corpus. The rest of the pipeline
                        doesn't care which path was taken; it just uses whichever PDF is available.
                    </p>
                </div>

                {/* Phase 4 + 5: Scaffolding & Layout */}
                <div style={{ marginBottom: '32px' }}>
                    <PhaseLabel number="4–5" title="Scaffolding & Layout Analysis" color="#6366f1" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Before extracting any content, the pipeline builds a structural scaffold: a Table of Contents with page mappings and hierarchy levels.
                        This is critical because the TOC determines how every downstream chunk gets classified and grouped.
                    </p>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Phase 4 uses <strong>4 complementary heuristic strategies</strong> — a printed-TOC regex pre-pass on the first 15 pages,
                        dedicated TOC page detection with dot-leader patterns, table-based TOC extraction (common in CAG reports),
                        and heading-based inference from font sizes. Hierarchy levels are inferred using quantile bucketing on font
                        sizes — deterministic and reproducible, unlike K-means clustering.
                    </p>
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        Phase 5 runs <strong>Docling v2</strong> (IBM's AI layout engine) with TableFormer ACCURATE mode. This gives us two outputs:
                        classified layout blocks per page (text, table, figure, header, footer) with bounding boxes and confidence scores,
                        and Section-header detections that serve as a second opinion on the TOC.
                    </p>
                </div>

                {/* Phase 5.5 + 5.7: TOC Improvement Cascade */}
                <div style={{ marginBottom: '8px' }}>
                    <PhaseLabel number="5.5 → 5.7" title="3-Layer TOC Validation Cascade" color="#7c3aed" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '16px' }}>
                        Heuristic TOC extraction alone achieves roughly 90% accuracy. For a RAG system where chunk-to-section assignment
                        drives retrieval quality, that's not enough. The pipeline uses a progressive improvement cascade — each layer only
                        fires when the previous one leaves quality gaps.
                    </p>
                    <DiagramCard title="TOC Accuracy Cascade">
                        <MermaidDiagram
                            chart={tocCascade}
                            caption="Phase 5.5 cross-validates heuristic TOC against Docling's AI-detected section headers. Phase 5.7 uses Claude Haiku as a last resort for the ~15% of reports with quality scores below 50. Total LLM cost for the entire corpus: ~$2–4."
                        />
                    </DiagramCard>

                    <div style={{ marginTop: '20px' }}>
                        <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '12px' }}>
                            <strong>Phase 5.5 (Reconciliation)</strong> applies a 3-tier strategy based on Phase 4's quality score:
                        </p>
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: '1fr 1fr 1fr',
                            gap: '12px',
                            marginBottom: '16px',
                        }}>
                            {[
                                { range: '≥ 70', label: 'High Quality', action: 'Supplement Phase 4 with missing Docling headers', bg: '#dcfce7', border: '#22c55e' },
                                { range: '40–69', label: 'Medium', action: 'Merge both signals, prefer Docling for tie-breaking', bg: '#fef3c7', border: '#f59e0b' },
                                { range: '< 40', label: 'Low Quality', action: 'Replace with Docling headers, keep high-confidence Phase 4 entries', bg: '#fee2e2', border: '#ef4444' },
                            ].map((tier) => (
                                <div key={tier.range} style={{
                                    padding: '14px 16px',
                                    background: tier.bg,
                                    borderRadius: '8px',
                                    border: `1px solid ${tier.border}`,
                                }}>
                                    <div style={{ fontSize: '18px', fontWeight: 700, color: '#1e293b', marginBottom: '2px' }}>{tier.range}</div>
                                    <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '6px' }}>{tier.label}</div>
                                    <div style={{ fontSize: '13px', color: '#334155', lineHeight: 1.5 }}>{tier.action}</div>
                                </div>
                            ))}
                        </div>
                        <p style={{ lineHeight: 1.7, color: '#475569' }}>
                            Critically, Phase 5.5 also enriches heading positions with <strong>Y-coordinates</strong> from Docling bounding boxes.
                            This enables accurate chunk assignment on pages where multiple sections start — without Y-awareness,
                            a paragraph at the bottom of a page might be assigned to the wrong section.
                        </p>
                        <p style={{ lineHeight: 1.7, color: '#475569', marginTop: '12px' }}>
                            <strong>Phase 5.7 (LLM Validation)</strong> fires only for reports with quality below 50 — roughly 15% of the corpus.
                            It sends the first 15 pages of raw text to Claude Haiku, which returns a corrected TOC as a JSON array.
                            Logical page numbers from the response are converted to physical (0-indexed) pages using the scaffold's page map.
                            The quality score is capped at 85 — LLM output is never treated as ground truth.
                            If no API key is configured, this phase silently skips with zero pipeline impact.
                        </p>
                    </div>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 2: Extracting Content
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Extracting Content"
                description="Phase 6 is where the pipeline extracts actual content from every layout block detected in Phase 5. Text extraction sounds simple — it isn't. Tables are the hard problem."
            >
                <PhaseLabel number="6" title="Content Extraction with Router-Dispatcher" color="#0891b2" />
                <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '16px' }}>
                    A router-dispatcher pattern maps each layout label to a specialized extractor.
                    Text blocks go through PyMuPDF's bounding-box-clipped extraction with normalization (ligature replacement,
                    soft hyphen removal, line-break rejoining). Figures are cropped and saved as images for Phase 10b.
                    Footnotes get dedicated number detection (plain digits, Unicode superscripts, "Note:" prefixes).
                    Page headers and footers are skipped as noise.
                </p>
                <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '20px' }}>
                    Tables get the most engineering attention — a quality-gated cascade through three extraction tiers,
                    routing based on the PDF classification from Phase 2.
                </p>

                {/* 3-Tier Table Strategy */}
                <div style={{
                    border: '1px solid #e2e8f0',
                    borderRadius: '12px',
                    overflow: 'hidden',
                    margin: '0 0 24px 0',
                    background: '#ffffff',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                }}>
                    <div style={{
                        padding: '16px 20px',
                        background: '#f8fafc',
                        borderBottom: '1px solid #e2e8f0',
                        fontSize: '16px',
                        fontWeight: 700,
                        color: '#1e293b',
                    }}>
                        3-Tier Table Extraction Cascade
                    </div>
                    {/* Header */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '80px 1fr 1fr 100px 1fr',
                        gap: '0',
                        borderBottom: '2px solid #cbd5e1',
                        fontSize: '12px',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        color: '#64748b',
                    }}>
                        <div style={{ padding: '10px 14px', background: '#f8fafc' }}>Tier</div>
                        <div style={{ padding: '10px 14px' }}>Tool</div>
                        <div style={{ padding: '10px 14px' }}>When It's Used</div>
                        <div style={{ padding: '10px 14px' }}>Speed</div>
                        <div style={{ padding: '10px 14px' }}>Quality Gate</div>
                    </div>
                    <TierRow
                        tier="Tier 1"
                        tool="pdfplumber"
                        when="Native PDFs only — extracts from text streams"
                        speed="Fast"
                        qualityGate="Min 2×2 cells, at least 1 header row"
                        color="#22c55e"
                    />
                    <TierRow
                        tier="Tier 2"
                        tool="Docling TableFormer"
                        when="Scanned PDFs, or Tier 1 failure"
                        speed="Medium"
                        qualityGate="≥ 3 non-empty cells in markdown output"
                        color="#f59e0b"
                    />
                    <TierRow
                        tier="Tier 3"
                        tool="Gemini 2.5 Flash"
                        when="All structural methods exhausted"
                        speed="Slow"
                        qualityGate="Deferred to Phase 10b (async batch)"
                        color="#ef4444"
                    />
                </div>

                <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                    The cascade logic: try fast extraction first (pdfplumber text streams), fall back to AI layout analysis
                    (Docling's TableFormer ACCURATE mode), then defer to vision (Gemini). Scanned PDFs skip Tier 1 entirely since
                    they have no text streams. Every extracted table carries an <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>extraction_method</code> field
                    for full provenance tracking.
                </p>

                <ProblemSolution
                    problem="What happens when all three tiers fail for a table?"
                    solution="The image is saved to a dead letter queue with full metadata (report_id, page, bbox, error) for manual inspection. The pipeline continues without crashing."
                />

                <ProblemSolution
                    problem="Paragraphs split across page breaks lose context when extracted per-page."
                    solution="Cross-page merging detects incomplete endings (no punctuation, trailing prepositions) and continuation starts (lowercase, conjunctions), then joins the fragments before chunking."
                />

                <p style={{ lineHeight: 1.7, color: '#475569', marginTop: '16px' }}>
                    All tables — regardless of extraction tier — are converted to a <strong>StructuredTable</strong> JSON
                    representation with typed headers, indexed rows and cells, captions, and table numbers.
                    This makes tables queryable, not just displayable.
                </p>

                <CodeBlock title="StructuredTable JSON (abbreviated)">
{`{
  "table_id": "table_15_72_150",
  "extraction_method": "pdfplumber-lines_strict",
  "is_multi_page": false,
  "source_pages": [15],
  "headers": [
    {"text": "Category", "col_index": 0},
    {"text": "Amount (₹ crore)", "col_index": 1}
  ],
  "rows": [
    {"row_index": 0, "cells": [
      {"text": "Irregular Expenditure", "col_index": 0},
      {"text": "847.71", "col_index": 1}
    ]}
  ],
  "row_count": 12,
  "col_count": 4,
  "caption": "Table 2.1: Summary of Financial Irregularities"
}`}
                </CodeBlock>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 3: Building the Knowledge Graph
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Building the Knowledge Graph"
                description="Phases 7–9 transform raw extracted content into a structured, queryable representation — parent-child chunk pairs with full hierarchy inheritance, semantic entities, and cross-reference resolution."
            >
                <DiagramCard title="Chunking, Assembly & Semantic Enrichment (Phases 7–9)">
                    <MermaidDiagram
                        chart={chunkingDiagram}
                        caption="TOC entries become parent chunks; extracted content becomes child chunks. Each child inherits its parent's full hierarchy. Assembly adds temporal, cross-reference, and footnote metadata. Semantic enrichment extracts domain-specific entities."
                    />
                </DiagramCard>

                {/* Phase 7: Chunking */}
                <div style={{ marginTop: '28px', marginBottom: '28px' }}>
                    <PhaseLabel number="7" title="Hierarchical Chunking" color="#059669" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        The chunking strategy uses a <strong>parent-child architecture</strong>.
                        Parent chunks are section-level containers derived from TOC entries — they carry hierarchy
                        metadata (<code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>level_1: "Chapter 2"</code>,
                        {' '}<code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>level_2: "2.3 Findings"</code>)
                        and page ranges. Child chunks are atomic units — individual paragraphs, tables, or figures —
                        linked to the <strong>most specific (deepest level) parent</strong> whose page range contains them.
                    </p>

                    <ProblemSolution
                        problem="On multi-section pages, two sections start on the same physical page. A paragraph near the bottom gets assigned to the wrong section based on page number alone."
                        solution="Y-coordinate-aware assignment. Heading positions captured in Phase 5.5 let the chunker filter parent candidates by vertical position, not just page number."
                    />

                    <p style={{ lineHeight: 1.7, color: '#475569', marginTop: '14px' }}>
                        Multi-page tables are detected before chunking (matching column structure &gt; 80% similarity, sequential pages,
                        "contd." indicators) and stitched into single chunks with merged rows and a <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>source_pages</code> array.
                        Children inherit the <strong>full ancestor chain</strong> from their parent — a chunk in "2.3.1 Irregular Expenditure"
                        carries the complete path: Chapter 2 → 2.3 Findings → 2.3.1 Irregular Expenditure.
                    </p>
                </div>

                {/* Phase 8: Assembly */}
                <div style={{ marginBottom: '28px' }}>
                    <PhaseLabel number="8" title="Document Assembly & Enrichment" color="#0284c7" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '12px' }}>
                        Assembly serializes chunks to JSON and runs four enrichment passes:
                    </p>
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr',
                        gap: '12px',
                        marginBottom: '14px',
                    }}>
                        {[
                            { title: 'Temporal Annotation', desc: 'Extracts fiscal years ("2021-22"), absolute dates, and relative references ("as of March 2023") into structured temporal_references fields.' },
                            { title: 'Cross-Reference Resolution', desc: 'Resolves "see para 3.2.1", "Table 4.1", "Section 2.3" references to actual chunk IDs for linked navigation.' },
                            { title: 'Contextual Captions', desc: 'Replaces generic AI image captions ("black background with red text") with section-aware context from the parent hierarchy.' },
                            { title: 'Confidence Scoring', desc: 'Composite 0–1 score per chunk from layout confidence (40%), TOC quality (30%), and content quality heuristics (30%).' },
                        ].map((item) => (
                            <div key={item.title} style={{
                                padding: '14px 16px',
                                background: '#f8fafc',
                                border: '1px solid #e2e8f0',
                                borderRadius: '8px',
                            }}>
                                <div style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b', marginBottom: '4px' }}>{item.title}</div>
                                <div style={{ fontSize: '13px', color: '#475569', lineHeight: 1.5 }}>{item.desc}</div>
                            </div>
                        ))}
                    </div>
                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        Assembly also builds two indexes: a <strong>footnote index</strong> (keyed by footnote number for O(1) lookup)
                        and a <strong>visual asset registry</strong> (tables and figures grouped by section with counts, captions, and page numbers).
                    </p>
                </div>

                {/* Phase 9: Semantic Enrichment */}
                <div style={{ marginBottom: '8px' }}>
                    <PhaseLabel number="9" title="Semantic Enrichment" color="#7c3aed" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '14px' }}>
                        This is where domain expertise is encoded. The enrichment engine is <strong>report-type-aware</strong> — it loads
                        one of 7 profiles (Compliance, Performance, Financial, Revenue, Railways, Defence, General Purpose)
                        based on report metadata, each with tuned extraction patterns.
                    </p>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr',
                        gap: '14px',
                        marginBottom: '16px',
                    }}>
                        <div style={{ padding: '16px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px' }}>
                            <div style={{ fontSize: '14px', fontWeight: 700, color: '#991b1b', marginBottom: '8px' }}>Finding Extraction</div>
                            <div style={{ fontSize: '13px', color: '#7f1d1d', lineHeight: 1.6 }}>
                                Classifies into 8 types (irregular expenditure, revenue loss, fraud, etc.).
                                Extracts monetary values with regex (<code style={{ fontSize: '12px' }}>₹847.71 crore</code>),
                                normalizes to INR paise for cross-report comparison.
                                Assigns severity: CRITICAL (&gt;₹100 Cr), HIGH (₹10–100 Cr), MEDIUM (₹1–10 Cr), LOW (&lt;₹1 Cr).
                            </div>
                        </div>
                        <div style={{ padding: '16px', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '8px' }}>
                            <div style={{ fontSize: '14px', fontWeight: 700, color: '#1e40af', marginBottom: '8px' }}>Recommendation Extraction</div>
                            <div style={{ fontSize: '13px', color: '#1e3a5f', lineHeight: 1.6 }}>
                                3-strategy approach: structural (dedicated "Recommendations" section), numbered
                                patterns ("Recommendation 1.2.3:"), and verb-based matching ("Ministry should...",
                                "Audit recommends that..."). Extracts addressee, action text, and priority.
                            </div>
                        </div>
                    </div>

                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        Entity extraction identifies government schemes, ministries, and organizations with hardened filters —
                        rejecting sentence fragments that start with verbs, capping entity length at 60 characters, and stopping
                        before "and Ministry" (to avoid merging separate entities). Monetary values are aggregated by category
                        across the entire report: total irregular expenditure, total revenue loss, total wasteful expenditure.
                    </p>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 4: AI Enrichment at Scale
            ══════════════════════════════════════════════ */}
            <DocSection
                title="AI Enrichment at Scale"
                description="Phase 10 uses three AI models — each chosen for a specific cost/quality tradeoff — processed asynchronously through batch APIs. The entire corpus costs under $30 to enrich."
            >
                {/* 10a: Overviews + Summaries */}
                <div style={{ marginBottom: '32px' }}>
                    <PhaseLabel number="10a" title="Overview Extraction + Summary Generation" color="#9333ea" />
                    <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '16px' }}>
                        For each report, Phase 10a submits two types of prompts to the Anthropic Batch API:
                        one for structured overview extraction and five for summary generation (one per variant).
                        All use Extended Thinking for deeper reasoning. Batch API provides <InlineStat value="50%" label="cost savings" /> over synchronous calls.
                    </p>

                    <div style={{ marginBottom: '24px' }}>
                        <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '10px' }}>Enhanced Overview Extraction</h3>
                        <p style={{ lineHeight: 1.7, color: '#475569', marginBottom: '12px' }}>
                            Claude extracts structured metadata that goes beyond what heuristics can parse — audit scope (time period,
                            geographic coverage, sample size, entities), audit objectives, topic summaries with section and page
                            mappings, and a glossary of domain-specific abbreviations. The LLM-extracted fields are merged with
                            algorithmically extracted data (findings summaries, entity lists, TOC) into a unified <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>{'{report_id}'}_overview.json</code>.
                        </p>
                    </div>

                    <div style={{ marginBottom: '20px' }}>
                        <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>5 Summary Variants</h3>
                        <div style={{ display: 'grid', gap: '10px' }}>
                            <SummaryVariantCard
                                name="Executive Brief"
                                audience="C-suite, policymakers"
                                description="High-level strategic overview with key metrics and action items. Gets to the point in under 2,500 words."
                                wordRange="2,200–2,500 words"
                                color="#1a365d"
                            />
                            <SummaryVariantCard
                                name="Journalist's Take"
                                audience="General public, news media"
                                description="Inverted pyramid structure, plain language, human interest angle. Written as if it were a news story."
                                wordRange="2,000–2,200 words"
                                color="#059669"
                            />
                            <SummaryVariantCard
                                name="Deep Dive"
                                audience="Researchers, academics"
                                description="Methodology critique, data quality assessment, theoretical frameworks. The longest and most analytical variant."
                                wordRange="3,500–4,000 words"
                                color="#7c3aed"
                            />
                            <SummaryVariantCard
                                name="Simple Explainer"
                                audience="Non-experts, students"
                                description="ELI5 style with analogies and minimal jargon. Makes government audits accessible to anyone."
                                wordRange="1,200–1,500 words"
                                color="#f59e0b"
                            />
                            <SummaryVariantCard
                                name="Policy Brief"
                                audience="Government officials, legislators"
                                description="Action-oriented with concrete recommendations, implementation timelines, and resource requirements."
                                wordRange="2,200–2,500 words"
                                color="#dc2626"
                            />
                        </div>
                    </div>

                    <CalloutBox type="info">
                        <strong>Batch Job Lifecycle:</strong> Prompts are prepared for all reports → submitted to Anthropic Batch API → polled for completion
                        (typically 1–2 hours) → results downloaded, parsed, and stored as JSON. A job tracker file persists the batch ID
                        and request-to-report mapping for reliable result hydration.
                    </CalloutBox>
                </div>

                {/* 10b: Gemini Visuals */}
                <div style={{ marginBottom: '32px' }}>
                    <PhaseLabel number="10b" title="Gemini Visual Extraction (Tier 3)" color="#ea580c" />
                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        All chart and table images that failed structural extraction in Phase 6 are sent to Gemini 2.5 Flash
                        as a vision-based fallback. For tables, Gemini returns markdown which is converted to StructuredTable JSON.
                        For charts, it generates descriptions: chart type, axis labels, data points, and key insights.
                        Cost: <InlineStat value="~$0.02" label="per image" />.
                    </p>
                </div>

                {/* 10c: Post-processing */}
                <div style={{ marginBottom: '8px' }}>
                    <PhaseLabel number="10c" title="Visual Post-Processing" color="#64748b" />
                    <p style={{ lineHeight: 1.7, color: '#475569' }}>
                        The final pass hydrates image placeholders in child chunks with extracted content,
                        filters out chunks from TOC/preface pages (non-substantive content), and enriches
                        chart/table captions with numbers and titles from the parent hierarchy. The result
                        is saved as the final enriched JSON.
                    </p>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 5: Engineering Edge Cases
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Engineering Details"
                description="The difference between a demo and production is edge case handling. These are the problems that only surface when you process 159 real-world government PDFs."
            >
                <div style={{ display: 'grid', gap: '12px', marginBottom: '24px' }}>
                    <ProblemSolution
                        problem="Multiple TOC sections start on the same physical page (e.g., 'Findings' at Y=150 and 'Conclusion' at Y=450 on page 15)."
                        solution="Y-coordinate tracking from Docling bounding boxes. Chunks at Y=200 are assigned to 'Findings', not 'Conclusion'. Without this, ~8% of chunks in dense reports land in the wrong section."
                    />
                    <ProblemSolution
                        problem="Forward-looking page range calculation produces end_page < start_page when TOC entries are malformed."
                        solution="Post-calculation guard: if end_page < start_page, set end_page = start_page. Guarantees valid ranges for all parent chunks."
                    />
                    <ProblemSolution
                        problem="Footnotes appear in wildly different formats: '7 FSSAI standards...', '¹ FSSAI...', 'Note: FSSAI...'."
                        solution="Multi-pattern detection with Unicode superscript conversion. Footnotes are normalized to '[Footnote 7] {text}' format and indexed by number for O(1) lookup."
                    />
                    <ProblemSolution
                        problem="Report year is needed for filtering but exists in different places across reports — sometimes only in the report number string."
                        solution="3-source extraction cascade: try publication_date, then report_id pattern, then 'X of YYYY' in Report No. If all fail, year is null (never guessed)."
                    />
                    <ProblemSolution
                        problem="AI image captions are generic: 'The image shows a black background with red and blue text...'"
                        solution="Pattern detection for generic captions, replaced with section-aware context: 'Figure in {section_title}'. Improves downstream retrieval by adding meaningful semantic signal."
                    />
                </div>

                {/* Quality Gates */}
                <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b', marginBottom: '12px' }}>Quality Gates Across the Pipeline</h3>
                <div style={{
                    border: '1px solid #e2e8f0',
                    borderRadius: '10px',
                    overflow: 'hidden',
                    marginBottom: '20px',
                    background: '#ffffff',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                        <thead>
                            <tr style={{ background: '#f8fafc', borderBottom: '2px solid #cbd5e1' }}>
                                <th style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 700, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>Phase</th>
                                <th style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 700, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>Gate</th>
                                <th style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 700, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b' }}>On Failure</th>
                            </tr>
                        </thead>
                        <tbody>
                            {[
                                ['Phase 4', 'TOC quality < 20 or < 3 entries', 'Fallback to single document-level parent'],
                                ['Phase 5', 'Layout confidence < 0.65', 'Block is discarded (noise filtering)'],
                                ['Phase 5', 'Table markdown < 3 non-empty cells', 'Marked as failed, routed to Tier 3'],
                                ['Phase 5.5', 'Title similarity < 0.65', 'Docling header not matched to TOC entry'],
                                ['Phase 5.7', 'TOC quality ≥ 50', 'LLM validation skipped entirely'],
                                ['Phase 6', 'pdfplumber returns empty', 'Fall through to Tier 2 (Docling)'],
                                ['Phase 7', 'Header similarity < 80%', 'Tables not merged (treated as separate)'],
                            ].map(([phase, gate, action], i) => (
                                <tr key={i} style={{ borderBottom: '1px solid #e2e8f0' }}>
                                    <td style={{ padding: '10px 14px', fontWeight: 600, color: '#334155', whiteSpace: 'nowrap' }}>{phase}</td>
                                    <td style={{ padding: '10px 14px', color: '#475569' }}>{gate}</td>
                                    <td style={{ padding: '10px 14px', color: '#475569' }}>{action}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <CalloutBox type="note">
                    <strong>Dead Letter Queue:</strong> When any extraction fails, the block image and full metadata
                    (report_id, page, label, bbox, error message) are saved to <code style={{ background: '#e2e8f0', padding: '2px 6px', borderRadius: '4px' }}>data/dead_letter_queue/</code> for
                    debugging. The pipeline never crashes — it logs the failure and continues.
                    Failed extractions can be manually reviewed or re-processed through Tier 3.
                </CalloutBox>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 6: Pipeline Outputs
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Pipeline Outputs"
                description="The pipeline produces three JSON deliverables per report, plus a corpus-level manifest."
            >
                <div style={{ display: 'grid', gap: '20px' }}>

                    {/* Chunks JSON */}
                    <div style={{ padding: '20px 24px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                            <span style={{ background: '#dbeafe', color: '#1e40af', fontSize: '12px', fontWeight: 700, padding: '4px 10px', borderRadius: '4px' }}>PRIMARY</span>
                            <span style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b' }}>{'{report_id}'}_chunks.json</span>
                        </div>
                        <p style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6, marginBottom: '12px' }}>
                            The main structured output. Contains report metadata, parent chunks (section-level with hierarchy and page ranges),
                            child chunks (paragraph/table-level with content, bounding boxes, and extraction provenance),
                            footnote index, visual asset registry, semantic enrichment (findings, recommendations, entities, monetary aggregates),
                            and processing statistics.
                        </p>
                        <div style={{ fontSize: '13px', color: '#64748b' }}>
                            Typical size: <InlineStat value="~350" label="child chunks" /> per report, <InlineStat value="~45" label="parent chunks" />
                        </div>
                    </div>

                    {/* Overview JSON */}
                    <div style={{ padding: '20px 24px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                            <span style={{ background: '#fae8ff', color: '#7c3aed', fontSize: '12px', fontWeight: 700, padding: '4px 10px', borderRadius: '4px' }}>LLM-ENRICHED</span>
                            <span style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b' }}>{'{report_id}'}_overview.json</span>
                        </div>
                        <p style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6, marginBottom: '12px' }}>
                            Merges algorithmic extraction (basic info, TOC, findings summaries, entities) with LLM-extracted fields
                            (audit scope, objectives, topics with page ranges, glossary terms). Designed for report browsing and navigation.
                        </p>
                        <div style={{ fontSize: '13px', color: '#64748b' }}>
                            Contains both structured data and natural-language descriptions for each topic.
                        </div>
                    </div>

                    {/* Summaries JSON */}
                    <div style={{ padding: '20px 24px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                            <span style={{ background: '#fef3c7', color: '#92400e', fontSize: '12px', fontWeight: 700, padding: '4px 10px', borderRadius: '4px' }}>AI-GENERATED</span>
                            <span style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b' }}>{'{report_id}'}_summaries.json</span>
                        </div>
                        <p style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6, marginBottom: '12px' }}>
                            Five summary variants per report (Executive Brief, Journalist's Take, Deep Dive, Simple Explainer, Policy Brief),
                            each with content (markdown), word count, and Extended Thinking metadata. Generated via Anthropic Batch API.
                        </p>
                        <div style={{ fontSize: '13px', color: '#64748b' }}>
                            Total: <InlineStat value="5 × 159" label="= 795 summaries" /> across the corpus
                        </div>
                    </div>

                    {/* Manifest */}
                    <div style={{ padding: '20px 24px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                            <span style={{ background: '#f1f5f9', color: '#475569', fontSize: '12px', fontWeight: 700, padding: '4px 10px', borderRadius: '4px' }}>CORPUS</span>
                            <span style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b' }}>manifest.json</span>
                        </div>
                        <p style={{ fontSize: '14px', color: '#475569', lineHeight: 1.6 }}>
                            Registry of all processed reports with metadata, file references, and processing timestamps.
                            Used by the API layer to discover available reports without scanning the filesystem.
                        </p>
                    </div>
                </div>
            </DocSection>

            {/* ══════════════════════════════════════════════
                SECTION 7: Performance & Cost
            ══════════════════════════════════════════════ */}
            <DocSection
                title="Performance & Cost"
            >
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '20px',
                    marginBottom: '20px',
                }}>
                    {/* Processing Time */}
                    <div style={{ padding: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '14px' }}>Processing Time</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['Phases 1–3 (Ingest + OCR)', '10–30 min*'],
                                ['Phases 4–5.7 (Structure)', '4–6 min'],
                                ['Phase 6 (Extraction)', '2–3 min'],
                                ['Phases 7–9 (Chunks + Enrich)', '~1 min'],
                                ['Phase 10 (Batch AI)', '1–2 hours†'],
                            ].map(([phase, time]) => (
                                <div key={phase} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569' }}>{phase}</span>
                                    <span style={{ fontWeight: 600, color: '#1e293b' }}>{time}</span>
                                </div>
                            ))}
                        </div>
                        <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '10px', lineHeight: 1.5 }}>
                            * OCR only for scanned PDFs; native PDFs skip to ~1 min<br />
                            † Async batch — does not block the pipeline
                        </div>
                    </div>

                    {/* Cost Breakdown */}
                    <div style={{ padding: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#1e293b', marginBottom: '14px' }}>Cost Per Report</h3>
                        <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                            {[
                                ['Phases 1–9 (algorithmic)', '$0.00–0.02'],
                                ['Phase 10a (overviews)', '~$0.20'],
                                ['Phase 10a (5 summaries)', '~$0.80–1.30'],
                                ['Phase 10b (Gemini visuals)', '~$0.10–0.30'],
                            ].map(([item, cost]) => (
                                <div key={item} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569' }}>{item}</span>
                                    <span style={{ fontWeight: 600, color: '#1e293b' }}>{cost}</span>
                                </div>
                            ))}
                            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderTop: '2px solid #e2e8f0', marginTop: '4px' }}>
                                <span style={{ fontWeight: 700, color: '#1e293b' }}>Total per report</span>
                                <span style={{ fontWeight: 700, color: '#1a365d' }}>~$1.10–1.80</span>
                            </div>
                        </div>
                        <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '10px' }}>
                            Full corpus (159 reports): ~$175–285
                        </div>
                    </div>
                </div>

                <CalloutBox type="success">
                    <strong>Cost optimization strategy:</strong> Phases 1–9 are purely algorithmic — zero API cost for the core pipeline.
                    Phase 5.7 LLM validation only fires for ~15% of reports (~$2–4 total).
                    Batch API pricing provides 50% savings over synchronous calls. Gemini is used only as a last resort for visuals
                    that structural extraction couldn't handle. Total setup cost for the entire 159-report corpus: under $300.
                </CalloutBox>
            </DocSection>
        </div>
    );
};