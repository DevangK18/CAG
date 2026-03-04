"""
CAG RAG Evaluation Utilities
============================

Helper functions for evaluation, analysis, and reporting.
"""

import json
import csv
import re
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
from dataclasses import dataclass
from collections import defaultdict


# =============================================================================
# TEST CASE MANAGEMENT
# =============================================================================

def load_test_cases(path: str) -> List[Dict]:
    """Load test cases from JSON file."""
    with open(path, 'r') as f:
        data = json.load(f)
    
    if 'test_cases' in data:
        return data['test_cases']
    elif isinstance(data, list):
        return data
    else:
        return [data]


def save_test_cases(test_cases: List[Dict], path: str, metadata: Dict = None):
    """Save test cases to JSON file."""
    output = {
        'metadata': metadata or {
            'version': '1.0',
            'description': 'CAG RAG Test Cases'
        },
        'test_cases': test_cases
    }
    
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)


def validate_test_case(test_case: Dict) -> List[str]:
    """
    Validate a test case structure.
    Returns list of validation errors.
    """
    errors = []
    
    required_fields = ['id', 'question', 'category', 'expected']
    for field in required_fields:
        if field not in test_case:
            errors.append(f"Missing required field: {field}")
    
    if 'category' in test_case:
        if 'difficulty' not in test_case['category']:
            errors.append("Missing category.difficulty")
        if 'type' not in test_case['category']:
            errors.append("Missing category.type")
    
    if 'expected' in test_case:
        if 'answer_summary' not in test_case['expected']:
            errors.append("Missing expected.answer_summary")
    
    return errors


def create_test_case_template() -> Dict:
    """Create an empty test case template."""
    return {
        "id": "TC_XXX",
        "question": "",
        "category": {
            "difficulty": "easy|medium|hard",
            "type": "factual|list|explanation|comparison|aggregation|negative",
            "reports": []
        },
        "expected": {
            "answer_summary": "",
            "key_facts": [],
            "key_amounts": [
                {"value": 0.0, "unit": "crore", "context": "", "required": True}
            ],
            "key_entities": [],
            "source_sections": [],
            "source_pages": []
        },
        "negative_criteria": {
            "must_not_contain": [],
            "must_not_hallucinate": True
        }
    }


# =============================================================================
# RESULT ANALYSIS
# =============================================================================

def analyze_failures(results: List[Dict]) -> Dict[str, Any]:
    """
    Analyze failure patterns in evaluation results.
    Returns structured analysis.
    """
    failed = [r for r in results if not r.get('passed', False)]
    
    if not failed:
        return {'message': 'No failures to analyze'}
    
    analysis = {
        'total_failures': len(failed),
        'by_difficulty': defaultdict(list),
        'by_type': defaultdict(list),
        'by_issue': defaultdict(list),
        'common_patterns': [],
        'recommendations': []
    }
    
    # Group by category
    for result in failed:
        diff = result.get('category', {}).get('difficulty', 'unknown')
        qtype = result.get('category', {}).get('type', 'unknown')
        
        analysis['by_difficulty'][diff].append(result['test_id'])
        analysis['by_type'][qtype].append(result['test_id'])
        
        for issue in result.get('issues', []):
            analysis['by_issue'][issue].append(result['test_id'])
    
    # Identify patterns
    # Pattern 1: Difficulty concentration
    diff_counts = {k: len(v) for k, v in analysis['by_difficulty'].items()}
    max_diff = max(diff_counts, key=diff_counts.get) if diff_counts else None
    if max_diff and diff_counts[max_diff] > len(failed) * 0.5:
        analysis['common_patterns'].append(
            f"Failures concentrated in '{max_diff}' difficulty ({diff_counts[max_diff]}/{len(failed)})"
        )
        analysis['recommendations'].append(
            f"Focus on improving handling of {max_diff} questions"
        )
    
    # Pattern 2: Type concentration
    type_counts = {k: len(v) for k, v in analysis['by_type'].items()}
    max_type = max(type_counts, key=type_counts.get) if type_counts else None
    if max_type and type_counts[max_type] > len(failed) * 0.4:
        analysis['common_patterns'].append(
            f"Failures concentrated in '{max_type}' question type ({type_counts[max_type]}/{len(failed)})"
        )
        analysis['recommendations'].append(
            f"Improve handling of {max_type} questions - may need prompt tuning"
        )
    
    # Pattern 3: Common issues
    for issue, test_ids in sorted(analysis['by_issue'].items(), key=lambda x: -len(x[1])):
        if len(test_ids) >= 3:
            analysis['common_patterns'].append(
                f"Recurring issue: '{issue}' ({len(test_ids)} cases)"
            )
    
    # Convert defaultdicts to regular dicts
    analysis['by_difficulty'] = dict(analysis['by_difficulty'])
    analysis['by_type'] = dict(analysis['by_type'])
    analysis['by_issue'] = dict(analysis['by_issue'])
    
    return analysis


