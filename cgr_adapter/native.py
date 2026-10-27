"""Start a fresh Windows-native Neo4j distribution; never modify an existing user DB."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
from pathlib import Path

import psutil


def record_process(state, home, pid):
    """Bind the helper's JVM to PID creation time, executable and owned home."""
    process = psutil.Process(pid)
    command = " ".join(process.cmdline())
    if (
        Path(process.exe()).name != "java.exe"
        or str(home) not in command
        or "Neo4jBoot" not in command
    ):
        raise ValueError("Native JVM ownership could not be established")
    (state / "native-pid.json").write_text(
        json.dumps(dict(pid=pid, home=str(home), created=process.create_time(), exe=process.exe())),
        encoding="utf-8",
    )


def stop(home, state):
    """Stop only the explicitly owned disposable native JVM tree, never all Java processes."""
    home = Path(home).resolve()
    state = Path(state).resolve()
    marker = json.loads((home / ".lct-code-graph-owned.json").read_text(encoding="utf-8"))
    if Path(marker["home"]).resolve() != home or Path(marker["state"]).resolve() != state:
        raise ValueError("Owned native instance metadata mismatch")
    record = json.loads((state / "native-pid.json").read_text(encoding="utf-8"))
    if not psutil.pid_exists(record["pid"]):
        return dict(status="stopped")
    process = psutil.Process(record["pid"])
    if (
        abs(process.create_time() - record["created"]) > 0.01
        or process.exe() != record["exe"]
        or str(home) not in " ".join(process.cmdline())
    ):
        raise ValueError("Native PID identity mismatch; no process stopped")
    children = []
    console = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/conhost.exe"
    for child in process.children(recursive=True):
        executable = Path(child.exe())
        if executable == console:
            # Owned JVM console hosts exit with their JVM; never terminate them by name.
            continue
        if executable.name != "java.exe" or str(home) not in " ".join(child.cmdline()):
            raise ValueError("Unexpected native process child; refusing stop")
        children.append(child)
    for child in children:
        child.terminate()
    process.terminate()
    _, alive = psutil.wait_procs(children + [process], timeout=20)
    if alive:
        raise RuntimeError("Owned native JVM stop timed out")
    return dict(status="stopped")


def start(home, java_home, state, port=17687, guava_jar=None):
    """Keep data/config/logs in the explicitly owned distribution; do not install a service."""
    home = Path(home).resolve()
    java_home = Path(java_home).resolve()
    state = Path(state).resolve()
    marker = home / ".lct-code-graph-owned.json"
    java = java_home / "bin/java.exe"
    if not java.is_file() or not (home / "lib/neo4j-bootcheck-5.26.12.jar").exists():
        raise ValueError("Use native Neo4j 5.26.12 and Java 21")
    if not marker.exists():
        if any((home / "data/databases").rglob("*")):
            raise ValueError("Refusing to configure an existing database")
        state.mkdir(parents=True, exist_ok=True)
        password = secrets.token_urlsafe(32)
        auth = dict(
            user="neo4j",
            password=password,
            uri=f"bolt://127.0.0.1:{port}",
            home=str(home),
            port=port,
        )
        (state / "native-auth.json").write_text(json.dumps(auth), encoding="utf-8")
        marker.write_text(
            json.dumps(dict(home=str(home), state=str(state), port=port)), encoding="utf-8"
        )
        config = (
            "\n".join(
                [
                    "server.default_listen_address=127.0.0.1",
                    f"server.bolt.listen_address=127.0.0.1:{port}",
                    f"server.bolt.advertised_address=127.0.0.1:{port}",
                    "server.http.listen_address=127.0.0.1:17474",
                    "server.http.advertised_address=127.0.0.1:17474",
                    "server.https.enabled=false",
                    "server.memory.heap.initial_size=256m",
                    "server.memory.heap.max_size=512m",
                    "server.memory.pagecache.size=128m",
                    "dbms.usage_report.enabled=false",
                    "dbms.security.procedures.unrestricted=apoc.meta.*",
                ]
            )
            + "\n"
        )
        (home / "conf/neo4j.conf").write_text(config, encoding="utf-8")
        plugin = home / "labs/apoc-5.26.12-core.jar"
        shutil.copy2(plugin, home / "plugins" / plugin.name)
    else:
        owned = json.loads(marker.read_text(encoding="utf-8"))
        if owned != {"home": str(home), "state": str(state), "port": port}:
            raise ValueError("Owned native instance metadata mismatch")
    expected = "f3d7f57f67fd622f4d468dfdd692b3a5e3909246c28017ac3263405f0fe617ed"
    destination = home / "plugins/guava-33.4.8-jre.jar"
    selected = Path(guava_jar) if guava_jar else destination
    if not selected.is_file() or hashlib.sha256(selected.read_bytes()).hexdigest() != expected:
        raise ValueError(
            "Supply the pinned Guava 33.4.8-jre jar required by this APOC distribution"
        )
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
        raise ValueError("Refusing to replace a different existing plugin jar")
    if selected.resolve() != destination.resolve() and not destination.exists():
        shutil.copy2(selected, destination)
    auth = json.loads((state / "native-auth.json").read_text(encoding="utf-8"))
    env = dict(
        os.environ, JAVA_HOME=str(java_home), NEO4J_HOME=str(home), NEO4J_CONF=str(home / "conf")
    )
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    base = [str(java), "-cp", str(home / "lib/*")]
    # Idempotent for our fresh owned instance only; never reset a running user's password.
    if not any((home / "data/databases").rglob("*")):
        result = subprocess.run(
            base
            + [
                "org.neo4j.server.startup.Neo4jAdminBoot",
                "dbms",
                "set-initial-password",
                auth["password"],
            ],
            cwd=home,
            env=env,
            creationflags=flags,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            raise RuntimeError("Native initial password setup failed: " + result.stderr[-2000:])
    with socket.socket() as sock:
        sock.settimeout(0.2)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            # Connect only after ownership marker and credentials are known, not just by port.
            from neo4j import GraphDatabase

            with GraphDatabase.driver(auth["uri"], auth=(auth["user"], auth["password"])) as driver:
                driver.verify_connectivity()
            prior = json.loads((state / "native-pid.json").read_text(encoding="utf-8"))
            record_process(state, home, prior["pid"])
            return dict(status="owned_instance_running", port=port)
    output = (state / "native-stdout.log").open("a", encoding="utf-8")
    errors = (state / "native-stderr.log").open("a", encoding="utf-8")
    proc = subprocess.Popen(
        base + ["org.neo4j.server.startup.Neo4jBoot", "console"],
        cwd=home,
        env=env,
        creationflags=flags,
        stdout=output,
        stderr=errors,
    )
    output.close()
    errors.close()
    record_process(state, home, proc.pid)
    return dict(status="starting", pid=proc.pid, port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--java-home")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--state", required=True)
    parser.add_argument("--port", type=int, default=17687)
    parser.add_argument("--guava-jar")
    args = parser.parse_args()
    if args.stop:
        result = stop(args.home, args.state)
    else:
        if not args.java_home:
            parser.error("--java-home is required to start")
        result = start(args.home, args.java_home, args.state, args.port, args.guava_jar)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
