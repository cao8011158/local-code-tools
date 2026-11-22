"""Start, refresh and serve config-driven local retrieval through CGR."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import replace
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from filelock import FileLock, Timeout

from .cgr_config import Repository, load_config
from .cgr_lexical import CATEGORIES, require_ready
from .cgr_runtime import (
    CGR,
    HERE,
    MODEL,
    MODEL_FILES,
    MODEL_REVISION,
    bind_indexes,
    cgr_environment,
    configure,
    database,
    guard,
    model_snapshot,
    project_filter,
    published_graph_members,
    qdrant,
)
from .cgr_runtime import (
    hybrid_search as search_code,
)
from .cgr_runtime import (
    refresh_index as refresh,
)
from .cgr_runtime import (
    search_docs as search_documents,
)


def ensure_model(config):
    """Fetch public model assets once, before enabling offline inference."""
    config.model_cache.mkdir(parents=True, exist_ok=True)
    cache = config.model_cache / "hub"
    snapshot = model_snapshot(config)
    with FileLock(config.model_cache / "lct-model.lock", timeout=600):
        if not all((snapshot / file).is_file() for file in MODEL_FILES):
            hf = CGR.with_name("hf.exe" if os.name == "nt" else "hf")
            env = dict(
                os.environ,
                HF_HOME=str(config.model_cache),
                HF_HUB_CACHE=str(cache),
                HF_HUB_DISABLE_TELEMETRY="1",
                HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
            )
            env.pop("HF_HUB_OFFLINE", None)
            subprocess.run(
                [str(hf), "download", MODEL, *MODEL_FILES, "--revision", MODEL_REVISION],
                env=env,
                cwd=HERE,
                stdout=sys.stderr,
                check=True,
            )
        ref = snapshot.parent.parent / "refs" / "main"
        ref.parent.mkdir(parents=True, exist_ok=True)
        if not ref.exists() or ref.read_text(encoding="utf-8").strip() != MODEL_REVISION:
            temporary = ref.with_suffix(".lct-tmp")
            temporary.write_text(MODEL_REVISION, encoding="utf-8")
            temporary.replace(ref)


def qdrant_ready(config):
    """Check the configured local server without honoring HTTP proxy settings."""
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(config.qdrant_url + "/readyz", timeout=2) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def ensure_qdrant(config):
    """Reuse the listening service or start the configured local binary."""
    if qdrant_ready(config):
        return "reused"
    if config.qdrant_exe is None or not config.qdrant_exe.is_file():
        raise RuntimeError(
            f"Qdrant is unavailable at {config.qdrant_url}; configure its executable"
        )
    directory = config.qdrant_dir
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(directory / "launch.lock", timeout=45):
        if qdrant_ready(config):
            return "reused"
        endpoint = urlsplit(config.qdrant_url)
        env = {key: value for key, value in os.environ.items() if not key.startswith("QDRANT__")}
        env.update(
            {
                "QDRANT__SERVICE__HOST": endpoint.hostname,
                "QDRANT__SERVICE__HTTP_PORT": str(endpoint.port or 80),
                "QDRANT__SERVICE__GRPC_PORT": "0",
                "QDRANT__TELEMETRY_DISABLED": "true",
                "QDRANT__CLUSTER__ENABLED": "false",
                "QDRANT__STORAGE__STORAGE_PATH": str(directory / "storage"),
            }
        )
        log = directory / "server.log"
        with log.open("ab") as stream:
            proc = subprocess.Popen(
                [str(config.qdrant_exe)],
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
        for _ in range(30):
            if qdrant_ready(config):
                return "started"
            if proc.poll() is not None:
                break
            time.sleep(1)
        raise RuntimeError(f"Qdrant did not become ready; see {log}")


def save_cgr_workspace(config):
    """Register configured roots and durably published additions with the graph MCP."""
    from codebase_rag.workspaces.models import WorkspaceConfig, WorkspaceRepo
    from codebase_rag.workspaces.storage import save_workspace, workspace_path

    projects = [
        alias
        for alias in config.code
        if alias not in config.added_repositories or alias in config.published_repositories
    ]
    workspace = WorkspaceConfig(
        name=config.name,
        repos=[
            WorkspaceRepo(
                path=str(config.repositories[alias].path),
                project_name=config.repositories[alias].name,
            )
            for alias in projects
        ],
    )
    destination = workspace_path(config.name, config.data / "cgr")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.data) as temporary:
        generated = save_workspace(workspace, home=Path(temporary))
        generated.replace(destination)
    return destination


def _publish_ready_workspace_member(config, alias):
    """Write registry and manifest while the caller holds the code guard."""
    with FileLock(config.data / "identity.lock"):
        current = load_config(config.path)
        members = published_graph_members(current)
        registry = config.data / "repository_registry.json"
        saved = json.loads(registry.read_text(encoding="utf-8"))
        if alias not in current.published_repositories:
            saved["published"] = [*current.published_repositories, alias]
            temporary = registry.with_suffix(".tmp")
            temporary.write_text(json.dumps(saved, sort_keys=True), encoding="utf-8")
            temporary.replace(registry)
            current = load_config(config.path)
        # Another registry entry may be waiting for its own interrupted manifest write.
        published = tuple(
            key for key in current.published_repositories if key == alias or key in members
        )
        save_cgr_workspace(replace(current, published_repositories=published))
    return alias not in members


def publish_workspace_member(config, alias):
    """Admit a completed addition only while its index remains ready."""
    with guard(config, alias), database(config, alias) as db:
        require_ready(db, (alias,))
        return _publish_ready_workspace_member(config, alias)


def codex_servers(config):
    """Register the configured MCP names and allow only the core graph tools."""
    prefix = config.mcp_prefix
    entry = ["-m", "lct.entrypoint"]
    return {
        f"{prefix}_graph": {
            "command": str(CGR),
            "args": ["mcp-server", "--read-only", "--workspace", config.name],
            "cwd": str(HERE),
            "env": cgr_environment(config),
            "startup_timeout_sec": 300,
            "tool_timeout_sec": 120,
            "enabled_tools": [
                "resolve",
                "definition",
                "context",
                "callers",
                "callees",
                "list_projects",
            ],
        },
        f"{prefix}_search": {
            "command": sys.executable,
            "args": [*entry, "local-mcp", "--config", str(config.path)],
            "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            "startup_timeout_sec": 120,
            "tool_timeout_sec": 7200,
        },
    }


def register_codex(config):
    """Update only this installation's managed MCP block."""
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    home.mkdir(parents=True, exist_ok=True)
    file = home / "config.toml"
    with FileLock(home / "lct-config.lock", timeout=30):
        old = file.read_bytes() if file.exists() else b""
        source = old.decode("utf-8-sig")
        begin = f"# BEGIN lct {config.name}"
        end = f"# END lct {config.name}"
        marker = re.compile(rf"(?ms)^{re.escape(begin)}\n.*?^{re.escape(end)}\n?")
        if block := marker.search(source):
            previous = tomllib.loads(block.group()).get("mcp_servers", {})
            search_name = next((name for name in previous if name.endswith("_search")), "")
            existing = previous.get(search_name, {})
            graph_env = previous.get(f"{search_name.removesuffix('_search')}_graph", {}).get(
                "env", {}
            )
            same_installation = graph_env.get("CGR_HOME") == str(config.data / "cgr")
            if (
                existing
                and not same_installation
                and existing.get("args", [])[-1:] != [str(config.path)]
            ):
                raise ValueError("This MCP workspace is already registered for a different config")
        source = marker.sub("", source)
        servers = codex_servers(config)
        unmanaged = tomllib.loads(source).get("mcp_servers", {})
        if servers.keys() & unmanaged.keys():
            raise ValueError("Codex already has an unmanaged MCP with this config name")
        lines = [begin]
        for name, settings in servers.items():
            lines.append(f"[mcp_servers.{name}]")
            lines.extend(
                f"{key} = {json.dumps(value, ensure_ascii=False)}"
                for key, value in settings.items()
                if key != "env"
            )
            if "env" in settings:
                lines.append(f"[mcp_servers.{name}.env]")
                lines.extend(
                    f"{key} = {json.dumps(value, ensure_ascii=False)}"
                    for key, value in settings["env"].items()
                )
            lines.append("")
        lines.append(end)
        updated = source.rstrip() + "\n\n" + "\n".join(lines) + "\n"
        tomllib.loads(updated)
        data = updated.encode("utf-8")
        if data != old:
            with tempfile.NamedTemporaryFile(dir=home, prefix=".lct-", delete=False) as tmp:
                tmp.write(data)
                temp = Path(tmp.name)
            try:
                if (file.read_bytes() if file.exists() else b"") != old:
                    raise RuntimeError("Codex configuration changed during registration; retry up")
                temp.replace(file)
            finally:
                temp.unlink(missing_ok=True)
    return str(file)


