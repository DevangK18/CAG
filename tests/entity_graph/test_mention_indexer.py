"""
Tests for mention indexer (Phase 12).

Test cases:
1. AliasResolver resolves an alias to entity ID
2. index_report populates EntityMention rows correctly from a fixture chunks.json
3. Re-indexing the same report is idempotent (delete-before-insert)
4. Co-occurrence relations created for findings with multiple entities
"""

import json
import pytest
import tempfile
from pathlib import Path

pytest.importorskip("src.entity_graph.mention_indexer")

from src.entity_graph.models import Entity, EntityMention, EntityRelation
from src.entity_graph.mention_indexer import AliasResolver, index_report, _refresh_entity_counts


class TestAliasResolver:
    """Test AliasResolver resolves aliases to entity IDs."""

    def test_resolves_canonical_name(self, test_db):
        """Resolves exact canonical name (case-insensitive)."""
        # Setup: insert entity
        entity = Entity(
            canonical_name="National Highways Authority of India",
            entity_type="psu",
            aliases=json.dumps(["NHAI", "National Highways Authority"]),
            primary_tier="union",
        )
        test_db.add(entity)
        test_db.commit()

        resolver = AliasResolver(test_db)

        # Exact match
        assert resolver.resolve("National Highways Authority of India") == entity.id

        # Case-insensitive
        assert resolver.resolve("national highways authority of india") == entity.id

    def test_resolves_alias(self, test_db):
        """Resolves alias to canonical entity ID."""
        entity = Entity(
            canonical_name="National Highways Authority of India",
            entity_type="psu",
            aliases=json.dumps(["NHAI", "National Highways Authority"]),
            primary_tier="union",
        )
        test_db.add(entity)
        test_db.commit()

        resolver = AliasResolver(test_db)

        assert resolver.resolve("NHAI") == entity.id
        assert resolver.resolve("nhai") == entity.id  # case-insensitive
        assert resolver.resolve("National Highways Authority") == entity.id

    def test_returns_none_for_unknown(self, test_db):
        """Returns None for unknown entities."""
        resolver = AliasResolver(test_db)

        assert resolver.resolve("Unknown Entity") is None


class TestIndexReport:
    """Test index_report populates EntityMention rows correctly."""

    def test_indexes_finding_mentions(self, test_db):
        """Extracts entity mentions from findings and creates EntityMention rows."""
        # Setup: create entity
        entity = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI", "National Highways Authority of India"]),
            primary_tier="union",
        )
        test_db.add(entity)
        test_db.commit()

        # Create fixture chunks.json
        chunks_data = {
            "report_metadata": {
                "report_id": "2023_01_Test_Report",
                "report_title": "Test Report 2023-24",
                "report_year": "2023-24",
                "government_body_type": "union",
            },
            "semantic_enrichment": {
                "findings": [
                    {
                        "finding_id": "F001",
                        "source_chunk_id": "chunk_1",
                        "entities_mentioned": ["NHAI"],
                        "finding_type": "loss_of_revenue",
                        "severity": "high",
                        "total_amount_inr": 640000000,  # ₹64 crore
                        "page": 36,
                    }
                ]
            },
            "child_chunks": [],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_chunks.json", delete=False
        ) as f:
            json.dump(chunks_data, f)
            temp_path = Path(f.name)

        try:
            # Index the report
            from src.entity_graph.db import init_db

            init_db()
            count = index_report(temp_path)

            assert count == 1

            # Verify mention was created
            mention = test_db.query(EntityMention).first()
            assert mention is not None
            assert mention.entity_id == entity.id
            assert mention.report_id == "2023_01_Test_Report"
            assert mention.finding_id == "F001"
            assert mention.mention_text == "NHAI"
            assert mention.finding_type == "loss_of_revenue"
            assert mention.severity == "high"
            assert mention.amount_crore == 64.0  # converted from INR
            assert mention.page == 36

        finally:
            temp_path.unlink()

    def test_indexes_recommendation_mentions(self, test_db):
        """Extracts entity mentions from recommendations."""
        entity = Entity(
            canonical_name="Ministry of Railways",
            entity_type="ministry",
            aliases=json.dumps(["MoR", "Min. of Railways"]),
            primary_tier="union",
        )
        test_db.add(entity)
        test_db.commit()

        chunks_data = {
            "report_metadata": {
                "report_id": "2023_02_Test_Report",
                "government_body_type": "union",
            },
            "semantic_enrichment": {
                "findings": [],
                "recommendations": [
                    {
                        "recommendation_id": "R001",
                        "source_chunk_id": "chunk_5",
                        "target_entity": "Ministry of Railways",
                        "page": 112,
                    }
                ],
            },
            "child_chunks": [],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_chunks.json", delete=False
        ) as f:
            json.dump(chunks_data, f)
            temp_path = Path(f.name)

        try:
            from src.entity_graph.db import init_db

            init_db()
            count = index_report(temp_path)

            assert count == 1

            mention = test_db.query(EntityMention).first()
            assert mention.entity_id == entity.id
            assert mention.recommendation_id == "R001"
            assert mention.mention_text == "Ministry of Railways"

        finally:
            temp_path.unlink()

    def test_reindexing_is_idempotent(self, test_db):
        """Re-indexing the same report deletes old mentions first."""
        entity = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
            primary_tier="union",
        )
        test_db.add(entity)
        test_db.commit()

        chunks_data = {
            "report_metadata": {
                "report_id": "2023_01_Test_Report",
                "government_body_type": "union",
            },
            "semantic_enrichment": {
                "findings": [
                    {
                        "finding_id": "F001",
                        "entities_mentioned": ["NHAI"],
                        "page": 36,
                    }
                ]
            },
            "child_chunks": [],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_chunks.json", delete=False
        ) as f:
            json.dump(chunks_data, f)
            temp_path = Path(f.name)

        try:
            from src.entity_graph.db import init_db

            init_db()

            # Index once
            count1 = index_report(temp_path)
            assert count1 == 1

            # Index again
            count2 = index_report(temp_path)
            assert count2 == 1

            # Should still have exactly 1 mention
            total = test_db.query(EntityMention).count()
            assert total == 1

        finally:
            temp_path.unlink()