def compare_evaluations(eval1_path: str, eval2_path: str) -> Dict[str, Any]:
    """
    Compare two evaluation runs to track improvement.
    Returns comparison analysis.
    """
    with open(eval1_path) as f:
        eval1 = json.load(f)
    with open(eval2_path) as f:
        eval2 = json.load(f)
    
    comparison = {
        'eval1_timestamp': eval1.get('timestamp'),
        'eval2_timestamp': eval2.get('timestamp'),
        'pass_rate_change': eval2['pass_rate'] - eval1['pass_rate'],
        'score_changes': {},
        'newly_passing': [],
        'newly_failing': [],
        'consistent_failures': []
    }
    
    # Compare scores
    score_fields = [
        'avg_factual_accuracy', 'avg_completeness', 
        'avg_relevance', 'avg_citation_quality',
        'avg_amount_accuracy', 'avg_entity_coverage'
    ]
    
    for field in score_fields:
        old_val = eval1.get(field, 0)
        new_val = eval2.get(field, 0)
        comparison['score_changes'][field] = {
            'old': old_val,
            'new': new_val,
            'change': new_val - old_val,
            'improved': new_val > old_val
        }
    
    # Compare individual results
    eval1_results = {r['test_id']: r for r in eval1.get('results', [])}
    eval2_results = {r['test_id']: r for r in eval2.get('results', [])}
    
    common_ids = set(eval1_results.keys()) & set(eval2_results.keys())
    
    for test_id in common_ids:
        r1_passed = eval1_results[test_id].get('passed', False)
        r2_passed = eval2_results[test_id].get('passed', False)
        
        if not r1_passed and r2_passed:
            comparison['newly_passing'].append(test_id)
        elif r1_passed and not r2_passed:
            comparison['newly_failing'].append(test_id)
        elif not r1_passed and not r2_passed:
            comparison['consistent_failures'].append(test_id)
    
    return comparison


# =============================================================================
# MANUAL TESTING SUPPORT
# =============================================================================

def export_to_csv(test_cases: List[Dict], output_path: str):
    """
    Export test cases to CSV for manual testing/recording.
    """
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            'test_id', 'question', 'difficulty', 'type', 'expected_summary',
            'key_amounts', 'key_entities',
            # Columns for manual entry
            'actual_answer', 'factual_correct', 'amounts_correct',
            'complete', 'relevant', 'citations_ok', 'issues', 'notes'
        ])
        
        for tc in test_cases:
            amounts = ', '.join([
                f"{a['value']} {a.get('unit', 'crore')}"
                for a in tc.get('expected', {}).get('key_amounts', [])
            ])
            entities = ', '.join(tc.get('expected', {}).get('key_entities', []))
            
            writer.writerow([
                tc['id'],
                tc['question'],
                tc.get('category', {}).get('difficulty', ''),
                tc.get('category', {}).get('type', ''),
                tc.get('expected', {}).get('answer_summary', ''),
                amounts,
                entities,
                '', '', '', '', '', '', '', ''  # Empty columns for manual entry
            ])
    
    print(f"Exported {len(test_cases)} test cases to {output_path}")


def import_from_csv(csv_path: str) -> List[Dict]:
    """
    Import manual test results from CSV.
    Returns list of test results.
    """
    results = []
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            result = {
                'test_id': row['test_id'],
                'question': row['question'],
                'actual_answer': row.get('actual_answer', ''),
                'manual_scores': {
                    'factual_correct': row.get('factual_correct', '').lower() == 'yes',
                    'amounts_correct': row.get('amounts_correct', '').lower() == 'yes',
                    'complete': row.get('complete', '').lower() == 'yes',
                    'relevant': row.get('relevant', '').lower() == 'yes',
                    'citations_ok': row.get('citations_ok', '').lower() == 'yes',
                },
                'issues': row.get('issues', '').split(';') if row.get('issues') else [],
                'notes': row.get('notes', '')
            }
            results.append(result)
    
    return results


