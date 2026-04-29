"""
Postgres connection management for the entity graph.

Uses SQLAlchemy 2.0 with psycopg v3 driver.
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional, Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

# Load environment variables
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _resolve_dsn() -> str:
    """Resolve the Postgres DSN from env or raise."""
    dsn = os.getenv("ENTITY_GRAPH_DSN")
    if not dsn:
        raise RuntimeError(
            "ENTITY_GRAPH_DSN not set. Required for entity graph operations."
        )
    return dsn


def get_engine() -> Engine:
    """Lazy-initialize the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        dsn = _resolve_dsn()

        # SQLite doesn't support pool_size/max_overflow - detect and skip
        engine_kwargs = {
            "echo": False,
            "future": True,
        }

        if dsn.startswith("postgresql://") or dsn.startswith("postgresql+psycopg"):
            # Postgres-specific pooling parameters
            engine_kwargs.update(
                {
                    "pool_pre_ping": True,
                    "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
                    "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
                }
            )

        _engine = create_engine(dsn, **engine_kwargs)
        logger.info(f"Entity graph engine initialized")
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def init_db():
    """Create tables if they don't exist. Idempotent."""
    Base.metadata.create_all(get_engine())
    logger.info("Entity graph schema initialized")


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standard session context manager."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
