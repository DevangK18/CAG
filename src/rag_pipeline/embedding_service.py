"""
CAG RAG Pipeline - Embedding Service
=====================================

Handles:
1. Dense embeddings (OpenAI text-embedding-3-large)
2. Sparse embeddings (Built-in BM25 - no fastembed needed)
3. LLM-based table summaries (gpt-4o-mini)
4. Semantic payload extraction (Findings + Recommendations)

Requirements:
    pip install openai tqdm

NOTE: fastembed is NOT used due to huggingface_hub version conflict with docling.
      The built-in BM25 implementation works excellently for CAG documents.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from tqdm import tqdm

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("Install openai: pip install openai")

try:
    from ..core.config import EmbeddingConfig, RAGConfig
except ImportError:
    from src.core.config import EmbeddingConfig, RAGConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# SPARSE VECTOR SERVICE (Built-in BM25)
# =============================================================================


class SparseVectorService:
    """
    Generates BM25-style sparse vectors for hybrid search.

    Uses built-in tokenization optimized for CAG audit reports.
    Critical for exact matching of:
    - Section numbers: "Section 143(3)"
    - Form numbers: "Form 26AS"
    - Entity acronyms: "NHAI", "PMJAY"
    - Monetary values: "₹847.71 crore"

    NOTE: This built-in implementation is used instead of fastembed
    due to huggingface_hub version conflicts with docling.
    """

    def __init__(self, model_name: str = "built-in-bm25"):
        """Initialize the sparse vector service."""
        self.model_name = model_name
        self._vocab: Dict[str, int] = {}
        self._next_id = 0

        # Stopwords for filtering
        self._stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "been",
            "be",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
            "they",
            "them",
            "their",
            "which",
            "who",
            "whom",
            "what",
            "where",
            "when",
            "why",
            "how",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "just",
            "also",
            "being",
            "into",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "again",
            "further",
            "then",
            "once",
            "here",
            "there",
            "any",
            "no",
            "nor",
            "not",
            "can",
            "cannot",
            "now",
        }

        logger.info(f"SparseVectorService initialized (built-in BM25)")

    def _extract_special_tokens(self, text: str) -> List[str]:
        """Extract special patterns important for CAG documents."""
        tokens = []
        text_lower = text.lower()

        # Section references: "Section 143(3)" -> "section_143_3"
        for match in re.finditer(r"section\s*(\d+)(?:\s*\(([^)]+)\))?", text_lower):
            section_num = match.group(1)
            subsection = match.group(2) if match.group(2) else ""
            if subsection:
                tokens.append(f"section_{section_num}_{subsection.replace(' ', '')}")
            else:
                tokens.append(f"section_{section_num}")

        # Rule references: "Rule 86B" -> "rule_86b"
        for match in re.finditer(r"rule\s*(\d+[a-z]?)", text_lower):
            tokens.append(f"rule_{match.group(1)}")

        # Form references: "Form 26AS" -> "form_26as"
        for match in re.finditer(r"form\s*(\d+[a-z]*)", text_lower):
            tokens.append(f"form_{match.group(1)}")

        # Article references: "Article 311" -> "article_311"
        for match in re.finditer(r"article\s*(\d+)", text_lower):
            tokens.append(f"article_{match.group(1)}")

        # Monetary values: "₹847.71 crore" -> "money_crore"
        for match in re.finditer(
            r"₹?\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand|cr|lac)", text_lower
        ):
            unit = match.group(2)
            if unit in ("cr", "crore"):
                tokens.append("money_crore")
            elif unit in ("lac", "lakh"):
                tokens.append("money_lakh")
            else:
                tokens.append(f"money_{unit}")

        # Year references: "2023-24" or "2023"
        for match in re.finditer(r"\b(20\d{2}(?:-\d{2})?)\b", text):
            tokens.append(f"year_{match.group(1)}")

        # Percentage values
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", text_lower):
            tokens.append("has_percentage")

        # Acronyms (2-6 uppercase letters) - from original text
        for match in re.finditer(r"\b([A-Z]{2,6})\b", text):
            tokens.append(f"acronym_{match.group(1)}")

        return tokens

    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text with special handling for CAG documents.
        """
        tokens = []

        # Extract special patterns first (these get boosted)
        tokens.extend(self._extract_special_tokens(text))

        # Regular word tokenization
        text_lower = text.lower()
        words = re.findall(r"\b[a-z]{2,}\b", text_lower)

        # Filter stopwords and add remaining words
        tokens.extend([w for w in words if w not in self._stopwords])

        return tokens

    def _get_token_id(self, token: str) -> int:
        """Get or create ID for a token."""
        if token not in self._vocab:
            self._vocab[token] = self._next_id
            self._next_id += 1
        return self._vocab[token]

    def encode(self, texts: List[str]) -> List[Dict[str, List]]:
        """
        Generate sparse vectors for texts using BM25-style weighting.

        Returns:
            List of {"indices": [...], "values": [...]}
        """
        results = []

        for text in texts:
            tokens = self._tokenize(text)

            # Count term frequencies
            tf: Dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1

            # Build sparse vector with BM25-style weighting
            indices = []
            values = []

            for token, count in tf.items():
                token_id = self._get_token_id(token)

                # BM25-style term frequency saturation: tf / (tf + k1)
                k1 = 1.2
                tf_score = count / (count + k1)

                # IDF-like boost for important patterns
                if token.startswith(("section_", "rule_", "form_", "article_")):
                    idf_boost = 3.0  # Legal/regulatory references - very important
                elif token.startswith("acronym_"):
                    idf_boost = 2.5  # Entity acronyms
                elif token.startswith(("money_", "year_", "has_percentage")):
                    idf_boost = 1.5  # Numeric context
                else:
                    idf_boost = 1.0  # Regular words

                score = tf_score * idf_boost

                indices.append(token_id)
                values.append(float(score))

            results.append(
                {
                    "indices": indices,
                    "values": values,
                }
            )

        return results

    def encode_single(self, text: str) -> Dict[str, List]:
        """Encode a single text."""
        return self.encode([text])[0]


