"""One offline build and bounded real Neo4j acceptance; skip without a service URI."""

import json
import os
import subprocess
import sys
from collections import Counter

import pytest

from lct.common import ToolError
from lct.neo4j_graph import Neo4jGraph, load_snapshot
from tests.test_small_graph_mcp_e2e import ROOT, prepare


def test_scope_and_missing_version(tmp_path):
    from lct.neo4j_graph import _scope

    with pytest.raises(ToolError, match="namespace"):
        _scope("", "v")
    with pytest.raises(ToolError, match="version"):
        load_snapshot({"data": str(tmp_path)}, "not-present")


def test_neo4j_small_graph(tmp_path, monkeypatch):
    uri = os.getenv("LCT_TEST_NEO4J_URI")
    if not uri:
        pytest.skip("LCT_TEST_NEO4J_URI not set; real Neo4j service required")
    pytest.importorskip("neo4j")
    _, config_path, env = prepare(tmp_path)
    built = subprocess.run(
        [sys.executable, str(ROOT / "local_code_tools.py"), "--config", str(config_path),
         "build", "--offline", "--lexical-only"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90,
    )
    assert built.returncode == 0, built.stderr
    m = json.loads(built.stdout)
    c = json.loads(config_path.read_text())
    snapshot = load_snapshot(c, m["version"])
    nodes, edges = snapshot["nodes"], snapshot["edges"]
    assert len(nodes) == 17 and len(edges) == 30
    assert Counter(n["kind"] for n in nodes)["function"] > 0
    namespace = "test-" + tmp_path.name
    version = m["version"]
    password = os.getenv("LCT_TEST_NEO4J_PASSWORD", "synthetic-lct-batch1-only")
    user = os.getenv("LCT_TEST_NEO4J_USER", "neo4j")
    database = os.getenv("LCT_TEST_NEO4J_DATABASE", "neo4j")
    with Neo4jGraph(uri, user, password, database) as graph:
        with pytest.raises(ToolError, match="missing"):
            graph.snapshot_info(namespace, "wrong-version")
        with pytest.raises(ToolError, match="missing"):
            graph.get_nodes(namespace, "wrong-version", [nodes[0]["node_id"]])
        info = graph.import_snapshot(namespace, version, snapshot)
        assert info["nodes"] == 17 and info["edges"] == 30
        assert graph.snapshot_info(namespace, version)["graph"] == m["graph"]
        assert graph.snapshot_info(namespace, version)["source"]["repositories"] == m["repositories"]
        assert graph.list_nodes(namespace, version, limit=500) == dict(nodes=nodes, has_more=False)
        assert graph.list_nodes(namespace, version, limit=1)["has_more"] is True
        assert graph.get_nodes(namespace, version, [n["node_id"] for n in nodes]) == nodes
        for kind in ("module", "class", "function"):
            assert graph.list_nodes(namespace, version, kind=kind, limit=500)["nodes"] == [
                n for n in nodes if n["kind"] == kind
            ]
        assert graph.list_nodes(namespace, version, repository="small-graph-mcp",
                                limit=500)["nodes"] == nodes
        for n in nodes:
            for direction in ("in", "out", "both"):
                for kind in ("CALLS", "CONTAINS", "INHERITS", "REFERENCES", "IMPORTS",
                             "WRAPS", "CONTEXT_ENTERS"):
                    expected = [e for e in edges if e["kind"] == kind and (
                        e.get("source") == n["node_id"] if direction == "out" else
                        e.get("target") == n["node_id"] if direction == "in" else
                        n["node_id"] in (e.get("source"), e.get("target"))
                    )]
                    assert graph.get_relations(namespace, version, [n["node_id"]],
                                               [kind], direction, 500) == dict(
                                                   edges=expected, has_more=False)
        assert any(e.get("unknown_origin") is True and e.get("complete") is False
                   for e in edges)
        assert any(s.get("unknown_origin") is True and s.get("complete") is False
                   for s in graph.snapshot_info(namespace, version)["graph"]["sites"])
        assert graph.import_snapshot(namespace, version, snapshot)["already_present"]
        with graph.driver.session(database=database) as session:
            counts = session.run(
                "MATCH (s:LCTSnapshot {namespace:$ns, version:$v}) "
                "OPTIONAL MATCH (n:LCTNode {namespace:$ns, version:$v}) "
                "RETURN count(DISTINCT s) AS snapshots, count(DISTINCT n) AS nodes",
                ns=namespace, v=version,
            ).single()
            assert (counts["snapshots"], counts["nodes"]) == (1, 17)
            assert session.run("MATCH (e:LCTEdge {namespace:$ns, version:$v}) "
                               "RETURN count(e) AS c", ns=namespace, v=version).single()["c"] == 30
        changed = dict(snapshot, graph={**snapshot["graph"], "changed": True})
        from lct.common import canonical, digest
        changed["fingerprint"] = digest(canonical(dict(nodes=nodes, edges=edges,
                                                       graph=changed["graph"],
                                                       source=snapshot["source"])))
        with pytest.raises(ToolError, match="different content"):
            graph.import_snapshot(namespace, version, changed)
        assert graph.import_snapshot(namespace + "-other", version, changed)["nodes"] == 17
        assert graph.import_snapshot(namespace, version + "-other",
                                     dict(snapshot, version=version + "-other"))["edges"] == 30
        assert graph.snapshot_info(namespace, version)["graph"] == snapshot["graph"]

        # Inject a failure inside the write transaction, after at least one CREATE.
        original = graph.driver

        class FailedTx:
            def __init__(self, tx):
                self.tx = tx

            def __enter__(self):
                self.tx.__enter__()
                return self

            def __exit__(self, *exc):
                return self.tx.__exit__(*exc)

            def run(self, query, **params):
                if "CREATE (e:LCTEdge" in query:
                    raise RuntimeError("injected mid-transaction failure")
                return self.tx.run(query, **params)

        class FailedSession:
            def __init__(self, session):
                self.session = session

            def __enter__(self):
                self.session.__enter__()
                return self

            def __exit__(self, *exc):
                return self.session.__exit__(*exc)

            def run(self, *args, **kwargs):
                return self.session.run(*args, **kwargs)

            def begin_transaction(self, **kwargs):
                return FailedTx(self.session.begin_transaction(**kwargs))

        class FailedDriver:
            def session(self, **kwargs):
                return FailedSession(original.session(**kwargs))

        graph.driver = FailedDriver()
        with pytest.raises(RuntimeError, match="injected"):
            graph.import_snapshot(namespace + "-failed", version, snapshot)
        graph.driver = original
        with pytest.raises(ToolError, match="missing"):
            graph.snapshot_info(namespace + "-failed", version)
        with original.session(database=database) as session:
            assert session.run(
                "MATCH (n {namespace:$ns, version:$v}) RETURN count(n) AS c",
                ns=namespace + "-failed", v=version,
            ).single()["c"] == 0
