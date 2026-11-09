"""Compatibility entry point for the historical cold-budget acceptance oracle.

Jedi observations have no solver precision budget. A changed capture must have
identical published graph and source evidence to its fresh full build.
"""

from tests.semantic_comparison import assert_semantic_equal


def assert_limited_refinement(actual, fresh, sources):
    # `sources` remains accepted for older callers; no source-derived target
    # or annotation may be fabricated to excuse a graph mismatch.
    assert_semantic_equal(actual, fresh)
