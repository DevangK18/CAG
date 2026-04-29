"""
Root conftest for all tests.
Set environment variables before test collection.
"""
import os


def pytest_configure(config):
    """Set environment variables before pytest collection."""
    # Required for entity_graph tests to work with SQLite
    os.environ.setdefault("ENTITY_GRAPH_DSN", "sqlite:///:memory:")