# =============================================================================
# REPORT GENERATION HELPERS
# =============================================================================

def generate_issue_summary(results: List[Dict]) -> str:
    """Generate a formatted issue summary from results."""
    all_issues = []
    for r in results:
        for issue in r.get('issues', []):
            all_issues.append({
                'test_id': r['test_id'],
                'issue': issue
            })
    
    if not all_issues:
        return "No issues found."
    
    # Group by issue type
    issue_groups = defaultdict(list)
    for item in all_issues:
        issue_groups[item['issue']].append(item['test_id'])
    
    summary = "## Issue Summary\n\n"
    for issue, test_ids in sorted(issue_groups.items(), key=lambda x: -len(x[1])):
        summary += f"### {issue}\n"
        summary += f"Affected tests: {', '.join(test_ids)}\n\n"
    
    return summary


def generate_quick_report(results: List[Dict]) -> str:
    """Generate a quick console-friendly report."""
    total = len(results)
    passed = sum(1 for r in results if r.get('passed', False))
    
    report = f"""
╔══════════════════════════════════════════════════════════════╗
║                    EVALUATION QUICK REPORT                    ║
╠══════════════════════════════════════════════════════════════╣
║  Total Tests: {total:4d}                                          ║
║  Passed:      {passed:4d}  ({passed/total*100 if total else 0:5.1f}%)                                ║
║  Failed:      {total-passed:4d}  ({(total-passed)/total*100 if total else 0:5.1f}%)                                ║
╠══════════════════════════════════════════════════════════════╣
"""
    
    # Average scores
    if results:
        avg_factual = sum(r.get('scores', {}).get('factual_accuracy', 0) for r in results) / total
        avg_complete = sum(r.get('scores', {}).get('completeness', 0) for r in results) / total
        avg_overall = sum(r.get('scores', {}).get('overall_score', 0) for r in results) / total
        
        report += f"""║  Avg Factual Accuracy: {avg_factual:4.2f}/5                          ║
║  Avg Completeness:     {avg_complete:4.2f}/5                          ║
║  Avg Overall Score:    {avg_overall:5.1f}/100                        ║
╚══════════════════════════════════════════════════════════════╝
"""
    
    return report


# =============================================================================
# AMOUNT/ENTITY EXTRACTION FOR GROUND TRUTH CREATION
# =============================================================================

def suggest_key_amounts(text: str) -> List[Dict]:
    """
    Analyze text and suggest key amounts for ground truth.
    Useful when creating new test cases.
    """
    suggestions = []
    
    # Pattern for rupee amounts
    patterns = [
        (r'₹\s*([\d,]+\.?\d*)\s*(crore|lakh)', 'rupee'),
        (r'Rs\.?\s*([\d,]+\.?\d*)\s*(crore|lakh)', 'rupee'),
        (r'([\d,]+\.?\d*)\s*(crore|lakh)', 'amount'),
        (r'([\d.]+)\s*per\s*cent', 'percentage'),
        (r'([\d.]+)\s*%', 'percentage'),
    ]
    
    for pattern, amount_type in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                value = float(match.group(1).replace(',', ''))
                unit = match.group(2).lower() if len(match.groups()) > 1 else 'percent'
                
                # Get surrounding context
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].strip()
                
                suggestions.append({
                    'value': value,
                    'unit': unit,
                    'context': context,
                    'required': False,  # User should determine
                    'position': match.start()
                })
            except (ValueError, IndexError):
                continue
    
    # Remove duplicates based on value and unit
    seen = set()
    unique_suggestions = []
    for s in suggestions:
        key = (s['value'], s['unit'])
        if key not in seen:
            seen.add(key)
            unique_suggestions.append(s)
    
    return unique_suggestions


