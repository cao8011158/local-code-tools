"""Mixed dictionary and ordinary-function component admission controls."""

import json
import sqlite3

import pytest

import lct.extract as extraction
from lct.graph import Graph
from lct.simple_python import CERTIFICATE, certify
from lct.storage import build, current, manifest
from tests.synthetic_support import initialize

A = "def first(): pass\ndef second(): pass\nregistry={'go':first}\n"
B = "from a import registry\ndef run(): registry['go']()\n"
C = "from b import run\ndef call(): run()\n"
D = "from c import call\ndef outer(): call()\n"


def fixture(tmp_path, *, noise=0, b=B, c=C):
    config, repo = initialize(tmp_path / "fixture")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    for name, source in (("a", A), ("b", b), ("c", c), ("d", D)):
        (repo / f"src/{name}.py").write_text(source)
    for i in range(noise):
        (repo / f"src/noise_{i}.py").write_text(f"def idle_{i}(): pass\n")
    (repo / "src/producer_only.py").write_text(
        "def unrelated(): pass\nother={'go':unrelated}\n")
    return config, repo


def evidence(config, version):
    folder, _ = manifest(config, version)
    result = {}
    for file, tables in (("catalog.sqlite", ("nodes", "edges")),
                         ("graph-sites.sqlite", ("sites", "import_requests",
                                                  "import_dependencies", "query_observations",
                                                  "value_nodes", "value_edges", "value_reads"))):
        with sqlite3.connect(folder / file) as db:
            for table in tables:
                if table in {"value_edges", "value_reads"}:
                    result[table] = sorted(tuple(row) for row in db.execute(f"select * from {table}"))
                else:
                    result[table] = sorted(json.dumps(json.loads(raw), sort_keys=True)
                                           for (raw,) in db.execute(f"select data from {table}"))
    return result


def oracle(config, tmp_path, updated, name):
    separate = dict(config, data=str(tmp_path / name))
    fresh = build(separate, offline=True, lexical_only=True)
    assert evidence(config, updated["version"]) == evidence(separate, fresh["version"])


@pytest.mark.parametrize("noise", [0, 20])
def test_mixed_transitive_callers_rebuild_only_component(tmp_path, monkeypatch, noise):
    config, repo = fixture(tmp_path, noise=noise)
    first = build(config, offline=True, lexical_only=True)
    assert first["simple_python_certificate"] == CERTIFICATE
    old = evidence(config, first["version"])
    visited = []
    actual = extraction.python_nodes

    def count(file):
        visited.append(file["path"])
        return actual(file)

    monkeypatch.setattr(extraction, "python_nodes", count)
    (repo / "src/a.py").write_text(A.replace("'go':first", "'go':second"))
    changed = build(config, offline=True, lexical_only=True)
    assert changed["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    assert sorted(visited) == ["src/a.py"]
    assert evidence(config, first["version"]) == old
    oracle(config, tmp_path, changed, "oracle-target")


def test_missing_key_and_failed_publication_preserve_old_view(tmp_path):
    config, repo = fixture(tmp_path, b=B.replace("['go']", "['new']"))
    first = build(config, offline=True, lexical_only=True)
    old = evidence(config, first["version"])
    (repo / "src/a.py").write_text(A + "registry['new']=second\n")
    from lct.common import ToolError

    with pytest.raises(ToolError, match="Injected interruption"):
        build(config, offline=True, lexical_only=True, fail_at="before_publish")
    assert current(config) == first["version"]
    assert evidence(config, first["version"]) == old
    changed = build(config, offline=True, lexical_only=True)
    assert changed["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
    oracle(config, tmp_path, changed, "oracle-new-key")


def test_missing_export_and_unsafe_provider_fail_closed(tmp_path):
    config, repo = fixture(tmp_path, c="from b import absent\ndef call(): absent()\n")
    missing = build(config, offline=True, lexical_only=True)
    assert missing["simple_python_certificate"] is None
    (repo / "src/c.py").write_text(C)
    baseline = build(config, offline=True, lexical_only=True)
    assert baseline["simple_python_certificate"] == CERTIFICATE
    (repo / "src/a.py").write_text(A + "def expose(): return registry\n")
    unsupported = build(config, offline=True, lexical_only=True)
    assert unsupported["incremental"]["analysis_scope"]["mode"] == "incremental-owners"


def test_missing_target_ast_cannot_be_certified(tmp_path):
    config, repo = fixture(tmp_path)
    files = []
    from lct.common import digest

    for name in "abcd":
        path = f"src/{name}.py"
        content = (repo / path).read_text()
        files.append(dict(repository="synthetic-review", path=path, text=content,
                          is_test=False, sha256=digest(content)))
    nodes, asts = extraction.extract(files)
    modules = [n for n in nodes if n["kind"] == "module"]
    graph = Graph(modules, asts, [dict(name="synthetic-review", path=str(repo), head="captured")])
    assert certify(files, asts, graph=graph) == CERTIFICATE
    target = next(n["node_id"] for n in modules if n["path"] == "src/b.py")
    assert certify(files, {k: v for k, v in asts.items() if k != target}, graph=graph) is None


@pytest.mark.parametrize("suffix", [
    "registry={'go':second}\n",
    "registry[dynamic_key]=second\n",
    "if condition:\n    registry['go']=second\n",
])
def test_mixed_context_does_not_override_invalid_provider(tmp_path, suffix):
    config, repo = fixture(tmp_path)
    build(config, offline=True, lexical_only=True)
    (repo / "src/a.py").write_text(A + suffix)
    result = build(config, offline=True, lexical_only=True)
    assert result["incremental"]["analysis_scope"]["mode"] in {
        "full-graph", "incremental-owners"}
    oracle(config, tmp_path, result, "oracle-invalid-provider")
