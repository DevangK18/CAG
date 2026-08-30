#!/usr/bin/env python3
"""
RAG Pipeline Analysis Script
=============================
Comprehensive analysis of the CAG RAG pipeline including:
1. Qdrant connection and collection stats
2. Retrieval quality metrics
3. Query type handling
4. Reranking effectiveness
5. Hybrid search (dense + sparse) analysis
6. Agentic RAG testing
7. Citation accuracy

Run: python scripts/analyze_rag_pipeline.py
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class RetrievalMetrics:
    """Metrics for a single retrieval test."""
    query: str
    query_type: str
    retrieval_time_ms: float
    total_candidates: int
    total_after_rerank: int
    search_type: str
    reranker_used: str
    top_1_score: float = 0.0
    top_5_avg_score: float = 0.0
    has_findings: bool = False
    has_recommendations: bool = False
    num_unique_reports: int = 0
    num_parents: int = 0
    filters_applied: Dict = field(default_factory=dict)


@dataclass
class PipelineAnalysis:
    """Complete pipeline analysis results."""
    # Qdrant stats
    qdrant_connected: bool = False
    child_chunks_count: int = 0
    parent_chunks_count: int = 0

    # Retrieval metrics
    retrieval_tests: List[RetrievalMetrics] = field(default_factory=list)
    avg_retrieval_time_ms: float = 0.0
    avg_top_1_score: float = 0.0
    avg_rerank_reduction: float = 0.0

    # Feature flags
    hybrid_search_enabled: bool = False
    reranking_enabled: bool = False
    query_enhancement_enabled: bool = False
    agentic_enabled: bool = False
    groundedness_enabled: bool = False

    # Error tracking
    errors: List[str] = field(default_factory=list)


def test_qdrant_connection(config) -> Dict[str, Any]:
    """Test Qdrant connection and get collection stats."""
    from src.rag_pipeline.qdrant_service import QdrantService

    try:
        qdrant = QdrantService(config)
        stats = qdrant.get_collection_stats()

        return {
            "connected": True,
            "child_chunks": stats.get("child_chunks", {}).get("count", 0),
            "parent_chunks": stats.get("parent_chunks", {}).get("count", 0),
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Qdrant connection failed: {e}")
        return {"connected": False, "error": str(e)}


def run_retrieval_test(
    retrieval_service,
    query: str,
    query_type: str,
    filters: Optional[Dict] = None,
    top_k: int = 10,
) -> RetrievalMetrics:
    """Run a single retrieval test and collect metrics."""
    start_time = time.time()

    result = retrieval_service.retrieve(
        query=query,
        top_k=top_k,
        filters=filters,
    )

    elapsed_ms = (time.time() - start_time) * 1000

    # Collect chunk scores
    all_chunks = result.get_all_chunks()
    scores = [c.score for c in all_chunks]

    # Check for semantic enrichment
    has_findings = any(c.finding_type for c in all_chunks)
    has_recommendations = any(c.is_recommendation for c in all_chunks)

    # Unique reports
    unique_reports = set(c.report_id for c in all_chunks)

    return RetrievalMetrics(
        query=query,
        query_type=query_type,
        retrieval_time_ms=round(elapsed_ms, 2),
        total_candidates=result.total_candidates,
        total_after_rerank=result.total_after_rerank,
        search_type=result.search_type,
        reranker_used=result.reranker_used,
        top_1_score=round(scores[0], 4) if scores else 0.0,
        top_5_avg_score=round(sum(scores[:5]) / min(5, len(scores)), 4) if scores else 0.0,
        has_findings=has_findings,
        has_recommendations=has_recommendations,
        num_unique_reports=len(unique_reports),
        num_parents=len(result.parents),
        filters_applied=result.filters_applied or {},
    )


def test_query_types(retrieval_service) -> List[RetrievalMetrics]:
    """Test retrieval with different query types."""
    test_queries = [
        # Factual queries
        ("What is the toll collection shortfall at NHAI?", "factual"),
        ("What was the revenue loss in 2023?", "factual"),
        ("What is FRBM compliance?", "factual"),

        # List queries
        ("What are the main findings in the toll audit?", "list"),
        ("List the recommendations for NHAI", "list"),
        ("What issues were found in food grain storage?", "list"),

        # Aggregation queries
        ("What is the total revenue loss across all audits?", "aggregation"),
        ("How much was the total expenditure shortfall?", "aggregation"),

        # Comparison queries
        ("How has FRBM compliance changed over the years?", "comparison"),
        ("Compare the fiscal deficit across different years", "comparison"),

        # Explanation queries
        ("Why did toll collection delays occur?", "explanation"),
        ("What caused the revenue shortfall at NHAI?", "explanation"),

        # Domain-specific queries
        ("GST collection issues in state audits", "domain"),
        ("Panchayati Raj audit findings", "domain"),
        ("Local body fund utilization", "domain"),
    ]

    results = []
    for query, query_type in test_queries:
        try:
            logger.info(f"Testing: {query[:60]}...")
            metrics = run_retrieval_test(retrieval_service, query, query_type)
            results.append(metrics)
        except Exception as e:
            logger.error(f"Query failed: {query[:40]}... - {e}")

    return results


def test_filtered_retrieval(retrieval_service) -> List[RetrievalMetrics]:
    """Test retrieval with various filters."""
    filter_tests = [
        # Report-scoped query
        {
            "query": "What are the key findings?",
            "query_type": "filtered_report",
            "filters": {"report_id": "2023_07"},
        },
        # Finding type filter
        {
            "query": "Show revenue loss findings",
            "query_type": "filtered_finding_type",
            "filters": {"finding_type": "loss_of_revenue"},
        },
        # Severity filter
        {
            "query": "What are the critical issues?",
            "query_type": "filtered_severity",
            "filters": {"severity": "critical"},
        },
        # State filter
        {
            "query": "Gujarat audit findings",
            "query_type": "filtered_state",
            "filters": {"state_name": "Gujarat"},
        },
        # Tier filter
        {
            "query": "Local body audit issues",
            "query_type": "filtered_tier",
            "filters": {"government_body_type": "local_body"},
        },
    ]

    results = []
    for test in filter_tests:
        try:
            logger.info(f"Testing filtered: {test['query'][:40]}...")
            metrics = run_retrieval_test(
                retrieval_service,
                test["query"],
                test["query_type"],
                filters=test["filters"],
            )
            results.append(metrics)
        except Exception as e:
            logger.error(f"Filtered query failed: {test['query'][:40]}... - {e}")

    return results


def test_hybrid_search_effectiveness(retrieval_service) -> Dict[str, Any]:
    """
    Compare hybrid vs dense-only search.
    Tests queries where BM25 should help (exact terms, section numbers).
    """
    exact_match_queries = [
        "Section 143(3) compliance",
        "Rule 86B violations",
        "NHAI toll collection",
        "₹847.71 crore revenue loss",
        "Form 26AS discrepancies",
        "PMAY scheme implementation",
    ]

    results = {
        "hybrid_scores": [],
        "total_queries": len(exact_match_queries),
        "queries_tested": [],
    }

    for query in exact_match_queries:
        try:
            metrics = run_retrieval_test(retrieval_service, query, "exact_match")
            results["hybrid_scores"].append(metrics.top_1_score)
            results["queries_tested"].append({
                "query": query,
                "search_type": metrics.search_type,
                "top_score": metrics.top_1_score,
            })
        except Exception as e:
            logger.error(f"Hybrid test failed: {query[:40]}... - {e}")

    results["avg_hybrid_score"] = (
        sum(results["hybrid_scores"]) / len(results["hybrid_scores"])
        if results["hybrid_scores"]
        else 0.0
    )

    return results


def test_reranking_effectiveness(retrieval_service) -> Dict[str, Any]:
    """Measure reranking impact on retrieval quality."""
    test_queries = [
        "What caused the toll collection delays?",
        "Revenue loss in food grain storage",
        "FRBM compliance issues",
    ]

    results = {
        "rerank_improvement": [],
        "reranker_used": "",
    }

    for query in test_queries:
        try:
            metrics = run_retrieval_test(retrieval_service, query, "rerank_test")
            results["reranker_used"] = metrics.reranker_used

            # Calculate reduction ratio
            if metrics.total_candidates > 0:
                reduction = 1 - (metrics.total_after_rerank / metrics.total_candidates)
                results["rerank_improvement"].append({
                    "query": query[:50],
                    "candidates": metrics.total_candidates,
                    "after_rerank": metrics.total_after_rerank,
                    "reduction_pct": round(reduction * 100, 1),
                    "top_score": metrics.top_1_score,
                })
        except Exception as e:
            logger.error(f"Reranking test failed: {query[:40]}... - {e}")

    return results


def test_query_enhancement(rag_service) -> Dict[str, Any]:
    """Test query enhancement service."""
    if not hasattr(rag_service, "query_enhancer") or not rag_service.query_enhancer:
        return {"enabled": False, "message": "Query enhancement not enabled"}

    test_queries = [
        "toll revenue problems",
        "what went wrong with NHAI",
        "food grain storage issues",
    ]

    results = {
        "enabled": True,
        "enhancements": [],
    }

    for query in test_queries:
        try:
            enhancement = rag_service.query_enhancer.enhance(query)
            results["enhancements"].append({
                "original": query,
                "question_type": enhancement.question_type,
                "expanded_queries": enhancement.expanded_queries,
                "suggested_filters": enhancement.suggested_filters,
                "top_k": enhancement.top_k,
                "recommended_style": enhancement.recommended_style,
            })
        except Exception as e:
            logger.error(f"Enhancement failed: {query[:40]}... - {e}")

    return results


def test_agentic_decomposition(rag_service) -> Dict[str, Any]:
    """Test agentic query decomposition."""
    if not hasattr(rag_service, "agentic_service") or not rag_service.agentic_service:
        return {"enabled": False, "message": "Agentic service not enabled"}

    test_queries = [
        ("What is the toll collection at NHAI?", "simple"),
        ("What caused toll delays and how much did users lose?", "multi_hop"),
        ("How has FRBM compliance evolved from 2022 to 2024?", "cross_report"),
    ]

    results = {
        "enabled": True,
        "decompositions": [],
    }

    for query, expected_complexity in test_queries:
        try:
            plan = rag_service.agentic_service._decompose(query)
            results["decompositions"].append({
                "query": query,
                "expected_complexity": expected_complexity,
                "actual_complexity": plan.get("complexity"),
                "correct": plan.get("complexity") == expected_complexity,
                "sub_queries": plan.get("sub_queries"),
                "reason": plan.get("reason"),
            })
        except Exception as e:
            logger.error(f"Decomposition failed: {query[:40]}... - {e}")

    return results


def test_end_to_end_response(rag_service) -> Dict[str, Any]:
    """Test full RAG response generation."""
    test_query = "What are the main findings in the NHAI toll audit?"

    try:
        start_time = time.time()
        response = rag_service.ask(
            question=test_query,
            filters={"report_id": "2023_07"},
            top_k=10,
        )
        elapsed_ms = (time.time() - start_time) * 1000

        return {
            "success": True,
            "query": test_query,
            "response_time_ms": round(elapsed_ms, 2),
            "answer_length": len(response.answer),
            "citations_count": len(response.citations),
            "sources_used": response.sources_used,
            "model_used": response.model_used,
            "search_type": response.search_type,
            "reranker_used": response.reranker_used,
            "has_groundedness": response.groundedness is not None,
            "answer_preview": response.answer[:500] + "..." if len(response.answer) > 500 else response.answer,
        }
    except Exception as e:
        logger.error(f"End-to-end test failed: {e}")
        return {"success": False, "error": str(e)}


def analyze_rag_pipeline() -> PipelineAnalysis:
    """Main analysis function."""
    from src.core.config import RAGConfig
    from src.rag_pipeline.retrieval_service import RetrievalService
    from src.rag_pipeline.rag_service import RAGService

    analysis = PipelineAnalysis()

    print("\n" + "="*80)
    print("CAG RAG PIPELINE ANALYSIS")
    print("="*80 + "\n")

    # 1. Initialize config
    print("1. Initializing configuration...")
    try:
        config = RAGConfig()
        analysis.hybrid_search_enabled = config.retrieval.enable_hybrid_search
        analysis.reranking_enabled = config.retrieval.enable_reranking
        analysis.query_enhancement_enabled = config.query_enhancement.enabled
        analysis.agentic_enabled = config.agentic.enabled
        analysis.groundedness_enabled = config.groundedness.enabled

        print(f"   - Hybrid search: {'✓' if analysis.hybrid_search_enabled else '✗'}")
        print(f"   - Reranking ({config.retrieval.reranker_type.value}): {'✓' if analysis.reranking_enabled else '✗'}")
        print(f"   - Query enhancement: {'✓' if analysis.query_enhancement_enabled else '✗'}")
        print(f"   - Agentic RAG: {'✓' if analysis.agentic_enabled else '✗'}")
        print(f"   - Groundedness: {'✓' if analysis.groundedness_enabled else '✗'}")
    except Exception as e:
        analysis.errors.append(f"Config init failed: {e}")
        logger.error(f"Config initialization failed: {e}")
        return analysis

    # 2. Test Qdrant connection
    print("\n2. Testing Qdrant connection...")
    qdrant_stats = test_qdrant_connection(config)
    analysis.qdrant_connected = qdrant_stats.get("connected", False)
    if analysis.qdrant_connected:
        analysis.child_chunks_count = qdrant_stats.get("child_chunks", 0)
        analysis.parent_chunks_count = qdrant_stats.get("parent_chunks", 0)
        print(f"   ✓ Connected to Qdrant")
        print(f"   - Child chunks: {analysis.child_chunks_count:,}")
        print(f"   - Parent chunks: {analysis.parent_chunks_count:,}")
    else:
        analysis.errors.append(f"Qdrant connection failed: {qdrant_stats.get('error')}")
        print(f"   ✗ Connection failed: {qdrant_stats.get('error')}")
        return analysis

    # 3. Initialize services
    print("\n3. Initializing RAG services...")
    try:
        retrieval_service = RetrievalService(config)
        rag_service = RAGService(config)
        print("   ✓ Services initialized")
    except Exception as e:
        analysis.errors.append(f"Service init failed: {e}")
        logger.error(f"Service initialization failed: {e}")
        return analysis

    # 4. Run retrieval tests
    print("\n4. Running retrieval tests...")
    retrieval_results = test_query_types(retrieval_service)
    filtered_results = test_filtered_retrieval(retrieval_service)

    all_results = retrieval_results + filtered_results
    analysis.retrieval_tests = all_results

    if all_results:
        analysis.avg_retrieval_time_ms = round(
            sum(r.retrieval_time_ms for r in all_results) / len(all_results), 2
        )
        analysis.avg_top_1_score = round(
            sum(r.top_1_score for r in all_results) / len(all_results), 4
        )

        total_candidates = sum(r.total_candidates for r in all_results)
        total_after = sum(r.total_after_rerank for r in all_results)
        if total_candidates > 0:
            analysis.avg_rerank_reduction = round(
                (1 - total_after / total_candidates) * 100, 1
            )

    print(f"   - Tests run: {len(all_results)}")
    print(f"   - Avg retrieval time: {analysis.avg_retrieval_time_ms}ms")
    print(f"   - Avg top-1 score: {analysis.avg_top_1_score}")
    print(f"   - Avg rerank reduction: {analysis.avg_rerank_reduction}%")

    # 5. Test hybrid search
    print("\n5. Testing hybrid search effectiveness...")
    hybrid_results = test_hybrid_search_effectiveness(retrieval_service)
    print(f"   - Avg hybrid score: {hybrid_results.get('avg_hybrid_score', 0):.4f}")
    print(f"   - Queries tested: {hybrid_results.get('total_queries', 0)}")

    # 6. Test reranking
    print("\n6. Testing reranking effectiveness...")
    rerank_results = test_reranking_effectiveness(retrieval_service)
    print(f"   - Reranker: {rerank_results.get('reranker_used', 'none')}")
    for item in rerank_results.get("rerank_improvement", []):
        print(f"   - {item['query']}: {item['candidates']}→{item['after_rerank']} ({item['reduction_pct']}% reduction)")

    # 7. Test query enhancement
    print("\n7. Testing query enhancement...")
    enhancement_results = test_query_enhancement(rag_service)
    if enhancement_results.get("enabled"):
        print(f"   ✓ Query enhancement enabled")
        for enh in enhancement_results.get("enhancements", [])[:2]:
            print(f"   - '{enh['original']}' → type={enh['question_type']}, expansions={len(enh['expanded_queries'])}")
    else:
        print(f"   ✗ {enhancement_results.get('message')}")

    # 8. Test agentic decomposition
    print("\n8. Testing agentic decomposition...")
    agentic_results = test_agentic_decomposition(rag_service)
    if agentic_results.get("enabled"):
        print(f"   ✓ Agentic RAG enabled")
        correct = sum(1 for d in agentic_results.get("decompositions", []) if d.get("correct"))
        total = len(agentic_results.get("decompositions", []))
        print(f"   - Decomposition accuracy: {correct}/{total}")
    else:
        print(f"   ✗ {agentic_results.get('message')}")

    # 9. End-to-end test
    print("\n9. Running end-to-end test...")
    e2e_results = test_end_to_end_response(rag_service)
    if e2e_results.get("success"):
        print(f"   ✓ End-to-end test passed")
        print(f"   - Response time: {e2e_results['response_time_ms']}ms")
        print(f"   - Answer length: {e2e_results['answer_length']} chars")
        print(f"   - Citations: {e2e_results['citations_count']}")
        print(f"   - Sources used: {e2e_results['sources_used']}")
        print(f"   - Model: {e2e_results['model_used']}")
    else:
        print(f"   ✗ Test failed: {e2e_results.get('error')}")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    print(f"""
