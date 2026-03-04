"""
CAG RAG Pipeline - CLI
=======================

Command-line interface for querying CAG audit reports.

Usage:
    # Single question
    python -m rag_pipeline.cli "What are the audit findings on toll collection?"

    # With filters
    python -m rag_pipeline.cli "Revenue losses" --finding-type loss_of_revenue --min-amount 10

    # Interactive mode
    python -m rag_pipeline.cli --interactive

    # With response style
    python -m rag_pipeline.cli --style concise "What was the revenue loss?"
"""

import argparse
import json
import sys
from typing import Optional, Dict, Any

try:
    from ..core.config import RAGConfig, LLMProvider, RerankerType
    from .rag_service import RAGService, ResponseStyle
except ImportError:
    from src.core.config import RAGConfig, LLMProvider, RerankerType
    from rag_service import RAGService, ResponseStyle


def parse_filters(args) -> Dict[str, Any]:
    """Parse filter arguments into filter dict."""
    filters = {}

    if args.report_id:
        filters["report_id"] = args.report_id

    if args.report_year:
        filters["report_year"] = args.report_year

    if args.min_year:
        filters["report_year"] = {"gte": args.min_year}

    if args.finding_type:
        filters["finding_type"] = args.finding_type

    if args.severity:
        filters["severity"] = args.severity

    if args.min_amount:
        filters["total_amount_crore"] = {"gte": args.min_amount}

    return filters


def get_style_from_string(style_str: str) -> ResponseStyle:
    """Convert style string to ResponseStyle enum."""
    style_map = {
        "concise": ResponseStyle.CONCISE,
        "conversational": ResponseStyle.CONVERSATIONAL,
        "executive": ResponseStyle.EXECUTIVE,
        "analytical": ResponseStyle.ANALYTICAL,
        "report": ResponseStyle.REPORT,
        "adaptive": ResponseStyle.ADAPTIVE,
    }
    return style_map.get(style_str.lower(), ResponseStyle.ADAPTIVE)


def run_interactive(rag: RAGService, filters: Dict[str, Any], style: ResponseStyle):
    """Run interactive mode."""
    print("\n" + "=" * 60)
    print("CAG RAG - Interactive Mode")
    print("=" * 60)
    print("Ask questions about CAG audit reports.")
    print(f"Current style: {style.value}")
    print("Commands:")
    print("  'quit' - exit")
    print("  'filters' - show active filters")
    print(
        "  'style <name>' - change style (concise/conversational/executive/analytical/report/adaptive)"
    )
    print("  'styles' - list all styles")
    print("=" * 60 + "\n")

    current_style = style

    while True:
        try:
            question = input("You: ").strip()

            if not question:
                continue

            if question.lower() in ["quit", "exit", "q"]:
                print("Goodbye!")
                break

            if question.lower() == "filters":
                if filters:
                    print(f"Active filters: {json.dumps(filters, indent=2)}")
                else:
                    print("No filters active")
                continue

            if question.lower() == "styles":
                print("\nAvailable styles:")
                print("  concise       - 3-4 sentences max, just the key finding")
                print("  conversational - Natural paragraphs, moderate detail")
                print("  executive     - Bottom line + bullet points with amounts")
                print("  analytical    - Deep dive with themes and implications")
                print("  report        - Formal structure for documentation")
                print("  adaptive      - Automatically matches question complexity")
                print(f"\nCurrent: {current_style.value}\n")
                continue

            if question.lower().startswith("style "):
                new_style = question[6:].strip().lower()
                if new_style in [
                    "concise",
                    "conversational",
                    "executive",
                    "analytical",
                    "report",
                    "adaptive",
                ]:
                    current_style = get_style_from_string(new_style)
                    print(f"Style changed to: {current_style.value}\n")
                else:
                    print(f"Unknown style: {new_style}. Use 'styles' to see options.\n")
                continue

            print("\nSearching...\n")
            response = rag.ask(question, filters=filters, style=current_style)

            print("=" * 60)
            print(f"ANSWER ({current_style.value}):")
            print("=" * 60)
            print(response.answer)

            if response.citations:
                print("\n" + "-" * 60)
                print("SOURCES:")
                for cite in response.citations[:5]:
                    print(
                        f"  [{cite.id}] {cite.report_id} - {cite.section} (p.{cite.page})"
                    )

            print(
                "\n"
                + f"[{response.sources_used} sources, {response.search_type} search, {response.reranker_used} rerank]"
            )
            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


