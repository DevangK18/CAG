"""
Tests for EntityService (Phase 12).

Test cases:
1. search_entities matches by alias substring
2. get_mentions filters work
3. get_related_entities returns top co-occurring
4. extract_entities_from_query extracts known entities from a query string
"""

import json
import pytest

pytest.importorskip("src.entity_graph.entity_service")

from src.entity_graph.models import Entity, EntityMention, EntityRelation
from src.entity_graph.entity_service import EntityService


class TestSearchEntities:
    """Test search_entities matches by alias substring."""

    def test_matches_by_canonical_name_substring(self, test_db):
        """Searches canonical_name with substring match (case-insensitive)."""
        entity1 = Entity(
            canonical_name="National Highways Authority of India",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
            mention_count=100,
        )
        entity2 = Entity(
            canonical_name="Ministry of Road Transport",
            entity_type="ministry",
            aliases=json.dumps(["MoRT"]),
            mention_count=50,
        )
        test_db.add_all([entity1, entity2])
        test_db.commit()

        service = EntityService()

        # Substring match
        results = service.search_entities("highways", limit=10)

        assert len(results) == 1
        assert results[0]["canonical_name"] == "National Highways Authority of India"

    def test_matches_by_alias_substring(self, test_db):
        """Searches aliases with substring match."""
        entity = Entity(
            canonical_name="National Highways Authority of India",
            entity_type="psu",
            aliases=json.dumps(["NHAI", "National Highways Authority"]),
            mention_count=100,
        )
        test_db.add(entity)
        test_db.commit()

        service = EntityService()

        results = service.search_entities("NHAI", limit=10)

        assert len(results) == 1
        assert results[0]["canonical_name"] == "National Highways Authority of India"

    def test_case_insensitive_search(self, test_db):
        """Search is case-insensitive."""
        entity = Entity(
            canonical_name="Ministry of Railways",
            entity_type="ministry",
            aliases=json.dumps(["MoR"]),
            mention_count=80,
        )
        test_db.add(entity)
        test_db.commit()

        service = EntityService()

        results = service.search_entities("railways", limit=10)
        assert len(results) == 1

        results = service.search_entities("RAILWAYS", limit=10)
        assert len(results) == 1

    def test_filters_by_entity_type(self, test_db):
        """Filters results by entity_type."""
        entity1 = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps([]),
            mention_count=100,
        )
        entity2 = Entity(
            canonical_name="Ministry of Road Transport",
            entity_type="ministry",
            aliases=json.dumps([]),
            mention_count=50,
        )
        test_db.add_all([entity1, entity2])
        test_db.commit()

        service = EntityService()

        results = service.search_entities("", entity_type="psu", limit=10)
        assert len(results) == 1
        assert results[0]["entity_type"] == "psu"

    def test_orders_by_mention_count_desc(self, test_db):
        """Results are ordered by mention_count descending."""
        entity1 = Entity(
            canonical_name="Entity A",
            entity_type="org",
            aliases=json.dumps(["A"]),
            mention_count=10,
        )
        entity2 = Entity(
            canonical_name="Entity B",
            entity_type="org",
            aliases=json.dumps(["B"]),
            mention_count=100,
        )
        entity3 = Entity(
            canonical_name="Entity C",
            entity_type="org",
            aliases=json.dumps(["C"]),
            mention_count=50,
        )
        test_db.add_all([entity1, entity2, entity3])
        test_db.commit()

        service = EntityService()

        results = service.search_entities("Entity", limit=10)

        assert len(results) == 3
        assert results[0]["canonical_name"] == "Entity B"  # highest count
        assert results[1]["canonical_name"] == "Entity C"
        assert results[2]["canonical_name"] == "Entity A"


class TestGetMentions:
    """Test get_mentions filters work."""

    def test_returns_mentions_for_entity(self, test_db):
        """Returns all mentions for a given entity."""
        entity = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
        )
        test_db.add(entity)
        test_db.commit()

        mention1 = EntityMention(
            entity_id=entity.id,
            report_id="2023_01_Test",
            mention_text="NHAI",
            page=10,
        )
        mention2 = EntityMention(
            entity_id=entity.id,
            report_id="2023_02_Test",
            mention_text="NHAI",
            page=20,
        )
        test_db.add_all([mention1, mention2])
        test_db.commit()

        service = EntityService()

        mentions = service.get_mentions(entity.id)

        assert len(mentions) == 2

    def test_filters_by_finding_type(self, test_db):
        """Filters mentions by finding_type."""
        entity = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
        )
        test_db.add(entity)
        test_db.commit()

        mention1 = EntityMention(
            entity_id=entity.id,
            report_id="2023_01_Test",
            finding_type="loss_of_revenue",
            mention_text="NHAI",
        )
        mention2 = EntityMention(
            entity_id=entity.id,
            report_id="2023_02_Test",
            finding_type="performance_shortfall",
            mention_text="NHAI",
        )
        test_db.add_all([mention1, mention2])
        test_db.commit()

        service = EntityService()

        mentions = service.get_mentions(
            entity.id, finding_type="loss_of_revenue", limit=100
        )

        assert len(mentions) == 1
        assert mentions[0]["finding_type"] == "loss_of_revenue"

    def test_filters_by_audit_year(self, test_db):
        """Filters mentions by audit_year."""
        entity = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
        )
        test_db.add(entity)
        test_db.commit()

        mention1 = EntityMention(
            entity_id=entity.id,
            report_id="2023_01_Test",
            audit_year="2022-23",
            mention_text="NHAI",
        )
        mention2 = EntityMention(
            entity_id=entity.id,
            report_id="2023_02_Test",
            audit_year="2023-24",
            mention_text="NHAI",
        )
        test_db.add_all([mention1, mention2])
        test_db.commit()

        service = EntityService()

        mentions = service.get_mentions(entity.id, audit_year="2023-24", limit=100)

        assert len(mentions) == 1
        assert mentions[0]["audit_year"] == "2023-24"

    def test_filters_by_government_body_type(self, test_db):
        """Filters mentions by government_body_type."""
        entity = Entity(
            canonical_name="Entity A",
            entity_type="org",
            aliases=json.dumps(["A"]),
        )
        test_db.add(entity)
        test_db.commit()

        mention1 = EntityMention(
            entity_id=entity.id,
            report_id="2023_01_Union",
            government_body_type="union",
            mention_text="A",
        )
        mention2 = EntityMention(
            entity_id=entity.id,
            report_id="2023_02_State",
            government_body_type="state",
            mention_text="A",
        )
        test_db.add_all([mention1, mention2])
        test_db.commit()

        service = EntityService()

        mentions = service.get_mentions(
            entity.id, government_body_type="state", limit=100
        )

        assert len(mentions) == 1
        assert mentions[0]["government_body_type"] == "state"