Qdrant Status:
  - Connected: {'✓' if analysis.qdrant_connected else '✗'}
  - Child chunks: {analysis.child_chunks_count:,}
  - Parent chunks: {analysis.parent_chunks_count:,}

Feature Status:
  - Hybrid Search (Dense + BM25): {'✓ Enabled' if analysis.hybrid_search_enabled else '✗ Disabled'}
  - Reranking (Cohere/BGE): {'✓ Enabled' if analysis.reranking_enabled else '✗ Disabled'}
  - Query Enhancement: {'✓ Enabled' if analysis.query_enhancement_enabled else '✗ Disabled'}
  - Agentic RAG (Multi-hop): {'✓ Enabled' if analysis.agentic_enabled else '✗ Disabled'}
  - Groundedness Verification: {'✓ Enabled' if analysis.groundedness_enabled else '✗ Disabled'}

Retrieval Metrics:
  - Average retrieval time: {analysis.avg_retrieval_time_ms}ms
  - Average top-1 relevance score: {analysis.avg_top_1_score}
  - Average rerank reduction: {analysis.avg_rerank_reduction}%
  - Tests with findings: {sum(1 for r in analysis.retrieval_tests if r.has_findings)}/{len(analysis.retrieval_tests)}
  - Tests with recommendations: {sum(1 for r in analysis.retrieval_tests if r.has_recommendations)}/{len(analysis.retrieval_tests)}