def suggest_key_entities(text: str) -> List[str]:
    """
    Analyze text and suggest key entities for ground truth.
    """
    entities = set()
    
    # Known entity patterns
    patterns = [
        # Organizations
        r'\b(NHAI|CBDT|FCI|NHA|SHA|SEBI|CAG|CPC|MoRTH)\b',
        # Acts and Rules
        r'\b(\w+\s+Act,?\s+\d{4})\b',
        r'\b(NH\s+Fee\s+Rules?,?\s*\d{4})\b',
        r'\b(FRBM\s+Act)\b',
        # Schemes
        r'\b(PMJAY|Ayushman\s+Bharat|Bharatmala)\b',
        # States
        r'\b(Bihar|Chandigarh|Tamil\s+Nadu|Uttar\s+Pradesh|Karnataka|Maharashtra|Nagaland|Tripura)\b',
        # Highway references
        r'\b(NH\s*\d+)\b',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            entities.add(match.strip())
    
    return list(entities)


# =============================================================================
# QUICK TESTING HELPERS
# =============================================================================

def quick_test_query(question: str, expected_contains: List[str] = None) -> Dict:
    """
    Run a quick test on a single query.
    Returns pass/fail with details.
    """
    try:
        from services.rag_pipeline.rag_service import RAGService
        from services.rag_pipeline.config import RAGConfig, LLMProvider
        
        config = RAGConfig()
        config.llm.provider = LLMProvider.OPENAI
        rag = RAGService(config)
        
        response = rag.ask(question)
        answer = response.answer
        
        result = {
            'question': question,
            'answer': answer,
            'sources': response.sources_used,
            'checks': {}
        }
        
        if expected_contains:
            for item in expected_contains:
                found = item.lower() in answer.lower()
                result['checks'][item] = found
            
            result['all_checks_passed'] = all(result['checks'].values())
        
        return result
        
    except Exception as e:
        return {
            'question': question,
            'error': str(e),
            'all_checks_passed': False
        }


# =============================================================================
# STATISTICS HELPERS
# =============================================================================

def calculate_confidence_interval(pass_rate: float, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Calculate confidence interval for pass rate.
    Uses Wilson score interval for better accuracy with small samples.
    """
    import math
    
    if n == 0:
        return (0.0, 1.0)
    
    z = 1.96 if confidence == 0.95 else 2.576  # 95% or 99%
    
    denominator = 1 + z**2 / n
    center = (pass_rate + z**2 / (2 * n)) / denominator
    margin = z * math.sqrt((pass_rate * (1 - pass_rate) + z**2 / (4 * n)) / n) / denominator
    
    lower = max(0, center - margin)
    upper = min(1, center + margin)
    
    return (lower, upper)


def calculate_required_sample_size(
    target_precision: float = 0.05,
    expected_pass_rate: float = 0.8,
    confidence: float = 0.95
) -> int:
    """
    Calculate required sample size for a given precision.
    """
    import math
    
    z = 1.96 if confidence == 0.95 else 2.576
    
    n = (z**2 * expected_pass_rate * (1 - expected_pass_rate)) / (target_precision**2)
    
    return int(math.ceil(n))


# =============================================================================
# CLI FOR UTILITIES
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Evaluation Utilities")
    subparsers = parser.add_subparsers(dest='command')
    
    # Export to CSV
    export_parser = subparsers.add_parser('export-csv', help='Export test cases to CSV')
    export_parser.add_argument('--input', required=True, help='Input JSON file')
    export_parser.add_argument('--output', required=True, help='Output CSV file')
    
    # Analyze failures
    analyze_parser = subparsers.add_parser('analyze', help='Analyze evaluation results')
    analyze_parser.add_argument('--results', required=True, help='Results JSON file')
    
    # Compare evaluations
    compare_parser = subparsers.add_parser('compare', help='Compare two evaluations')
    compare_parser.add_argument('--eval1', required=True, help='First evaluation JSON')
    compare_parser.add_argument('--eval2', required=True, help='Second evaluation JSON')
    
    # Quick test
    quick_parser = subparsers.add_parser('quick-test', help='Quick test a query')
    quick_parser.add_argument('question', help='Question to test')
    quick_parser.add_argument('--contains', nargs='+', help='Expected content')
    
    args = parser.parse_args()
    
    if args.command == 'export-csv':
        test_cases = load_test_cases(args.input)
        export_to_csv(test_cases, args.output)
    
    elif args.command == 'analyze':
        with open(args.results) as f:
            data = json.load(f)
        results = data.get('results', data)
        analysis = analyze_failures(results)
        print(json.dumps(analysis, indent=2))
    
    elif args.command == 'compare':
        comparison = compare_evaluations(args.eval1, args.eval2)
        print(json.dumps(comparison, indent=2))
    
    elif args.command == 'quick-test':
        result = quick_test_query(args.question, args.contains)
        print(json.dumps(result, indent=2))
    
    else:
        parser.print_help()
