"""
CAG RAG Pipeline - Indexing Script
====================================

Indexes all processed JSON files into Qdrant.

Usage:
    python -m rag_pipeline.indexer --input-dir data/processed
    python -m rag_pipeline.indexer --input-dir data/processed --recreate
"""

import json
import argparse
import logging
from pathlib import Path
from typing import Dict, Any
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
    ) -> Dict[str, Any]:
        """
        Index all JSON files in directory.

        Args:
            input_dir: Directory containing *_chunks.json or *_enriched.json
            recreate: Delete and recreate collections

        Returns:
            Statistics about indexing
        """
        input_path = Path(input_dir)

        # Find JSON files
        json_files = list(input_path.glob("*_enriched.json"))
        if not json_files:
            json_files = list(input_path.glob("*_chunks.json"))

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

        return {
            "report_id": report_id,
            "children": children_indexed,
            "parents": parents_indexed,
            "has_enrichment": semantic_enrichment is not None,
        }


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
    print("=" * 60 + "\n")

    # Run indexer
    indexer = Indexer(config)
    stats = indexer.index_all(args.input_dir, args.recreate)

    # Print results
    print("\n" + "=" * 60)
    print("INDEXING COMPLETE")
    print("=" * 60)
    print(f"Files processed: {stats['files_processed']}")
    print(f"Children indexed: {stats['total_children']}")
    print(f"Parents indexed: {stats['total_parents']}")
    print(f"Files with enrichment: {stats['files_with_enrichment']}")

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