Errors: {len(analysis.errors)}
""")

    if analysis.errors:
        print("Errors encountered:")
        for err in analysis.errors:
            print(f"  - {err}")

    # Save detailed results
    output_path = PROJECT_ROOT / "results" / "rag_pipeline_analysis.json"
    output_path.parent.mkdir(exist_ok=True)

    output_data = {
        "qdrant_connected": analysis.qdrant_connected,
        "child_chunks_count": analysis.child_chunks_count,
        "parent_chunks_count": analysis.parent_chunks_count,
        "features": {
            "hybrid_search": analysis.hybrid_search_enabled,
            "reranking": analysis.reranking_enabled,
            "query_enhancement": analysis.query_enhancement_enabled,
            "agentic": analysis.agentic_enabled,
            "groundedness": analysis.groundedness_enabled,
        },
        "metrics": {
            "avg_retrieval_time_ms": analysis.avg_retrieval_time_ms,
            "avg_top_1_score": analysis.avg_top_1_score,
            "avg_rerank_reduction": analysis.avg_rerank_reduction,
        },
        "retrieval_tests": [asdict(r) for r in analysis.retrieval_tests],
        "hybrid_search_results": hybrid_results,
        "reranking_results": rerank_results,
        "query_enhancement_results": enhancement_results,
        "agentic_results": agentic_results,
        "e2e_results": e2e_results,
        "errors": analysis.errors,
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2, default=str)

    print(f"\nDetailed results saved to: {output_path}")

    return analysis


if __name__ == "__main__":
    analyze_rag_pipeline()