def reusable(config, project):
    """Check a prior publication and that its graph and point count still exist."""
    with guard(config, project), database(config, project) as db:
        try:
            require_ready(db, [project])
        except RuntimeError:
            return False
        if project == config.doc:
            return True
        if not (config.data / "cgr" / "graph.sqlite").is_file():
            return False
        expected = db.execute("SELECT count(*) FROM entry WHERE project=?", (project,)).fetchone()[
            0
        ]
        collections = qdrant()
        if not collections.collection_exists(config.collection):
            return False
        return (
            collections.count(
                config.collection, count_filter=project_filter(config, [project]), exact=True
            ).count
            == expected
        )


def register_repository(
    config, workspace: str, repo_path: str, project_name: str, project: str | None = None
) -> dict:
    """Serialize registration, build and graph workspace publication for one installation."""
    config.data.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(config.data / "registration.lock", timeout=0):
            return _register_repository(config, workspace, repo_path, project_name, project)
    except Timeout:
        return {"ok": False, "stage": "lock", "error": "repository registration is in use"}


def _register_repository(
    config, workspace: str, repo_path: str, project_name: str, project: str | None
) -> dict:
    """Register one absolute code checkout, refresh it, and publish it to the graph workspace.

    Registration is durable before refresh so a failed build can be retried with the
    same inputs or by refresh_index. Existing checkout identities cannot be remapped.
    The running graph MCP must restart to reload its workspace membership.
    """
    if workspace != config.name:
        raise ValueError(f"workspace must equal {config.name!r}")
    if not Path(repo_path).is_absolute():
        raise ValueError("repo_path must be an absolute checkout path")
    root = Path(repo_path).resolve(strict=True)
    if not root.is_dir() or not (root / ".git").exists():
        raise ValueError("repo_path must be the exact absolute Git checkout root")
    checkout = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    if Path(checkout.stdout.strip()).resolve() != root:
        raise ValueError("repo_path must be the exact absolute Git checkout root")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_name):
        raise ValueError("project_name must be a CGR project name")
    alias = project or project_name
    if not re.fullmatch(r"[A-Za-z0-9_-]+", alias):
        raise ValueError("project must be a repository alias")

    config.data.mkdir(parents=True, exist_ok=True)
    already_added = False
    with FileLock(config.data / "identity.lock"):
        current = load_config(config.path)
        identity = config.data / "identity.json"
        if identity.exists() and identity.read_text(encoding="utf-8") != current.index_identity():
            raise ValueError(f"Index ownership differs at {config.data}; choose a new index_dir")
        for key, repo in current.repositories.items():
            if key == alias:
                if repo.path != root or repo.name != project_name or repo.kind != "code":
                    raise ValueError(f"Repository alias {alias!r} already has a different identity")
                if key not in current.added_repositories:
                    raise ValueError(f"Repository alias {alias!r} is configured; use refresh_index")
                already_added = True
                break
            if repo.name == project_name:
                raise ValueError(f"CGR project name {project_name!r} is already registered")
            if root == repo.path or root in repo.path.parents or repo.path in root.parents:
                raise ValueError(f"Checkout overlaps registered repository {key!r}")
        else:
            base_identity = current.index_identity()
            current.repositories[alias] = Repository(root, "code", project_name, (), ())
            registry = config.data / "repository_registry.json"
            added = {
                key: [str(repo.path), repo.kind, repo.name, repo.exclude, repo.exclude_dirs]
                for key, repo in current.repositories.items()
                if key in (*current.added_repositories, alias)
            }
            temporary = registry.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "base_identity": base_identity,
                        "repos": added,
                        "published": current.published_repositories,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            temporary.replace(registry)
    current = load_config(config.path)
    if already_added:
        with guard(current, alias), database(current, alias) as db:
            try:
                published = require_ready(db, (alias,))[0]
            except RuntimeError:
                pass
            else:
                first = _publish_ready_workspace_member(current, alias)
                return {
                    **published,
                    "ok": True,
                    "project": alias,
                    "already_indexed": True,
                    "graph_mcp_restart_required": first,
                }
    ensure_model(current)
    ensure_qdrant(current)
    result = refresh(current, alias)
    if result["ok"]:
        result["graph_mcp_restart_required"] = publish_workspace_member(current, alias)
    return result


