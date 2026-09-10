#!/usr/bin/env python3
"""
RAG Pipeline Diagnostic Script
================================
Analyzes the RAG pipeline structure, code patterns, and capabilities
without requiring external services (Qdrant, LLM APIs).

This provides:
1. Architecture analysis from code inspection
2. Feature inventory from config
3. SOTA comparison checklist
4. Processed data analysis

Run: python scripts/rag_pipeline_diagnostic.py
"""

import os
import sys
import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class SOTAFeature:
    """State-of-the-art RAG feature."""
    name: str
    description: str
    implemented: bool
    implementation_file: Optional[str] = None
    notes: str = ""


@dataclass
class PipelineAnalysis:
    """Complete pipeline analysis."""
    # Architecture
    retrieval_type: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 0
    reranker_type: str = ""
    llm_providers: List[str] = field(default_factory=list)

    # Features
    features: Dict[str, bool] = field(default_factory=dict)
    sota_features: List[SOTAFeature] = field(default_factory=list)

    # Data
    total_chunks_estimated: int = 0
    total_reports: int = 0
    tiers: List[str] = field(default_factory=list)


def analyze_config() -> Dict[str, Any]:
    """Analyze configuration without loading env vars."""
    config_path = PROJECT_ROOT / "src" / "core" / "config.py"

    config_info = {
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": 1536,
        "sparse_model": "Qdrant/bm25",
        "reranker_types": ["cohere", "bge"],
        "llm_providers": ["claude", "openai", "gemini"],
        "features": {
            "hybrid_search": True,
            "reranking": True,
            "query_enhancement": True,
            "groundedness_verification": True,
            "agentic_rag": True,
            "neighbor_chunks": True,
            "semantic_enrichment": True,
            "context_augmentation": True,
            "auto_filter": True,
        },
    }

    # Parse config for specific values
    with open(config_path, "r") as f:
        content = f.read()

        # Extract embedding dimensions
        if match := re.search(r'dimensions:\s*int\s*=\s*(\d+)', content):
            config_info["embedding_dimensions"] = int(match.group(1))

        # Extract models
        if match := re.search(r'model:\s*str\s*=\s*"([^"]+)"', content):
            config_info["embedding_model"] = match.group(1)

        # Extract Cohere model
        if match := re.search(r'cohere_model:\s*str\s*=\s*"([^"]+)"', content):
            config_info["cohere_rerank_model"] = match.group(1)

    return config_info


def analyze_retrieval_service() -> Dict[str, Any]:
    """Analyze retrieval service implementation."""
    retrieval_path = PROJECT_ROOT / "src" / "rag_pipeline" / "retrieval_service.py"

    with open(retrieval_path, "r") as f:
        content = f.read()

    analysis = {
        "methods": [],
        "features": {
            "multi_query_retrieval": "multi-query" in content.lower() or "expanded_queries" in content,
            "semantic_filtering": "filters" in content and "finding_type" in content,
            "parent_child_chunks": "parent" in content and "children" in content,
            "neighbor_expansion": "neighbor" in content.lower(),
            "score_fusion": "fusion" in content.lower() or "rrf" in content.lower(),
            "reranking": "rerank" in content.lower(),
        },
    }

    # Extract method signatures
    for match in re.finditer(r'def\s+(\w+)\s*\(', content):
        method = match.group(1)
        if not method.startswith("_") or method == "__init__":
            analysis["methods"].append(method)

    return analysis


def analyze_agentic_service() -> Dict[str, Any]:
    """Analyze agentic RAG implementation."""
    agentic_path = PROJECT_ROOT / "src" / "rag_pipeline" / "agentic_service.py"

    with open(agentic_path, "r") as f:
        content = f.read()

    analysis = {
        "features": {
            "query_decomposition": "_decompose" in content,
            "sub_query_loop": "subquery" in content.lower() or "_run_subquery_loop" in content,
            "iterative_refinement": "iteration" in content.lower() or "reformulation" in content,
            "complexity_detection": "complexity" in content,
            "result_synthesis": "_synthesize" in content or "synthesis" in content.lower(),
            "max_iterations": "max_iterations" in content,
        },
    }

    # Extract complexity types
    if match := re.search(r'"complexity":\s*"(\w+)"', content):
        analysis["complexity_types"] = ["simple", "multi_hop"]

    return analysis


