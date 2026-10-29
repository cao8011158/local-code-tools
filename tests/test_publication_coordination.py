"""Fault boundaries for the terminal coordinator; no Neo4j or embedding calls."""

import json

import pytest

from lct import publication
from lct.common import ToolError
from lct.query import Query
from lct.storage import build, current, manifest, recover
from tests.synthetic_support import forbid_provider, initialize, seed_cache


class Graph:
    def __init__(self, uri, user, password, database):
        self.marker = None
        self.fail_import = False
        self.fail_marker = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def import_snapshot(self, namespace, version, snapshot):
        self.marker = dict(namespace=namespace, version=version,
                           fingerprint=snapshot["fingerprint"],
                           projection_schema=publication.PROJECTION_SCHEMA,
                           nodes=1, edges=1, native_edges=1)
        if self.fail_import:
            raise OSError("lost graph acknowledgement")

    def snapshot_summary(self, namespace, version):
        if self.fail_marker or self.marker is None:
            raise ToolError("graph unavailable")
        return self.marker


@pytest.fixture
def staged(tmp_path, monkeypatch):
    data = tmp_path / "data"
    folder = data / "versions" / "new"
    folder.mkdir(parents=True)
    state = {"current": None}
    graph = Graph("bolt://graph", "u", "p", "neo4j")
    m = {"version": "new"}
    snapshot = dict(version="new", fingerprint="a" * 64, nodes=[{}], edges=[{}])
    monkeypatch.setattr(publication, "current", lambda c: state["current"])
    monkeypatch.setattr(publication, "load_snapshot", lambda c, v: snapshot)
    monkeypatch.setattr(publication, "validate_folder", lambda folder, m: None)
    monkeypatch.setattr(publication, "manifest", lambda c, v=None: (folder, m))
    return dict(c={"data": str(data)}, folder=folder, state=state, graph=graph, m=m)


def test_candidate_binds_only_after_verified_graph(staged):
    s = staged
    hook = publication._candidate(s["c"], s["graph"], "bolt://graph", "neo4j", "space", {})
    s["graph"].fail_marker = True
    with pytest.raises(ToolError):
        hook("new", s["folder"], s["m"], None)
    assert "publication" not in s["m"]
    assert not (s["folder"] / "summary.json").exists()
    s["graph"].fail_marker = False
    s["graph"].fail_import = True
    hook("new", s["folder"], s["m"], None)
    assert json.loads((s["folder"] / "summary.json").read_text())["publication"]["version"] == "new"


def test_lost_pointer_ack_is_reconciled_only_if_committed(staged, monkeypatch):
    s = staged

    def fake_build(c, **kwargs):
        kwargs["on_candidate"]("new", s["folder"], s["m"], None)
        s["state"]["current"] = "new"
        raise OSError("lost pointer acknowledgement")

    monkeypatch.setattr(publication, "build", fake_build)
    result = publication.coordinated_update(s["c"], "space", "neo4j", uri="bolt://graph",
        user="u", password="p", graph_factory=lambda *args: s["graph"])
    assert result["publication"]["version"] == "new"


def test_uncommitted_pointer_failure_keeps_old(staged, monkeypatch):
    s = staged

    def fake_build(c, **kwargs):
        kwargs["on_candidate"]("new", s["folder"], s["m"], None)
        raise OSError("pointer not committed")

    monkeypatch.setattr(publication, "build", fake_build)
    with pytest.raises(OSError, match="pointer not committed"):
        publication.coordinated_update(s["c"], "space", "neo4j", uri="bolt://graph",
            user="u", password="p", graph_factory=lambda *args: s["graph"])
    assert s["state"]["current"] is None


def test_resolver_requires_actual_matching_marker(staged, monkeypatch):
    s = staged
    hook = publication._candidate(s["c"], s["graph"], "bolt://graph", "neo4j", "space", {})
    hook("new", s["folder"], s["m"], None)
    s["state"]["current"] = "new"
    assert publication.resolve_current(s["c"], user="u", password="p",
        graph_factory=lambda *args: s["graph"])["version"] == "new"
    s["graph"].marker["fingerprint"] = "b" * 64
    with pytest.raises(ToolError, match="differs"):
        publication.resolve_current(s["c"], user="u", password="p",
            graph_factory=lambda *args: s["graph"])


def test_search_pins_first_page_and_rejects_conflicting_cursor(monkeypatch):
    query = Query({})
    seen = []

    def stop_at_snapshot(version):
        seen.append(version)
        raise RuntimeError("snapshot selected")

    monkeypatch.setattr(query, "snapshot", stop_at_snapshot)
    with pytest.raises(RuntimeError, match="snapshot selected"):
        query.search_code("lookup", mode="bm25", version="v1")
    with pytest.raises(RuntimeError, match="snapshot selected"):
        query.search_docs("lookup", version="v2")
    assert seen == ["v1", "v2"]
    monkeypatch.setattr(query, "decode_cursor", lambda *args: {"version": "v0"})
    with pytest.raises(ToolError, match="differs"):
        query.search_code("lookup", mode="bm25", cursor="cursor", version="v1")


def test_offline_small_candidate_publishes_after_graph_and_blocks_bypass(tmp_path, monkeypatch):
    c, _ = initialize(tmp_path / "fixture")
    seed_cache(c)

    class CandidateGraph(Graph):
        def import_snapshot(self, namespace, version, snapshot):
            self.marker = dict(namespace=namespace, version=version,
                fingerprint=snapshot["fingerprint"],
                projection_schema=publication.PROJECTION_SCHEMA,
                nodes=len(snapshot["nodes"]), edges=len(snapshot["edges"]),
                native_edges=len(snapshot["edges"]))

    graph = CandidateGraph("bolt://graph", "u", "p", "neo4j")
    with forbid_provider():
        m = publication.coordinated_update(c, "space", "neo4j", uri="bolt://graph",
            user="u", password="p", offline=True, graph_factory=lambda *args: graph)
    assert current(c) == m["version"]
    assert manifest(c)[1]["publication"] == m["publication"]
    assert Query(c).search_code("weight", mode="bm25", version=m["version"])["version"] == m["version"]
    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected build must not scan or parse source")

    monkeypatch.setattr("lct.storage.inventory", forbidden)
    monkeypatch.setattr("lct.storage.extract", forbidden)
    monkeypatch.setattr("lct.storage.Graph", forbidden)
    with pytest.raises(ToolError, match="update-coordinated"):
        build(c, offline=True)
    with pytest.raises(ToolError, match="coordinated recovery"):
        recover(c, m["version"])
