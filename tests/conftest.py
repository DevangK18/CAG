"""
Root conftest for all tests.
Set environment variables before test collection.
"""
import os


def pytest_configure(config):
    """Set environment variables before pytest collection."""
    # Required for entity_graph tests to work with SQLite
    os.environ.setdefault("ENTITY_GRAPH_DSN", "sqlite:///:memory:")


# ── Known failures (see tests/known_failures.py) ─────────────────────────────
import importlib.util as _ilu
from pathlib import Path as _Path

import pytest

_spec = _ilu.spec_from_file_location("known_failures", _Path(__file__).with_name("known_failures.py"))
_known = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_known)

# Modules that cannot be imported are left out of collection
collect_ignore = list(_known.BROKEN_IMPORT_FILES)


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.nodeid in _known.KNOWN_ERRORS_SKIPPED:
            item.add_marker(pytest.mark.skip(reason=_known.KNOWN_ERRORS_SKIPPED[item.nodeid]))
        elif item.nodeid in _known.KNOWN_FAILURES:
            item.add_marker(pytest.mark.xfail(reason=_known.KNOWN_FAILURES[item.nodeid], strict=False))


# ── No real Google credentials in tests ──────────────────────────────────────
@pytest.fixture(autouse=True)
def _anonymous_google_credentials(monkeypatch):
    """Tests must not depend on the machine's Application Default Credentials (CI has none)."""
    try:
        import google.auth
        from google.auth.credentials import AnonymousCredentials
    except ImportError:
        return
    monkeypatch.setattr(google.auth, "default", lambda *a, **k: (AnonymousCredentials(), "test-project"))


@pytest.fixture(autouse=True)
def _fresh_gemini_limiter():
    """The Gemini limiter is process-wide: start each test with a new one and no retry waits."""
    from src.core.gemini_limiter import LimiterSettings, configure_limiter, reset_limiter

    configure_limiter(LimiterSettings(retry_first_wait_s=(0.0, 0.0), retry_max_wait_s=0.0))
    yield
    reset_limiter()
