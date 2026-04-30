"""
Generate ministry canonicalization bridge using Claude Batch API.

This is a one-off infrastructure script that creates a mapping between
ReportInfo.ministry values (from parsed report metadata) and entity_id values
from the Phase 12 entity graph (ministry-type entities).

Usage:
    python scripts/generate_ministry_bridge.py

Output:
    data/canonical/ministry_bridge.json

The script:
1. Loads distinct ReportInfo.ministry values from report registry
2. Loads entity rows where entity_type='ministry' from entity graph Postgres
3. Submits Claude Batch API call (claude-sonnet-4-6) to map them
4. Polls until complete
5. Writes output JSON with high-confidence matches (>= 0.85)
"""

import anthropic
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Set

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_ministries_from_titles() -> List[str]:
    """
    Extract actual ministry names from full report titles.

    The ReportInfo.ministry field often contains audit categories like "Commercial"
    instead of actual ministry names. We extract real ministry names from the full
    report titles where they appear.

    Returns:
        List of ministry names extracted from titles
    """
    import re
    from pathlib import Path
    import json

    logger.info("Extracting ministry names from report titles...")

    # Find all chunks.json files across all tiers
    processed_dir = Path("data/processed")
    json_files = list(processed_dir.glob("**/*_chunks.json"))

    ministry_mentions = set()

    for json_file in json_files:
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)

            # Get the FULL report title (not sanitized)
            meta = data.get("report_metadata", {})
            title = meta.get("report_title", "")

            if not title:
                continue

            # Pattern 1: "Ministry of XXX" - stops at delimiters
            # Improved pattern that handles parentheses better
            ministry_pattern = r'Ministry of ([A-Z][a-zA-Z,\s&-]+?)(?:\s*[-–—]\s+|\s+Report|\s+Audit|\s+for\s+the\s+|,\s+Union|\s+\(|$)'
            matches = re.finditer(ministry_pattern, title)

            for match in matches:
                ministry_name = 'Ministry of ' + match.group(1).strip().rstrip(',.-')
                # Skip if it's too short (likely a parsing error)
                if len(ministry_name) > len("Ministry of X"):
                    ministry_mentions.add(ministry_name)

            # Pattern 2: "Department of XXX" - common in Direct Taxes reports
            # Stop at dashes, "Report", opening parentheses, etc.
            dept_pattern = r'Department of ([A-Z][a-zA-Z,\s&-]+?)(?:\s*[-–—]\s+|\s+Report|\s+Audit|\s+for\s+|\s+\(|,\s+Union|$)'
            dept_matches = re.finditer(dept_pattern, title)

            for match in dept_matches:
                dept_name = 'Department of ' + match.group(1).strip().rstrip(',.-')
                if len(dept_name) > len("Department of X"):
                    ministry_mentions.add(dept_name)

        except Exception as e:
            logger.warning(f"Error processing {json_file.name}: {e}")
            continue

    ministry_list = sorted(ministry_mentions)
    logger.info(f"Extracted {len(ministry_list)} ministry names from report titles")

    return ministry_list


def load_distinct_ministry_values() -> List[str]:
    """
    Load ALL ministry-related values from reports.

    This combines:
    1. ReportInfo.ministry field values (often audit categories, but might contain real names)
    2. Ministry names extracted from full report titles (actual ministry names)

    Returns:
        Combined list of all ministry-related strings
    """
    from pathlib import Path
    from src.rag_pipeline.report_registry import get_registry

    logger.info("Loading report registry...")
    registry = get_registry()

    # Load reports from processed directory
    processed_dir = Path("data/processed")
    registry.load_from_json_dir(processed_dir)

    # Get all reports
    reports = registry.get_all_reports()

    # Part 1: Collect ministry field values (from structured metadata)
    ministry_field_values: Set[str] = set()
    for report in reports:
        if report.ministry and report.ministry.strip():
            # Skip placeholder values
            ministry_lower = report.ministry.lower().strip()
            if ministry_lower not in ('unknown', 'unknown ministry', 'n/a', '-', 'none'):
                ministry_field_values.add(report.ministry.strip())

    logger.info(f"Found {len(ministry_field_values)} values from ministry field: {sorted(ministry_field_values)}")

    # Part 2: Extract ministry names from full report titles
    ministry_from_titles = extract_ministries_from_titles()

    # Combine both sources
    all_ministries = ministry_field_values.union(set(ministry_from_titles))

    ministry_list = sorted(all_ministries)
    logger.info(f"Total combined ministry strings: {len(ministry_list)}")

    return ministry_list


