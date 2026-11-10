"""Call the installed LCT MCP pair through Codex App Server without a model turn."""

import argparse
import json
import os
import queue
import re
import subprocess
import threading
import tomllib
from pathlib import Path


class Codex:
    """Send JSON-RPC requests to the locally installed Codex CLI."""

    def __init__(self, config_name):
        """Launch Codex with the two requested MCP servers for this probe."""
        home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        servers = tomllib.loads((home / "config.toml").read_text(encoding="utf-8-sig")).get(
            "mcp_servers", {}
        )
        allowed = {f"lct_{config_name}_{name}" for name in ("graph", "search")}
        command = ["codex"]
        for name in servers.keys() - allowed:
            if re.fullmatch(r"[A-Za-z0-9_-]+", name):
                command += ["-c", f"mcp_servers.{name}.enabled=false"]
        self.process = subprocess.Popen(
            [*command, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
        self.incoming = queue.Queue()
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        """Forward each JSON-RPC message from the app server."""
        for line in self.process.stdout:
            self.incoming.put(json.loads(line))
        self.incoming.put(None)

    def send(self, message):
        """Write one request or notification."""
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def rpc(self, method, params):
        """Wait for the matching response, ignoring notifications."""
        self.next_id += 1
        self.send({"id": self.next_id, "method": method, "params": params})
        while True:
            response = self.incoming.get(timeout=360)
            if response is None:
                raise RuntimeError("Codex app-server closed stdout")
            if response.get("id") == self.next_id:
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response["result"]

    def close(self):
        """Shut down the ephemeral app server."""
        self.process.terminate()
        self.process.wait(timeout=10)


def call(codex, thread, server, tool, args):
    """Call one MCP tool and decode either structured or text results."""
    result = codex.rpc(
        "mcpServer/tool/call",
        {
            "threadId": thread,
            "server": server,
            "tool": tool,
            "arguments": args,
        },
    )
    if result.get("isError"):
        raise RuntimeError(result)
    if result.get("structuredContent") is not None:
        value = result["structuredContent"]
        return value.get("result", value) if isinstance(value, dict) else value
    items = [
        json.loads(content["text"]) for content in result["content"] if content["type"] == "text"
    ]
    return items[0] if len(items) == 1 else items


def main():
    """Verify Codex discovery, hybrid-to-graph handoff and optional DOC search."""
    parser = argparse.ArgumentParser()
    parser.add_argument("config_name")
    parser.add_argument("query")
    parser.add_argument("--project")
    parser.add_argument("--target-suffix")
    parser.add_argument("--docs")
    args = parser.parse_args()
    codex = Codex(args.config_name)
    try:
        codex.rpc(
            "initialize",
            {
                "clientInfo": {
                    "name": "lct-local-acceptance",
                    "version": "1.0",
                }
            },
        )
        codex.send({"method": "initialized"})
        thread = codex.rpc("thread/start", {"cwd": str(Path.cwd()), "ephemeral": True})["thread"][
            "id"
        ]
        search = f"lct_{args.config_name}_search"
        graph = f"lct_{args.config_name}_graph"
        tool_lists = {}
        for name in (graph, search):
            status = codex.rpc(
                "mcpServerStatus/list",
                {
                    "threadId": thread,
                    "serverName": name,
                    "detail": "toolsAndAuthOnly",
                },
            )
            tools = status["data"][0]["tools"]
            tool_lists[name] = (
                list(tools) if isinstance(tools, dict) else [t["name"] for t in tools]
            )
        assert set(tool_lists[search]) == {"hybrid_search", "search_docs", "refresh_index"}
        assert {"definition", "callees", "callers", "context", "resolve"} <= set(
            tool_lists[graph]
        ), tool_lists
        assert "semantic_search" not in tool_lists[graph]
        filters = {"query": args.query}
        if args.project:
            filters["project"] = args.project
        hits = call(codex, thread, search, "hybrid_search", filters)
        if args.project:
            assert all(hit["project"] == args.project for hit in hits)
        hit = next(hit for hit in hits if hit["qualified_name"].endswith(args.target_suffix or ""))
        callees = call(
            codex,
            thread,
            graph,
            "callees",
            {
                "project": hit["graph_project"],
                "qualified_name": hit["qualified_name"],
                "depth": 2,
            },
        )
        result = {"hits": hits, "callees_depth_2": callees}
        if args.docs:
            docs = call(codex, thread, search, "search_docs", {"query": args.docs, "top_k": 1})
            result["docs"] = [
                {key: value for key, value in row.items() if key != "excerpt"} for row in docs
            ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        codex.close()


if __name__ == "__main__":
    main()