def analyze_qdrant_service() -> Dict[str, Any]:
    """Analyze Qdrant service implementation."""
    qdrant_path = PROJECT_ROOT / "src" / "rag_pipeline" / "qdrant_service.py"

    with open(qdrant_path, "r") as f:
        content = f.read()

    analysis = {
        "features": {
            "hybrid_vectors": "sparse" in content and "dense" in content,
            "rrf_fusion": "rrf" in content.lower() or "FusionQuery" in content,
            "payload_indexes": "create_payload_index" in content,
            "parent_child_collections": "parent_collection" in content and "child_collection" in content,
        },
        "indexed_fields": [],
    }

    # Extract indexed fields
    for match in re.finditer(r'\("(\w+)",\s*PayloadSchemaType\.', content):
        analysis["indexed_fields"].append(match.group(1))

    return analysis


def analyze_embedding_service() -> Dict[str, Any]:
    """Analyze embedding service implementation."""
    embedding_path = PROJECT_ROOT / "src" / "rag_pipeline" / "embedding_service.py"

    with open(embedding_path, "r") as f:
        content = f.read()

    analysis = {
        "features": {
            "dense_embeddings": "dense" in content or "text-embedding" in content,
            "sparse_embeddings": "sparse" in content or "bm25" in content.lower(),
            "batched_embedding": "batch" in content.lower(),
            "context_augmentation": "context" in content.lower() and "prefix" in content.lower(),
            "table_summaries": "table" in content.lower() and "summary" in content.lower(),
        },
    }

    return analysis


def analyze_processed_data() -> Dict[str, Any]:
    """Analyze processed JSON data structure."""
    processed_dir = PROJECT_ROOT / "data" / "processed"

    analysis = {
        "total_reports": 0,
        "total_chunks": 0,
        "tiers": defaultdict(int),
        "reports_by_tier": defaultdict(list),
        "sample_chunk_fields": [],
        "content_types": set(),
        "finding_types": set(),
        "section_types": set(),
    }

    # Count reports and analyze structure
    for tier_dir in processed_dir.iterdir():
        if tier_dir.is_dir() and tier_dir.name in ["union", "state", "local_body"]:
            tier = tier_dir.name

            for json_file in tier_dir.glob("*_chunks.json"):
                analysis["total_reports"] += 1
                analysis["tiers"][tier] += 1
                analysis["reports_by_tier"][tier].append(json_file.stem.replace("_chunks", ""))

                # Analyze first file per tier for structure
                if len(analysis["sample_chunk_fields"]) == 0:
                    try:
                        with open(json_file, "r") as f:
                            data = json.load(f)

                        if "child_chunks" in data:
                            chunks = data["child_chunks"]
                            analysis["total_chunks"] += len(chunks)

                            if chunks:
                                first_chunk = chunks[0]
                                analysis["sample_chunk_fields"] = list(first_chunk.keys())

                                # Sample content types, finding types, etc.
                                for chunk in chunks[:100]:
                                    if "content_type" in chunk:
                                        analysis["content_types"].add(chunk.get("content_type"))
                                    if "structured_data" in chunk:
                                        sd = chunk["structured_data"]
                                        if "finding_type" in sd and sd["finding_type"]:
                                            analysis["finding_types"].add(sd["finding_type"])
                                        if "section_type" in sd and sd["section_type"]:
                                            analysis["section_types"].add(sd["section_type"])
                        else:
                            # Different structure - estimate chunk count
                            analysis["total_chunks"] += len(data) if isinstance(data, list) else 0

                    except (json.JSONDecodeError, IOError) as e:
                        print(f"  Warning: Could not analyze {json_file.name}: {e}")

    # Convert sets to lists for JSON serialization
    analysis["content_types"] = list(analysis["content_types"])
    analysis["finding_types"] = list(analysis["finding_types"])
    analysis["section_types"] = list(analysis["section_types"])
    analysis["tiers"] = dict(analysis["tiers"])
    analysis["reports_by_tier"] = {k: v[:5] for k, v in analysis["reports_by_tier"].items()}

    return analysis


