"""CLI adapter; queries call the same Query implementation as the MCP tools."""

import argparse
import json
import sys

from .common import ToolError, config
from .query import Query
from .storage import attach_dense, build, estimate, migrate_metadata, recover


def main():
    """Dispatch build/status/query/portable management; return nonzero for explicit errors."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("build", "update"):
        s = commands.add_parser(name)
        s.add_argument("--offline", action="store_true")
        s.add_argument("--lexical-only", action="store_true")
    s = commands.add_parser("update-coordinated")
    s.add_argument("--namespace", required=True)
    s.add_argument("--database", required=True)
    s.add_argument("--offline", action="store_true")
    s = commands.add_parser("bind-current-graph")
    s.add_argument("--namespace", required=True)
    s.add_argument("--database", required=True)
    commands.add_parser("publication-current")
    s = commands.add_parser("publication-official-requests")
    s.add_argument("ids", nargs="+")
    s.add_argument("--direction", choices=("in", "out", "both"), default="both")
    s.add_argument("--limit", type=int, default=100)
    s = commands.add_parser("attach-dense", help="Attach vectors to an expected frozen lexical version")
    s.add_argument("--version", dest="expected_version", required=True)
    s.add_argument("--expected-program-hash")
    s.add_argument("--offline", action="store_true")
    commands.add_parser("estimate")
    s = commands.add_parser("status")
    s.add_argument("--refresh", action="store_true")
    s = commands.add_parser("graph-evidence")
    s.add_argument("--version")
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--max-bytes", type=int, default=100000)
    s = commands.add_parser("migrate-metadata")
    s.add_argument("--version", required=True)
    s.add_argument("--expected-program-hash", required=True)
    for name in ("search-code", "search-docs"):
        s = commands.add_parser(name)
        s.add_argument("query")
        s.add_argument("--repo", action="append", dest="repositories")
        s.add_argument("--candidates", type=int, default=50)
        s.add_argument("--limit", type=int, default=10)
        s.add_argument("--cursor")
        s.add_argument("--version")
        if name == "search-code":
            s.add_argument(
                "--level", choices=["module", "class", "function", "all"], default="function"
            )
            s.add_argument("--mode", choices=["dense", "bm25", "rrf"], default="rrf")
            s.add_argument("--exact", action="store_true")
            s.add_argument("--include-tests", action="store_true")
        else:
            s.add_argument(
                "--category", choices=["contract", "implementation", "history", "experiment"]
            )
    s = commands.add_parser("get-nodes")
    s.add_argument("node_ids", nargs="+")
    s.add_argument("--version")
    s.add_argument("--no-source", action="store_false", dest="include_source")
    s.add_argument("--max-bytes", type=int, default=64000)
    s = commands.add_parser("relations")
    s.add_argument("node_ids", nargs="+")
    s.add_argument("--type", action="append", dest="relation_types")
    s.add_argument("--direction", choices=["in", "out", "both"], default="out")
    s.add_argument("--depth", type=int, default=1)
    s.add_argument("--max-nodes", type=int, default=100)
    s.add_argument("--max-edges", type=int, default=200)
    s.add_argument("--max-bytes", type=int, default=100000)
    s.add_argument("--version")
    s = commands.add_parser("recover")
    s.add_argument("version")
    commands.add_parser("backup")
    s = commands.add_parser("restore")
    s.add_argument("archive")
    s.add_argument("destination")
    commands.add_parser("gc")
    commands.add_parser("mcp")
    args = vars(p.parse_args())
    c = config(args.pop("config"))
    command = args.pop("command")
    core = Query(c)
    try:
        if command in ("build", "update"):
            out = build(c, **args)
        elif command in ("update-coordinated", "bind-current-graph", "publication-current",
                         "publication-official-requests"):
            from .publication import bind_current, coordinated_update, resolve_current

            if command == "update-coordinated":
                out = coordinated_update(c, **args)
            elif command == "bind-current-graph":
                out = bind_current(c, **args)
            else:
                binding = resolve_current(c)
                if command == "publication-current":
                    out = binding
                else:
                    from .official_mcp import read_cypher_requests

                    out = read_cypher_requests(binding["namespace"], binding["version"],
                        args["ids"], binding["fingerprint"], direction=args["direction"],
                        limit=args["limit"])
        elif command == "attach-dense":
            out = attach_dense(c, **args)
        elif command == "estimate":
            out = estimate(c)
        elif command == "status":
            out = core.index_status(**args)
        elif command == "graph-evidence":
            out = core.graph_evidence(**args)
        elif command == "migrate-metadata":
            out = migrate_metadata(c, **args)
        elif command == "search-code":
            out = core.search_code(**args)
        elif command == "search-docs":
            out = core.search_docs(**args)
        elif command == "get-nodes":
            out = core.get_nodes(**args)
        elif command == "relations":
            out = core.get_relations(**args)
        elif command == "recover":
            out = recover(c, **args)
        elif command in ("backup", "restore", "gc"):
            from . import management

            out = getattr(management, command)(c, **args)
        elif command == "mcp":
            import os

            os.environ["LCT_CONFIG"] = c["_path"]
            from .mcp_server import main as serve

            serve()
            return
        print(json.dumps(out, ensure_ascii=False, indent=2))
    except (ToolError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
