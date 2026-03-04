"""
CAG RAG Pipeline - Qdrant Service
==================================

Handles:
1. Collection creation (hybrid vectors)
2. Indexing (upsert with dense + sparse)
3. Hybrid search (dense + sparse with RRF fusion)
4. Parent/neighbor lookups

Requirements:
    pip install qdrant-client
"""

import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from qdrant_client.http.models import (
        Distance,
        VectorParams,
        SparseVectorParams,
        PointStruct,
        SparseVector,
        Filter,
        FieldCondition,
        MatchValue,
        MatchAny,
        Range,
        Prefetch,
        FusionQuery,
        PayloadSchemaType,
    )
except ImportError:
    raise ImportError("Install qdrant-client: pip install qdrant-client")

try:
    from ..core.config import QdrantConfig, RAGConfig
    from .models import RetrievedChunk
except ImportError:
    from src.core.config import QdrantConfig, RAGConfig
    from models import RetrievedChunk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QdrantService:
    """
    Manages Qdrant vector store for CAG chunks.

    Features:
    - Hybrid vectors (dense + sparse)
    - Rich payload indexing
    - O(1) neighbor lookup via ID prediction
    """

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()
        qdrant_config = self.config.qdrant

        # Connect to Qdrant
        if qdrant_config.url:
            self.client = QdrantClient(
                url=qdrant_config.url, api_key=qdrant_config.api_key, timeout=300
            )
        else:
            self.client = QdrantClient(
                host=qdrant_config.host,
                port=qdrant_config.port,
            )

        self.child_collection = qdrant_config.child_collection
        self.parent_collection = qdrant_config.parent_collection

        logger.info(f"Connected to Qdrant")

    # =========================================================================
    # COLLECTION MANAGEMENT
    # =========================================================================

    def create_collections(
        self,
        recreate: bool = False,
        enable_sparse: bool = True,
    ):
        """
        Create Qdrant collections with hybrid vector support.

        Args:
            recreate: Delete existing collections first
            enable_sparse: Enable sparse vectors for hybrid search
        """
        embedding_config = self.config.embedding

        # Child chunks collection
        child_exists = self.client.collection_exists(self.child_collection)

        if recreate and child_exists:
            self.client.delete_collection(self.child_collection)
            child_exists = False
            logger.info(f"Deleted: {self.child_collection}")

        if not child_exists:
            # Dense vector config
            vectors_config = {
                "dense": VectorParams(
                    size=embedding_config.dimensions,
                    distance=Distance.COSINE,
                ),
            }

            # Sparse vector config
            sparse_config = None
            if enable_sparse:
                sparse_config = {
                    "sparse": SparseVectorParams(
                        modifier=models.Modifier.IDF,
                    ),
                }

            self.client.create_collection(
                collection_name=self.child_collection,
                vectors_config=vectors_config,
                sparse_vectors_config=sparse_config,
            )

            # Create payload indexes
            self._create_child_indexes()
            logger.info(f"Created: {self.child_collection}")

        # Parent chunks collection (metadata only)
        parent_exists = self.client.collection_exists(self.parent_collection)

        if recreate and parent_exists:
            self.client.delete_collection(self.parent_collection)
            parent_exists = False

        if not parent_exists:
            # Parent collection needs named vectors to match upsert format
            self.client.create_collection(
                collection_name=self.parent_collection,
                vectors_config={
                    "dense": VectorParams(
                        size=4,  # Minimal dummy vector (parents are metadata-only)
                        distance=Distance.COSINE,
                    ),
                },
            )
            logger.info(f"Created: {self.parent_collection}")

    def _create_child_indexes(self):
        """Create payload indexes for efficient filtering."""
        indexes = [
            # Standard indexes
            ("report_id", PayloadSchemaType.KEYWORD),
            ("report_year", PayloadSchemaType.INTEGER),
            ("parent_chunk_id", PayloadSchemaType.KEYWORD),
            ("content_type", PayloadSchemaType.KEYWORD),
            ("page_physical", PayloadSchemaType.INTEGER),
            # Semantic enrichment indexes
            ("finding_type", PayloadSchemaType.KEYWORD),
            ("severity", PayloadSchemaType.KEYWORD),
            ("section_type", PayloadSchemaType.KEYWORD),
            ("total_amount_crore", PayloadSchemaType.FLOAT),
            ("is_recommendation", PayloadSchemaType.BOOL),
            ("recommendation_target", PayloadSchemaType.KEYWORD),
        ]

        for field_name, field_type in indexes:
            try:
                self.client.create_payload_index(
                    collection_name=self.child_collection,
                    field_name=field_name,
                    field_schema=field_type,
                )
            except Exception:
                pass  # Index may already exist

    # =========================================================================
    # INDEXING
    # =========================================================================

    def upsert_children(
        self,
        payloads: List[Dict[str, Any]],
        dense_embeddings: List[List[float]],
        sparse_vectors: List[Dict[str, List]],
    ) -> int:
        """
        Index child chunks with hybrid vectors.

        Args:
            payloads: List of chunk payloads
            dense_embeddings: Dense embedding vectors
            sparse_vectors: Sparse vectors {"indices": [], "values": []}

        Returns:
            Number of points upserted
        """
        points = []

        for payload, dense, sparse in zip(payloads, dense_embeddings, sparse_vectors):
            point_id = self._chunk_id_to_point_id(payload["chunk_id"])

            # Build vectors
            vectors = {"dense": dense}

            if sparse.get("indices"):
                vectors["sparse"] = SparseVector(
                    indices=sparse["indices"],
                    values=sparse["values"],
                )

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vectors,
                    payload=payload,
                )
            )

        # Upsert in batches
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self.client.upsert(
                collection_name=self.child_collection,
                points=batch,
            )

        return len(points)

    def upsert_parents(self, parent_chunks: List[Dict[str, Any]]) -> int:
        """
        Index parent chunks (metadata only).

        Args:
            parent_chunks: List of parent chunk dicts

        Returns:
            Number of points upserted
        """
        points = []

        for parent in parent_chunks:
            point_id = self._chunk_id_to_point_id(parent["chunk_id"])

            payload = {
                "chunk_id": parent.get("chunk_id"),
                "report_id": parent.get("report_id"),
                "toc_entry": parent.get("toc_entry", ""),
                "toc_level": parent.get("toc_level", 1),
                "hierarchy": parent.get("hierarchy", {}),
                "page_range_physical": parent.get("page_range_physical", [0, 0]),
            }

            points.append(
                PointStruct(
                    id=point_id,
                    vector={"dense": [0.0, 0.0, 0.0, 0.0]},
                    payload=payload,
                )
            )

        # Upsert
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self.client.upsert(
                collection_name=self.parent_collection,
                points=batch,
            )

        return len(points)

    # =========================================================================
    # SEARCH
    # =========================================================================

    def hybrid_search(
        self,
        dense_vector: List[float],
        sparse_vector: Dict[str, List],
        limit: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """
        Hybrid search using dense + sparse vectors with RRF fusion.

        Args:
            dense_vector: Dense embedding
            sparse_vector: Sparse vector {"indices": [], "values": []}
            limit: Number of results
            filters: Semantic filters

        Returns:
            List of RetrievedChunk
        """
        query_filter = self._build_filter(filters)

        try:
            results = self.client.query_points(
                collection_name=self.child_collection,
                prefetch=[
                    Prefetch(
                        query=dense_vector,
                        using="dense",
                        limit=limit,
                        filter=query_filter,
                    ),
                    Prefetch(
                        query=SparseVector(
                            indices=sparse_vector.get("indices", []),
                            values=sparse_vector.get("values", []),
                        ),
                        using="sparse",
                        limit=limit,
                        filter=query_filter,
                    ),
                ],
                query=FusionQuery(fusion="rrf"),
                limit=limit,
            )

            return self._convert_results(results.points)

        except Exception as e:
            logger.warning(f"Hybrid search failed, falling back to dense: {e}")
            return self.dense_search(dense_vector, limit, filters)

    def dense_search(
        self,
        dense_vector: List[float],
        limit: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """
        Dense-only vector search.

        Args:
            dense_vector: Dense embedding
            limit: Number of results
            filters: Semantic filters

        Returns:
            List of RetrievedChunk
        """
        query_filter = self._build_filter(filters)

        results = self.client.search(
            collection_name=self.child_collection,
            query_vector=("dense", dense_vector),
            query_filter=query_filter,
            limit=limit,
        )

        return self._convert_results(results)

    def _build_filter(self, filters: Optional[Dict[str, Any]]) -> Optional[Filter]:
        """Build Qdrant filter from semantic filters."""
        if not filters:
            return None

        conditions = []

        for key, value in filters.items():
            if value is None:
                continue

            if isinstance(value, dict):
                # Range filter (e.g., {"gte": 10.0})
                conditions.append(
                    FieldCondition(
                        key=key,
                        range=Range(
                            gte=value.get("gte"),
                            lte=value.get("lte"),
                            gt=value.get("gt"),
                            lt=value.get("lt"),
                        ),
                    )
                )
            elif isinstance(value, list):
                # Array match any
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchAny(any=value),
                    )
                )
            else:
                # Exact match
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value),
                    )
                )

        return Filter(must=conditions) if conditions else None

    def _convert_results(self, hits: List[Any]) -> List[RetrievedChunk]:
        """Convert Qdrant results to RetrievedChunk objects."""
        chunks = []

        for hit in hits:
            payload = hit.payload if hasattr(hit, "payload") else {}
            score = hit.score if hasattr(hit, "score") else 0

            chunks.append(
                RetrievedChunk(
                    chunk_id=payload.get("chunk_id", ""),
                    content=payload.get("content", ""),
                    score=score,
                    parent_chunk_id=payload.get("parent_chunk_id"),
                    hierarchy=payload.get("hierarchy", {}),
                    report_id=payload.get("report_id", ""),
                    report_year=payload.get("report_year"),
                    page_physical=payload.get("page_physical", 0),
                    page_logical=str(payload.get("page_logical", "")),
                    content_type=payload.get("content_type", "paragraph"),
                    finding_type=payload.get("finding_type"),
                    severity=payload.get("severity"),
                    total_amount_crore=payload.get("total_amount_crore"),
                    entities_mentioned=payload.get("entities_mentioned", []),
                    is_recommendation=payload.get("is_recommendation", False),
                    recommendation_target=payload.get("recommendation_target"),
                    action_required=payload.get("action_required"),
                    section_type=payload.get("section_type"),
                )
            )

        return chunks

    # =========================================================================
    # LOOKUPS
    # =========================================================================

    def get_parent(self, parent_chunk_id: str) -> Optional[Dict[str, Any]]:
        """Fetch parent chunk by ID."""
        point_id = self._chunk_id_to_point_id(parent_chunk_id)

        try:
            results = self.client.retrieve(
                collection_name=self.parent_collection,
                ids=[point_id],
            )
            if results:
                return results[0].payload
        except Exception:
            pass

        return None

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Fetch child chunk by ID (O(1) lookup)."""
        point_id = self._chunk_id_to_point_id(chunk_id)

        try:
            results = self.client.retrieve(
                collection_name=self.child_collection,
                ids=[point_id],
            )
            if results:
                return results[0].payload
        except Exception:
            pass

        return None

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        try:
            child_info = self.client.get_collection(self.child_collection)
            parent_info = self.client.get_collection(self.parent_collection)

            return {
                "child_chunks": {
                    "count": child_info.points_count,
                    "vectors_count": child_info.vectors_count,
                },
                "parent_chunks": {
                    "count": parent_info.points_count,
                },
            }
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # UTILITIES
    # =========================================================================

    @staticmethod
    def _chunk_id_to_point_id(chunk_id: str) -> int:
        """Convert chunk_id string to Qdrant point ID (integer)."""
        hash_bytes = hashlib.md5(chunk_id.encode()).digest()
        return int.from_bytes(hash_bytes[:8], byteorder="big", signed=False)
