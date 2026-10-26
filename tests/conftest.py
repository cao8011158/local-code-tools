"""Make default tests independent of private configuration, real indices and API keys."""

import json
import os
from pathlib import Path

import pytest


def pytest_addoption(parser):
    """Keep the existing real-cache compatibility test explicitly opt-in."""
    parser.addoption(
        "--run-local-index",
        action="store_true",
        help="Enable optional tests requiring the local configured real cache",
    )


def pytest_configure(config):
    """Register the local-only evidence boundary without changing runtime configuration."""
    config.addinivalue_line(
        "markers", "local_index: requires existing real local indices/cache; never calls API"
    )


def pytest_collection_modifyitems(config, items):
    """Do not silently present an absent real cache as independently reproduced evidence."""
    for item in items:
        if item.name == "test_real_compatible_cache_reuse_without_network":
            item.add_marker(pytest.mark.local_index)
            if not config.getoption("--run-local-index"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="optional existing real-cache test; use --run-local-index"
                    )
                )


@pytest.fixture(scope="session", autouse=True)
def isolated_default_config(tmp_path_factory, request):
    """Supply a temporary template config only to tests, preserving the user's config."""
    if request.config.getoption("--run-local-index"):
        yield
        return
    root = Path(__file__).resolve().parents[1]
    folder = tmp_path_factory.mktemp("review-config")
    c = json.loads((root / "config.example.json").read_text(encoding="utf-8-sig"))
    c["data"] = str(folder / "unused-data")
    path = folder / "config.json"
    path.write_text(json.dumps(c), encoding="utf-8")
    previous = os.environ.get("LCT_CONFIG")
    os.environ["LCT_CONFIG"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LCT_CONFIG", None)
        else:
            os.environ["LCT_CONFIG"] = previous


@pytest.fixture(autouse=True)
def forbid_embedding_api(monkeypatch):
    """Any accidental provider request fails immediately; synthetic caches are explicit."""
    from lct.embedding import Embeddings

    def denied(*args, **kwargs):
        raise AssertionError("Embedding API is forbidden in this test suite")

    monkeypatch.setattr(Embeddings, "call", denied)