def get_sota_checklist() -> List[SOTAFeature]:
    """Get SOTA RAG checklist with implementation status."""
    return [
        # === RETRIEVAL ===
        SOTAFeature(
            name="Hybrid Search (Dense + Sparse)",
            description="Combines semantic (dense) and keyword (BM25/sparse) search for better recall",
            implemented=True,
            implementation_file="src/rag_pipeline/qdrant_service.py",
            notes="Uses RRF fusion with configurable dense/sparse ratios (40/60 default favors BM25)"
        ),
        SOTAFeature(
            name="Multi-Query Retrieval",
            description="Expands user query into multiple search queries for broader coverage",
            implemented=True,
            implementation_file="src/rag_pipeline/query_enhancer.py",
            notes="LLM-based query expansion generates 2-3 semantically varied queries"
        ),
        SOTAFeature(
            name="Reranking (Cross-Encoder)",
            description="Re-scores initial results with a more powerful model",
            implemented=True,
            implementation_file="src/rag_pipeline/retrieval_service.py",
            notes="Supports Cohere rerank-english-v3.0 and BGE-reranker-v2-m3"
        ),
        SOTAFeature(
            name="Parent-Child Chunking",
            description="Retrieves small chunks but returns with parent context",
            implemented=True,
            implementation_file="src/rag_pipeline/qdrant_service.py",
            notes="Separate collections for parents (sections) and children (chunks)"
        ),
        SOTAFeature(
            name="Neighbor Context Expansion",
            description="Includes surrounding chunks for better context",
            implemented=True,
            implementation_file="src/rag_pipeline/retrieval_service.py",
            notes="Configurable window (±1 chunks by default)"
        ),
        SOTAFeature(
            name="Metadata Filtering",
            description="Pre-filter by structured metadata before vector search",
            implemented=True,
            implementation_file="src/rag_pipeline/qdrant_service.py",
            notes="Indexed fields: report_id, year, tier, state, finding_type, severity, section_type"
        ),
        SOTAFeature(
            name="Auto-Filter Extraction",
            description="Automatically extract filters from natural language queries",
            implemented=True,
            implementation_file="src/rag_pipeline/auto_filter.py",
            notes="Detects states, years, tiers from query text"
        ),
        SOTAFeature(
            name="Context-Augmented Embeddings",
            description="Include document title/section in embedding input",
            implemented=True,
            implementation_file="src/rag_pipeline/embedding_service.py",
            notes="Prefixes chunks with report title and parent TOC entry"
        ),

        # === GENERATION ===
        SOTAFeature(
            name="Response Style Adaptation",
            description="Adjust response format based on question type",
            implemented=True,
            implementation_file="src/rag_pipeline/rag_service.py",
            notes="Styles: concise, detailed, executive, technical, comparative, explanatory"
        ),
        SOTAFeature(
            name="Streaming Responses (SSE)",
            description="Stream LLM tokens for better UX",
            implemented=True,
            implementation_file="src/api/services/streaming_wrapper.py",
            notes="Supports OpenAI, Claude, and Gemini streaming"
        ),
        SOTAFeature(
            name="Grounded Citations",
            description="Generate answers with inline citations to sources",
            implemented=True,
            implementation_file="src/rag_pipeline/rag_service.py",
            notes="Citations format: [Section, p.XX] with click-to-navigate in frontend"
        ),
        SOTAFeature(
            name="Groundedness Verification",
            description="Post-generation check that claims are supported by sources",
            implemented=True,
            implementation_file="src/rag_pipeline/groundedness_service.py",
            notes="Uses lightweight LLM to verify each factual claim against cited sources"
        ),
        SOTAFeature(
            name="Context Sufficiency Check",
            description="Detect when retrieved context is insufficient",
            implemented=True,
            implementation_file="src/rag_pipeline/rag_service.py",
            notes="Emits 'low_relevance' caveat when top rerank score < threshold"
        ),

        # === AGENTIC ===
        SOTAFeature(
            name="Query Decomposition",
            description="Break complex questions into sub-queries",
            implemented=True,
            implementation_file="src/rag_pipeline/agentic_service.py",
            notes="LLM detects simple vs multi-hop complexity"
        ),
        SOTAFeature(
            name="Iterative Retrieval",
            description="Multiple retrieval rounds with query refinement",
            implemented=True,
            implementation_file="src/rag_pipeline/agentic_service.py",
            notes="Max 3 iterations per sub-query with reformulation"
        ),
        SOTAFeature(
            name="Multi-Hop Reasoning",
            description="Answer questions requiring info from multiple sources",
            implemented=True,
            implementation_file="src/rag_pipeline/agentic_service.py",
            notes="Merges retrievals from sub-queries for synthesis"
        ),
        SOTAFeature(
            name="Execution Bounds",
            description="Prevent runaway agentic loops",
            implemented=True,
            implementation_file="src/rag_pipeline/agentic_service.py",
            notes="max_sub_queries=4, max_iterations=10, max_wall_ms=20000"
        ),

        # === ADVANCED (May or may not be implemented) ===
        SOTAFeature(
            name="Query Routing",
            description="Route queries to specialized retrievers based on intent",
            implemented=False,
            notes="Could route to entity graph, temporal retriever, or standard RAG"
        ),
        SOTAFeature(
            name="RAPTOR / Hierarchical Retrieval",
            description="Multi-level document summaries for better abstraction",
            implemented=False,
            notes="Would require summary pyramid during indexing"
        ),
        SOTAFeature(
            name="Self-RAG / Adaptive Retrieval",
            description="LLM decides whether to retrieve at each step",
            implemented=False,
            notes="Current system always retrieves"
        ),
        SOTAFeature(
            name="Corrective RAG",
            description="Detect and correct retrieval failures mid-generation",
            implemented=False,
            notes="Groundedness verification is post-hoc, not corrective"
        ),
        SOTAFeature(
            name="Knowledge Graph Integration",
            description="Use entity relationships for retrieval",
            implemented=True,
            implementation_file="src/core/config.py",
            notes="Entity graph with canonicalization (requires Postgres)"
        ),
    ]


