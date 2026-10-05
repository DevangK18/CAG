"""
Tests known to fail on feature/gcp-migration as of 2026-10-04.

They are marked expected (xfail, non-strict) so CI stays green while they are
triaged: each is either fixed, rewritten for current behaviour, or deleted with
the dead code it covers. Remove an entry as soon as its test passes. The list
may only shrink. Each reason ends with the PR expected to remove the entry.
"""

# Files that cannot be imported: they use module layouts that no longer exist
# (..src.modules / services.parsing_pipeline.src). Relative to tests/.
BROKEN_IMPORT_FILES = [
]

# Test node ID -> reason
KNOWN_FAILURES = {
}

# Errors outside the test call (setup/teardown) cannot be xfailed; skipped instead
KNOWN_ERRORS_SKIPPED = {
}
