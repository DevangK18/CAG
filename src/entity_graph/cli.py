"""
Entity graph CLI.

Usage:
    python -m src.entity_graph.cli init-db
    python -m src.entity_graph.cli canonicalize [--overviews-dir DIR] [--reset]
    python -m src.entity_graph.cli index [--processed-dir DIR]
    python -m src.entity_graph.cli index-report --file PATH
    python -m src.entity_graph.cli stats
"""

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import func

from src.core.config import default_config
from .canonicalizer import canonicalize_all
from .mention_indexer import index_all, index_report
from .db import init_db, session_scope
from .models import Entity, EntityMention, EntityRelation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def cmd_init_db(args):
    init_db()
    print("✅ Schema created (or verified)")


def _truncate_entity_tables():
    """Truncate all entity graph tables."""
    with session_scope() as session:
        # Delete in order: relations → mentions → entities (respects FK constraints)
        relation_count = session.query(EntityRelation).count()
        mention_count = session.query(EntityMention).count()
        entity_count = session.query(Entity).count()

        session.query(EntityRelation).delete()
        session.query(EntityMention).delete()
        session.query(Entity).delete()

        logger.info(f"Truncated entity_relations: {relation_count} rows")
        logger.info(f"Truncated entity_mentions: {mention_count} rows")
        logger.info(f"Truncated entities: {entity_count} rows")

    print(f"🗑️  Truncated {entity_count} entities, {mention_count} mentions, {relation_count} relations")


def cmd_canonicalize(args):
    init_db()

    if args.reset:
        _truncate_entity_tables()

    # Pull two-pass config from default_config (supports env override)
    entity_cfg = default_config.entity_graph

    overviews_dir = Path(args.overviews_dir)
    output_path = Path(args.output) if args.output else Path("data/entity_graph/canonical_entities.json")
    entities = canonicalize_all(
        overviews_dir=overviews_dir,
        output_path=output_path,
        model=args.model,
        batch_size=args.batch_size,
        two_pass_threshold=entity_cfg.two_pass_threshold,
        pass2_batch_size=entity_cfg.pass2_batch_size,
        pass2_model=entity_cfg.pass2_model,
    )
    print(f"✅ Canonicalized {len(entities)} entities")
    print(f"   Output: {output_path}")


def cmd_index(args):
    init_db()
    total = index_all(Path(args.processed_dir))
    print(f"✅ Indexed {total} mentions across the corpus")


def cmd_index_report(args):
    init_db()
    count = index_report(Path(args.file))
    print(f"✅ Indexed {count} mentions from {args.file}")


def cmd_stats(args):
    init_db()
    with session_scope() as session:
        num_entities = session.query(Entity).count()
        num_mentions = session.query(EntityMention).count()
        by_type = dict(
            session.query(Entity.entity_type, func.count(Entity.id))
            .group_by(Entity.entity_type)
            .all()
        )
        by_tier = dict(
            session.query(Entity.primary_tier, func.count(Entity.id))
            .group_by(Entity.primary_tier)
            .all()
        )
        top10 = (
            session.query(Entity.canonical_name, Entity.mention_count, Entity.entity_type)
            .order_by(Entity.mention_count.desc())
            .limit(10)
            .all()
        )

    print(f"Entities: {num_entities}")
    print(f"Mentions: {num_mentions}")
    print(f"By type: {json.dumps(by_type, indent=2)}")
    print(f"By tier: {json.dumps(by_tier, indent=2)}")
    print("Top 10 most-mentioned entities:")
    for name, count, etype in top10:
        print(f"  {count:>6}  ({etype:<20})  {name}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-db", help="Create schema if missing")
    p_init.set_defaults(func=cmd_init_db)

    p_can = sub.add_parser("canonicalize", help="Run cross-corpus canonicalization")
    p_can.add_argument("--overviews-dir", default="data/batch_jobs/overviews")
    p_can.add_argument("--output", default=None)
    p_can.add_argument("--model", default="gpt-4o-mini")
    p_can.add_argument("--batch-size", type=int, default=40)
    p_can.add_argument("--reset", action="store_true", help="Truncate entity tables before loading")
    p_can.set_defaults(func=cmd_canonicalize)

    p_idx = sub.add_parser("index", help="Index all reports' mentions")
    p_idx.add_argument("--processed-dir", default="data/processed")
    p_idx.set_defaults(func=cmd_index)

    p_one = sub.add_parser("index-report", help="Index one report's mentions")
    p_one.add_argument("--file", required=True)
    p_one.set_defaults(func=cmd_index_report)

    p_stats = sub.add_parser("stats", help="Print entity graph statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