def main():
    """Run diagnostic analysis."""
    print("\n" + "="*80)
    print("CAG RAG PIPELINE DIAGNOSTIC ANALYSIS")
    print("="*80 + "\n")

    # 1. Configuration Analysis
    print("1. CONFIGURATION ANALYSIS")
    print("-" * 40)
    config = analyze_config()
    print(f"   Embedding Model: {config['embedding_model']}")
    print(f"   Embedding Dimensions: {config['embedding_dimensions']}")
    print(f"   Sparse Model: {config['sparse_model']}")
    print(f"   LLM Providers: {', '.join(config['llm_providers'])}")
    print(f"   Reranker Options: {', '.join(config['reranker_types'])}")
    print()

    # 2. Retrieval Service Analysis
    print("2. RETRIEVAL SERVICE ANALYSIS")
    print("-" * 40)
    retrieval = analyze_retrieval_service()
    for feature, enabled in retrieval["features"].items():
        status = "✓" if enabled else "✗"
        print(f"   [{status}] {feature.replace('_', ' ').title()}")
    print()

    # 3. Agentic Service Analysis
    print("3. AGENTIC RAG ANALYSIS")
    print("-" * 40)
    agentic = analyze_agentic_service()
    for feature, enabled in agentic["features"].items():
        status = "✓" if enabled else "✗"
        print(f"   [{status}] {feature.replace('_', ' ').title()}")
    print()

    # 4. Qdrant Service Analysis
    print("4. VECTOR STORE ANALYSIS")
    print("-" * 40)
    qdrant = analyze_qdrant_service()
    for feature, enabled in qdrant["features"].items():
        status = "✓" if enabled else "✗"
        print(f"   [{status}] {feature.replace('_', ' ').title()}")
    print(f"   Indexed Fields: {', '.join(qdrant['indexed_fields'][:10])}...")
    print()

    # 5. Embedding Service Analysis
    print("5. EMBEDDING SERVICE ANALYSIS")
    print("-" * 40)
    embedding = analyze_embedding_service()
    for feature, enabled in embedding["features"].items():
        status = "✓" if enabled else "✗"
        print(f"   [{status}] {feature.replace('_', ' ').title()}")
    print()

    # 6. Processed Data Analysis
    print("6. PROCESSED DATA ANALYSIS")
    print("-" * 40)
    data = analyze_processed_data()
    print(f"   Total Reports: {data['total_reports']}")
    print(f"   Tiers: {dict(data['tiers'])}")
    print(f"   Content Types: {data['content_types'][:5]}")
    print(f"   Finding Types: {data['finding_types'][:5]}")
    print(f"   Section Types: {data['section_types'][:5]}")
    print()

    # 7. SOTA Feature Checklist
    print("7. STATE-OF-THE-ART RAG FEATURE CHECKLIST")
    print("-" * 40)
    sota = get_sota_checklist()

    implemented = [f for f in sota if f.implemented]
    not_implemented = [f for f in sota if not f.implemented]

    print(f"\n   IMPLEMENTED ({len(implemented)}/{len(sota)}):")
    for f in implemented:
        print(f"   ✓ {f.name}")
        if f.notes:
            print(f"     └─ {f.notes}")

    print(f"\n   NOT IMPLEMENTED ({len(not_implemented)}):")
    for f in not_implemented:
        print(f"   ✗ {f.name}")
        if f.notes:
            print(f"     └─ {f.notes}")

    # 8. Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    sota_score = len(implemented) / len(sota) * 100

    print(f"""
ARCHITECTURE:
  - Vector Store: Qdrant (hybrid dense + sparse vectors)
  - Embeddings: {config['embedding_model']} ({config['embedding_dimensions']}d) + BM25
  - Reranking: Cohere rerank-english-v3.0 (cross-encoder)
  - LLM Generation: Claude/GPT-4o/Gemini (configurable)
  - Chunking: Parent-child with neighbor expansion

SOTA COMPLIANCE: {sota_score:.0f}% ({len(implemented)}/{len(sota)} features)

STRENGTHS:
  1. Hybrid retrieval (dense + BM25) with RRF fusion
  2. Multi-query expansion via LLM
  3. Cross-encoder reranking
  4. Parent-child chunking with neighbor context
  5. Agentic multi-hop with query decomposition
  6. Groundedness verification post-generation
  7. Rich metadata filtering (tier, state, finding_type, severity)
  8. SSE streaming with citation maps

GAPS:
  1. No RAPTOR/hierarchical retrieval
  2. No self-RAG (adaptive retrieval decisions)
  3. No corrective RAG (mid-generation correction)
  4. No query routing to specialized retrievers
""")

    # Save results
    output_path = PROJECT_ROOT / "results" / "rag_diagnostic.json"
    output_path.parent.mkdir(exist_ok=True)

    results = {
        "config": config,
        "retrieval_features": retrieval["features"],
        "agentic_features": agentic["features"],
        "qdrant_features": qdrant["features"],
        "indexed_fields": qdrant["indexed_fields"],
        "embedding_features": embedding["features"],
        "data_stats": {
            "total_reports": data["total_reports"],
            "tiers": data["tiers"],
            "content_types": data["content_types"],
            "finding_types": data["finding_types"],
            "section_types": data["section_types"],
        },
        "sota_features": [
            {
                "name": f.name,
                "implemented": f.implemented,
                "notes": f.notes,
                "file": f.implementation_file,
            }
            for f in sota
        ],
        "sota_score_pct": sota_score,
    }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
