"""Consistent candidate snapshots, incremental SQLite maintenance and atomic publication."""

import hashlib
import json
import shutil
import sqlite3
import stat
import sys
import time
import uuid
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

import jedi
import numpy as np
from usearch.index import Index

from . import python_analysis
from .common import (
    FORMAT,
    SCHEMA,
    TEMPLATE,
    TOKENIZER,
    VERSION,
    ToolError,
    atomic,
    canonical,
    digest,
    identity,
    inventory,
    load,
    lock,
    now,
    program_hash,
)
from .dense_update import write_partitions
from .embedding import Embeddings, bound
from .extract import embedding_texts, extract
from .graph import Graph
from .lexical import add_document
from .python_analysis import Atom, Result
from .simple_python import certify
from .value_flow import LIMIT as VALUE_FLOW_LIMIT

DDL = """
create table if not exists nodes(node_id text primary key, repository text, path text, kind text, data text, search_hash text);
create index if not exists node_scope on nodes(repository,kind,path);
create table if not exists files(repository text,path text,sha256 text,text text,primary key(repository,path));
create table if not exists edges(edge_id text primary key,source text,target text,kind text,status text,data text);
create index if not exists edge_source on edges(source,kind);
create index if not exists edge_target on edges(target,kind);
create table if not exists postings(term text,node_id text,tf integer,primary key(term,node_id));
create index if not exists posting_node on postings(node_id);
create table if not exists lengths(node_id text primary key,repository text,kind text,length integer);
create table if not exists terms(term text primary key,df integer);
"""
GRAPH_SITES = "graph-sites.sqlite"
SOURCE_FILES = "source-files.json"
QUERY_RUNTIME = {"python": sys.version, "implementation": sys.implementation.cache_tag,
                 "jedi": jedi.__version__}


def current(c):
    """Read an atomic version pointer; an incomplete candidate is never considered current."""
    p = Path(c["data"]) / "current.json"
    return load(p)["version"] if p.exists() else None


def manifest(c, version=None, compatible=True):
    """Validate schema/config/build compatibility before allowing queries."""
    version = version or current(c)
    if not version or "/" in version or "\\" in version or ".." in version:
        raise ToolError("Index missing or invalid version")
    folder = Path(c["data"]) / "versions" / version
    if not (folder / "manifest.json").exists():
        raise ToolError("Index version expired or incomplete")
    if not (folder / "summary.json").exists():
        raise ToolError("Legacy index metadata requires explicit migrate-metadata")
    m = load(folder / "summary.json")
    if m.get("metadata_layout") != 2:
        raise ToolError("Legacy index metadata requires explicit migrate-metadata")
    if m.get("state") != "complete":
        raise ToolError("Index incomplete")
    if compatible and (
        m.get("schema") != SCHEMA
        or m.get("format") != FORMAT
        or m.get("template") != TEMPLATE
        or m.get("tokenizer") != TOKENIZER
        or m.get("config_hash") != identity(c)
        or m.get("program_hash") != program_hash()
    ):
        raise ToolError("Index incompatible with program/config; rebuild before querying")
    return folder, m


def required_artifacts(specs, graph_detail=False):
    """Names produced by this build, independent of incidental candidate files."""
    names = {"catalog.sqlite"}
    if graph_detail:
        names.update((GRAPH_SITES, SOURCE_FILES))
    for part, spec in enumerate(specs):
        stem = f"partition-{part}"
        if spec.get("stem") != stem:
            raise ToolError("Invalid index partition artifact")
        names.update(stem + ext for ext in (".npy", ".usearch", ".json"))
    return names


def artifact_file(folder, rel):
    """Locate a required regular artifact without following a symlink."""
    p = folder / rel
    try:
        info = p.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ToolError("Index artifact is not a regular file: " + rel)
        return p, info.st_size
    except OSError as exc:
        raise ToolError("Index artifact unavailable: " + rel) from exc


def hash_artifact(folder, rel):
    """Hash and count the same stream without retaining the artifact in memory."""
    p, _ = artifact_file(folder, rel)
    checksum = hashlib.sha256()
    size = 0
    try:
        with p.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise ToolError("Index artifact unavailable: " + rel) from exc
    return checksum.hexdigest(), size


def check_catalog_sidecars(folder, graph=False):
    # Opening SQLite for validation may replay a hot journal; refuse it first.
    for base in (("catalog.sqlite", GRAPH_SITES) if graph else ("catalog.sqlite",)):
        for suffix in ("-journal", "-wal"):
            p = folder / (base + suffix)
            try:
                if p.lstat().st_size:
                    raise ToolError("Catalog has a nonempty SQLite sidecar: " + p.name)
            except FileNotFoundError:
                pass