def refresh_registered(config, project):
    """Refresh a project and republish graph workspace membership after an added build."""
    result = refresh(config, project)
    if result["ok"] and project in config.added_repositories:
        result["graph_mcp_restart_required"] = publish_workspace_member(config, project)
    return result


def up(config):
    """Start Qdrant, prepare missing indexes and configure Codex once ready."""
    started = time.perf_counter()
    ensure_model(config)
    configure(config)
    service = ensure_qdrant(config)
    repos = {}
    for project in config.repositories:
        if reusable(config, project):
            if project in config.added_repositories and project not in published_graph_members(
                config
            ):
                publish_workspace_member(config, project)
            repos[project] = {"reused": True}
            print(f"{project}: reused", file=sys.stderr, flush=True)
            continue
        print(f"{project}: refreshing", file=sys.stderr, flush=True)
        result = refresh_registered(config, project)
        repos[project] = result
        if not result["ok"]:
            return {"ok": False, "qdrant": service, "repos": repos}
    with guard(config, config.code[0]), FileLock(config.data / "identity.lock"):
        current = load_config(config.path)
        save_cgr_workspace(
            replace(current, published_repositories=published_graph_members(current))
        )
    file = register_codex(config)
    return {
        "ok": True,
        "qdrant": service,
        "collection": config.collection,
        "repos": repos,
        "codex_config": file,
        "mcp_servers": list(codex_servers(config)),
        "seconds": round(time.perf_counter() - started, 3),
    }


