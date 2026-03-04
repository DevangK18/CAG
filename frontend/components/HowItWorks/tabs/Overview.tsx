import React from 'react';
import { DocSection } from '../shared/DocSection';
import { TechBadge } from '../shared/TechBadge';
import { DiagramCard } from '../shared/DiagramCard';
import { CalloutBox } from '../shared/CalloutBox';
import { MermaidDiagram } from '../shared/MermaidDiagram';

export const Overview: React.FC = () => {
    const architectureDiagram = `
graph TB
    PDF[PDF Reports] --> Docling[Docling Parser]
    Docling --> Chunking[Chunking Engine]
    Chunking --> Qdrant[(Qdrant Vector DB)]

    User[User] --> Frontend[React Frontend]
    Frontend --> Backend[FastAPI Backend]
    Backend --> Claude[Claude API<br/>Haiku/Sonnet]
    Backend --> QdrantSearch[Qdrant Search]
    QdrantSearch --> Context[Context Assembly]
    Context --> Claude
    Claude --> Stream[Streaming Response]
    Stream --> Frontend

    style PDF fill:#fef3c7
    style Qdrant fill:#dcfce7
    style Frontend fill:#e0e7ff
    style Backend fill:#dbeafe
    style Claude fill:#fae8ff
`;

    return (
        <div className="tab-page">
            <h1 className="page-title">How CAG Gateway Works</h1>

            {/* Mission Statement */}
            <DocSection
                title="Project Mission"
                description="CAG Gateway transforms static audit reports from India's Comptroller & Auditor General into interactive, searchable data experiences."
            >
                <CalloutBox type="note">
                    <strong>Disclaimer:</strong> This is an independent initiative and is not affiliated with the Comptroller & Auditor General of India.
                </CalloutBox>
            </DocSection>

            {/* Key Stats */}
            <DocSection title="Key Statistics">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginTop: '16px' }}>
                    <div className="stat-card">
                        <div className="stat-value">19</div>
                        <div className="stat-label">Reports Processed</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-value">1,022+</div>
                        <div className="stat-label">Findings Extracted</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-value">5</div>
                        <div className="stat-label">Ministries Covered</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-value">Python</div>
                        <div className="stat-label">Primary Language</div>
                    </div>
                </div>
            </DocSection>

            {/* Architecture Diagram */}
            <DocSection
                title="System Architecture"
                description="High-level overview of how data flows through the CAG Gateway system"
            >
                <DiagramCard title="End-to-End Data Flow">
                    <MermaidDiagram
                        chart={architectureDiagram}
                        caption="PDF reports are parsed, chunked, and indexed into a vector database. User queries are processed through FastAPI, searched against Qdrant, and answered by Claude with streaming responses."
                    />
                </DiagramCard>
            </DocSection>

            {/* Tech Stack */}
            <DocSection
                title="Technology Stack"
                description="All technologies powering the CAG Gateway, grouped by category"
            >
                <div className="tech-stack-section">
                    <h3 className="tech-category-title">Language</h3>
                    <div className="tech-badges">
                        <TechBadge name="Python 3.11+" category="language" />
                    </div>
                </div>

                <div className="tech-stack-section">
                    <h3 className="tech-category-title">Backend</h3>
                    <div className="tech-badges">
                        <TechBadge name="FastAPI" category="backend" />
                        <TechBadge name="Pydantic" category="backend" />
                        <TechBadge name="Uvicorn" category="backend" />
                    </div>
                </div>

                <div className="tech-stack-section">
                    <h3 className="tech-category-title">Frontend</h3>
                    <div className="tech-badges">
                        <TechBadge name="React" category="frontend" />
                        <TechBadge name="TypeScript" category="frontend" />
                        <TechBadge name="Vite" category="frontend" />
                        <TechBadge name="Tailwind CSS" category="frontend" />
                        <TechBadge name="Recharts" category="frontend" />
                        <TechBadge name="Zustand" category="frontend" />
                    </div>
                </div>

                <div className="tech-stack-section">
                    <h3 className="tech-category-title">AI/LLM</h3>
                    <div className="tech-badges">
                        <TechBadge name="Claude API (Sonnet/Haiku)" category="ai" />
                        <TechBadge name="Anthropic Batch API" category="ai" />
                        <TechBadge name="Extended Thinking" category="ai" />
                        <TechBadge name="OpenAI Embeddings" category="ai" />
                        <TechBadge name="Gemini 2.5 Flash" category="ai" />
                    </div>
                </div>

                <div className="tech-stack-section">
                    <h3 className="tech-category-title">Vector Database</h3>
                    <div className="tech-badges">
                        <TechBadge name="Qdrant" category="database" />
                        <TechBadge name="Docker" category="infrastructure" />
                    </div>
                </div>

                <div className="tech-stack-section">
                    <h3 className="tech-category-title">Document Parsing</h3>
                    <div className="tech-badges">
                        <TechBadge name="Docling (IBM)" category="parsing" />
                        <TechBadge name="PyMuPDF" category="parsing" />
                        <TechBadge name="pdfplumber" category="parsing" />
                        <TechBadge name="Tesseract OCR" category="parsing" />
                    </div>
                </div>

                <div className="tech-stack-section">
                    <h3 className="tech-category-title">Data Processing</h3>
                    <div className="tech-badges">
                        <TechBadge name="Pandas" category="other" />
                        <TechBadge name="NumPy" category="other" />
                    </div>
                </div>

                <div className="tech-stack-section">
                    <h3 className="tech-category-title">Infrastructure</h3>
                    <div className="tech-badges">
                        <TechBadge name="Docker" category="infrastructure" />
                        <TechBadge name="Docker Compose" category="infrastructure" />
                    </div>
                </div>

                <div className="tech-stack-section">
                    <h3 className="tech-category-title">Other</h3>
                    <div className="tech-badges">
                        <TechBadge name="Server-Sent Events (SSE)" category="other" />
                        <TechBadge name="Mermaid.js" category="other" />
                    </div>
                </div>
            </DocSection>

            {/* Key Capabilities */}
            <DocSection title="Key Capabilities">
                <div style={{ display: 'grid', gap: '16px', marginTop: '16px' }}>
                    <CalloutBox type="info">
                        <strong>Intelligent Document Parsing:</strong> Handles complex government PDFs with tables, multi-column layouts, and scanned images using Docling and OCR.
                    </CalloutBox>
                    <CalloutBox type="info">
                        <strong>Semantic Search:</strong> Vector-based similarity search with hybrid BM25 sparse retrieval for accurate context discovery.
                    </CalloutBox>
                    <CalloutBox type="info">
                        <strong>AI-Powered Q&A:</strong> Claude-powered chat with inline citations that link back to source pages in the PDF.
                    </CalloutBox>
                    <CalloutBox type="info">
                        <strong>Time Series Analysis:</strong> Cross-report analysis to identify trends across multiple years of audits.
                    </CalloutBox>
                </div>
            </DocSection>
        </div>
    );
};
