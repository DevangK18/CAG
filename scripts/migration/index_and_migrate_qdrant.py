"""
Index and Migrate Qdrant - Multi-Tier Support
==============================================

This script handles three operations for adding multi-tier support to Qdrant:

1. Index new State/Local Body reports
2. Migrate existing Union report payloads to add tier metadata
3. Create payload indexes for efficient filtering

Usage:
    poetry run python scripts/index_and_migrate_qdrant.py --index-new
    poetry run python scripts/index_and_migrate_qdrant.py --migrate-union
    poetry run python scripts/index_and_migrate_qdrant.py --create-indexes
    poetry run python scripts/index_and_migrate_qdrant.py --all

Requirements:
    - Existing Qdrant collections (cag_child_chunks, cag_parent_chunks)
    - State/Local Body JSON files in data/processed/state/ and data/processed/local_body/
    - Union reports already indexed (for migration)
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Any, List
from tqdm import tqdm

from src.rag_pipeline.indexer import Indexer
from src.rag_pipeline.qdrant_service import QdrantService
from src.core.config import RAGConfig
from qdrant_client.http.models import PayloadSchemaType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# PART 1: INDEX NEW REPORTS
# =============================================================================


def index_new_reports(config: RAGConfig, tier_dirs: List[str]) -> Dict[str, Any]:
    """
    Index State and Local Body reports into existing Qdrant collections.

    Args:
        config: RAG configuration
        tier_dirs: List of directories to index (e.g., ["state", "local_body"])

    Returns:
        Statistics about indexed reports
    """
    logger.info("=" * 70)
    logger.info("PART 1: INDEXING NEW REPORTS")
    logger.info("=" * 70)

    indexer = Indexer(config)
    all_stats = {
        "tiers": {},
        "total_files": 0,
        "total_children": 0,
        "total_parents": 0,
    }

    for tier in tier_dirs:
        tier_dir = Path("data/processed") / tier

        if not tier_dir.exists():
            logger.warning(f"Directory not found: {tier_dir}")
            continue

        # Check if there are any files to index
        json_files = list(tier_dir.glob("*_chunks.json"))
        if not json_files:
            logger.warning(f"No *_chunks.json files in {tier_dir}")
            continue

        logger.info(f"\nIndexing {tier.upper()} reports from {tier_dir}...")
        logger.info(f"Found {len(json_files)} files")

        # Index this tier (recreate=False to append to existing collections)
        stats = indexer.index_all(str(tier_dir), recreate=False)

        all_stats["tiers"][tier] = stats
        all_stats["total_files"] += stats["files_processed"]
        all_stats["total_children"] += stats["total_children"]
        all_stats["total_parents"] += stats["total_parents"]

        logger.info(f"{tier.upper()} indexing complete:")
        logger.info(f"  Files: {stats['files_processed']}")
        logger.info(f"  Children: {stats['total_children']}")
        logger.info(f"  Parents: {stats['total_parents']}")

    logger.info("\n" + "=" * 70)
    logger.info("PART 1 COMPLETE")
    logger.info(f"Total files indexed: {all_stats['total_files']}")
    logger.info(f"Total children indexed: {all_stats['total_children']}")
    logger.info(f"Total parents indexed: {all_stats['total_parents']}")
    logger.info("=" * 70)

    return all_stats


# =============================================================================
# PART 2: MIGRATE EXISTING UNION PAYLOADS
# =============================================================================


def get_report_metadata(report_id: str) -> Dict[str, Any]:
    """
    Load metadata from a report's chunk JSON file.

    Args:
        report_id: Report ID to load

    Returns:
        Report metadata dict
    """
    # Try union directory (most common)
    chunk_file = Path("data/processed/union") / f"{report_id}_chunks.json"

    if not chunk_file.exists():
        # Fallback to root processed directory
        chunk_file = Path("data/processed") / f"{report_id}_chunks.json"

    if not chunk_file.exists():
        logger.warning(f"Chunk file not found for {report_id}")
        return {}

    try:
        with open(chunk_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("report_metadata", {})
    except Exception as e:
        logger.error(f"Error loading metadata for {report_id}: {e}")
        return {}


def migrate_union_payloads(config: RAGConfig, batch_size: int = 100) -> Dict[str, Any]:
    """
    Migrate existing Union report payloads to add tier metadata fields.

    Iterates through all points in cag_child_chunks and updates those
    without government_body_type to add:
    - government_body_type: "union"
    - state_name: null
    - department: null
    - audit_category: "compliance" (or from JSON if available)

    Args:
        config: RAG configuration
        batch_size: Batch size for updates

    Returns:
        Migration statistics
    """
    logger.info("=" * 70)
    logger.info("PART 2: MIGRATING UNION PAYLOADS")
    logger.info("=" * 70)

    qdrant_service = QdrantService(config)
    client = qdrant_service.client
    collection_name = qdrant_service.child_collection

    stats = {
        "total_points": 0,
        "points_needing_migration": 0,
        "points_migrated": 0,
        "batches_processed": 0,
        "errors": 0,
    }

    # Get total count
    collection_info = client.get_collection(collection_name)
    stats["total_points"] = collection_info.points_count

    logger.info(f"Collection has {stats['total_points']} total points")
    logger.info("Scanning for points needing migration...")

    # Scroll through all points
    offset = None
    points_to_update = []
    report_metadata_cache = {}

    while True:
        # Scroll batch
        scroll_result = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        points, next_offset = scroll_result

        if not points:
            break

        # Check each point
        for point in points:
            payload = point.payload

            # Check if migration needed (no government_body_type field)
            if "government_body_type" not in payload:
                stats["points_needing_migration"] += 1

                report_id = payload.get("report_id", "")

                # Get audit_category from report metadata if available
                audit_category = "compliance"  # default
                if report_id:
                    if report_id not in report_metadata_cache:
                        report_metadata_cache[report_id] = get_report_metadata(
                            report_id
                        )

                    metadata = report_metadata_cache[report_id]
                    audit_category = metadata.get("audit_category", "compliance")

                # Prepare update
                points_to_update.append(
                    {
                        "id": point.id,
                        "payload": {
                            "government_body_type": "union",
                            "state_name": None,
                            "department": None,
                            "audit_category": audit_category,
                        },
                    }
                )

                # Apply batch update
                if len(points_to_update) >= batch_size:
                    try:
                        for update in points_to_update:
                            client.set_payload(
                                collection_name=collection_name,
                                payload=update["payload"],
                                points=[update["id"]],
                            )

                        stats["points_migrated"] += len(points_to_update)
                        stats["batches_processed"] += 1

                        logger.info(
                            f"Migrated batch {stats['batches_processed']}: "
                            f"{stats['points_migrated']} points updated"
                        )

                        points_to_update = []

                    except Exception as e:
                        logger.error(f"Error updating batch: {e}")
                        stats["errors"] += 1
                        points_to_update = []

        offset = next_offset
        if offset is None:
            break

    # Apply remaining updates
    if points_to_update:
        try:
            for update in points_to_update:
                client.set_payload(
                    collection_name=collection_name,
                    payload=update["payload"],
                    points=[update["id"]],
                )

            stats["points_migrated"] += len(points_to_update)
            stats["batches_processed"] += 1

        except Exception as e:
            logger.error(f"Error updating final batch: {e}")
            stats["errors"] += 1

    logger.info("\n" + "=" * 70)
    logger.info("PART 2 COMPLETE")
    logger.info(f"Total points scanned: {stats['total_points']}")
    logger.info(f"Points needing migration: {stats['points_needing_migration']}")
    logger.info(f"Points migrated: {stats['points_migrated']}")
    logger.info(f"Batches processed: {stats['batches_processed']}")
    logger.info(f"Errors: {stats['errors']}")
    logger.info("=" * 70)

    return stats


# =============================================================================
# PART 3: CREATE PAYLOAD INDEXES
# =============================================================================


def create_payload_indexes(config: RAGConfig) -> Dict[str, Any]:
    """
    Create payload indexes for efficient tier-based filtering.

    Creates indexes for:
    - government_body_type (KEYWORD)
    - state_name (KEYWORD)
    - audit_category (KEYWORD)

    Args:
        config: RAG configuration

    Returns:
        Statistics about index creation
    """
    logger.info("=" * 70)
    logger.info("PART 3: CREATING PAYLOAD INDEXES")
    logger.info("=" * 70)

    qdrant_service = QdrantService(config)
    client = qdrant_service.client

    indexes_to_create = [
        ("government_body_type", PayloadSchemaType.KEYWORD),
        ("state_name", PayloadSchemaType.KEYWORD),
        ("audit_category", PayloadSchemaType.KEYWORD),
    ]

    stats = {
        "child_chunks": {"created": 0, "existed": 0, "errors": 0},
        "parent_chunks": {"created": 0, "existed": 0, "errors": 0},
    }

    # Create indexes for child chunks
    logger.info(f"\nCreating indexes for {qdrant_service.child_collection}...")
    for field_name, field_type in indexes_to_create:
        try:
            client.create_payload_index(
                collection_name=qdrant_service.child_collection,
                field_name=field_name,
                field_schema=field_type,
            )
            stats["child_chunks"]["created"] += 1
            logger.info(f"  ✓ Created index: {field_name}")

        except Exception as e:
            if "already exists" in str(e).lower():
                stats["child_chunks"]["existed"] += 1
                logger.info(f"  - Index already exists: {field_name}")
            else:
                stats["child_chunks"]["errors"] += 1
                logger.error(f"  ✗ Error creating index {field_name}: {e}")

    # Create indexes for parent chunks (if parents have these fields)
    logger.info(f"\nCreating indexes for {qdrant_service.parent_collection}...")
    for field_name, field_type in indexes_to_create:
        try:
            client.create_payload_index(
                collection_name=qdrant_service.parent_collection,
                field_name=field_name,
                field_schema=field_type,
            )
            stats["parent_chunks"]["created"] += 1
            logger.info(f"  ✓ Created index: {field_name}")

        except Exception as e:
            if "already exists" in str(e).lower():
                stats["parent_chunks"]["existed"] += 1
                logger.info(f"  - Index already exists: {field_name}")
            else:
                stats["parent_chunks"]["errors"] += 1
                logger.error(f"  ✗ Error creating index {field_name}: {e}")

    logger.info("\n" + "=" * 70)
    logger.info("PART 3 COMPLETE")
    logger.info(
        f"Child indexes: {stats['child_chunks']['created']} created, "
        f"{stats['child_chunks']['existed']} existed, "
        f"{stats['child_chunks']['errors']} errors"
    )
    logger.info(
        f"Parent indexes: {stats['parent_chunks']['created']} created, "
        f"{stats['parent_chunks']['existed']} existed, "
        f"{stats['parent_chunks']['errors']} errors"
    )
    logger.info("=" * 70)

    return stats


# =============================================================================
# MAIN
# =============================================================================


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Index State/Local reports and migrate Union payloads for multi-tier support"
    )
    parser.add_argument(
        "--index-new",
        action="store_true",
        help="Index new State and Local Body reports",
    )
    parser.add_argument(
        "--migrate-union", action="store_true", help="Migrate existing Union payloads"
    )
    parser.add_argument(
        "--create-indexes",
        action="store_true",
        help="Create payload indexes for tier fields",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all operations (index, migrate, create indexes)",
    )
    parser.add_argument(
        "--tiers",
        nargs="+",
        default=["state", "local_body"],
        help="Tiers to index (default: state local_body)",
    )

    args = parser.parse_args()

    # If --all, enable everything
    if args.all:
        args.index_new = True
        args.migrate_union = True
        args.create_indexes = True

    # Require at least one operation
    if not (args.index_new or args.migrate_union or args.create_indexes):
        parser.print_help()
        print(
            "\nError: Specify at least one operation: --index-new, --migrate-union, --create-indexes, or --all"
        )
        return 1

    # Initialize config
    config = RAGConfig()

    # Validate
    errors = config.validate()
    relevant = [e for e in errors if "OPENAI" in e or "QDRANT" in e]
    if relevant:
        print(f"ERROR: Configuration errors: {relevant}")
        return 1

    print("\n" + "=" * 70)
    print("QDRANT MULTI-TIER MIGRATION SCRIPT")
    print("=" * 70)
    print(f"Operations selected:")
    print(f"  - Index new reports: {args.index_new}")
    print(f"  - Migrate Union payloads: {args.migrate_union}")
    print(f"  - Create payload indexes: {args.create_indexes}")
    if args.index_new:
        print(f"  - Tiers to index: {', '.join(args.tiers)}")
    print("=" * 70 + "\n")

    # PART 1: Index new reports
    if args.index_new:
        try:
            index_stats = index_new_reports(config, args.tiers)
        except Exception as e:
            logger.error(f"Error indexing new reports: {e}", exc_info=True)
            return 1

    # PART 2: Migrate Union payloads
    if args.migrate_union:
        try:
            migrate_stats = migrate_union_payloads(config)
        except Exception as e:
            logger.error(f"Error migrating Union payloads: {e}", exc_info=True)
            return 1

    # PART 3: Create payload indexes
    if args.create_indexes:
        try:
            index_creation_stats = create_payload_indexes(config)
        except Exception as e:
            logger.error(f"Error creating payload indexes: {e}", exc_info=True)
            return 1

    print("\n" + "=" * 70)
    print("ALL OPERATIONS COMPLETE")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    exit(main())