def load_ministry_entities() -> List[Dict]:
    """Load entity rows where entity_type='ministry' from entity graph."""
    from src.entity_graph.entity_service import get_entity_service

    logger.info("Loading ministry entities from entity graph...")
    service = get_entity_service()

    if not service:
        raise RuntimeError(
            "Entity graph service not available. "
            "Check ENTITY_GRAPH_DSN environment variable."
        )

    # Search for all ministry-type entities (no query filter, just type filter)
    # Use a high limit to get all ministries
    ministry_entities = service.search_entities(
        query="",  # Empty query to match all
        entity_type="ministry",
        limit=200  # Should be enough for all ministries
    )

    # If empty query doesn't work, try a more direct approach
    if not ministry_entities:
        logger.info("Empty query returned nothing, trying direct DB query...")
        from src.entity_graph.db import session_scope
        from src.entity_graph.models import Entity

        with session_scope() as session:
            entities = session.query(Entity).filter_by(entity_type='ministry').all()
            ministry_entities = [
                {
                    'id': e.id,
                    'canonical_name': e.canonical_name,
                    'aliases': json.loads(e.aliases) if e.aliases else [],
                    'mention_count': e.mention_count,
                    'entity_type': e.entity_type
                }
                for e in entities
            ]

    logger.info(f"Found {len(ministry_entities)} ministry entities in entity graph")

    return ministry_entities


def build_batch_prompt(ministry_values: List[str], ministry_entities: List[Dict]) -> str:
    """Build the Claude prompt for ministry canonicalization."""

    # Format entity list with IDs
    entity_list = []
    for entity in ministry_entities:
        aliases = entity.get('aliases', [])
        aliases_str = ', '.join(aliases[:5]) if aliases else ''  # Show first 5 aliases
        entity_list.append(
            f"  - ID {entity['id']}: {entity['canonical_name']}"
            + (f" (aliases: {aliases_str})" if aliases_str else "")
        )

    entities_text = '\n'.join(entity_list)

    # Format ministry values from reports
    ministry_list_text = '\n'.join(f"  - {m}" for m in ministry_values)

    prompt = f"""You are helping canonicalize Indian government ministry names from two different sources:

**Source 1: Entity Graph (Canonical Entities)**
These are canonicalized ministry names from the entity graph database. Each has an entity_id:

{entities_text}

**Source 2: Report Metadata (Ministry Strings)**
These are ministry values extracted from report metadata during parsing:

{ministry_list_text}

**Your Task:**
Create a JSON mapping that matches each Source 2 ministry string to a Source 1 entity_id where there is high confidence (>= 0.85) that they refer to the same ministry.

**Matching Rules:**
1. Look for exact matches, abbreviations, and common name variants
2. "Ministry of Railways" matches "Ministry of Railways"
3. "MoRTH" matches "Ministry of Road Transport and Highways"
4. "Department of Revenue (Direct Taxes)" might match a broader "Department of Revenue" entity
5. Be aware of ministry reorganizations and name changes over time
6. Only include matches with confidence >= 0.85
7. If no confident match exists, OMIT that ministry from the output

**Output Format:**
Return ONLY a valid JSON object (no markdown, no explanation) with this structure:

{{
  "Ministry of Railways": {{"entity_id": 123, "confidence": 0.99}},
  "MoRTH": {{"entity_id": 234, "confidence": 0.95}},
  "Department of Revenue (Direct Taxes)": {{"entity_id": 88, "confidence": 0.87}}
}}

**Important:**
- Return ONLY the JSON object, nothing else
- Use confidence values between 0.85 and 1.0
- Better to have gaps than wrong mappings
- Each ministry string can only map to ONE entity_id
"""

    return prompt


