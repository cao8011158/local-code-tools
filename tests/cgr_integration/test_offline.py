"""Offline adapter contract tests; no native service, network, API key or real index."""

import json
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from codebase_rag.integration.api import build_snapshot
from codebase_rag.integration.model import validate

from cgr_adapter.retrieval import build, inputs, normalize, synthetic_vector
from lct.common import ToolError
from lct.embedding import Embeddings
from lct.query import Query

ORIGINAL_VOYAGE_CALL = Embeddings.call


def captured(tmp_path):
    repo = tmp_path / "fixture"
    repo.mkdir()
    (repo / "sample.py").write_text(
        '"""Dispatch module."""\ndef target():\n    """Dispatch command."""\n    return 1\na,b=(lambda:target()),(lambda:target())\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "--", "sample.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Fixture",
        ],
        check=True,
    )
    spec = [dict(name="fixture", path=str(repo), files=["sample.py"], source_roots=["."])]
    return build_snapshot(spec, mode="default"), spec


def configuration(tmp_path, spec):
    c = json.loads(
        (Path(__file__).resolve().parents[2] / "config.example.json").read_text(encoding="utf-8")
    )
    c.update(data=str(tmp_path / "index"), repositories=spec, synthetic_fixture=True)
    return c


def test_one_catalog_exact_lambda_spans_and_context(tmp_path):
    bundle, spec = captured(tmp_path)
    nodes, files = normalize(bundle, [])
    texts = inputs(nodes, files)
    lambdas = [n for n in nodes if n["subtype"] == "lambda"]
    assert len(lambdas) == 2 and lambdas[0]["node_id"] != lambdas[1]["node_id"]
    assert all(n["source"] == "lambda:target()" for n in lambdas)
    assert all(n["graph_node_id"] == n["node_id"] for n in nodes)
    for n in lambdas:
        text = next(t["text"] for t in texts if t["node_id"] == n["node_id"])
        assert "Module context: Dispatch module." in text
        assert text.endswith("lambda:target()")
    next(n for n in bundle["nodes"] if n["kind"] == "Function")["source"] = "forged source"
    with pytest.raises(ValueError, match="fingerprint"):
        validate(bundle)


def test_new_catalog_rebuild_no_paid_calls_and_manifest_incompatibility(tmp_path):
    bundle, spec = captured(tmp_path)
    c = configuration(tmp_path, spec)
    with patch("urllib.request.urlopen", side_effect=AssertionError("Network forbidden")):
        first = build(c, bundle, [], "fixture-1")
        second = build(c, bundle, [], "fixture-2")
    assert first["embedding_run"]["new_vectors"] > 0
    assert second["embedding_run"]["new_vectors"] == 0
    assert first["inputs"] == second["inputs"]
    c["hnsw"]["connectivity"] += 1
    with pytest.raises(ToolError, match="incompatible"):
        Query(c).snapshot("fixture-1")


def test_original_voyage_client_mock_http_payload_batch_cache(tmp_path, monkeypatch):
    bundle, spec = captured(tmp_path)
    c = configuration(tmp_path, spec)
    calls = []
    monkeypatch.setenv("VOYAGE_API_KEY", "SYNTHETIC-TEST-PLACEHOLDER")
    c["embedding"]["min_interval_seconds"] = 0

    def response(request, timeout):
        data = json.loads(request.data)
        calls.append(data)
        return BytesIO(
            json.dumps(
                dict(
                    model=data["model"],
                    usage=dict(total_tokens=7),
                    data=[
                        dict(
                            index=i,
                            embedding=synthetic_vector(text, data["output_dimension"]).tolist(),
                        )
                        for i, text in enumerate(data["input"])
                    ],
                )
            ).encode()
        )

    with (
        patch("urllib.request.urlopen", side_effect=response),
        patch.object(Embeddings, "call", ORIGINAL_VOYAGE_CALL),
    ):
        cache = Embeddings(c)
        try:
            a = cache.get_many(["first", "second"])
            b = cache.get_many(["first"])
            assert len(a) == 2 and len(b) == 1 and cache.requests == 1 and cache.hits == 1
            assert cache.lookup("changed", "document") is None
            cache.e = dict(cache.e, model="SYNTHETIC-OTHER")
            assert cache.lookup("first", "document") is None
        finally:
            cache.close()
    assert len(calls) == 1 and calls[0]["truncation"] is False
    assert calls[0]["input_type"] == "document" and calls[0]["output_dimension"] == 1024


def test_candidate_filters_precede_topk_and_partition_selection(tmp_path):
    bundle, spec = captured(tmp_path)
    a = Path(spec[0]["path"])
    (a / "test_hot.py").write_text(
        'def hidden():\n    """Dispatch dispatch dispatch dispatch."""\n    pass\n',
        encoding="utf-8",
    )
    spec[0]["files"].append("test_hot.py")
    second = tmp_path / "second"
    second.mkdir()
    _, other = captured(second)
    other[0]["name"] = "other"
    spec += other
    bundle = build_snapshot(spec, mode="default")
    c = configuration(tmp_path, spec)
    build(c, bundle, [], "filtered")
    from lct.common import atomic

    atomic(Path(c["data"]) / "current.json", dict(version="filtered"))
    result = Query(c).search_code(
        "Dispatch", mode="bm25", level="function", repositories=["fixture"], candidates=1
    )
    assert result["results"] and result["results"][0]["path"] == "sample.py"
    assert result["results"][0]["repository"] == "fixture"
    assert not result["results"][0]["is_test"]
    included = Query(c).search_code(
        "Dispatch",
        mode="bm25",
        level="function",
        repositories=["fixture"],
        include_tests=True,
        candidates=50,
    )
    assert any(r["is_test"] for r in included["results"])
