"""
CAG RAG Pipeline - Indexing Script
====================================

Indexes all processed JSON files into Qdrant.

Supports:
- Regular chunk indexing (*_chunks.json, *_enriched.json)
- Hierarchical summary indexing (*_hierarchical.json) for RAPTOR retrieval

Usage:
    python -m rag_pipeline.indexer --input-dir data/processed
    python -m rag_pipeline.indexer --input-dir data/processed --recreate
    python -m rag_pipeline.indexer --input-dir data/processed --include-hierarchical
"""

import json
import argparse
import logging
import uuid
from pathlib import Path
from typing import Dict, Any, List
from tqdm import tqdm

try:
    from ..core.config import RAGConfig
    from .embedding_service import EmbeddingService
    from .qdrant_service import QdrantService
except ImportError:
    from src.core.config import RAGConfig
    from embedding_service import EmbeddingService
    from qdrant_service import QdrantService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Indexer:
    """
    Indexes CAG report chunks into Qdrant.

    Process:
    1. Load JSON files
    2. Generate dense + sparse embeddings
    3. Extract semantic payloads
    4. Upsert to Qdrant
    """

    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()

        # Validate
        errors = self.config.validate()
        relevant_errors = [e for e in errors if "OPENAI" in e]
        if relevant_errors:
            raise ValueError(f"Configuration errors: {relevant_errors}")

        self.embedding_service = EmbeddingService(self.config)
        self.qdrant_service = QdrantService(self.config)

    def index_all(
        self,
        input_dir: str,
        recreate: bool = False,
        include_hierarchical: bool = False,
    ) -> Dict[str, Any]:
        """
        Index all JSON files in directory.

        Args:
            input_dir: Directory containing *_chunks.json or *_enriched.json
            recreate: Delete and recreate collections
            include_hierarchical: Also index *_hierarchical.json files for RAPTOR

        Returns:
            Statistics about indexing
        """
        input_path = Path(input_dir)

        # Find JSON files (recursively search subdirectories for multi-tier support)
        json_files = list(input_path.glob("**/*_enriched.json"))
        if not json_files:
            json_files = list(input_path.glob("**/*_chunks.json"))

        if not json_files:
            raise ValueError(f"No JSON files found in {input_dir}")

        logger.info(f"Found {len(json_files)} files to index")

        # Create collections
        self.qdrant_service.create_collections(
            recreate=recreate,
            enable_sparse=self.config.embedding.enable_sparse_vectors,
        )

        # Track stats
        stats = {
            "files_processed": 0,
            "total_children": 0,
            "total_parents": 0,
            "files_with_enrichment": 0,
            "tables_summarized": 0,
            "errors": [],
        }

        for json_file in tqdm(json_files, desc="Indexing reports"):
            try:
                file_stats = self.index_file(json_file)

                stats["files_processed"] += 1
                stats["total_children"] += file_stats["children"]
                stats["total_parents"] += file_stats["parents"]

                if file_stats.get("has_enrichment"):
                    stats["files_with_enrichment"] += 1

            except Exception as e:
                logger.error(f"Error indexing {json_file.name}: {e}")
                stats["errors"].append(
                    {
                        "file": json_file.name,
                        "error": str(e),
                    }
                )

        # Index hierarchical summaries if requested
        if include_hierarchical:
            logger.info("Indexing hierarchical summaries (RAPTOR)...")
            hierarchical_stats = self.index_all_hierarchical(input_dir)
            stats["hierarchical"] = hierarchical_stats

        # Add embedding stats
        embedding_stats = self.embedding_service.get_stats()
        stats["embedding_stats"] = embedding_stats

        # Add collection stats
        stats["collection_stats"] = self.qdrant_service.get_collection_stats()

        return stats

    def index_file(self, json_path: Path) -> Dict[str, Any]:
        """
        Index a single JSON file.

        Args:
            json_path: Path to JSON file

        Returns:
            Statistics for this file
        """
        # Load JSON
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        parent_chunks = data.get("parent_chunks", [])
        child_chunks = data.get("child_chunks", [])
        semantic_enrichment = data.get("semantic_enrichment")
        report_id = data.get("report_metadata", {}).get("report_id", json_path.stem)

        logger.info(
            f"Processing {report_id}: {len(child_chunks)} children, {len(parent_chunks)} parents"
        )

        # Process chunks
        texts, dense_embeddings, sparse_vectors, payloads = (
            self.embedding_service.process_chunks(
                child_chunks,
                parent_chunks,
                semantic_enrichment,
                show_progress=False,
            )
        )

        # Index children
        children_indexed = self.qdrant_service.upsert_children(
            payloads,
            dense_embeddings,
            sparse_vectors,
        )

        # Index parents
        parents_indexed = self.qdrant_service.upsert_parents(parent_chunks)

        # Phase 12: Optionally index entity mentions
        if (
            self.config.entity_graph.enabled
            and self.config.entity_graph.auto_index_on_ingest
        ):
            try:
                try:
                    from src.entity_graph.mention_indexer import index_report
                except ImportError:
                    from entity_graph.mention_indexer import index_report

                mentions = index_report(json_path)
                logger.info(f"  Entity mentions indexed: {mentions}")
            except Exception as e:
                # Non-fatal: chunk indexing succeeded; entity indexing failed
                logger.warning(f"Entity mention indexing failed for {json_path.name}: {e}")

        return {
            "report_id": report_id,
            "children": children_indexed,
            "parents": parents_indexed,
            "has_enrichment": semantic_enrichment is not None,
        }

    def index_hierarchical_file(self, json_path: Path) -> Dict[str, Any]:
        """
        Index a hierarchical summary JSON file (RAPTOR summaries).

        Hierarchical summaries are indexed into the same collection as child chunks
        but with special metadata (content_type, hierarchy_level) for filtered retrieval.

        Args:
            json_path: Path to *_hierarchical.json file

        Returns:
            Statistics for this file
        """
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        report_id = data.get("report_id", json_path.stem.replace("_hierarchical", ""))

        points = []

        # Index chapter summaries (L2)
        for chapter in data.get("chapter_summaries", []):
            if not chapter.get("summary"):
                continue

            chunk_id = f"{report_id}_L2_{chapter['parent_chunk_id']}"
            embedding = self.embedding_service.dense_service.embed_single(chapter["summary"])

            points.append({
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)),
                "vector": embedding,
                "payload": {
                    "chunk_id": chunk_id,
                    "content": chapter["summary"],
                    "content_type": "chapter_summary",
                    "hierarchy_level": 2,
                    "parent_chunk_id": chapter["parent_chunk_id"],
                    "title": chapter.get("title", ""),
                    "report_id": report_id,
                    "tier": chapter.get("tier", "union"),
                },
            })

        # Index section summaries (L1)
        for section in data.get("section_summaries", []):
            if not section.get("summary"):
                continue

            chunk_id = f"{report_id}_L1_{section['parent_chunk_id']}"
            embedding = self.embedding_service.dense_service.embed_single(section["summary"])

            points.append({
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)),
                "vector": embedding,
                "payload": {
                    "chunk_id": chunk_id,
                    "content": section["summary"],
                    "content_type": "section_summary",
                    "hierarchy_level": 1,
                    "parent_chunk_id": section["parent_chunk_id"],
                    "title": section.get("title", ""),
                    "report_id": report_id,
                    "tier": section.get("tier", "union"),
                },
            })

        if not points:
            logger.warning(f"No hierarchical summaries to index for {report_id}")
            return {
                "report_id": report_id,
                "chapter_summaries": 0,
                "section_summaries": 0,
            }

        # Upsert to child collection (same collection as regular chunks)
        self.qdrant_service.upsert_hierarchical_summaries(points)

        chapter_count = sum(1 for p in points if p["payload"]["hierarchy_level"] == 2)
        section_count = sum(1 for p in points if p["payload"]["hierarchy_level"] == 1)

        logger.info(
            f"Indexed {len(points)} hierarchical summaries for {report_id} "
            f"({chapter_count} chapters, {section_count} sections)"
        )

        return {
            "report_id": report_id,
            "chapter_summaries": chapter_count,
            "section_summaries": section_count,
        }

    def index_all_hierarchical(
        self,
        input_dir: str,
    ) -> Dict[str, Any]:
        """
        Index all hierarchical summary JSON files in directory.

        Args:
            input_dir: Directory containing *_hierarchical.json files

        Returns:
            Statistics about hierarchical indexing
        """
        input_path = Path(input_dir)

        # Find hierarchical JSON files
        hierarchical_files = list(input_path.glob("**/*_hierarchical.json"))

        if not hierarchical_files:
            logger.info(f"No hierarchical JSON files found in {input_dir}")
            return {
                "files_processed": 0,
                "total_chapter_summaries": 0,
                "total_section_summaries": 0,
                "errors": [],
            }

        logger.info(f"Found {len(hierarchical_files)} hierarchical files to index")

        stats = {
            "files_processed": 0,
            "total_chapter_summaries": 0,
            "total_section_summaries": 0,
            "errors": [],
        }

        for json_file in tqdm(hierarchical_files, desc="Indexing hierarchical summaries"):
            try:
                file_stats = self.index_hierarchical_file(json_file)

                stats["files_processed"] += 1
                stats["total_chapter_summaries"] += file_stats["chapter_summaries"]
                stats["total_section_summaries"] += file_stats["section_summaries"]

            except Exception as e:
                logger.error(f"Error indexing {json_file.name}: {e}")
                stats["errors"].append({
                    "file": json_file.name,
                    "error": str(e),
                })

        return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Index CAG reports into Qdrant")
    parser.add_argument(
        "--input-dir",
        type=str,
        default="data/processed",
        help="Directory containing JSON files",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate collections",
    )
    parser.add_argument(
        "--no-sparse",
        action="store_true",
        help="Disable sparse vectors",
    )
    parser.add_argument(
        "--no-tables",
        action="store_true",
        help="Disable LLM table summaries",
    )
    parser.add_argument(
        "--include-hierarchical",
        action="store_true",
        help="Index RAPTOR hierarchical summaries (*_hierarchical.json)",
    )

    args = parser.parse_args()

    # Configure
    config = RAGConfig()

    if args.no_sparse:
        config.embedding.enable_sparse_vectors = False

    if args.no_tables:
        config.embedding.enable_table_summaries = False

    # Validate
    errors = config.validate()
    relevant = [e for e in errors if "OPENAI" in e]
    if relevant:
        print(f"ERROR: {relevant}")
        return 1

    print("\n" + "=" * 60)
    print("CAG RAG INDEXER")
    print("=" * 60)
    print(f"Input: {args.input_dir}")
    print(f"Recreate: {args.recreate}")
    print(f"Sparse vectors: {config.embedding.enable_sparse_vectors}")
    print(f"Table summaries: {config.embedding.enable_table_summaries}")
    print(f"Hierarchical (RAPTOR): {args.include_hierarchical}")
    print("=" * 60 + "\n")

    # Run indexer
    indexer = Indexer(config)
    stats = indexer.index_all(
        args.input_dir,
        recreate=args.recreate,
        include_hierarchical=args.include_hierarchical,
    )

    # Print results
    print("\n" + "=" * 60)
    print("INDEXING COMPLETE")
    print("=" * 60)
    print(f"Files processed: {stats['files_processed']}")
    print(f"Children indexed: {stats['total_children']}")
    print(f"Parents indexed: {stats['total_parents']}")
    print(f"Files with enrichment: {stats['files_with_enrichment']}")

    # Hierarchical stats
    if "hierarchical" in stats:
        hier = stats["hierarchical"]
        print(f"\nHierarchical (RAPTOR):")
        print(f"  Files processed: {hier['files_processed']}")
        print(f"  Chapter summaries: {hier['total_chapter_summaries']}")
        print(f"  Section summaries: {hier['total_section_summaries']}")
        if hier.get("errors"):
            print(f"  Errors: {len(hier['errors'])}")

    if "embedding_stats" in stats:
        emb = stats["embedding_stats"]
        print(f"\nEmbedding Cost:")
        print(f"  Dense: ${emb['dense_embedding']['cost_usd']:.4f}")
        if "table_summary" in emb:
            print(f"  Tables: ${emb['table_summary']['estimated_cost_usd']:.4f}")

    if stats["errors"]:
        print(f"\nErrors ({len(stats['errors'])}):")
        for err in stats["errors"]:
            print(f"  - {err['file']}: {err['error']}")

    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    exit(main())
