"""Own one loopback official Neo4j HTTP MCP process; stop and drain before graph writes."""

import os
import socket
import subprocess
import time
from pathlib import Path

import psutil
from neo4j_mcp_server import get_binary_path

from lct.common import atomic, load


class OfficialMCP:
    """No forwarding/proxy: manage the official executable and keep requests independent."""

    def __init__(self, c, graph):
        self.c = c
        self.graph = graph
        self.state = Path(c["data"]) / "official-process.json"

    def process(self):
        if not self.state.exists():
            return None
        record = load(self.state)
        if not psutil.pid_exists(record["pid"]):
            return None
        p = psutil.Process(record["pid"])
        if (
            abs(p.create_time() - record["created"]) > 0.01
            or Path(p.exe()).resolve() != Path(record["exe"]).resolve()
        ):
            raise RuntimeError("Official MCP process identity mismatch; refusing to terminate")
        return p

    def stop(self):
        """Close existing HTTP connections and terminate owned requests; drain database transactions."""
        p = self.process()
        if p:
            children = p.children(recursive=True)
            p.terminate()
            gone, alive = psutil.wait_procs([p] + children, timeout=10)
            for child in alive:
                child.kill()
            _, alive = psutil.wait_procs(alive, timeout=5)
            if alive:
                raise RuntimeError("Official process did not stop")
        # Refuse an unmanaged listener. Never terminate a process selected only by its port.
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", self.c["official_port"])) == 0:
                raise RuntimeError("Unmanaged listener occupies official MCP port")
        deadline = time.monotonic() + self.c.get("drain_seconds", 15)
        while True:
            rows = self.graph.read(
                'SHOW TRANSACTIONS YIELD transactionId,currentQuery WHERE currentQuery IS NOT NULL AND NOT currentQuery STARTS WITH "SHOW TRANSACTIONS" RETURN transactionId,currentQuery'
            )
            if not rows:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Database requests have not drained; no graph mutation permitted"
                )
            time.sleep(0.05)

    def start(self):
        """Loopback only; HTTP clients authenticate to the official server using Neo4j credentials."""
        if self.process():
            return
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", self.c["official_port"])) == 0:
                raise RuntimeError("Refusing unmanaged official MCP listener")
        executable = str(get_binary_path())
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("NEO4J")}
        env["NEO4J_MCP_URI"] = self.c["uri"]
        args = [
            executable,
            "--uri",
            self.c["uri"],
            "--database",
            self.c.get("database", "neo4j"),
            "--read-only",
            "true",
            "--telemetry",
            "false",
            "--transport-mode",
            "http",
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(self.c["official_port"]),
        ]
        with (Path(self.c["data"]) / "official.log").open("ab") as log:
            p = subprocess.Popen(
                args,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        process = psutil.Process(p.pid)
        atomic(
            self.state,
            dict(pid=p.pid, created=process.create_time(), exe=str(Path(executable).resolve())),
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if p.poll() is not None:
                raise RuntimeError("Official MCP exited; inspect private local official.log")
            with socket.socket() as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(("127.0.0.1", self.c["official_port"])) == 0:
                    return
            time.sleep(0.05)
        self.stop()
        raise RuntimeError("Official MCP start timed out")