def run_single_query(
    rag: RAGService, question: str, filters: Dict[str, Any], args, style: ResponseStyle
):
    """Run a single query."""
    print("\n" + "=" * 60)
    print(f"Question: {question}")
    print(f"Style: {style.value}")
    if filters:
        print(f"Filters: {filters}")
    print("=" * 60 + "\n")

    response = rag.ask(question, filters=filters, top_k=args.top_k, style=style)

    print("ANSWER:")
    print("-" * 60)
    print(response.answer)
    print("-" * 60)

    if response.citations:
        print("\nSOURCES:")
        for cite in response.citations:
            parts = [f"[{cite.id}] {cite.report_id}"]
            parts.append(f"- {cite.section}")
            parts.append(f"(p.{cite.page})")
            if cite.finding_type:
                parts.append(f"[{cite.finding_type}]")
            if cite.amount_crore:
                parts.append(f"[₹{cite.amount_crore:.2f}cr]")
            print("  " + " ".join(parts))

    print(f"\nMetadata:")
    print(f"  Sources: {response.sources_used}")
    print(f"  Context: {response.context_length} chars")
    print(f"  Search: {response.search_type}")
    print(f"  Reranker: {response.reranker_used}")
    print(f"  Model: {response.model_used}")

    if args.json:
        print("\nJSON Output:")
        print(json.dumps(response.to_dict(), indent=2))


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Query CAG audit reports using RAG")

    # Query
    parser.add_argument(
        "question",
        nargs="?",
        help="Question to ask",
    )

    # Modes
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive mode",
    )

    # Retrieval settings
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of chunks to retrieve",
    )

    # Filters
    parser.add_argument(
        "--report-id",
        type=str,
        help="Filter by report ID",
    )
    parser.add_argument(
        "--report-year",
        type=int,
        help="Filter by exact report year",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        help="Filter by minimum report year",
    )
    parser.add_argument(
        "--finding-type",
        type=str,
        choices=[
            "loss_of_revenue",
            "wasteful_expenditure",
            "irregular_expenditure",
            "non_compliance",
            "fraud_misappropriation",
            "system_deficiency",
            "performance_shortfall",
            "procedural_lapse",
        ],
        help="Filter by finding type",
    )
    parser.add_argument(
        "--severity",
        type=str,
        choices=["critical", "high", "medium", "low"],
        help="Filter by severity",
    )
    parser.add_argument(
        "--min-amount",
        type=float,
        help="Filter by minimum amount (crore)",
    )

    # LLM settings
    parser.add_argument(
        "--provider",
        type=str,
        choices=["claude", "openai"],
        default="claude",
        help="LLM provider",
    )
    parser.add_argument(
        "--style",
        type=str,
        choices=[
            "concise",
            "conversational",
            "executive",
            "analytical",
            "report",
            "adaptive",
        ],
        default="adaptive",
        help="Response style (default: adaptive)",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Disable reranking",
    )

    # Output
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    # Validate
    if not args.interactive and not args.question:
        parser.print_help()
        print("\nError: Provide a question or use --interactive mode")
        return 1

    # Configure
    config = RAGConfig()
    config.llm.provider = (
        LLMProvider.CLAUDE if args.provider == "claude" else LLMProvider.OPENAI
    )

    if args.no_rerank:
        config.retrieval.enable_reranking = False

    # Validate config
    errors = config.validate()
    if errors:
        print(f"Configuration errors:")
        for e in errors:
            print(f"  - {e}")
        return 1

    # Initialize RAG
    try:
        rag = RAGService(config)
    except Exception as e:
        print(f"Failed to initialize RAG: {e}")
        return 1

    # Parse filters and style
    filters = parse_filters(args)
    style = get_style_from_string(args.style)

    # Run
    if args.interactive:
        run_interactive(rag, filters, style)
    else:
        run_single_query(rag, args.question, filters, args, style)

    return 0


if __name__ == "__main__":
    sys.exit(main())
