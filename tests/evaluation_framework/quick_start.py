#!/usr/bin/env python3
"""
Quick Start Script for CAG RAG Evaluation
==========================================

This script provides simple commands to get started with evaluation.

Usage:
    python quick_start.py run           # Run evaluation on sample test cases
    python quick_start.py test          # Run a quick test query
    python quick_start.py create        # Create a new test case interactively
    python quick_start.py analyze       # Analyze latest results
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Ensure we can import from parent
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass


def run_evaluation():
    """Run evaluation on sample test cases."""
    print("=" * 60)
    print("Running CAG RAG Evaluation")
    print("=" * 60)
    
    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set")
        print("Please set it in .env file or environment")
        return 1
    
    # Run evaluation
    import subprocess
    result = subprocess.run([
        sys.executable, 
        "evaluate.py",
        "--test-cases", "sample_test_cases.json",
        "--output", "results",
        "--provider", "openai",
        "--style", "adaptive",
        "--verbose"
    ], cwd=Path(__file__).parent)
    
    return result.returncode


def quick_test():
    """Run a quick interactive test."""
    print("=" * 60)
    print("Quick RAG Test")
    print("=" * 60)
    
    try:
        from services.rag_pipeline.rag_service import RAGService, ResponseStyle
        from services.rag_pipeline.config import RAGConfig, LLMProvider
    except ImportError:
        try:
            from rag_pipeline.rag_service import RAGService, ResponseStyle
            from rag_pipeline.config import RAGConfig, LLMProvider
        except ImportError:
            print("Error: Could not import RAG service")
            print("Make sure you're running from the project root")
            return 1
    
    # Initialize
    config = RAGConfig()
    config.llm.provider = LLMProvider.OPENAI
    rag = RAGService(config)
    
    print("\nRAG Service initialized. Enter questions to test.")
    print("Commands: 'quit' to exit, 'style X' to change style")
    print("-" * 60)
    
    current_style = ResponseStyle.ADAPTIVE
    
    while True:
        try:
            question = input("\nQuestion: ").strip()
            
            if not question:
                continue
            
            if question.lower() == 'quit':
                break
            
            if question.lower().startswith('style '):
                style_name = question[6:].strip().lower()
                style_map = {
                    "concise": ResponseStyle.CONCISE,
                    "conversational": ResponseStyle.CONVERSATIONAL,
                    "executive": ResponseStyle.EXECUTIVE,
                    "analytical": ResponseStyle.ANALYTICAL,
                    "report": ResponseStyle.REPORT,
                    "adaptive": ResponseStyle.ADAPTIVE,
                }
                if style_name in style_map:
                    current_style = style_map[style_name]
                    print(f"Style changed to: {current_style.value}")
                else:
                    print(f"Unknown style. Options: {list(style_map.keys())}")
                continue
            
            print("\nSearching...")
            response = rag.ask(question, style=current_style)
            
            print("\n" + "=" * 60)
            print("ANSWER:")
            print("=" * 60)
            print(response.answer)
            print("-" * 60)
            print(f"Sources: {response.sources_used} | Style: {current_style.value}")
            
            # Quick verification prompts
            print("\nQuick Check:")
            print("  1. Factually accurate? (y/n)")
            print("  2. Complete? (y/n)")
            print("  3. Any issues? (describe or press Enter)")
            
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")
    
    return 0


def create_test_case():
    """Create a new test case interactively."""
    print("=" * 60)
    print("Create New Test Case")
    print("=" * 60)
    
    # Get test case ID
    test_id = input("Test ID (e.g., TC031): ").strip()
    if not test_id:
        test_id = f"TC_{datetime.now().strftime('%H%M%S')}"
    
    # Get question
    question = input("Question: ").strip()
    if not question:
        print("Question is required")
        return 1
    
    # Get category
    print("\nDifficulty options: easy, medium, hard")
    difficulty = input("Difficulty: ").strip().lower() or "medium"
    
    print("\nType options: factual, list, explanation, comparison, aggregation, negative")
    qtype = input("Type: ").strip().lower() or "factual"
    
    reports = input("Related reports (comma-separated): ").strip()
    reports = [r.strip() for r in reports.split(",")] if reports else []
    
    # Get expected answer
    print("\nExpected Answer Summary:")
    answer_summary = input().strip()
    
    # Get key facts
    print("\nKey Facts (one per line, empty line to finish):")
    key_facts = []
    while True:
        fact = input("  - ").strip()
        if not fact:
            break
        key_facts.append(fact)
    
    # Get key amounts
    print("\nKey Amounts (format: value unit context, e.g., '64.60 crore revenue loss'):")
    print("Empty line to finish")
    key_amounts = []
    while True:
        amount_str = input("  - ").strip()
        if not amount_str:
            break
        
        parts = amount_str.split()
        if len(parts) >= 2:
            try:
                value = float(parts[0])
                unit = parts[1]
                context = " ".join(parts[2:]) if len(parts) > 2 else ""
                required = input("    Required? (y/n): ").strip().lower() == 'y'
                
                key_amounts.append({
                    "value": value,
                    "unit": unit,
                    "context": context,
                    "required": required
                })
            except ValueError:
                print("    Invalid format, skipping")
    
    # Get key entities
    entities = input("\nKey Entities (comma-separated): ").strip()
    key_entities = [e.strip() for e in entities.split(",")] if entities else []
    
    # Get source info
    sections = input("Source Sections (comma-separated): ").strip()
    source_sections = [s.strip() for s in sections.split(",")] if sections else []
    
    pages = input("Source Pages (comma-separated): ").strip()
    source_pages = [int(p.strip()) for p in pages.split(",") if p.strip().isdigit()]
    
    # Build test case
    test_case = {
        "id": test_id,
        "question": question,
        "category": {
            "difficulty": difficulty,
            "type": qtype,
            "reports": reports
        },
        "expected": {
            "answer_summary": answer_summary,
            "key_facts": key_facts,
            "key_amounts": key_amounts,
            "key_entities": key_entities,
            "source_sections": source_sections,
            "source_pages": source_pages
        },
        "negative_criteria": {
            "must_not_contain": [],
            "must_not_hallucinate": True
        }
    }
    
    # Save
    print("\n" + "=" * 60)
    print("Created Test Case:")
    print(json.dumps(test_case, indent=2))
    
    save = input("\nSave to sample_test_cases.json? (y/n): ").strip().lower()
    if save == 'y':
        # Load existing
        test_file = Path(__file__).parent / "sample_test_cases.json"
        with open(test_file) as f:
            data = json.load(f)
        
        # Append
        data['test_cases'].append(test_case)
        data['metadata']['total_cases'] = len(data['test_cases'])
        
        # Save
        with open(test_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"Saved! Total test cases: {data['metadata']['total_cases']}")
    
    return 0


def analyze_results():
    """Analyze latest evaluation results."""
    results_dir = Path(__file__).parent / "results"
    
    if not results_dir.exists():
        print("No results directory found. Run evaluation first.")
        return 1
    
    # Find latest result
    json_files = list(results_dir.glob("evaluation_*.json"))
    if not json_files:
        print("No evaluation results found.")
        return 1
    
    latest = max(json_files, key=lambda p: p.stat().st_mtime)
    print(f"Analyzing: {latest.name}")
    
    with open(latest) as f:
        data = json.load(f)
    
    # Print summary
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    
    print(f"\nTimestamp: {data.get('timestamp', 'N/A')}")
    print(f"Total: {data['total_cases']} | Passed: {data['passed_cases']} | Failed: {data['failed_cases']}")
    print(f"Pass Rate: {data['pass_rate']:.1%}")
    
    print("\n--- Scores ---")
    print(f"Factual Accuracy: {data['avg_factual_accuracy']:.2f}/5")
    print(f"Completeness: {data['avg_completeness']:.2f}/5")
    print(f"Relevance: {data['avg_relevance']:.2f}/5")
    print(f"Citation Quality: {data['avg_citation_quality']:.2f}/5")
    print(f"Amount Accuracy: {data['avg_amount_accuracy']:.1%}")
    print(f"Entity Coverage: {data['avg_entity_coverage']:.1%}")
    
    if data.get('issue_counts'):
        print("\n--- Issues ---")
        for issue, count in sorted(data['issue_counts'].items(), key=lambda x: -x[1]):
            print(f"  {issue}: {count}")
    
    print("\n--- By Difficulty ---")
    for diff, stats in data.get('scores_by_difficulty', {}).items():
        print(f"  {diff}: {stats['pass_rate']:.1%} pass ({stats['count']} cases)")
    
    print("\n--- By Type ---")
    for qtype, stats in data.get('scores_by_type', {}).items():
        print(f"  {qtype}: {stats['pass_rate']:.1%} pass ({stats['count']} cases)")
    
    # List failed cases
    failed = [r for r in data.get('results', []) if not r.get('passed')]
    if failed:
        print(f"\n--- Failed Cases ({len(failed)}) ---")
        for r in failed:
            print(f"  {r['test_id']}: {r['question'][:50]}...")
            if r.get('issues'):
                for issue in r['issues'][:2]:
                    print(f"    - {issue}")
    
    return 0


def show_help():
    """Show help message."""
    print("""