def validate_folder(folder, m, full=True):
    """Validate every artifact checksum and SQLite integrity before publish or restore."""
    if m.get("metadata_layout") == 2 and m.get("graph_detail") != GRAPH_SITES:
        raise ToolError("Graph evidence layout mismatch")
    if set(m["artifacts"]) != required_artifacts(m["partitions"], m.get("graph_detail") == GRAPH_SITES):
        raise ToolError("Index artifact membership mismatch")
    check_catalog_sidecars(folder, graph=m.get("graph_detail") == GRAPH_SITES)
    for rel, expected in m["artifacts"].items():
        p, size = artifact_file(folder, rel)
        if (full and digest(p.read_bytes()) != expected) or (
            not full and rel in m.get("artifact_sizes", {})
            and size != m["artifact_sizes"][rel]
        ):
            raise ToolError("Index artifact checksum mismatch: " + rel)
    if full:
        with closing(sqlite3.connect(folder / "catalog.sqlite")) as db:
            if db.execute("pragma integrity_check").fetchone()[0] != "ok":
                raise ToolError("Catalog integrity check failed")
            if db.execute("select count(*) from nodes").fetchone()[0] != m["node_count"]:
                raise ToolError("Catalog node count mismatch")
        if m.get("graph_detail") == GRAPH_SITES:
            with closing(sqlite3.connect((folder / GRAPH_SITES).as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
                if db.execute("pragma integrity_check").fetchone()[0] != "ok":
                    raise ToolError("Graph evidence integrity check failed")
                if db.execute("select count(*) from sites").fetchone()[0] != m["graph"]["call_sites"]:
                    raise ToolError("Graph evidence site count mismatch")


def graph_detail(folder, m):
    """Read complete persisted graph evidence only for an explicit detail consumer."""
    if m.get("graph_detail") != GRAPH_SITES:
        if "sites" not in m["graph"]:
            raise ToolError("Graph evidence missing")
        return m["graph"]  # Pre-migration snapshot.
    checksum, size = hash_artifact(folder, GRAPH_SITES)
    if checksum != m["artifacts"][GRAPH_SITES] or size != m["artifact_sizes"][GRAPH_SITES]:
        raise ToolError("Graph evidence checksum mismatch")
    with closing(sqlite3.connect((folder / GRAPH_SITES).as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        sites = [json.loads(row[0]) for row in db.execute("select data from sites order by ordinal")]
    if len(sites) != m["graph"]["call_sites"]:
        raise ToolError("Graph evidence site count mismatch")
    return dict(m["graph"], sites=sites)


def graph_sites(folder, m, offset=0, limit=100, max_bytes=100000):
    """Bounded ordered evidence page; callers can continue from next_offset."""
    if type(offset) is not int or type(limit) is not int or not 0 <= offset or not 1 <= limit <= 500:
        raise ToolError("Invalid graph evidence page")
    if m.get("graph_detail") != GRAPH_SITES:
        raise ToolError("Legacy index metadata requires explicit migrate-metadata")
    total = m["graph"]["call_sites"]
    rows = []
    envelope = dict(sites=[], total=total, version=m["version"], next_offset=offset + limit)
    used = max(len(canonical(envelope).encode("utf-8")),
               len(canonical(dict(envelope, next_offset=None)).encode("utf-8")))
    if used > max_bytes:
        raise ToolError("Graph evidence response metadata exceeds max_bytes")
    with closing(sqlite3.connect((folder / GRAPH_SITES).as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        for (raw,) in db.execute("select data from sites where ordinal>=? order by ordinal limit ?",
                                 (offset, limit)):
            site = json.loads(raw)
            size = len(raw.encode("utf-8")) + (1 if rows else 0)
            if used + size > max_bytes:
                if not rows:
                    raise ToolError("Graph evidence site exceeds max_bytes; increase limit")
                break
            rows.append(site)
            used += size
    return dict(sites=rows, next_offset=offset + len(rows) if offset + len(rows) < total else None,
                total=total, version=m["version"])


def source_files(folder, m):
    """Reconstruct complete source revision evidence for an explicit full consumer."""
    if m.get("graph_detail") != GRAPH_SITES:
        return m["files"]
    checksum, size = hash_artifact(folder, SOURCE_FILES)
    if checksum != m["artifacts"][SOURCE_FILES] or size != m["artifact_sizes"][SOURCE_FILES]:
        raise ToolError("Source evidence checksum mismatch")
    files = load(folder / SOURCE_FILES)
    if not isinstance(files, list) or len(files) != m["file_count"]:
        raise ToolError("Source evidence file count mismatch")
    return files


def split_graph(folder, m, query_observations=(), import_dependencies=(),
                import_requests=None, nodes=(), edges=(), certified_files=(),
                analysis_reads=None, analysis_watches=None,
                analysis_dependency_truncated=False, value_flow=None):
    """Prepare immutable site evidence and a compact manifest before publication."""
    graph = m["graph"]
    sites = graph["sites"]
    if len(sites) != graph["call_sites"]:
        raise ToolError("Graph evidence site count mismatch")
    if (analysis_reads is not None and analysis_watches is not None and
            len(analysis_reads) + len(analysis_watches) > python_analysis.ANALYSIS_DEPENDENCY_LIMIT):
        raise ToolError("Analysis dependency record budget exceeded")
    db = sqlite3.connect(folder / GRAPH_SITES)
    try:
        db.execute("create table sites(ordinal integer primary key, data text not null)")
        db.executemany("insert into sites values(?,?)", ((i, canonical(site)) for i, site in enumerate(sites)))
        db.execute("create table node_order(ordinal integer primary key, node_id text not null unique)")
        db.executemany("insert into node_order values(?,?)", (
            (i, node["node_id"]) for i, node in enumerate(nodes)))
        db.execute("create table simple_python_certificates(repository text not null, path text not null, sha256 text not null, primary key(repository,path))")
        db.executemany("insert into simple_python_certificates values(?,?,?)", (
            (f["repository"], f["path"], f["sha256"]) for f in certified_files
            if f["path"].endswith(".py")))
        db.execute("create table query_observations(key text primary key, data text not null, checksum text not null)")
        db.executemany("insert into query_observations values(?,?,?)", (
            (canonical(record["key"]), canonical(record), digest(canonical(record)))
            for record in query_observations
        ))
        db.execute("create table import_dependencies(ordinal integer primary key, source_module text not null, namespace_module text not null, requested_name text not null, data text not null)")
        db.execute("create index import_dependency_namespace on import_dependencies(namespace_module)")
        db.execute("create table import_dependency_targets(ordinal integer not null, target_module text not null, primary key(ordinal,target_module))")
        db.execute("create index import_dependency_target on import_dependency_targets(target_module)")
        for ordinal, dependency in enumerate(import_dependencies):
            db.execute("insert into import_dependencies values(?,?,?,?,?)", (
                ordinal, dependency["source_module"], dependency["namespace_module"],
                dependency["requested_name"], canonical(dependency)))
            db.executemany("insert into import_dependency_targets values(?,?)", (
                (ordinal, target) for target in dependency["target_modules"]
            ))
        db.execute("create table import_requests(ordinal integer primary key, source_repository text not null, source_path text not null, lookup_repository text not null, requested_module text not null, data text not null)")
        db.execute("create index import_request_lookup on import_requests(lookup_repository,requested_module)")
        db.execute("create index import_request_source on import_requests(source_repository,source_path)")
        db.execute("create index import_request_requester on import_requests(source_repository,requested_module,source_path)")
        # A named `from pkg import foo` may resolve to the child module
        # `pkg.foo` even when `pkg` is an implicit namespace package and the
        # child did not exist in this snapshot. Keep this prospective lookup
        # separate from the syntactic import_requests evidence.
        db.execute("create table import_lookup_keys(ordinal integer not null, source_repository text not null, source_path text not null, lookup_repository text not null, module text not null, primary key(ordinal,module))")
        db.execute("create index import_lookup_namespace on import_lookup_keys(lookup_repository,module,source_repository,source_path)")
        db.execute("create index import_lookup_requester on import_lookup_keys(source_repository,module,source_path)")
        owners = {n["node_id"]: (n["repository"], n["path"]) for n in nodes}
        modules = {n["node_id"]: (n["repository"], n["path"])
                   for n in nodes if n["kind"] == "module"}
        db.execute("create table analysis_reads(consumer_module text not null, consumer_repository text not null, consumer_path text not null, producer_module text not null, producer_repository text not null, producer_path text not null, kind text not null, primary key(consumer_module,producer_module,kind))")
        db.execute("create index analysis_read_producer on analysis_reads(producer_repository,producer_path,kind,consumer_repository,consumer_path)")
        db.execute("create table analysis_watches(consumer_module text not null, consumer_repository text not null, consumer_path text not null, kind text not null, universe text not null, primary key(consumer_module,kind,universe))")
        db.execute("create index analysis_watch_kind on analysis_watches(kind,universe,consumer_repository,consumer_path)")
        db.execute("create table value_nodes(id text primary key, kind text not null, repository text not null, path text not null, data text not null)")
        db.execute("create index value_node_file on value_nodes(repository,path,kind,id)")
        db.execute("create table value_edges(source text not null,target text not null,kind text not null,primary key(source,target,kind))")
        db.execute("create index value_edge_target on value_edges(target,kind,source)")
        db.execute("create table value_reads(entry text not null,read text not null,consumer_repository text not null,consumer_path text not null,primary key(entry,read))")
        db.execute("create index value_read_consumer on value_reads(consumer_repository,consumer_path,entry)")
        flow = value_flow or {"nodes": [], "edges": [], "reads": []}
        for record in flow["nodes"]:
            owner = modules.get(record["module"])
            if owner is None:
                raise ToolError("Value node owner unavailable")
            db.execute("insert into value_nodes values(?,?,?,?,?)", (record["id"], record["kind"],
                *owner, canonical(record)))
        db.executemany("insert into value_edges values(?,?,?)", (
            (e["source"], e["target"], e["kind"]) for e in flow["edges"]))
        db.executemany("insert into value_reads values(?,?,?,?)", (
            (r["entry"], r["read"], r["consumer_repository"], r["consumer_path"])
            for r in flow["reads"]))
        for consumer, producer, kind in analysis_reads or ():
            if consumer not in modules or producer not in modules or kind != "container-effects":
                raise ToolError("Analysis read module ownership unavailable")
            db.execute("insert into analysis_reads values(?,?,?,?,?,?,?)", (
                consumer, *modules[consumer], producer, *modules[producer], kind))
        for consumer, kind, universe in analysis_watches or ():
            if (consumer not in modules or kind != "slot-writer-universe"
                    or universe != "all-captured-python"):
                raise ToolError("Analysis watch module ownership unavailable")
            db.execute("insert into analysis_watches values(?,?,?,?,?)", (
                consumer, *modules[consumer], kind, universe))
        for ordinal, request in enumerate(import_requests or ()):
            owner = owners.get(request["source_module"])
            if owner is None or not owner[1] or owner[0] != request["source_repository"]:
                raise ToolError("Import request source ownership unavailable")
            db.execute("insert into import_requests values(?,?,?,?,?,?)", (
                ordinal, *owner, request["lookup_repository"],
                request["requested_module"] or "", canonical(request)))
            namespace = request["requested_module"]
            if namespace and all(part.isidentifier() for part in namespace.split(".")):
                keys = [namespace]
                name = request["requested_name"]
                if request["request_kind"] == "from" and isinstance(name, str) and name.isidentifier():
                    keys.append(namespace + "." + name)
                db.executemany("insert into import_lookup_keys values(?,?,?,?,?)", (
                    (ordinal, *owner, request["lookup_repository"], module) for module in keys))
        db.execute("create table file_adjacency(source_repository text not null, source_path text not null, target_repository text not null, target_path text not null, primary key(source_repository,source_path,target_repository,target_path))")
        db.execute("create index file_adjacency_target on file_adjacency(target_repository,target_path,source_repository,source_path)")
        boundary_owners = defaultdict(set)
        for edge in edges:
            if edge["kind"] == "IMPORTS" and edge["target"] and edge["target"].startswith("boundary:"):
                owner = owners.get(edge["source"])
                if owner and owner[1]:
                    boundary_owners[edge["target"]].add(owner)
        adjacent = set()
        for edge in edges:
            if edge["kind"] == "CONTAINS":
                continue  # repository CONTAINS would connect every file in a repository
            sources = ({owners[edge["source"]]} if edge["source"] in owners else
                       boundary_owners.get(edge["source"], set())
                       if edge["kind"] == "LOOKUP_IN" else set())
            # Two files importing the same external boundary are not related
            # to each other. An unresolved target has no captured file owner.
            targets = {owners[edge["target"]]} if edge["target"] in owners else set()
            for source in sources:
                for target in targets:
                    if source[1] and target[1] and source != target:
                        adjacent.add((*source, *target))
        db.executemany("insert into file_adjacency values(?,?,?,?)", sorted(adjacent))
        db.commit()
    finally:
        db.close()
    atomic(folder / SOURCE_FILES, m["files"])
    m["file_count"] = len(m["files"])
    del m["files"]
    m["graph"] = {k: v for k, v in graph.items() if k != "sites"}
    m.pop("dependency_store", None)
    if nodes and import_requests is not None and analysis_reads is not None and analysis_watches is not None:
        m["dependency_store"] = "indexed-v3"
        m["analysis_dependency_schema"] = 1
        m["analysis_dependency_coverage"] = "partial"
        m["analysis_read_count"] = len(analysis_reads)
        m["analysis_watch_count"] = len(analysis_watches)
        m["analysis_dependency_truncated"] = bool(analysis_dependency_truncated)
    m["value_flow_schema"] = 1
    m["value_flow_coverage"] = ("certified-dictionary-v1" if
                                m.get("simple_python_certificate") == "simple-python-v5" and
                                value_flow is not None and value_flow.get("complete") else "partial")
    m["value_flow_node_count"] = len((value_flow or {}).get("nodes", ()))
    m["value_flow_edge_count"] = len((value_flow or {}).get("edges", ()))
    m["value_flow_projection"] = "internal-sqlite-only"
    m["graph_detail"] = GRAPH_SITES
    m["metadata_layout"] = 2
    for rel in (GRAPH_SITES, SOURCE_FILES):
        checksum, size = hash_artifact(folder, rel)
        m["artifacts"][rel] = checksum
        m["artifact_sizes"][rel] = size


class FileDependencies:
    """Read-only indexed old-snapshot relations; missing/legacy evidence fails closed."""

    def __init__(self, folder, manifest):
        if (manifest.get("dependency_store") != "indexed-v3"
                or manifest.get("analysis_dependency_schema") != 1
                or manifest.get("analysis_dependency_coverage") != "partial"
                or manifest.get("graph_detail") != GRAPH_SITES):
            raise ToolError("Previous file dependency index unavailable")
        checksum, size = hash_artifact(folder, GRAPH_SITES)
        if (checksum != manifest["artifacts"][GRAPH_SITES]
                or size != manifest["artifact_sizes"][GRAPH_SITES]):
            raise ToolError("Previous file dependency index integrity failed")
        self.db = sqlite3.connect((folder / GRAPH_SITES).as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            expected = {"file_adjacency", "import_requests", "import_lookup_keys",
                        "analysis_reads", "analysis_watches"}
            present = {row[0] for row in self.db.execute(
                "select name from sqlite_master where type='table' and name in ('file_adjacency','import_requests','import_lookup_keys','analysis_reads','analysis_watches')")}
            if present != expected:
                raise ToolError("Previous file dependency index unavailable")
            if not any(row[1] == "import_request_requester" for row in self.db.execute(
                    "pragma index_list('import_requests')")):
                raise ToolError("Previous import requester index unavailable")
            if not {"ordinal", "source_repository", "source_path", "lookup_repository", "module"} <= {
                    row[1] for row in self.db.execute("pragma table_info('import_lookup_keys')")}:
                raise ToolError("Previous import lookup key columns unavailable")
            indexes = {row[1] for row in self.db.execute("pragma index_list('import_lookup_keys')")}
            if not {"import_lookup_namespace", "import_lookup_requester"} <= indexes:
                raise ToolError("Previous import lookup key indexes unavailable")
            for table, columns, index in (
                ("analysis_reads", {"consumer_module", "consumer_repository", "consumer_path",
                                    "producer_module", "producer_repository", "producer_path", "kind"},
                 "analysis_read_producer"),
                ("analysis_watches", {"consumer_module", "consumer_repository", "consumer_path",
                                      "kind", "universe"}, "analysis_watch_kind"),
            ):
                if not columns <= {row[1] for row in self.db.execute(f"pragma table_info('{table}')")}:
                    raise ToolError("Previous analysis dependency columns unavailable")
                if index not in {row[1] for row in self.db.execute(f"pragma index_list('{table}')")}:
                    raise ToolError("Previous analysis dependency index unavailable")
            if (type(manifest.get("analysis_read_count")) is not int or
                    manifest["analysis_read_count"] < 0 or
                    type(manifest.get("analysis_watch_count")) is not int or
                    manifest["analysis_watch_count"] < 0 or
                    not isinstance(manifest.get("analysis_dependency_truncated"), bool)):
                raise ToolError("Previous analysis dependency summary unavailable")
            self.analysis_dependency_truncated = manifest["analysis_dependency_truncated"]
            if manifest.get("value_flow_schema") == 1:
                if (manifest.get("value_flow_coverage") not in
                        ("certified-dictionary-v1", "partial") or
                        manifest.get("value_flow_projection") != "internal-sqlite-only" or
                        type(manifest.get("value_flow_node_count")) is not int or
                        type(manifest.get("value_flow_edge_count")) is not int or
                        not 0 <= manifest["value_flow_node_count"] <= VALUE_FLOW_LIMIT or
                        not 0 <= manifest["value_flow_edge_count"] <= VALUE_FLOW_LIMIT):
                    raise ToolError("Previous value-flow summary unavailable")
                required = {"value_nodes", "value_edges", "value_reads"}
                present = {r[0] for r in self.db.execute(
                    "select name from sqlite_master where type='table' and name in ('value_nodes','value_edges','value_reads')")}
                if present != required or not {"value_node_file"} <= {
                    r[1] for r in self.db.execute("pragma index_list('value_nodes')")
                } or not {"value_edge_target"} <= {
                    r[1] for r in self.db.execute("pragma index_list('value_edges')")
                } or not {"value_read_consumer"} <= {
                    r[1] for r in self.db.execute("pragma index_list('value_reads')")
                } or not {"id", "kind", "repository", "path", "data"} <= {
                    r[1] for r in self.db.execute("pragma table_info('value_nodes')")
                } or not {"source", "target", "kind"} <= {
                    r[1] for r in self.db.execute("pragma table_info('value_edges')")
                } or not {"entry", "read", "consumer_repository", "consumer_path"} <= {
                    r[1] for r in self.db.execute("pragma table_info('value_reads')")
                }:
                    raise ToolError("Previous value-flow index unavailable")
            self.value_flow_available = manifest.get("value_flow_schema") == 1
            self.value_flow_complete = (self.value_flow_available and
                manifest.get("value_flow_coverage") == "certified-dictionary-v1")
            if self.value_flow_available and (
                    self.db.execute("select count(*) from value_nodes").fetchone()[0]
                    != manifest["value_flow_node_count"] or
                    self.db.execute("select count(*) from value_edges").fetchone()[0]
                    != manifest["value_flow_edge_count"]):
                raise ToolError("Previous value-flow count mismatch")
        except (sqlite3.Error, ToolError):
            self.close()
            raise

    def adjacent(self, repository, path):
        rows = self.db.execute(
            "select target_repository,target_path from file_adjacency where source_repository=? and source_path=? "
            "union select source_repository,source_path from file_adjacency where target_repository=? and target_path=?",
            (repository, path, repository, path))
        return set(rows)

    def entry_ids_for_file(self, repository, path):
        """Seed only entries belonging to one changed producer file."""
        if not self.value_flow_complete:
            raise ToolError("Previous value-flow index unavailable")
        return {r[0] for r in self.db.execute(
            "select id from value_nodes where repository=? and path=? and kind='entry'",
            (repository, path))}

    def value_readers(self, entry):
        """Exact container-origin/key subscription, including prior missing keys."""
        if not self.value_flow_complete:
            raise ToolError("Previous value-flow index unavailable")
        return set(self.db.execute(
            "select consumer_repository,consumer_path from value_reads where entry=?", (entry,)))

    def get_value_nodes(self, ids):
        """Bounded internal evidence lookup, never a search catalog inventory."""
        if not self.value_flow_complete or not isinstance(ids, (tuple, list)) or len(ids) > 100:
            raise ToolError("Value node request unavailable or too large")
        return [json.loads(row[0]) for ident in ids for row in self.db.execute(
            "select data from value_nodes where id=?", (ident,))]

    def get_value_relations(self, node_id, direction="out", limit=100):
        if not self.value_flow_complete or direction not in ("in", "out") or not 1 <= limit <= 100:
            raise ToolError("Invalid value relation request")
        column = "source" if direction == "out" else "target"
        rows = [dict(source=s, target=t, kind=k) for s, t, k in self.db.execute(
            f"select source,target,kind from value_edges where {column}=? order by kind,source,target limit ?",
            (node_id, limit + 1))]
        return dict(relations=rows[:limit], has_more=len(rows) > limit)

    def analysis_readers(self, repository, path):
        """Observed container-effect consumers, not a complete invalidation set."""
        if self.analysis_dependency_truncated:
            raise ToolError("Previous analysis dependency records truncated")
        rows = self.db.execute(
            "select consumer_repository,consumer_path from analysis_reads "
            "where producer_repository=? and producer_path=? and kind='container-effects'",
            (repository, path))
        return set(rows)

    def analysis_watchers(self, kind):
        """Consumers of a capture-wide future writer class; coverage is partial."""
        if self.analysis_dependency_truncated:
            raise ToolError("Previous analysis dependency records truncated")
        rows = self.db.execute(
            "select consumer_repository,consumer_path from analysis_watches "
            "where kind=? and universe='all-captured-python'", (kind,))
        return set(rows)

    def importers(self, repository, module):
        rows = self.db.execute(
            "select source_repository,source_path from import_lookup_keys "
            "where lookup_repository=? and module=?", (repository, module))
        return set(rows)

    def requesters(self, repository, module):
        """Find old same-repository requests that a new local module may shadow."""
        rows = self.db.execute(
            "select source_repository,source_path from import_lookup_keys "
            "where source_repository=? and module=?", (repository, module))
        return set(rows)

    def has_descendant_requesters(self, repository, module):
        """Detect layout shadows not already covered by an exact base requester.

        A `from pkg import child` requester has both `pkg` and the possible
        `pkg.child` key, so it is selected by the exact base lookup. A direct
        `from pkg.child import name` requester lacks `pkg` and cannot be
        certified when a newly added `pkg.py` changes ancestor layout.
        """
        prefix = module + "."
        row = self.db.execute(
            "select 1 from import_lookup_keys child where child.source_repository=? "
            "and child.module>=? and child.module<? and not exists ("
            "select 1 from import_lookup_keys base where base.source_repository=child.source_repository "
            "and base.module=? and base.source_path=child.source_path) limit 1",
            (repository, prefix, module + "/", module)).fetchone()
        return row is not None

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class _QueryReuse:
    """Indexed private observations; one row is checked only when a site asks for it."""

    def __init__(self, folder, allowed_modules, python_changed):
        self.db = sqlite3.connect((folder / GRAPH_SITES).as_uri() + "?mode=ro&immutable=1", uri=True)
        self.allowed_modules = allowed_modules
        self.python_changed = python_changed

    def get(self, key):
        if key[0] not in self.allowed_modules:
            return None
        try:
            row = self.db.execute("select data,checksum from query_observations where key=?",
                                  (canonical(list(key)),)).fetchone()
            if not row or digest(row[0]) != row[1]:
                return None
            record = json.loads(row[0])
            if record["key"] != list(key):
                return None
            return (Result(frozenset(Atom(**atom) for atom in record["atoms"]),
                           frozenset(record["reasons"]), frozenset(record["proofs"])), record["raw"])
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            return None

    def close(self):
        self.db.close()


def _same_python_inputs(previous_folder, previous_manifest, files, repos, c):
    """Locate unchanged captured modules; only certified local queries may reuse."""
    if (previous_manifest.get("program_hash") != program_hash()
            or previous_manifest.get("config_hash") != identity(c)
            or previous_manifest.get("graph", {}).get("query_runtime") != QUERY_RUNTIME
            or previous_manifest.get("graph_detail") != GRAPH_SITES):
        return False, "program-or-config-or-cache-changed", set(), False
    # HEAD/tree/branch/status describe provenance. A committed documentation edit
    # changes them without changing Jedi's captured Python input. The separately
    # computed dependency_bindings gate checks pin/head/cleanliness semantics.
    provenance = {"head", "tree", "branch", "status", "source_manifest_sha256"}
    if [{k: v for k, v in repo.items() if k not in provenance} for repo in previous_manifest["repositories"]] != [
        {k: v for k, v in repo.items() if k not in provenance} for repo in repos
    ]:
        return False, "repository-or-pin-metadata-changed", set(), False
    try:
        old_files = source_files(previous_folder, previous_manifest)
    except (OSError, ValueError, KeyError, ToolError):
        return False, "previous-source-inventory-unavailable", set(), False
    def python_keys(items):
        return sorted((f["repository"], f["path"], f["sha256"], f["is_test"])
                      for f in items if f["path"].endswith(".py"))
    old_python = python_keys(old_files)
    new_python = python_keys(files)
    unchanged = set(old_python) & set(new_python)
    if not unchanged:
        return False, "no-unchanged-python-modules", set(), old_python != new_python
    return True, ("python-inputs-identical" if old_python == new_python
                  else "python-source-or-membership-changed;local-query-only"), {
        (repo, path) for repo, path, _, _ in unchanged
    }, old_python != new_python


def _reuse_python_graph(folder, prior, files, repos, c):
    """Prepare an exact graph when captured Python and owning repository IDs persist.

    Documentation in a Python-owning repository changes that repository's capture
    identity, so this path deliberately declines it. The returned products are
    fresh documents plus verified immutable Python evidence, not a local Python
    dependency scheduler.
    """
    eligible, reason, _, python_changed = _same_python_inputs(folder, prior, files, repos, c)
    if not eligible or python_changed:
        return None, reason
    if prior.get("dependency_store") != "indexed-v3":
        return None, "previous-graph-evidence-unavailable"
    if (prior.get("simple_python_certificate") == "simple-python-v5" and
            (prior.get("value_flow_schema") != 1 or
             prior.get("value_flow_coverage") != "certified-dictionary-v1")):
        return None, "previous-value-flow-evidence-unavailable"
    old_files = source_files(folder, prior)
    # SOURCE_FILES stores inventory without text. Its source hashes certify the
    # identical decoded captures only when the whole repository inventory agrees.
    def captures(items):
        return {repo: digest(canonical(sorted((f["path"], f["sha256"])
                                                   for f in items if f["repository"] == repo)))
                for repo in {f["repository"] for f in items}}
    old_capture, new_capture = captures(old_files), captures(files)
    decoded_hashes = {(f["repository"], f["path"]): digest(f["text"]) for f in files}
    node_snapshots = {
        repo: digest(canonical(sorted((f["path"], decoded_hashes[f["repository"], f["path"]])
                                      for f in files if f["repository"] == repo)))
        for repo in {f["repository"] for f in files}
    }
    python_repos = {f["repository"] for f in files if f["path"].endswith(".py")}
    if any(old_capture.get(repo) != new_capture.get(repo) for repo in python_repos):
        return None, "python-repository-capture-changed"
    for rel in ("catalog.sqlite", GRAPH_SITES):
        checksum, size = hash_artifact(folder, rel)
        if checksum != prior["artifacts"][rel] or size != prior["artifact_sizes"][rel]:
            return None, "previous-graph-evidence-integrity-failed"
    # This constructor checks live dependency pins and configured repository
    # bindings, without preparing a Jedi project or visiting a Python AST.
    document_nodes, _ = extract([f for f in files if not f["path"].endswith(".py")])
    present_repositories = {n["repository"] for n in document_nodes if n["kind"] == "repository"}
    for repo in sorted({f["repository"] for f in files} - present_repositories):
        document_nodes.append(dict(
            node_id=f"{repo}::repository", repository=repo, path="", kind="repository",
            qualname=repo, parent=None, start=0, end=0, signature="", docstring="",
            brief="", fingerprint=digest(repo), is_test=False,
        ))
    with closing(sqlite3.connect((folder / "catalog.sqlite").as_uri() + "?mode=ro&immutable=1",
                                 uri=True)) as db:
        python_records = {node_id: json.loads(raw) for node_id, raw in db.execute(
            "select node_id,data from nodes where path like '%.py'")}
        with closing(sqlite3.connect((folder / GRAPH_SITES).as_uri() + "?mode=ro&immutable=1",
                                     uri=True)) as evidence:
            order = [node_id for (node_id,) in evidence.execute(
                "select node_id from node_order order by ordinal")]
        python_nodes = [python_records[node_id] for node_id in order if node_id in python_records]
        if len(python_nodes) != len(python_records) or len(order) != prior["node_count"]:
            return None, "previous-node-order-unavailable"
        edges = [json.loads(raw) for (raw,) in db.execute(
            "select data from edges where kind!='CONTAINS' order by edge_id")]
    expected = {(f["repository"], f["path"]): f for f in files if f["path"].endswith(".py")}
    if (not all((n["repository"], n["path"]) in expected
                and n["source_sha256"] == decoded_hashes[n["repository"], n["path"]]
                and n["snapshot_id"] == node_snapshots[n["repository"]]
                and n["file_fingerprint"] == expected[n["repository"], n["path"]]["sha256"]
                for n in python_nodes)
            or {(n["repository"], n["path"]) for n in python_nodes if n["kind"] == "module"} != set(expected)):
        return None, "previous-python-catalog-mismatch"
    nodes = document_nodes + python_nodes
    graph = Graph(nodes, {}, repos)
    if graph.cross_bindings != prior["graph"].get("dependency_bindings"):
        return None, "dependency-bindings-changed"
    for n in nodes:
        if n["parent"]:
            graph.add_edge(n["parent"], n["node_id"], "CONTAINS", "resolved",
                           "AST lexical ownership", n["start"], n.get("column", 0))
    edges = list({e["edge_id"]: e for e in (*graph.edges, *edges)}.values())
    with closing(sqlite3.connect((folder / GRAPH_SITES).as_uri() + "?mode=ro&immutable=1",
                                 uri=True)) as db:
        sites = [json.loads(raw) for (raw,) in db.execute("select data from sites order by ordinal")]
        def private(table):
            return [json.loads(raw) for (raw,) in db.execute(
                "select data from " + table + " order by " +
                ("key" if table == "query_observations" else "ordinal"))]
        observations = private("query_observations")
        dependencies = private("import_dependencies")
        requests = private("import_requests")
        analysis_reads = list(db.execute(
            "select consumer_module,producer_module,kind from analysis_reads order by consumer_module,producer_module,kind"))
        analysis_watches = list(db.execute(
            "select consumer_module,kind,universe from analysis_watches order by consumer_module,kind,universe"))
        if prior.get("value_flow_schema") == 1:
            value_flow = dict(
                nodes=[json.loads(raw) for (raw,) in db.execute("select data from value_nodes order by id")],
                edges=[dict(source=s, target=t, kind=k) for s, t, k in db.execute(
                    "select source,target,kind from value_edges order by source,target,kind")],
                reads=[dict(entry=e, read=r, consumer_repository=cr,
                            consumer_path=cp) for e, r, cr, cp in db.execute(
                    "select entry,read,consumer_repository,consumer_path from value_reads order by entry,read")],
                complete=prior.get("value_flow_coverage") == "certified-dictionary-v1")
        else:
            value_flow = dict(nodes=[], edges=[], reads=[], complete=False)
    if len(sites) != prior["graph"]["call_sites"]:
        return None, "previous-graph-evidence-count-mismatch"
    info = dict(prior["graph"], sites=sites, _query_observations=observations,
                _import_dependencies=dependencies, _import_requests=requests,
                _analysis_reads=analysis_reads, _analysis_watches=analysis_watches,
                _analysis_dependency_truncated=prior["analysis_dependency_truncated"],
                _value_flow=value_flow)
    info["jedi_queries_reused"] = info["jedi_queries"]
    info["jedi_queries_executed"] = 0
    info["association_evaluations"] = 0
    for key in ("slot_scope_index_build_scopes", "slot_scope_fallback_scopes",
                "slot_scope_candidates_checked", "slot_events_checked"):
        info[key] = 0
    return (nodes, edges, info), "python-capture-identical"


def migrate_metadata(c, version, expected_program_hash):
    """Explicit offline migration of a frozen version; publish only the small sidecar last.

    The original manifest and version identity are retained. A failed preparation
    leaves it unmigrated, and no cursor or current pointer is changed.
    """
    if not isinstance(version, str) or not version or any(x in version for x in ("/", "\\", "..")):
        raise ToolError("Invalid index version")
    if not isinstance(expected_program_hash, str) or len(expected_program_hash) != 64:
        raise ToolError("Explicit old program hash required")
    with lock(Path(c["data"]) / "update.lock"):
        folder = Path(c["data"]) / "versions" / version
        original = folder / "manifest.json"
        if not original.is_file():
            raise ToolError("Index version expired or incomplete")
        old = load(original)
        if old.get("version") != version or old.get("state") != "complete":
            raise ToolError("Index incomplete")
        if old.get("program_hash") != expected_program_hash:
            raise ToolError("Frozen program hash differs from explicit predecessor")
        if old.get("schema") != SCHEMA or old.get("format") != FORMAT or old.get("template") != TEMPLATE or old.get("tokenizer") != TOKENIZER or old.get("config_hash") != identity(c):
            raise ToolError("Frozen index incompatible with metadata migration")
        if (folder / "summary.json").exists():
            _, summary = manifest(c, version)
            if summary.get("migrated_from_program_hash", summary["program_hash"]) != expected_program_hash:
                raise ToolError("Existing metadata migration predecessor differs")
            return dict(version=version, already_migrated=True)
        if old.get("metadata_layout") == 2:
            # A new-format candidate with a missing sidecar is not a legacy version.
            raise ToolError("Summary metadata missing from new-format version")
        if old.get("embedding") != {k: c["embedding"][k] for k in ("model", "dimension", "dtype")} or old.get("hnsw") != c["hnsw"]:
            raise ToolError("Frozen index embedding configuration differs")
        validate_folder(folder, old, full=True)
        m = dict(old)
        m["artifacts"] = dict(old["artifacts"])
        m["artifact_sizes"] = dict(old.get("artifact_sizes", {}))
        for rel in (GRAPH_SITES, SOURCE_FILES, GRAPH_SITES + "-journal", GRAPH_SITES + "-wal"):
            (folder / rel).unlink(missing_ok=True)
        split_graph(folder, m)
        m["migrated_from_program_hash"] = old["program_hash"]
        m["migrated_from_config_hash"] = old["config_hash"]
        m["program_hash"] = program_hash()
        validate_folder(folder, m, full=True)
        atomic(folder / "summary.json", m)
        return dict(version=version, already_migrated=False, graph_sites=m["graph"]["call_sites"],
                    manifest_bytes=original.stat().st_size, summary_bytes=(folder / "summary.json").stat().st_size)


def source_text(n, files):
    """Assemble lexical input from current source and existing descriptions only."""
    f = files.get((n["repository"], n["path"]))
    source = "".join(f["text"].splitlines(keepends=True)[n["start"] - 1 : n["end"]]) if f else ""
    return n["path"] + "\n" + n["qualname"] + "\n" + source


def estimate(c):
    """Extract current scope and report conservative missing-input budget, without network."""
    files, repos, fingerprint = inventory(c)
    nodes, _ = extract(files)
    texts = embedding_texts(nodes, files)
    cache = Embeddings(c)
    try:
        missing = [t["text"] for t in texts if cache.lookup(t["text"], "document") is None]
        unique = list(dict.fromkeys(missing))
        tokens = sum(bound(t) for t in unique)
        return dict(
            files=len(files),
            nodes=dict(Counter(n["kind"] for n in nodes)),
            vector_chunks=len(texts),
            uncached_unique=len(unique),
            conservative_token_byte_bound=tokens,
            list_cost_upper_usd=tokens * c["embedding"]["price_per_million_usd"] / 1e6,
            historical_cache_hits=cache.historical_hits,
            repositories=repos,
            source_fingerprint=fingerprint,
        )
    finally:
        cache.close()


def build(c, offline=False, fail_at=None, lexical_only=False, prepare_only=False,
          on_candidate=None):
    """Build all channels from captured source; publish only after rechecking source bytes.

    AST/Jedi relationships are reused only for identical captured Python repositories;
    HNSW is maintained during update, not retrieval. SQLite
    nodes/edges/postings update by content difference; unchanged vectors never call API.
    """
    data = Path(c["data"])
    with lock(data / "update.lock"):
        previous = current(c)
        if previous and on_candidate is None and not prepare_only:
            _, prior_manifest = manifest(c, previous, compatible=False)
            if prior_manifest.get("publication"):
                raise ToolError("Bound publication requires update-coordinated")
        started = time.monotonic()
        files, repos, fingerprint = inventory(c)
        prepared = None
        preparation_reason = "no-previous-snapshot"
        local_metrics = None
        local_attempts = {"python_files_parsed": 0}
        if previous:
            try:
                old_folder, old_manifest = manifest(c, previous, compatible=False)
                prepared, preparation_reason = _reuse_python_graph(
                    old_folder, old_manifest, files, repos, c)
            except (OSError, ToolError, KeyError, ValueError, sqlite3.Error):
                preparation_reason = "previous-graph-evidence-unavailable"
        if previous and prepared is None:
            try:
                old_folder, old_manifest = manifest(c, previous, compatible=False)
                compatible, reason, _, _ = _same_python_inputs(
                    old_folder, old_manifest, files, repos, c)
                if compatible and old_manifest.get("dependency_store") == "indexed-v3":
                    checksum, size = hash_artifact(old_folder, "catalog.sqlite")
                    if (checksum != old_manifest["artifacts"]["catalog.sqlite"]
                            or size != old_manifest["artifact_sizes"]["catalog.sqlite"]):
                        reason = "previous-catalog-integrity-failed"
                    else:
                        from .python_incremental import prepare
                        with FileDependencies(old_folder, old_manifest) as dependencies:
                            candidate, reason = prepare(
                                old_folder, old_manifest, files, repos,
                                dependencies=dependencies, graph_sites=GRAPH_SITES,
                                attempts=local_attempts)
                        if candidate is not None:
                            nodes, edges, graph_info, local_metrics = candidate
                            prepared = nodes, edges, graph_info
                preparation_reason = reason
            except (OSError, ToolError, KeyError, ValueError, sqlite3.Error, SyntaxError):
                preparation_reason = "previous-local-evidence-unavailable"
        if prepared is None:
            nodes, asts = extract(files)
        else:
            nodes, edges, graph_info = prepared
            asts = {}
        texts = embedding_texts(nodes, files)
        reuse = None
        reuse_reason = preparation_reason
        if previous and prepared is None:
            graph = Graph(nodes, asts, repos)
            try:
                old_folder, old_manifest = manifest(c, previous, compatible=False)
                eligible, reuse_reason, unchanged, python_changed = _same_python_inputs(
                    old_folder, old_manifest, files, repos, c)
                if eligible and old_manifest["graph"].get("dependency_bindings") == graph.cross_bindings:
                    checksum, size = hash_artifact(old_folder, GRAPH_SITES)
                    if (checksum == old_manifest["artifacts"][GRAPH_SITES]
                            and size == old_manifest["artifact_sizes"][GRAPH_SITES]):
                        allowed = {n["node_id"] for n in nodes if n["kind"] == "module"
                                   and (n["repository"], n["path"]) in unchanged}
                        reuse = _QueryReuse(old_folder, allowed, python_changed)
                    else:
                        reuse_reason = "previous-query-cache-integrity-failed"
                elif eligible:
                    reuse_reason = "dependency-bindings-changed"
            except (OSError, ToolError, KeyError, sqlite3.Error):
                reuse_reason = "previous-query-cache-unavailable"
        if prepared is None:
            if not previous:
                graph = Graph(nodes, asts, repos)
            try:
                edges, graph_info = graph.build(query_reuse=reuse)
            finally:
                if reuse is not None:
                    reuse.close()
        if prepared is None:
            graph_info["association_bound"] = graph_info["association_evaluations"]
        observations = graph_info.pop("_query_observations")
        import_dependencies = graph_info.pop("_import_dependencies")
        import_requests = graph_info.pop("_import_requests", None)
        analysis_reads = graph_info.pop("_analysis_reads", None)
        analysis_watches = graph_info.pop("_analysis_watches", None)
        analysis_dependency_truncated = graph_info.pop("_analysis_dependency_truncated", False)
        value_flow = graph_info.pop("_value_flow", None)
        graph_info["query_reuse_reason"] = reuse_reason
        graph_info["query_runtime"] = QUERY_RUNTIME
        graph_info["import_dependency_count"] = len(import_dependencies)
        analysis_scope = dict(
            mode=("certified-simple-python-component" if local_metrics is not None else
                  "identical-python-capture-reuse" if prepared is not None else "full-graph"),
            reason=preparation_reason,
            python_files_parsed=local_metrics["parsed_python_files"] if local_metrics else 0 if prepared is not None else sum(
                f["path"].endswith(".py") for f in files),
            python_ast_context_files=local_metrics["selected_files"] if local_metrics else 0 if prepared is not None else sum(
                f["path"].endswith(".py") for f in files),
            reused_python_nodes=(sum(n["path"].endswith(".py") and
                                     (n["repository"], n["path"]) not in local_metrics["selected_keys"]
                                     for n in nodes) if local_metrics else
                                 sum(n["path"].endswith(".py") for n in nodes)
                                 if prepared is not None else 0),
            document_files_parsed=sum(not f["path"].endswith(".py") for f in files),
            reused_graph_sites=(local_metrics["reused_sites"] if local_metrics else
                                graph_info["call_sites"] if prepared is not None else 0),
            sites_analyzed=(graph_info["call_sites"] - local_metrics["reused_sites"]
                            if local_metrics else 0 if prepared is not None else graph_info["call_sites"]),
            jedi_queries_executed=graph_info["jedi_queries_executed"],
            reused_graph_edges=(local_metrics["reused_edges"] if local_metrics else
                                sum(e["kind"] != "CONTAINS" for e in edges)
                                if prepared is not None else 0),
            output_nodes=len(nodes), output_edges=len(edges),
        )
        if local_metrics:
            analysis_scope.update(local_metrics)
        else:
            analysis_scope["local_preflight_python_files_parsed"] = local_attempts["python_files_parsed"]
        analysis_scope["total_python_files_parsed"] = (
            analysis_scope["python_files_parsed"] if local_metrics else
            analysis_scope["python_files_parsed"] + local_attempts["python_files_parsed"])
        ident = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:10]
        folder = data / "versions" / ident
        folder.mkdir(parents=True)
        atomic(folder / "build-state.json", dict(state="candidate", started=now()))
        cache = Embeddings(c)
        try:
            vectors = (
                [] if lexical_only else cache.get_many([t["text"] for t in texts], offline=offline)
            )
            if fail_at == "after_embeddings":
                raise ToolError("Injected interruption after durable embeddings")
            old = old_dense_manifest = None
            if previous:
                try:
                    old, old_dense_manifest = manifest(c, previous, compatible=False)
                    shutil.copy2(old / "catalog.sqlite", folder / "catalog.sqlite")
                except (OSError, ToolError):
                    old = old_dense_manifest = None
            db = sqlite3.connect(folder / "catalog.sqlite")
            db.executescript(DDL)
            old_nodes = {
                r[0]: r[1:] for r in db.execute("select node_id,data,search_hash from nodes")
            }
            old_edges = {r[0]: r[1] for r in db.execute("select edge_id,data from edges")}
            new_ids = {n["node_id"] for n in nodes}
            removed = set(old_nodes) - new_ids
            for nid in removed:
                db.execute("delete from nodes where node_id=?", (nid,))
                db.execute("delete from postings where node_id=?", (nid,))
                db.execute("delete from lengths where node_id=?", (nid,))
            changed = posting_updates = 0
            byfile = {(f["repository"], f["path"]): f for f in files}
            for n in nodes:
                # Versioned node data is stored once; index_version is supplied by reader.
                f = byfile.get((n["repository"], n["path"]))
                n["file_fingerprint"] = f["sha256"] if f else None
                lexical = source_text(n, byfile)
                sh = digest(lexical)
                encoded = canonical(n)
                prior = old_nodes.get(n["node_id"])
                if not prior or prior[0] != encoded:
                    db.execute(
                        "insert or replace into nodes values(?,?,?,?,?,?)",
                        (n["node_id"], n["repository"], n["path"], n["kind"], encoded, sh),
                    )
                    changed += 1
                if not prior or prior[1] != sh:
                    add_document(db, n, lexical)
                    posting_updates += 1
            incoming = {e["edge_id"]: e for e in edges}
            for eid in set(old_edges) - set(incoming):
                db.execute("delete from edges where edge_id=?", (eid,))
            for eid, e in incoming.items():
                if eid not in old_edges:
                    db.execute(
                        "insert into edges values(?,?,?,?,?,?)",
                        (eid, e["source"], e["target"], e["kind"], e["status"], canonical(e)),
                    )
            db.execute("delete from terms")
            db.execute("insert into terms select term,count(*) from postings group by term")
            old_files = {
                (r[0], r[1]): r[2] for r in db.execute("select repository,path,sha256 from files")
            }
            for key in set(old_files) - set(byfile):
                db.execute("delete from files where repository=? and path=?", key)
            for key, f in byfile.items():
                if old_files.get(key) != f["sha256"]:
                    db.execute(
                        "insert or replace into files values(?,?,?,?)",
                        (*key, f["sha256"], f["text"]),
                    )
            db.commit()
            db.execute("vacuum")
            db.close()
            partitions = defaultdict(list)
            byid = {n["node_id"]: n for n in nodes}
            for i, t in enumerate(texts if not lexical_only else []):
                n = byid[t["node_id"]]
                partitions[n["repository"], n["kind"], n["is_test"]].append(i)
            def dense_parts():
                for key, indices in sorted(partitions.items()):
                    a = np.asarray([vectors[i] for i in indices], dtype=np.float32)
                    a /= np.linalg.norm(a, axis=1, keepdims=True)
                    yield key, a, [texts[i]["node_id"] for i in indices]

            specs, dense_update = write_partitions(
                folder, dense_parts(),
                {k: c["embedding"][k] for k in ("model", "dimension", "dtype")},
                c["hnsw"], prior_folder=old, prior_manifest=old_dense_manifest,
            )
            # Detect edits/additions/deletions during API/build, never publish a mixed snapshot.
            _, end_repos, end_fingerprint = inventory(c)
            if end_fingerprint != fingerprint or [(r["head"], r["branch"]) for r in end_repos] != [
                (r["head"], r["branch"]) for r in repos
            ]:
                raise ToolError(
                    "Sources changed during build; candidate withheld, cached vectors reusable"
                )
            m = dict(
                toolkit_version=VERSION,
                program_hash=program_hash(),
                schema=SCHEMA,
                format=FORMAT,
                template=TEMPLATE,
                tokenizer=TOKENIZER,
                config_hash=identity(c),
                embedding={k: c["embedding"][k] for k in ("model", "dimension", "dtype")},
                metric="cosine; normalized float32; exact uses dot product",
                hnsw=c["hnsw"],
                partitions=specs,
                repositories=repos,
                source_fingerprint=fingerprint,
                files=[{k: v for k, v in f.items() if k != "text"} for f in files],
                state="complete",
                dense_ready=not lexical_only,
                version=ident,
                completed=now(),
                node_count=len(nodes),
                nodes=dict(Counter(n["kind"] for n in nodes)),
                counts_by_repository={
                    r["name"]: dict(
                        Counter(n["kind"] for n in nodes if n["repository"] == r["name"])
                    )
                    for r in repos
                },
                edges=dict(Counter(e["kind"] for e in edges)),
                call_resolution=dict(Counter(e["status"] for e in edges if e["kind"] == "CALLS")),
                graph=graph_info,
                simple_python_certificate=(
                    old_manifest["simple_python_certificate"] if local_metrics else
                    certify(files, asts, graph=graph) if prepared is None else
                    old_manifest.get("simple_python_certificate")),
                vector_chunks=0 if lexical_only else len(texts),
                planned_vector_chunks=len(texts),
                incremental=dict(
                    previous=previous,
                    analysis_scope=analysis_scope,
                    nodes_updated=changed,
                    nodes_removed=len(removed),
                    postings_updated=posting_updates,
                    edges_added=len(set(incoming) - set(old_edges)),
                    edges_removed=len(set(old_edges) - set(incoming)),
                    dense_partitions_reused=dense_update["reused"],
                    dense_partitions_rebuilt=dense_update["rebuilt"],
                ),
                embedding_run=dict(
                    cache_hits=cache.hits,
                    historical_hits=cache.historical_hits,
                    new_vectors=cache.new_vectors,
                    requests=cache.requests,
                ),
                seconds=round(time.monotonic() - started, 2),
            )
            if (m["simple_python_certificate"] == "simple-python-v5" and
                    (value_flow is None or not value_flow.get("complete"))):
                m["simple_python_certificate"] = None
            check_catalog_sidecars(folder)
            m["artifacts"] = {}
            m["artifact_sizes"] = {}
            for rel in sorted(required_artifacts(specs)):
                checksum, size = hash_artifact(folder, rel)
                m["artifacts"][rel] = checksum
                m["artifact_sizes"][rel] = size
            split_graph(folder, m, observations, import_dependencies, import_requests,
                        nodes, edges, files if m.get("simple_python_certificate") else (),
                        analysis_reads, analysis_watches, analysis_dependency_truncated,
                        value_flow)
            atomic(folder / "manifest.json", m)
            validate_folder(folder, m)
            atomic(folder / "summary.json", m)
            if fail_at == "before_publish":
                raise ToolError("Injected interruption before atomic pointer publication")
            if on_candidate is not None:
                on_candidate(ident, folder, m, previous)
            if prepare_only:
                return m
            activate(c, ident)
            atomic(
                data / "freshness.json",
                dict(
                    version=ident,
                    status="matched_at_check",
                    checked_at=now(),
                    source_fingerprint=fingerprint,
                    repositories=repos,
                ),
            )
            atomic(folder / "build-state.json", dict(state="published", completed=now()))
            prune(c)
            return m
        except BaseException:
            atomic(folder / "build-state.json", dict(
                state="published" if current(c) == ident else "failed-or-interrupted", at=now()))
            raise
        finally:
            cache.close()


def attach_dense(c, expected_version, offline=False, expected_program_hash=None,
                 fail_at=None, prepare_only=False, on_candidate=None):
    """Attach real cached/provider vectors to one frozen lexical catalog, without source parsing.

    The expected-version fence and update lock make the new candidate atomic. The
    predecessor's captured files/nodes, graph, BM25 and source identity are retained.
    No live repository is consulted; freshness remains the predecessor's last check.
    """
    data = Path(c["data"])
    with lock(data / "update.lock"):
        if current(c) != expected_version:
            raise ToolError("Dense attachment expected current version mismatch")
        old_folder, old = manifest(c, expected_version, compatible=False)
        if old.get("publication") and on_candidate is None and not prepare_only:
            raise ToolError("Bound publication requires coordinated dense attachment")
        if (expected_program_hash is not None and old["program_hash"] != expected_program_hash or
            old["program_hash"] != program_hash() and expected_program_hash is None):
            raise ToolError("Frozen lexical program hash differs from explicit predecessor")
        if (old["schema"] != SCHEMA or old["format"] != FORMAT or
            old["template"] != TEMPLATE or old["tokenizer"] != TOKENIZER or
            old["config_hash"] != identity(c) or
            old["embedding"] != {k: c["embedding"][k] for k in ("model", "dimension", "dtype")} or
            old["hnsw"] != c["hnsw"]):
            raise ToolError("Frozen lexical index incompatible with dense attachment")
        if old["dense_ready"] or old["partitions"] or old["vector_chunks"]:
            raise ToolError("Expected version already has a dense index")
        validate_folder(old_folder, old)
        started = time.monotonic()
        with closing(sqlite3.connect((old_folder / "catalog.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            # Match the prior frozen-catalog vector preflight exactly. Member
            # summaries are generated from this explicit deterministic order.
            nodes = [json.loads(r[0]) for r in db.execute("select data from nodes order by node_id")]
            files = [dict(repository=r[0], path=r[1], sha256=r[2], text=r[3])
                     for r in db.execute("select repository,path,sha256,text from files")]
        original_files = source_files(old_folder, old)
        if len(nodes) != old["node_count"] or len(files) != len(original_files):
            raise ToolError("Frozen catalog capture incomplete")
        expected_files = {(f["repository"], f["path"]): f["sha256"] for f in original_files}
        if {(f["repository"], f["path"]): f["sha256"] for f in files} != expected_files:
            raise ToolError("Frozen catalog file inventory differs")
        if any(f["sha256"] not in (digest(f["text"]), digest(b"\xef\xbb\xbf" + f["text"].encode()))
               for f in files):
            raise ToolError("Frozen source bytes differ from file checksums")
        texts = embedding_texts(nodes, files)
        if len(texts) != old["planned_vector_chunks"]:
            raise ToolError("Frozen vector text count differs from plan")
        ident = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:10]
        folder = data / "versions" / ident
        folder.mkdir(parents=True)
        atomic(folder / "build-state.json", dict(state="candidate", started=now()))
        cache = Embeddings(c)
        try:
            vectors = cache.get_many([t["text"] for t in texts], offline=offline)
            shutil.copy2(old_folder / "catalog.sqlite", folder / "catalog.sqlite")
            partitions = defaultdict(list)
            byid = {n["node_id"]: n for n in nodes}
            for i, t in enumerate(texts):
                n = byid[t["node_id"]]
                partitions[n["repository"], n["kind"], n["is_test"]].append(i)
            specs = []
            for part, (key, indices) in enumerate(sorted(partitions.items())):
                a = np.asarray([vectors[i] for i in indices], dtype=np.float32)
                a /= np.linalg.norm(a, axis=1, keepdims=True)
                stem = f"partition-{part}"
                np.save(folder / (stem + ".npy"), a, allow_pickle=False)
                index = Index(ndim=c["embedding"]["dimension"], metric="cos", dtype="f32", **c["hnsw"])
                index.add(np.arange(len(a), dtype=np.uint64), a, threads=1)
                index.save(str(folder / (stem + ".usearch")))
                mapping = [texts[i]["node_id"] for i in indices]
                atomic(folder / (stem + ".json"), mapping)
                specs.append(dict(repository=key[0], kind=key[1], is_test=key[2],
                                  stem=stem, chunks=len(indices), nodes=len(set(mapping))))
            m = dict(old)
            m.update(version=ident, completed=now(), program_hash=program_hash(),
                     partitions=specs, dense_ready=True, vector_chunks=len(texts),
                     embedding_run=dict(cache_hits=cache.hits, historical_hits=cache.historical_hits,
                                        new_vectors=cache.new_vectors, requests=cache.requests),
                     incremental=dict(previous=expected_version, nodes_updated=0, nodes_removed=0,
                                      postings_updated=0, edges_added=0, edges_removed=0),
                     seconds=round(time.monotonic() - started, 2))
            m["artifacts"] = {}
            m["artifact_sizes"] = {}
            shutil.copy2(old_folder / GRAPH_SITES, folder / GRAPH_SITES)
            shutil.copy2(old_folder / SOURCE_FILES, folder / SOURCE_FILES)
            for rel in sorted(required_artifacts(specs, graph_detail=True)):
                checksum, size = hash_artifact(folder, rel)
                m["artifacts"][rel] = checksum
                m["artifact_sizes"][rel] = size
            if m["artifacts"]["catalog.sqlite"] != old["artifacts"]["catalog.sqlite"]:
                raise ToolError("Frozen catalog changed during dense attachment")
            atomic(folder / "manifest.json", m)
            validate_folder(folder, m)
            atomic(folder / "summary.json", m)
            if fail_at == "before_publish":
                raise ToolError("Injected interruption before dense publish")
            if current(c) != expected_version:
                raise ToolError("Dense attachment expected current version changed")
            if on_candidate is not None:
                on_candidate(ident, folder, m, expected_version)
            if prepare_only:
                return m
            activate(c, ident)
            freshness = data / "freshness.json"
            if freshness.exists():
                prior = load(freshness)
                if prior.get("version") == expected_version:
                    atomic(freshness, dict(prior, version=ident))
            atomic(folder / "build-state.json", dict(state="published", completed=now()))
            prune(c)
            return m
        except BaseException:
            atomic(folder / "build-state.json", dict(
                state="published" if current(c) == ident else "failed-or-interrupted", at=now()))
            raise
        finally:
            cache.close()


def activation_history(c):
    """Read authoritative activation order, with a conservative legacy pointer fallback."""
    path = Path(c["data"]) / "current.json"
    if not path.exists():
        return []
    pointer = load(path)
    ordered = [pointer.get("version"), pointer.get("previous")] + pointer.get("history", [])
    result = []
    for version in ordered:
        if not version or version in result:
            continue
        if not isinstance(version, str) or "/" in version or "\\" in version or ".." in version:
            raise ToolError("Invalid publication history")
        result.append(version)
    return result


def activate(c, version):
    """Atomically publish one bounded activation chain under the existing update lock.

    The pointer is the sole publication record. Completed-but-unpublished manifests
    and diagnostic build-state timestamps never participate in retention ordering.
    """
    data = Path(c["data"])
    previous = current(c)
    limit = max(2, c.get("retained_versions", 2))
    history = [version] + [v for v in activation_history(c) if v != version]
    atomic(
        data / "current.json",
        dict(version=version, previous=previous, history=history[:limit], history_schema=1),
    )


def prune(c):
    """Keep current plus recent distinct activations; never sort random version names.

    Callers hold update.lock. Legacy complete snapshots of uncertain age are preserved
    until enough explicit pointer history exists. Incomplete candidates are removed;
    completed unlisted candidates are removed once history is sufficient. Pointer-
    referenced versions survive even a stale build-state marker.
    """
    data = Path(c["data"])
    versions = data / "versions"
    history = activation_history(c)
    if not history:
        return
    limit = max(2, c.get("retained_versions", 2))
    keep = set(history[:limit])
    valid_history = []
    for version in history[:limit]:
        folder = versions / version
        if (folder / "summary.json").is_file() and load(folder / "summary.json").get(
            "state"
        ) == "complete":
            valid_history.append(version)
    # With insufficient legacy history, deleting an unlisted completed publication
    # could discard a required predecessor. Keep it until the chain proves enough.
    sufficient = len(valid_history) >= limit
    for folder in versions.iterdir():
        if not folder.is_dir() or folder.name in keep:
            continue
        if folder.is_symlink() or folder.resolve().parent != versions.resolve():
            raise ToolError("Unsafe version cleanup target")
        complete = (folder / "summary.json").is_file() and load(folder / "summary.json").get(
            "state"
        ) == "complete"
        # A legacy failed marker may have been written after pointer publication.
        # Without sufficient history, do not use that marker to discard a complete
        # snapshot whose older activation order can no longer be established.
        if not complete or sufficient:
            shutil.rmtree(folder)


def recover(c, version):
    """Explicitly validate a complete retained snapshot and atomically activate it."""
    with lock(Path(c["data"]) / "update.lock"):
        folder, m = manifest(c, version)
        old_version = current(c)
        if m.get("publication") or (old_version and
            manifest(c, old_version)[1].get("publication")):
            raise ToolError("Bound publication requires coordinated recovery")
        validate_folder(folder, m)
        previous = current(c)
        if previous == version:
            return {"recovered": version, "previous": previous}
        activate(c, version)
        atomic(
            Path(c["data"]) / "freshness.json",
            dict(version=version, status="unchecked_after_recovery", checked_at=None),
        )
        prune(c)
        return {"recovered": version, "previous": previous}