def submit_batch_job(prompt: str) -> str:
    """Submit Claude Batch API job."""
    logger.info("Submitting Claude Batch API job...")

    client = anthropic.Anthropic()

    # Create single batch request
    requests = [
        {
            "custom_id": "ministry_bridge_v1",
            "params": {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 16000,
                "temperature": 0.0,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
        }
    ]

    # Submit batch
    batch = client.messages.batches.create(requests=requests)

    logger.info(f"✅ Batch submitted: {batch.id}")
    logger.info(f"   Status: {batch.processing_status}")

    return batch.id


def poll_batch_completion(batch_id: str, poll_interval: int = 30, max_wait: int = 1800) -> Dict:
    """Poll batch until completion or timeout."""
    logger.info(f"Polling batch {batch_id} every {poll_interval}s (max wait: {max_wait}s)...")

    client = anthropic.Anthropic()
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait:
            raise TimeoutError(f"Batch did not complete within {max_wait}s")

        # Check status
        batch = client.messages.batches.retrieve(batch_id)
        status = batch.processing_status

        # Get request counts
        request_counts = batch.request_counts
        if hasattr(request_counts, 'succeeded'):
            completed = request_counts.succeeded
            total = (
                request_counts.processing + request_counts.succeeded +
                request_counts.errored + request_counts.canceled + request_counts.expired
            )
        else:
            completed = getattr(request_counts, 'completed', 0)
            total = getattr(request_counts, 'total', 1)

        logger.info(f"   Status: {status} | Progress: {completed}/{total} | Elapsed: {int(elapsed)}s")

        if status == "ended":
            logger.info("✅ Batch completed!")
            return {"batch_id": batch_id, "status": status, "batch": batch}

        if status in ("failed", "canceled", "expired"):
            raise RuntimeError(f"Batch failed with status: {status}")

        time.sleep(poll_interval)


def extract_batch_results(batch_id: str) -> Dict[str, Dict]:
    """Extract and parse batch results."""
    logger.info("Extracting batch results...")

    client = anthropic.Anthropic()

    # Get results
    results = list(client.messages.batches.results(batch_id))

    if not results:
        raise ValueError("No results returned from batch")

    result = results[0]

    if result.result.type == "errored":
        error = result.result.error
        error_msg = error.message if hasattr(error, 'message') else str(error)
        raise RuntimeError(f"Batch request failed: {error_msg}")

    if result.result.type != "succeeded":
        raise RuntimeError(f"Unexpected result type: {result.result.type}")

    # Extract content
    message = result.result.message
    content_text = None

    for block in message.content:
        if block.type == "text":
            content_text = block.text
            break

    if not content_text:
        raise ValueError("No text content in batch result")

    logger.info(f"Received {len(content_text)} characters of response")

    # Parse JSON from response
    # Handle potential markdown code blocks
    content_text = content_text.strip()
    if content_text.startswith("```json"):
        content_text = content_text[7:]  # Remove ```json
    if content_text.startswith("```"):
        content_text = content_text[3:]  # Remove ```
    if content_text.endswith("```"):
        content_text = content_text[:-3]  # Remove trailing ```

    content_text = content_text.strip()

    try:
        mapping = json.loads(content_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Response text (first 500 chars):\n{content_text[:500]}")
        raise

    # Validate structure
    if not isinstance(mapping, dict):
        raise ValueError(f"Expected dict, got {type(mapping)}")

    # Filter for high confidence only (>= 0.85)
    filtered = {}
    for ministry, data in mapping.items():
        if isinstance(data, dict) and 'entity_id' in data and 'confidence' in data:
            confidence = data['confidence']
            if confidence >= 0.85:
                filtered[ministry] = data

    logger.info(f"Extracted {len(filtered)} high-confidence mappings (>= 0.85)")

    return filtered


def save_ministry_bridge(mapping: Dict[str, Dict], output_path: Path):
    """Save ministry bridge to JSON file."""
    logger.info(f"Saving ministry bridge to {output_path}...")

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Add metadata
    output = {
        "_metadata": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_mappings": len(mapping),
            "description": "Ministry canonicalization bridge: maps ReportInfo.ministry values to entity_graph entity_id",
            "confidence_threshold": 0.85
        },
        "mappings": mapping
    }

    # Write JSON
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"✅ Saved {len(mapping)} mappings to {output_path}")


def main():
    """Main execution."""
    try:
        # Step 1: Load source data
        logger.info("=" * 70)
        logger.info("Ministry Canonicalization Bridge - Phase A.5")
        logger.info("=" * 70)

        ministry_values = load_distinct_ministry_values()
        ministry_entities = load_ministry_entities()

        logger.info(f"\nSummary:")
        logger.info(f"  - Report ministry values: {len(ministry_values)}")
        logger.info(f"  - Entity graph ministries: {len(ministry_entities)}")

        # Step 2: Build prompt
        prompt = build_batch_prompt(ministry_values, ministry_entities)

        # Step 3: Submit batch
        batch_id = submit_batch_job(prompt)

        # Save batch ID for reference
        batch_ref_path = Path("data/canonical/ministry_bridge_batch_id.txt")
        batch_ref_path.parent.mkdir(parents=True, exist_ok=True)
        batch_ref_path.write_text(batch_id)
        logger.info(f"Batch ID saved to {batch_ref_path}")

        # Step 4: Poll for completion
        poll_batch_completion(batch_id, poll_interval=30, max_wait=1800)

        # Step 5: Extract results
        mapping = extract_batch_results(batch_id)

        # Step 6: Save output
        output_path = Path("data/canonical/ministry_bridge.json")
        save_ministry_bridge(mapping, output_path)

        logger.info("\n" + "=" * 70)
        logger.info("✅ Ministry bridge generation complete!")
        logger.info(f"✅ Output: {output_path}")
        logger.info(f"✅ Total mappings: {len(mapping)}")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