class TestCoOccurrenceRelations:
    """Test co-occurrence relations created for findings with multiple entities."""

    def test_creates_relations_for_multi_entity_findings(self, test_db):
        """When a finding mentions multiple entities, co-occurrence relations are created."""
        entity1 = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
            primary_tier="union",
        )
        entity2 = Entity(
            canonical_name="Ministry of Road Transport",
            entity_type="ministry",
            aliases=json.dumps(["MoRT", "Ministry of Road Transport"]),
            primary_tier="union",
        )
        test_db.add(entity1)
        test_db.add(entity2)
        test_db.commit()

        chunks_data = {
            "report_metadata": {
                "report_id": "2023_01_Test_Report",
                "government_body_type": "union",
            },
            "semantic_enrichment": {
                "findings": [
                    {
                        "finding_id": "F001",
                        "entities_mentioned": ["NHAI", "Ministry of Road Transport"],
                        "page": 36,
                    }
                ]
            },
            "child_chunks": [],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_chunks.json", delete=False
        ) as f:
            json.dump(chunks_data, f)
            temp_path = Path(f.name)

        try:
            from src.entity_graph.db import init_db

            init_db()
            index_report(temp_path)

            # Should have 2 mentions
            assert test_db.query(EntityMention).count() == 2

            # Should have 1 co-occurrence relation
            relations = test_db.query(EntityRelation).all()
            assert len(relations) == 1

            rel = relations[0]
            assert rel.relation_type == "co_occurs_in_finding"
            assert rel.finding_id == "F001"

            # Relation should be between the two entities
            entity_ids = {rel.source_entity_id, rel.target_entity_id}
            assert entity_ids == {entity1.id, entity2.id}

        finally:
            temp_path.unlink()


class TestRefreshEntityCounts:
    """Test _refresh_entity_counts updates aggregates correctly."""

    def test_updates_mention_and_finding_counts(self, test_db):
        """Entity counts are updated after indexing."""
        entity = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
            primary_tier="union",
            mention_count=0,
            finding_count=0,
            report_count=0,
        )
        test_db.add(entity)
        test_db.commit()

        # Add mentions
        mention1 = EntityMention(
            entity_id=entity.id,
            report_id="2023_01_Test",
            finding_id="F001",
            mention_text="NHAI",
        )
        mention2 = EntityMention(
            entity_id=entity.id,
            report_id="2023_01_Test",
            finding_id="F002",
            mention_text="NHAI",
        )
        mention3 = EntityMention(
            entity_id=entity.id,
            report_id="2023_02_Test",
            chunk_id="chunk_5",
            mention_text="NHAI",
        )
        test_db.add_all([mention1, mention2, mention3])
        test_db.commit()

        # Refresh counts
        _refresh_entity_counts(test_db)
        test_db.commit()

        test_db.refresh(entity)
        assert entity.mention_count == 3
        assert entity.finding_count == 2  # 2 have finding_id
        assert entity.report_count == 2  # 2 distinct reports
