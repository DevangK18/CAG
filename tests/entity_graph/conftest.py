import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch


def pytest_configure(config):
    """
    Set environment variable before pytest collection.
    This allows pytest.importorskip to succeed in test files.
    """
    os.environ["ENTITY_GRAPH_DSN"] = "sqlite:///:memory:"

# Import will fail until entity_graph module is created (Steps 2-6 of plan)
try:
    from src.entity_graph.models import Base
    from src.entity_graph import db as entity_db_module
except ImportError:
    # Placeholder for tests to at least load
    from sqlalchemy.orm import DeclarativeBase

    class Base(DeclarativeBase):
        pass

    entity_db_module = None


@pytest.fixture(scope="function")
def test_db(monkeypatch):
    """In-memory SQLite for unit tests (Postgres-compatible SQL only)."""
    # Create in-memory SQLite engine
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    # Monkeypatch environment variable
    monkeypatch.setenv("ENTITY_GRAPH_DSN", "sqlite:///:memory:")

    # Mock get_engine to return our test engine
    if entity_db_module:
        monkeypatch.setattr(entity_db_module, "_engine", engine)
        monkeypatch.setattr(entity_db_module, "_SessionLocal", SessionLocal)

    session = SessionLocal()
    yield session

    # Cleanup
    session.close()
    engine.dispose()
