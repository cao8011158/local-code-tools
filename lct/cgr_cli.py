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
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from filelock import FileLock

from .cgr_config import load_config
from .cgr_lexical import CATEGORIES, require_ready
from .cgr_runtime import (
    CGR,
    HERE,
    bind_indexes,
    cgr_environment,
    configure,
    database,
    guard,
    project_filter,
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

MODEL = "microsoft/unixcoder-base"
MODEL_REVISION = "5604afdc964f6c53782a6813140ade5216b99006"
MODEL_FILES = ("config.json", "vocab.json", "merges.txt", "pytorch_model.bin")


def ensure_model(config):
    """Fetch public model assets once, before enabling offline inference."""
    config.model_cache.mkdir(parents=True, exist_ok=True)
    cache = config.model_cache / "hub"
    repo = cache / "models--microsoft--unixcoder-base"
    snapshot = repo / "snapshots" / MODEL_REVISION
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
        ref = repo / "refs" / "main"
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
    """Register all code checkout roots with the official read-only MCP."""
    from codebase_rag.workspaces.models import WorkspaceConfig, WorkspaceRepo
    from codebase_rag.workspaces.storage import save_workspace

    workspace = WorkspaceConfig(
        name=config.name,
        repos=[
            WorkspaceRepo(
                path=str(config.repositories[alias].path),
                project_name=config.repositories[alias].name,
            )
            for alias in config.code
        ],
    )
    return save_workspace(workspace)


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
    """Update only this installation's managed block and requested legacy flags."""
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
        for name in config.disable_legacy:
            if name in unmanaged and unmanaged[name].get("enabled", True):
                section = re.compile(rf"(?m)^\[mcp_servers\.{re.escape(name)}\][^\n]*\n")
                match = section.search(source)
                if match is None:
                    raise ValueError(f"Cannot locate legacy Codex config section {name}")
                next_section = re.search(r"(?m)^\[", source[match.end() :])
                end_at = match.end() + next_section.start() if next_section else len(source)
                block = source[match.end() : end_at]
                block, count = re.subn(r"(?m)^\s*enabled\s*=.*$", "enabled = false", block)
                if count == 0:
                    block = "enabled = false\n" + block
                source = source[: match.end()] + block + source[end_at:]
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


def up(config):
    """Start Qdrant, prepare missing indexes and configure Codex once ready."""
    started = time.perf_counter()
    ensure_model(config)
    configure(config)
    service = ensure_qdrant(config)
    repos = {}
    for project in config.repositories:
        if reusable(config, project):
            repos[project] = {"reused": True}
            print(f"{project}: reused", file=sys.stderr, flush=True)
            continue
        print(f"{project}: refreshing", file=sys.stderr, flush=True)
        result = refresh(config, project)
        repos[project] = result
        if not result["ok"]:
            return {"ok": False, "qdrant": service, "repos": repos}
    save_cgr_workspace(config)
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
    """Expose only the three supplemental tools through stdio."""
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    server = MCPServer("Local Code Tools")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def hybrid_search(query: str, top_k: int = 5, project: str | None = None) -> list[dict]:
        """Find graph nodes. Pass qualified_name and graph_project to the graph MCP."""
        return search_code(config, query, top_k, project)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def search_docs(query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        """Find Markdown sections. Categories are contract, implementation, history, experiment."""
        return search_documents(config, query, top_k, category)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def refresh_index(project: str) -> dict:
        """Refresh a configured repository alias after local changes."""
        return refresh(config, project)

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
            result = refresh(config, args.project)
        elif args.command == "hybrid-search":
            result = search_code(config, args.query, args.top_k, args.project)
        else:
            result = search_documents(config, args.query, args.top_k, args.category)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(result, dict) and not result.get("ok", True) else 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
