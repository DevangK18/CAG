import React from 'react';
import { DocSection } from '../shared/DocSection';
import { DiagramCard } from '../shared/DiagramCard';
import { CalloutBox } from '../shared/CalloutBox';
import { CodeBlock } from '../shared/CodeBlock';
import { MermaidDiagram } from '../shared/MermaidDiagram';

export const AIFeatures: React.FC = () => {
    const summaryVariantsDiagram = `
graph TB
    Chunks[Report Chunks] --> Variants[Prompt Variants]

    Variants --> Executive[Executive Brief]
    Variants --> Journalist[Journalist's Take]
    Variants --> DeepDive[Deep Dive]
    Variants --> Simple[Simple Explainer]
    Variants --> Policy[Policy Brief]

    Executive --> Batch[Claude Batch API<br/>with Extended Thinking]
    Journalist --> Batch
    DeepDive --> Batch
    Simple --> Batch
    Policy --> Batch

    Batch --> Poll[Poll for<br/>Completion]
    Poll --> Parse[Parse Results]
    Parse --> Store[(Store JSON)]
    Store --> API[Serve via<br/>API]
    API --> Frontend[Frontend<br/>Tabs]

    style Chunks fill:#fef3c7
    style Batch fill:#fae8ff
    style Store fill:#dcfce7
`;

    const aiPipelineDiagram = `
graph LR
    Report[Report Chunks] --> RAG[RAG Chat]
    Report --> Summaries[AI Summaries]
    Report --> Overview[Overview<br/>Extraction]
    Report --> TimeSeries[Time Series<br/>Analysis]

    RAG --> Output1[Interactive Q&A]
    Summaries --> Output2[5 Variants]
    Overview --> Output3[Scope, Topics,<br/>Glossary]
    TimeSeries --> Output4[Cross-Report<br/>Trends]

    style Report fill:#fef3c7
    style RAG fill:#dbeafe
    style Summaries fill:#fae8ff
    style Overview fill:#e0e7ff
    style TimeSeries fill:#dcfce7
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">AI Features</h1>
            <p className="page-subtitle">
                Claude-powered intelligence for summaries, overviews, and cross-report analysis
            </p>

            {/* AI Summaries */}
            <DocSection
                title="AI Summaries (5 Variants)"
                description="Multiple perspectives on each audit report, tailored to different audiences"
            >
                <DiagramCard title="Summary Generation Pipeline">
                    <MermaidDiagram
                        chart={summaryVariantsDiagram}
                        caption="Report chunks are processed through 5 prompt variants, sent to Claude Batch API with Extended Thinking, and stored as JSON for frontend consumption."
                    />
                </DiagramCard>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>5 Summary Variants</h3>

                    <CalloutBox type="success">
                        <strong>1. Executive Brief:</strong> For boardroom presentations. High-level strategic overview with key metrics and action items. Target audience: C-suite, board members, policymakers.
                    </CalloutBox>

                    <CalloutBox type="info">
                        <strong>2. Journalist's Take:</strong> News-style summary for general public. Plain language, inverted pyramid structure, human interest angle. Target audience: Media, citizens, advocacy groups.
                    </CalloutBox>

                    <CalloutBox type="warning">
                        <strong>3. Deep Dive:</strong> Academic analysis for researchers. Detailed methodology critique, data quality assessment, theoretical frameworks. Target audience: Scholars, think tanks, PhD students.
                    </CalloutBox>

                    <CalloutBox type="note">
                        <strong>4. Simple Explainer:</strong> Plain language for everyone. ELI5 style, analogies, minimal jargon. Target audience: Students, non-experts, international observers.
                    </CalloutBox>

                    <CalloutBox type="success">
                        <strong>5. Policy Brief:</strong> Action-oriented for government. Concrete recommendations, implementation timelines, resource requirements. Target audience: Civil servants, ministry officials, legislators.
                    </CalloutBox>
                </div>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Extended Thinking</h3>
                    <CalloutBox type="info">
                        <strong>Claude Extended Thinking:</strong> A premium feature that allows Claude to "think" longer before responding, producing more nuanced and well-structured summaries. Used for all 5 variants to ensure high-quality analysis.
                    </CalloutBox>
                </div>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Batch Job Lifecycle</h3>
                    <CodeBlock>
{`1. Submission
   - Create 5 prompt variants per report
   - Submit to Claude Batch API
   - Receive batch_id and request_ids

2. Processing (1-2 hours)
   - Claude processes in background
   - Extended Thinking active
   - python -m src.batch_pipeline.check_status

3. Result Retrieval
   - Poll for completion
   - Download result files
   - python -m src.batch_pipeline.process_results

4. Storage & Serving
   - Parse responses into JSON
   - Store in data/processed/
   - Serve via /api/reports/:id/summaries`}
                    </CodeBlock>
                </div>
            </DocSection>

            {/* Enhanced Overview Generation */}
            <DocSection
                title="Enhanced Overview Generation"
                description="LLM-extracted audit scope, objectives, topics, and glossary"
            >
                <div style={{ lineHeight: '1.7', color: '#475569' }}>
                    <p>
                        For each report, Claude extracts structured metadata that goes beyond simple text parsing:
                    </p>

                    <ul style={{ paddingLeft: '24px', marginTop: '12px', lineHeight: '1.8' }}>
                        <li><strong>Audit Scope:</strong> Period covered, geographic coverage, sample size, entities audited</li>
                        <li><strong>Audit Objectives:</strong> What the audit aimed to assess or investigate</li>
                        <li><strong>Topics Covered:</strong> Major themes with descriptions, sections, and page ranges (clickable in UI)</li>
                        <li><strong>Glossary & Abbreviations:</strong> Domain-specific terms and acronyms with definitions</li>
                    </ul>

                    <CodeBlock title="Example Extracted Data">
{`Audit Scope:
  Period: 2017-18 to 2021-22 (5 years)
  Geographic Coverage: Pan-India (28 states, 8 UTs)
  Sample Size: 156 road projects, ₹1.2 lakh crore
  Entities: NHAI, MoRTH, State PWDs

Topics Covered:
  - Land Acquisition Delays (Pages 45-67)
  - Cost Overruns (Pages 68-89)
  - Quality Assurance Issues (Pages 90-112)

Glossary:
  NHAI: National Highways Authority of India
  EPC: Engineering, Procurement, Construction
  DPR: Detailed Project Report`}
                    </CodeBlock>

                    <p style={{ marginTop: '16px' }}>
                        This structured extraction allows for faceted browsing, topic-based navigation, and more precise search filtering.
                    </p>
                </div>
            </DocSection>

            {/* Time Series Analysis */}
            <DocSection
                title="Time Series Analysis"
                description="Cross-report intelligence for longitudinal trend analysis"
            >
                <CalloutBox type="info">
                    <strong>Longitudinal Analysis:</strong> CAG Gateway identifies reports on the same topic across multiple years (e.g., "Railway Safety" audits from 2019-2024) and creates a unified time series for comparative analysis.
                </CalloutBox>

                <div style={{ marginTop: '16px', lineHeight: '1.7', color: '#475569' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>How It Works</h3>
                    <ol style={{ paddingLeft: '24px', lineHeight: '1.8' }}>
                        <li><strong>Series Detection:</strong> Manually curated or AI-detected report clusters based on ministry, topic, and audit type</li>
                        <li><strong>Multi-Report Context:</strong> When querying a series, chunks from all years are available in the context window</li>
                        <li><strong>Citation Switching:</strong> Citations include the audit year. Clicking a citation auto-switches the PDF viewer to that year's report</li>
                        <li><strong>Trend Prompts:</strong> Special system prompts guide Claude to identify patterns, improvements, deteriorations, and recurring issues</li>
                    </ol>

                    <CodeBlock title="Example Time Series Query">
{`User: "How have cost overruns in highway projects changed over the years?"

AI Response:
"Cost overruns have shown a concerning trend:
- 2018-19: Average 45% over DPR estimates [Page 67, 2019 Report]
- 2020-21: Increased to 62% [Page 89, 2021 Report]
- 2022-23: Peaked at 78% [Page 102, 2023 Report]

The primary driver has been land acquisition delays, which
increased from 18 months to 34 months [Page 45, 2023 Report]."`}
                    </CodeBlock>
                </div>
            </DocSection>

            {/* AI Features Architecture */}
            <DocSection
                title="AI Features Architecture"
                description="How different AI features connect to the underlying data"
            >
                <DiagramCard title="AI Feature Pipeline">
                    <MermaidDiagram
                        chart={aiPipelineDiagram}
                        caption="All AI features draw from the same chunked report data but produce different outputs: interactive Q&A, 5 summary variants, enhanced overviews, and time series trends."
                    />
                </DiagramCard>

                <div style={{ marginTop: '24px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>Model Selection</h3>
                    <CalloutBox type="success">
                        <strong>Claude Sonnet 4:</strong> Used for RAG chat and time series analysis. Excels at nuanced reasoning and citation accuracy.
                    </CalloutBox>
                    <CalloutBox type="info">
                        <strong>Claude Haiku:</strong> Used for TOC validation (Phase 5.7). Fast, cost-effective for structured extraction tasks.
                    </CalloutBox>
                    <CalloutBox type="warning">
                        <strong>Gemini 2.5 Flash:</strong> Used for visual extraction (Tier 3 tables, charts). Multimodal capabilities for complex visual data.
                    </CalloutBox>
                    <CalloutBox type="note">
                        <strong>OpenAI text-embedding-3-small:</strong> Used for all vector embeddings. 1536 dimensions, cost-effective, high quality.
                    </CalloutBox>
                </div>

                <p style={{ marginTop: '16px', lineHeight: '1.7', color: '#475569' }}>
                    This multi-model approach optimizes for cost, latency, and quality. Batch API usage for summaries reduces costs by 50% compared to real-time API calls.
                </p>
            </DocSection>

            {/* Cost Estimates */}
            <DocSection title="Cost Estimates">
                <CodeBlock title="Estimated Costs (19 reports)">
{`AI Summaries (Batch API with Extended Thinking):
  - 5 variants × 19 reports = 95 summaries
  - ~$15-25 total

Overview Extraction:
  - 19 reports × ~$0.20 = ~$3.80

TOC Validation (Phase 5.7):
  - ~10-20% of reports need validation
  - ~$0.50-$2.00 for entire corpus

RAG Chat:
  - Pay-per-query (~$0.02-0.05 per query)
  - Cost scales with usage

Total Setup Cost: ~$20-30
Total Query Cost: Variable based on usage`}
                </CodeBlock>

                <CalloutBox type="success">
                    <strong>Cost Optimization:</strong> Batch API reduces costs by 50%. Caching and reranking reduce unnecessary LLM calls. Haiku for simple tasks keeps costs low.
                </CalloutBox>
            </DocSection>
        </div>
    );
};