def serve(config):
    """Expose search, refresh and additive repository indexing through stdio."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    server = MCPServer("Local Code Tools")

    def current_config():
        """Load durable repository membership for each request in an existing MCP process."""
        current = load_config(config.path)
        bind_indexes(current)
        return current

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def hybrid_search(query: str, top_k: int = 5, project: str | None = None) -> list[dict]:
        """Find code nodes using vector search and BM25.

        For project, use a CGR project name returned by the graph MCP's list_projects.
        LCT code aliases are also accepted. Omit project to search all configured
        code projects. Pass the hit's graph_project as project and its qualified_name
        as qualified_name when calling a graph tool.
        """
        try:
            return search_code(current_config(), query, top_k, project)
        except ValueError as error:
            raise ToolError(str(error)) from error

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def search_docs(query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        """Find Markdown sections. Categories are contract, implementation, history, experiment."""
        return search_documents(current_config(), query, top_k, category)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def refresh_index(project: str) -> dict:
        """Refresh a configured repository alias after local changes."""
        return refresh_registered(current_config(), project)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def index_repository(
        workspace: str, repo_path: str, project_name: str, project: str | None = None
    ) -> dict:
        """Index a Git checkout in this workspace; project defaults to project_name.

        Pass the exact absolute checkout root and a unique CGR project name. A
        successful result requires restarting the separate read-only graph MCP.
        """
        try:
            return register_repository(
                current_config(), workspace, repo_path, project_name, project
            )
        except (ValueError, OSError) as error:
            raise ToolError(str(error)) from error

    server.run()


COMMANDS = {"up", "refresh", "hybrid-search", "doc-search", "graph-mcp", "local-mcp"}


def main(argv=None):
    """Dispatch the CGR runtime without importing any legacy parser or index."""
    parser = argparse.ArgumentParser(prog="lct")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in sorted(COMMANDS):
        sub = commands.add_parser(command)
        sub.add_argument("--config", required=True)
        if command in {"hybrid-search", "doc-search"}:
            sub.add_argument("query")
            sub.add_argument("--top-k", type=int, default=5)
        if command in {"hybrid-search", "refresh"}:
            sub.add_argument("--project", required=command == "refresh")
        if command == "doc-search":
            sub.add_argument("--category", choices=CATEGORIES)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        bind_indexes(config)
        if args.command == "graph-mcp":
            configure(config)
            return subprocess.call(
                [str(CGR), "mcp-server", "--read-only", "--workspace", config.name],
                cwd=HERE,
            )
        if args.command == "local-mcp":
            serve(config)
            return 0
        if args.command == "up":
            result = up(config)
        elif args.command == "refresh":
            result = refresh_registered(config, args.project)
        elif args.command == "hybrid-search":
            result = search_code(config, args.query, args.top_k, args.project)
        else:
            result = search_documents(config, args.query, args.top_k, args.category)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(result, dict) and not result.get("ok", True) else 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