# =============================================================================
# TABLE SUMMARY SERVICE (LLM-based)
# =============================================================================


class TableSummaryService:
    """
    Generates semantic summaries for markdown tables using LLM.

    Why LLM instead of rule-based:
    - CAG tables have complex merged headers
    - Rule-based split("|") fails on nested structures
    - LLM captures actual meaning, not just structure

    Cost: ~$0.0001 per table with gpt-4o-mini
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.total_tables = 0
        self.total_tokens = 0

    def summarize(self, table_markdown: str, context: str = "") -> str:
        """
        Generate a natural language summary of a table.

        Args:
            table_markdown: The markdown table
            context: Section title/hierarchy for context

        Returns:
            1-2 sentence summary capturing the table's insight
        """
        if not table_markdown or len(table_markdown.strip()) < 20:
            return ""

        # Truncate very long tables
        table_text = table_markdown[:2000]

        prompt = f"""Summarize this table from a CAG (Comptroller and Auditor General) audit report in 1-2 sentences.
Focus on: what data it shows, time period covered, key totals or trends.

Context: {context}

Table:
{table_text}

Summary (1-2 sentences, be specific about numbers and entities):"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0,
            )

            self.total_tables += 1
            self.total_tokens += response.usage.total_tokens

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.warning(f"Table summary failed: {e}")
            return self._fallback_summary(table_markdown)

    def _fallback_summary(self, table_markdown: str) -> str:
        """Rule-based fallback if LLM fails."""
        lines = table_markdown.strip().split("\n")
        if len(lines) < 3:
            return ""

        # Try to extract headers
        headers = [h.strip() for h in lines[0].split("|") if h.strip()]
        data_rows = len([l for l in lines[2:] if "|" in l])

        if headers:
            header_str = ", ".join(headers[:4])
            return f"Table with {data_rows} rows showing: {header_str}."

        return f"Table with {data_rows} rows of data."

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return {
            "tables_summarized": self.total_tables,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.total_tokens * 0.00000015,  # gpt-4o-mini pricing
        }


# =============================================================================
# SEMANTIC PAYLOAD EXTRACTOR
# =============================================================================