class TestGetRelatedEntities:
    """Test get_related_entities returns top co-occurring."""

    def test_returns_co_occurring_entities(self, test_db):
        """Returns entities that co-occur in findings."""
        entity1 = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
        )
        entity2 = Entity(
            canonical_name="Ministry of Road Transport",
            entity_type="ministry",
            aliases=json.dumps(["MoRT"]),
        )
        entity3 = Entity(
            canonical_name="Ministry of Railways",
            entity_type="ministry",
            aliases=json.dumps(["MoR"]),
        )
        test_db.add_all([entity1, entity2, entity3])
        test_db.commit()

        # NHAI co-occurs with MoRT 3 times
        rel1 = EntityRelation(
            source_entity_id=entity1.id,
            target_entity_id=entity2.id,
            relation_type="co_occurs_in_finding",
            finding_id="F001",
        )
        rel2 = EntityRelation(
            source_entity_id=entity1.id,
            target_entity_id=entity2.id,
            relation_type="co_occurs_in_finding",
            finding_id="F002",
        )
        rel3 = EntityRelation(
            source_entity_id=entity1.id,
            target_entity_id=entity2.id,
            relation_type="co_occurs_in_finding",
            finding_id="F003",
        )

        # NHAI co-occurs with MoR 1 time
        rel4 = EntityRelation(
            source_entity_id=entity1.id,
            target_entity_id=entity3.id,
            relation_type="co_occurs_in_finding",
            finding_id="F004",
        )

        test_db.add_all([rel1, rel2, rel3, rel4])
        test_db.commit()

        service = EntityService()

        related = service.get_related_entities(entity1.id, limit=20)

        assert len(related) == 2
        # Ordered by co-occurrence count desc
        assert related[0]["canonical_name"] == "Ministry of Road Transport"
        assert related[0]["co_occurrence_count"] == 3
        assert related[1]["canonical_name"] == "Ministry of Railways"
        assert related[1]["co_occurrence_count"] == 1


class TestExtractEntitiesFromQuery:
    """Test extract_entities_from_query extracts known entities."""

    def test_extracts_capitalized_entities(self, test_db):
        """Extracts capitalized phrases that match known entities."""
        entity = Entity(
            canonical_name="National Highways Authority of India",
            entity_type="psu",
            aliases=json.dumps(["NHAI", "National Highways Authority"]),
            mention_count=100,
        )
        test_db.add(entity)
        test_db.commit()

        service = EntityService()

        query = "What are the findings related to NHAI in 2023?"
        results = service.extract_entities_from_query(query)

        assert len(results) == 1
        assert results[0]["canonical_name"] == "National Highways Authority of India"

    def test_extracts_multi_word_entities(self, test_db):
        """Extracts multi-word capitalized entities."""
        entity = Entity(
            canonical_name="Ministry of Road Transport",
            entity_type="ministry",
            aliases=json.dumps(["MoRT", "Ministry of Road Transport"]),
            mention_count=80,
        )
        test_db.add(entity)
        test_db.commit()

        service = EntityService()

        query = "Compare findings for Ministry of Road Transport across years"
        results = service.extract_entities_from_query(query)

        assert len(results) == 1
        assert results[0]["canonical_name"] == "Ministry of Road Transport"

    def test_deduplicates_multiple_mentions(self, test_db):
        """Deduplicates if an entity is mentioned multiple times."""
        entity = Entity(
            canonical_name="NHAI",
            entity_type="psu",
            aliases=json.dumps(["NHAI"]),
            mention_count=100,
        )
        test_db.add(entity)
        test_db.commit()

        service = EntityService()

        query = "What did NHAI report in 2022? Did NHAI comply?"
        results = service.extract_entities_from_query(query)

        # Should return only 1 result despite 2 mentions
        assert len(results) == 1
        assert results[0]["canonical_name"] == "NHAI"

    def test_returns_empty_for_no_matches(self, test_db):
        """Returns empty list if no entities are recognized."""
        service = EntityService()

        query = "what are the general findings?"
        results = service.extract_entities_from_query(query)

        assert len(results) == 0
