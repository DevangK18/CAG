"""
SQLAlchemy ORM models for the entity graph.

Three tables:
- entities: canonical entities with aliases + counts
- entity_mentions: every mention found in chunks/findings/recommendations
- entity_relations: co-occurrence edges within findings (sparse)
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Integer,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Aliases stored as JSON-encoded array (Postgres TEXT[] would also work but JSON is portable)
    aliases: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Tier hint (union/state/local_body) — informational; mentions can span tiers
    primary_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    first_seen_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_seen_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    report_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    mentions: Mapped[List["EntityMention"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class EntityMention(Base):
    __tablename__ = "entity_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    # nullable: chunk-level mentions point to chunk_id; finding-level mentions may not
    chunk_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    finding_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    recommendation_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    mention_text: Mapped[str] = mapped_column(String(500), nullable=False)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    finding_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    amount_crore: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Tier metadata (denormalized for fast filtering)
    audit_year: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    government_body_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    state_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entity: Mapped["Entity"] = relationship(back_populates="mentions")


class EntityRelation(Base):
    __tablename__ = "entity_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            "finding_id",
            name="uq_entity_relation",
        ),
        Index("idx_relations_source", "source_entity_id"),
        Index("idx_relations_target", "target_entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE")
    )
    target_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE")
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    report_id: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    finding_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