class SemanticPayloadExtractor:
    """
    Extracts semantic enrichment data for Qdrant payload.

    Checks BOTH:
    - Findings (finding_type, severity, amount, entities)
    - Recommendations (target_entity, action_required)
    """

    def extract_for_chunk(
        self,
        chunk: Dict[str, Any],
        semantic_enrichment: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Extract semantic fields for a chunk's payload.

        Args:
            chunk: Child chunk dict
            semantic_enrichment: Report's semantic_enrichment data

        Returns:
            Dict of additional payload fields
        """
        payload = {}

        if not semantic_enrichment:
            return payload

        chunk_id = chunk.get("chunk_id", "")

        # Check Findings
        for finding in semantic_enrichment.get("findings", []):
            if finding.get("source_chunk_id") == chunk_id:
                payload["finding_type"] = finding.get("finding_type")
                payload["severity"] = finding.get("severity")

                # Convert to crore for easier filtering
                total_inr = finding.get("total_amount_inr", 0)
                if total_inr:
                    payload["total_amount_crore"] = total_inr / 10_000_000_00

                payload["entities_mentioned"] = finding.get("entities_mentioned", [])
                break

        # Check Recommendations (includes target ministries)
        for rec in semantic_enrichment.get("recommendations", []):
            if rec.get("source_chunk_id") == chunk_id:
                payload["is_recommendation"] = True
                payload["recommendation_target"] = rec.get("target_entity")
                payload["action_required"] = rec.get("action_required")

                # Add target entity to entities list
                if rec.get("target_entity"):
                    existing = payload.get("entities_mentioned", [])
                    if rec["target_entity"] not in existing:
                        payload["entities_mentioned"] = existing + [
                            rec["target_entity"]
                        ]
                break

        # Section type classification
        for section in semantic_enrichment.get("section_classifications", []):
            if section.get("chunk_id") == chunk_id:
                payload["section_type"] = section.get("section_type")
                break

        return payload


# =============================================================================
# DENSE EMBEDDING SERVICE
# =============================================================================


class DenseEmbeddingService:
    """
    Generates dense embeddings using OpenAI.
    """

    def __init__(self, config: EmbeddingConfig, api_key: str):
        self.config = config
        self.client = OpenAI(api_key=api_key)
        self.total_tokens = 0

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []

        # Truncate overly long texts
        truncated = []
        for text in texts:
            max_chars = self.config.max_chunk_tokens * 4
            if len(text) > max_chars:
                text = text[:max_chars]
            truncated.append(text)

        response = self.client.embeddings.create(
            model=self.config.model,
            input=truncated,
            dimensions=self.config.dimensions,
        )

        self.total_tokens += response.usage.total_tokens

        return [item.embedding for item in response.data]

    def embed_single(self, text: str) -> List[float]:
        """Embed a single text."""
        return self.embed_texts([text])[0]

    def embed_batch(
        self,
        texts: List[str],
        show_progress: bool = True,
    ) -> List[List[float]]:
        """Embed texts in batches."""
        all_embeddings = []

        batches = [
            texts[i : i + self.config.batch_size]
            for i in range(0, len(texts), self.config.batch_size)
        ]

        iterator = tqdm(batches, desc="Embedding") if show_progress else batches

        for batch in iterator:
            embeddings = self.embed_texts(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    def get_cost_estimate(self) -> float:
        """Get estimated cost in USD."""
        # text-embedding-3-large: $0.13 per 1M tokens
        return (self.total_tokens / 1_000_000) * 0.13


# =============================================================================
# MAIN EMBEDDING SERVICE
# =============================================================================


class EmbeddingService:
    """
    Complete embedding service with all features:
    - Dense embeddings (OpenAI)
    - Sparse embeddings (Built-in BM25)
    - LLM table summaries
    - Semantic payload extraction
    """

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()

        # Validate
        if not self.config.openai_api_key:
            raise ValueError("OPENAI_API_KEY required")

        # Initialize services
        self.dense_service = DenseEmbeddingService(
            self.config.embedding,
            self.config.openai_api_key,
        )

        # Always use built-in sparse vectors (no fastembed dependency)
        self.sparse_service = None
        if self.config.embedding.enable_sparse_vectors:
            self.sparse_service = SparseVectorService()

        self.table_service = None
        if self.config.embedding.enable_table_summaries:
            self.table_service = TableSummaryService(
                self.config.openai_api_key,
                self.config.embedding.table_summary_model,
            )

        self.semantic_extractor = SemanticPayloadExtractor()

        logger.info("EmbeddingService initialized")

    def prepare_text_for_embedding(
        self,
        chunk: Dict[str, Any],
        parent_hierarchy: Dict[str, str],
    ) -> str:
        """
        Prepare chunk text for embedding with enhancements.

        Adds:
        - Hierarchy prefix
        - Table summary (for table chunks)
        """
        content = chunk.get("content", "")
        content_type = chunk.get("content_type", "paragraph")

        parts = []

        # Hierarchy prefix
        if self.config.embedding.enable_hierarchy_prefix and parent_hierarchy:
            hierarchy_str = " > ".join(parent_hierarchy.values())
            parts.append(f"[{hierarchy_str}]")

        # Table summary
        if self.table_service and content_type in ("table_markdown", "table"):
            hierarchy_context = (
                " > ".join(parent_hierarchy.values()) if parent_hierarchy else ""
            )
            summary = self.table_service.summarize(content, hierarchy_context)
            if summary:
                parts.append(f"[Table Summary: {summary}]")

        # Main content
        parts.append(content)

        return "\n\n".join(parts)

    def process_chunks(
        self,
        child_chunks: List[Dict[str, Any]],
        parent_chunks: List[Dict[str, Any]],
        semantic_enrichment: Optional[Dict[str, Any]] = None,
        show_progress: bool = True,
    ) -> Tuple[List[str], List[List[float]], List[Dict], List[Dict[str, Any]]]:
        """
        Process all chunks for indexing.

        Returns:
            Tuple of (texts, dense_embeddings, sparse_vectors, payloads)
        """
        # Build parent lookup
        parent_lookup = {p["chunk_id"]: p for p in parent_chunks}

        texts = []
        payloads = []

        for chunk in child_chunks:
            # Get hierarchy from parent
            parent_id = chunk.get("parent_chunk_id", "")
            parent = parent_lookup.get(parent_id, {})
            hierarchy = chunk.get("hierarchy") or parent.get("hierarchy", {})

            # Prepare text
            text = self.prepare_text_for_embedding(chunk, hierarchy)
            texts.append(text)

            # Build payload
            payload = {
                "chunk_id": chunk.get("chunk_id"),
                "parent_chunk_id": chunk.get("parent_chunk_id"),
                "content": chunk.get("content", ""),
                "content_type": chunk.get("content_type", "paragraph"),
                "report_id": chunk.get("report_id"),
                "report_year": chunk.get("report_year"),
                "page_physical": chunk.get("source_page_physical", 0),
                "page_logical": str(chunk.get("source_page_logical", "")),
                "hierarchy": hierarchy,
                "report_title": chunk.get("report_title", ""),
            }

            # Add semantic enrichment
            if semantic_enrichment:
                semantic_payload = self.semantic_extractor.extract_for_chunk(
                    chunk, semantic_enrichment
                )
                payload.update(semantic_payload)

            payloads.append(payload)

        # Generate dense embeddings
        logger.info(f"Generating dense embeddings for {len(texts)} chunks...")
        dense_embeddings = self.dense_service.embed_batch(texts, show_progress)

        # Generate sparse embeddings
        sparse_vectors = []
        if self.sparse_service:
            logger.info("Generating sparse embeddings...")
            sparse_vectors = self.sparse_service.encode(texts)
        else:
            sparse_vectors = [{"indices": [], "values": []} for _ in texts]

        return texts, dense_embeddings, sparse_vectors, payloads

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        stats = {
            "dense_embedding": {
                "tokens": self.dense_service.total_tokens,
                "cost_usd": self.dense_service.get_cost_estimate(),
            },
        }

        if self.table_service:
            stats["table_summary"] = self.table_service.get_stats()

        return stats
