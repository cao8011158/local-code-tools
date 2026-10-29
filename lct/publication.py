"""Terminal-only coordination of an index version and its Neo4j projection."""

import os
from pathlib import Path

from .common import ToolError, atomic, load, lock
from .neo4j_graph import PROJECTION_SCHEMA, Neo4jGraph, load_snapshot
from .storage import build, current, manifest, validate_folder


def _connection(uri=None, user=None, password=None, database=None):
    uri = uri or os.getenv("LCT_NEO4J_URI")
    user = user or os.getenv("LCT_NEO4J_USER")
    password = password or os.getenv("LCT_NEO4J_PASSWORD")
    if not all((uri, user, password, database)):
        raise ToolError("Explicit Neo4j connection and database required")
    return uri, user, password, database


def _verify(graph, binding):
    row = graph.snapshot_summary(binding["namespace"], binding["version"])
    if (row.get("fingerprint") != binding["fingerprint"] or
        row.get("projection_schema") != PROJECTION_SCHEMA or
        row.get("nodes") != binding["nodes"] or
        row.get("edges") != binding["edges"] or
        row.get("native_edges") != binding["edges"]):
        raise ToolError("Neo4j projection differs from bound index version")


def _bind(folder, m, binding):
    if m.get("publication") not in (None, binding):
        raise ToolError("Existing publication binding differs")
    if m.get("publication") == binding:
        return
    m["publication"] = binding
    atomic(folder / "manifest.json", m)
    atomic(folder / "summary.json", m)
    validate_folder(folder, m)


def _candidate(c, graph, uri, database, namespace, state):
    def prepare(version, folder, m, previous):
        state["version"] = version
        if current(c) != previous:
            raise ToolError("Publication predecessor changed")
        snapshot = load_snapshot(c, version)
        binding = dict(uri=uri, database=database, namespace=namespace,
                       version=version, fingerprint=snapshot["fingerprint"],
                       projection_schema=PROJECTION_SCHEMA, nodes=len(snapshot["nodes"]),
                       edges=len(snapshot["edges"]))
        if m.get("publication") not in (None, binding):
            raise ToolError("Existing publication binding differs")
        try:
            graph.import_snapshot(namespace, version, snapshot)
        except Exception:
            # A committed final marker can outlive a lost driver acknowledgement.
            _verify(graph, binding)
        _verify(graph, binding)  # Also resolves a lost import acknowledgement.
        _bind(folder, m, binding)
        if current(c) != previous:
            raise ToolError("Publication predecessor changed")
        state["binding"] = binding
    return prepare


def coordinated_update(c, namespace, database, *, uri=None, user=None, password=None,
                       offline=False, graph_factory=Neo4jGraph):
    """Prepare a new immutable graph scope before build commits its pointer.

    The build owns update.lock throughout the callback and pointer replacement. A
    failed candidate may leave an unreferenced complete graph, never a changed old scope.
    """
    uri, user, password, database = _connection(uri, user, password, database)
    state = {}
    with graph_factory(uri, user, password, database) as graph:
        previous = current(c)
        if previous:
            _, old = manifest(c, previous)
            prior = old.get("publication")
            if not prior:
                raise ToolError("Bind the existing current version before coordinated update")
            if prior["uri"] != uri or prior["database"] != database:
                raise ToolError("Prior publication uses a different Neo4j endpoint")
            _verify(graph, prior)
        try:
            return build(c, offline=offline,
                         on_candidate=_candidate(c, graph, uri, database, namespace, state))
        except Exception:
            version = state.get("version")
            # os.replace can succeed while an acknowledgement or later metadata write fails.
            if version and current(c) == version and state.get("binding"):
                folder, m = manifest(c, version)
                if m.get("publication") == state["binding"]:
                    _verify(graph, state["binding"])
                    return m
            raise


def bind_current(c, namespace, database, *, uri=None, user=None, password=None,
                 graph_factory=Neo4jGraph):
    """Explicitly prepare a legacy current graph before the first coordinated update."""
    uri, user, password, database = _connection(uri, user, password, database)
    with lock(Path(c["data"]) / "update.lock"):
        version = current(c)
        folder, m = manifest(c, version)
        validate_folder(folder, m)
        snapshot = load_snapshot(c, version)
        binding = dict(uri=uri, database=database, namespace=namespace, version=version,
                       fingerprint=snapshot["fingerprint"], projection_schema=PROJECTION_SCHEMA,
                       nodes=len(snapshot["nodes"]), edges=len(snapshot["edges"]))
        if m.get("publication") not in (None, binding):
            raise ToolError("Existing publication binding differs")
        with graph_factory(uri, user, password, database) as graph:
            try:
                graph.import_snapshot(namespace, version, snapshot)
            except Exception:
                _verify(graph, binding)
            _verify(graph, binding)
        _bind(folder, m, binding)
        return binding


def resolve_current(c, *, uri=None, user=None, password=None,
                    graph_factory=Neo4jGraph):
    """Pin one published descriptor and fail closed if its graph is unavailable."""
    folder, m = manifest(c)
    binding = m.get("publication")
    if not isinstance(binding, dict) or binding.get("version") != m["version"]:
        raise ToolError("Current index lacks a coordinated graph binding")
    if uri is not None and uri != binding["uri"]:
        raise ToolError("Neo4j endpoint differs from publication binding")
    uri, user, password, _ = _connection(binding["uri"], user, password,
                                          binding["database"])
    with graph_factory(uri, user, password, binding["database"]) as graph:
        _verify(graph, binding)
    # Prevent a racing activation from causing a caller to mistake this for current.
    if current(c) != m["version"] or load(folder / "summary.json").get("publication") != binding:
        raise ToolError("Current publication changed during resolution; retry")
    return binding
