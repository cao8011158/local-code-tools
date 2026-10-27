"""Fail-closed maintenance publication across independent graph and retrieval MCP endpoints."""

import uuid
from pathlib import Path

from codebase_rag.integration.api import build_snapshot
from codebase_rag.integration.model import verify_sources
from codebase_rag.integration.neo4j import Neo4jGraph

from lct.common import ToolError, atomic, canonical, digest, load, lock, now

from .retrieval import CanonicalQuery, build
from .services import OfficialMCP


def credentials(c):
    """Read only a local ignored credential file; never include secrets in version manifests."""
    auth = load(c["auth_file"])
    if auth["uri"] != c["uri"]:
        raise ValueError("Native auth target mismatch")
    home = Path(c["owned_home"]).resolve()
    marker = load(home / ".lct-code-graph-owned.json")
    if Path(auth["home"]).resolve() != home or Path(marker["home"]).resolve() != home:
        raise ValueError("Not the explicitly owned native Neo4j instance")
    if not c["uri"].startswith("bolt://127.0.0.1:") or not c["namespace"].startswith(
        "lct-fixture-"
    ):
        raise ValueError(
            "This reviewed first version permits only owned loopback fixture namespaces"
        )
    return (auth["user"], auth["password"])


class Coordinator:
    """All LCT reads take the same OS lock; official MCP is stopped/drained before writer entry."""

    def __init__(self, c):
        self.c = c
        import json
        from importlib.metadata import distribution

        import codebase_rag.integration as cgr_api

        direct = json.loads(distribution("code-graph-rag").read_text("direct_url.json") or "{}")
        if direct.get("vcs_info", {}).get("commit_id") != c["cgr_commit"]:
            raise ValueError(
                "CGR must be installed from the configured full Git commit, not editable or floating main"
            )
        self.cgr_files = {
            p.name: digest(p.read_bytes()) for p in Path(cgr_api.__file__).parent.glob("*.py")
        }
        self.data = Path(c["data"]).resolve()
        from lct.common import ROOT

        legacy = (ROOT / "data").resolve()
        if self.data == legacy or self.data.is_relative_to(legacy):
            raise ValueError("The preserved legacy data directory is forbidden")
        marker = self.data / "integration-owned.json"
        ownership = dict(namespace=c["namespace"], uri=c["uri"])
        if self.data.exists() and any(self.data.iterdir()) and not marker.exists():
            raise ValueError("Refusing a nonempty unowned integration data directory")
        self.data.mkdir(parents=True, exist_ok=True)
        if marker.exists() and load(marker) != ownership:
            raise ValueError("Integration data ownership mismatch")
        if not marker.exists():
            atomic(marker, ownership)
        self.graph = Neo4jGraph(
            c["uri"], c["namespace"], credentials(c), c.get("database", "neo4j"), seconds=30
        )
        self.official = OfficialMCP(c, self.graph)
        self.query = CanonicalQuery(c)
        self.state_path = self.data / "publication.json"
        # A fresh process must not revive official MCP after a failed/incomplete build.
        if self.state()["state"] != "PUBLISHED":
            self.official.stop()

    def close(self):
        self.graph.close()

    def state(self):
        return load(self.state_path) if self.state_path.exists() else dict(state="EMPTY")

    def status(self):
        state = self.state()
        return dict(
            state,
            official_running=self.official.process() is not None,
            graph_snapshot=self.graph.active(),
        )

    def _check(self, expected_version=None):
        state = self.state()
        if state["state"] != "PUBLISHED":
            raise ToolError("Maintenance/unavailable: " + state["state"])
        if expected_version and state["version"] != expected_version:
            raise ToolError(
                f"Version mismatch: expected={expected_version}; actual={state['version']}"
            )
        binding = load(self.data / "versions" / state["version"] / "binding.json")
        actual = {p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob("*.py")}
        if (
            binding["adapter"] != actual
            or binding["cgr_commit"] != self.c["cgr_commit"]
            or binding["cgr_files"] != self.cgr_files
        ):
            raise ToolError(
                "Published adapter/CGR version is incompatible; maintenance rebuild required"
            )
        _, metadata = self.query.snapshot(state["version"])
        if (
            metadata["graph_snapshot"] != state["graph_snapshot"]
            or metadata["source_fingerprint"] != state["source_snapshot"]
            or binding["graph"] != state["graph_snapshot"]
            or binding["source"] != state["source_snapshot"]
            or binding["build_key"] != state["build_key"]
        ):
            raise ToolError("Graph/source/manifest binding mismatch")
        pointer = load(self.data / "current.json")
        graph = self.graph.read(
            "MATCH(s:CGScope {key:$ns}) RETURN s.active AS active,s.build_version AS build"
        )
        if (
            pointer["version"] != state["version"]
            or not graph
            or graph[0]["active"] != state["graph_snapshot"]
            or graph[0]["build"] != state["version"]
        ):
            raise ToolError("Published graph/retrieval versions do not agree")
        return state

    def call(self, method, expected_version=None, **kwargs):
        """Never expose the inherited graph-query API or inventory refresh through this MCP."""
        if method not in {"search_code", "search_docs", "get_nodes"}:
            raise ValueError("Unsupported retrieval operation")
        with lock(self.data / "publication.lock"):
            state = self._check(expected_version)
            if kwargs.get("version") and kwargs["version"] != state["version"]:
                raise ToolError(
                    "Retained retrieval snapshot is not the currently published graph version"
                )
            result = getattr(self.query, method)(**kwargs)
            if result["version"] != state["version"]:
                raise ToolError("Cursor refers to obsolete publication")
            result.update(
                graph_snapshot=state["graph_snapshot"], source_snapshot=state["source_snapshot"]
            )
            return result

    def update(self, fail_at=None):
        """Reparse fixed explicit files; any exception leaves both services unavailable until retry."""
        with lock(self.data / "publication.lock"):
            previous = self.state()
            atomic(
                self.state_path,
                dict(state="BUILDING", previous=previous.get("version"), started=now()),
            )
            try:
                # Closing the owned official listener breaks keepalive connections before any DML.
                self.official.stop()
                if fail_at == "drain":
                    raise RuntimeError("Injected drain refusal")
                self.graph.setup()
                old = (
                    load(self.data / "last-capture.json")
                    if (self.data / "last-capture.json").exists()
                    else None
                )
                bundle = build_snapshot(self.c["repositories"], self.c.get("mode", "jedi"), old)
                documents = []
                for repo in self.c["repositories"]:
                    for rel in repo.get("documents", []):
                        path = (Path(repo["path"]) / rel).resolve()
                        path.relative_to(Path(repo["path"]).resolve())
                        if path.suffix != ".md" or path.is_symlink():
                            raise ValueError("Explicit non-symlink DOC required")
                        raw = path.read_bytes()
                        documents.append(
                            dict(
                                repository=repo["name"],
                                path=rel,
                                text=raw.decode("utf-8-sig"),
                                sha256=digest(raw),
                                absolute=str(path),
                                kind="markdown",
                            )
                        )
                bundle["retrieval_source_snapshot_id"] = digest(
                    canonical(
                        dict(
                            python=bundle["source_snapshot_id"],
                            documents=[
                                (d["repository"], d["path"], d["sha256"]) for d in documents
                            ],
                        )
                    )
                )
                identity_record = dict(
                    graph=bundle["snapshot_id"],
                    source=bundle["retrieval_source_snapshot_id"],
                    code_source=bundle["source_snapshot_id"],
                    cgr_files=self.cgr_files,
                    documents=[(d["repository"], d["path"], d["sha256"]) for d in documents],
                    config={
                        k: v for k, v in self.c.items() if k not in {"auth_file", "owned_home"}
                    },
                    adapter={
                        p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob("*.py")
                    },
                    cgr_commit=self.c["cgr_commit"],
                )
                build_key = digest(canonical(identity_record))
                # Unique build attempt dirs preserve failed candidates; content identity remains separate.
                version = build_key[:24] + "-" + uuid.uuid4().hex[:8]
                self.graph.build(bundle, fail_at="batch" if fail_at == "graph" else None)
                if fail_at == "after_graph":
                    raise RuntimeError("Injected after graph commit")
                m = build(self.c, bundle, documents, version)
                if fail_at == "retrieval":
                    raise RuntimeError("Injected after retrieval verification")
                verify_sources(bundle)
                for d in documents:
                    if digest(Path(d["absolute"]).read_bytes()) != d["sha256"]:
                        raise ValueError("DOC changed")
                if fail_at == "before_publish":
                    raise RuntimeError("Injected before pointer publication")
                # Independent stores are safe only inside the closed maintenance window.
                self.graph.read(
                    "MATCH(s:CGScope {key:$ns}) SET s.build_version=$version", version=version
                )
                atomic(
                    self.data / "current.json",
                    dict(version=version, previous=previous.get("version")),
                )
                atomic(self.data / "last-capture.json", dict(file_hashes=bundle["file_hashes"]))
                atomic(
                    self.data / "freshness.json",
                    dict(version=version, status="matched_at_check", checked_at=now()),
                )
                atomic(
                    self.data / "versions" / version / "binding.json",
                    dict(build_key=build_key, **identity_record),
                )
                state = dict(
                    state="PUBLISHED",
                    version=version,
                    graph_snapshot=bundle["snapshot_id"],
                    source_snapshot=bundle["retrieval_source_snapshot_id"],
                    code_source_snapshot=bundle["source_snapshot_id"],
                    build_key=build_key,
                    completed=now(),
                    synthetic_fixture=self.c["synthetic_fixture"],
                )
                atomic(self.state_path, state)
                if fail_at == "restart":
                    raise RuntimeError("Injected before official restart")
                self.official.start()
                return dict(state, retrieval=m)
            except BaseException:
                atomic(
                    self.state_path,
                    dict(state="FAILED", previous=previous.get("version"), failed=now()),
                )
                # If stop itself failed, do not attempt new mutation or reopen either endpoint.
                raise