CAG RAG Evaluation - Quick Start
================================

Commands:
  python quick_start.py run       Run full evaluation on sample test cases
  python quick_start.py test      Interactive testing mode
  python quick_start.py create    Create a new test case interactively
  python quick_start.py analyze   Analyze latest evaluation results

Full Evaluation:
  python evaluate.py --test-cases sample_test_cases.json --output results/

Options:
  --verbose         Show progress for each test
  --style X         Use specific response style
  --difficulty X    Filter by difficulty (easy/medium/hard)
  --category X      Filter by type (factual/list/explanation/etc.)

Files:
  sample_test_cases.json    30 pre-built test cases
  evaluate.py               Main evaluation script
  evaluation_utils.py       Helper functions
  manual_testing_template.csv   Template for manual testing
  results/                  Output directory for reports
""")
    return 0


def main():
    if len(sys.argv) < 2:
        return show_help()
    
    command = sys.argv[1].lower()
    
    if command == 'run':
        return run_evaluation()
    elif command == 'test':
        return quick_test()
    elif command == 'create':
        return create_test_case()
    elif command == 'analyze':
        return analyze_results()
    elif command in ['help', '-h', '--help']:
        return show_help()
    else:
        print(f"Unknown command: {command}")
        return show_help()


if __name__ == "__main__":
    sys.exit(main())
