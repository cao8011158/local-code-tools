"""Bounded synthetic instrumentation of the exact Neo4jGraph.import_snapshot implementation.

Run with the pinned review venv. Owns and terminates one Neo4j service process; writes only
to unique diagnostic namespaces. It does not call load_snapshot or alter production code.
"""
import json
import os
import signal
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

from neo4j import GraphDatabase

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
RUNTIME = PROJECT.parent / ".runtime/neo4j-batch1/neo4j-community-5.26.0"
URI = "bolt://127.0.0.1:17687"
AUTH = ("neo4j", "synthetic-lct-batch1-only")
DEADLINE = time.monotonic() + 175
sys.path.insert(0, str(PROJECT))
stub = types.ModuleType("lct.storage")
def forbidden(*args, **kwargs):
    raise AssertionError("Synthetic diagnostic must not load a SQLite snapshot")
stub.manifest = forbidden
stub.validate_folder = forbidden
sys.modules["lct.storage"] = stub
from lct.neo4j_graph import Neo4jGraph, _snapshot_payload, digest

measurements = []
current = {"case": None, "phase": None, "batch": 0}

def observe(observer, phase, batch):
    # SHOW TRANSACTIONS is a separate session and is never run once per input row.
    try:
        with observer.session(database="system") as session:
            rows = [dict(r) for r in session.run("SHOW TRANSACTIONS YIELD * RETURN *")]
        candidates = [r for r in rows if r.get("database") == "neo4j"
                      and "SHOW TRANSACTIONS" not in str(r.get("currentQuery", ""))]
        out = [{k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
                for k, v in r.items() if k in ("transactionId", "currentQuery", "allocatedBytes",
                "allocatedDirectBytes", "estimatedUsedHeapMemory", "activeLockCount", "status")}
               for r in candidates]
        measurements.append({"case": current["case"], "phase": phase, "batch": batch,
                             "at_seconds": round(time.monotonic() - START, 3), "transactions": out})
    except Exception as exc:
        measurements.append({"case": current["case"], "phase": phase, "batch": batch,
                             "observer_error": repr(exc)})

class ResultProxy:
    def __init__(self, result, callback): self.result, self.callback = result, callback
    def consume(self):
        ret = self.result.consume(); self.callback(); return ret
    def single(self, *a, **kw):
        ret = self.result.single(*a, **kw); self.callback(); return ret

class TxProxy:
    def __init__(self, tx, observer): self.tx, self.observer = tx, observer
    def __enter__(self): self.tx.__enter__(); observe(self.observer, "begin", 0); return self
    def __exit__(self, *args):
        if args[0] is None:
            current["phase"] = "commit"
        try: return self.tx.__exit__(*args)
        finally: observe(self.observer, "after_commit_or_rollback", current["batch"])
    def run(self, query, **params):
        if "CREATE (n:LCTNode:" in query: phase = "nodes"
        elif "CREATE (e:LCTEdge" in query: phase = "edges"
        elif "CREATE (a)-[:" in query: phase = "relations"
        elif "SET s.graph_json" in query: phase = "graph_property"
        else: phase = "scope"
        if phase != current["phase"]:
            current["phase"], current["batch"] = phase, 0
            observe(self.observer, "before_" + phase, 0)
        current["batch"] += 1
        batch = current["batch"]
        def after():
            if phase in ("scope", "graph_property") or batch in (1, 2, 5, 10, 20):
                observe(self.observer, "after_" + phase, batch)
        return ResultProxy(self.tx.run(query, **params), after)

class SessionProxy:
    def __init__(self, session, observer): self.session, self.observer = session, observer
    def __enter__(self): self.session.__enter__(); return self
    def __exit__(self, *a): return self.session.__exit__(*a)
    def begin_transaction(self, *a, **kw):
        return TxProxy(self.session.begin_transaction(*a, **kw), self.observer)
    def run(self, *a, **kw): return self.session.run(*a, **kw)

class DriverProxy:
    def __init__(self, driver, observer): self.driver, self.observer = driver, observer
    def session(self, *a, **kw): return SessionProxy(self.driver.session(*a, **kw), self.observer)
    def close(self): return self.driver.close()

def snapshot(n, e, blob_mb):
    nodes = [{"node_id": f"n{i}", "kind": "function", "repository": "synthetic",
              "path": f"p{i//20}.py", "qualname": f"f{i}"} for i in range(n)]
    edges = [{"edge_id": f"e{i}", "kind": "CALLS", "source": f"n{i%n}",
              "target": f"n{(i*37+1)%n}", "status": "resolved"} for i in range(e)]
    # This is intentionally compressible; emitted UTF-8 parameter size is the varied quantity.
    graph = {"synthetic_evidence": "x" * int(blob_mb * 1024 * 1024)}
    source = {"repositories": ["synthetic"], "files": [], "source_fingerprint": "synthetic"}
    payload = _snapshot_payload(nodes, edges, graph, source)
    return {"version": "v1", "nodes": nodes, "edges": edges, "graph": graph,
            "source": source, "fingerprint": digest(payload), "canonical_bytes": len(payload.encode())}

def plan(observer, namespace):
    from lct.neo4j_graph import _scope
    # Literal original relation statement, with only EXPLAIN/PROFILE prepended.
    query = ("UNWIND $rows AS row "
             "MATCH (a:LCTNode {namespace:$namespace, version:$version, node_id:row.source}) "
             "MATCH (b:LCTNode {namespace:$namespace, version:$version, node_id:row.target}) "
             "CREATE (a)-[:CALLS {edge_id:row.edge_id, namespace:$namespace, "
             "version:$version}]->(b)")
    rows = [{"edge_id": "plan-only", "source": "n0", "target": "n1"}]
    with observer.session(database="neo4j") as session:
        result = session.run("EXPLAIN " + query, **_scope(namespace, "v1"), rows=rows)
        explained = str(result.consume().plan)
        with session.begin_transaction() as tx:
            result = tx.run("PROFILE " + query, **_scope(namespace, "v1"), rows=rows)
            profiled = str(result.consume().profile)
            tx.rollback()
    return {"explain": explained, "profile_one_row_rolled_back": profiled}

def run():
    global START
    START = time.monotonic()
    data = {"runtime": "Neo4j 5.26.0, 1 GiB JVM heap, 128 MiB pagecache",
            "source": "exact remote SHA 4557d4cd2c5a6b33933b3832f81dfb64207e4e4b",
            "synthetic": True, "cases": [], "measurements": measurements}
    logpath = HERE / "neo4j-owned.log"
    command = ["java", "-Xms128m", "-Xmx1024m",
               "--add-opens=java.base/java.nio=ALL-UNNAMED",
               "--add-opens=java.base/java.io=ALL-UNNAMED",
               "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED",
               "-cp", str(RUNTIME / "lib/*"), "org.neo4j.server.CommunityEntryPoint",
               "--home-dir=" + str(RUNTIME), "--config-dir=" + str(RUNTIME / "conf")]
    process = None
    with logpath.open("w") as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            while True:
                if process.poll() is not None: raise RuntimeError("Owned Neo4j exited during startup")
                try:
                    with GraphDatabase.driver(URI, auth=AUTH, connection_timeout=1) as check:
                        check.verify_connectivity()
                    break
                except Exception:
                    if time.monotonic() > START + 45: raise TimeoutError("Neo4j startup >45 s")
                    time.sleep(.4)
            with GraphDatabase.driver(URI, auth=AUTH) as observer:
                for n, e, blob in [(100, 500, 0), (1000, 5000, 0),
                                   (100, 500, 8), (100, 500, 61.16)]:
                    if time.monotonic() > DEADLINE: raise TimeoutError("Total diagnostic >175 s")
                    name = f"diag-20261029-{uuid.uuid4().hex[:12]}"
                    current.update(case=f"n{n}-e{e}-blob{blob}", phase=None, batch=0)
                    case = {"name": current["case"], "namespace": name, "nodes": n,
                            "edges": e, "blob_mb": blob}
                    data["cases"].append(case)
                    try:
                        fixture = snapshot(n, e, blob)
                        case["canonical_bytes"] = fixture.pop("canonical_bytes")
                        with Neo4jGraph(URI, *AUTH, "neo4j") as graph:
                            graph.driver = DriverProxy(graph.driver, observer)
                            case["result"] = graph.import_snapshot(name, "v1", fixture)
                        if n == 100 and blob == 0:
                            case["original_query_plan"] = plan(observer, name)
                    except Exception as exc:
                        case["error"] = repr(exc)
                        case["error_phase"] = current["phase"]
                    case["seconds_since_start"] = round(time.monotonic() - START, 3)
                    del fixture
                    (HERE / "results.json").write_text(json.dumps(data, indent=2))
        finally:
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try: process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            data["service_exit_code"] = None if process is None else process.returncode
            data["elapsed_seconds"] = round(time.monotonic() - START, 3)
            (HERE / "results.json").write_text(json.dumps(data, indent=2))
    print(json.dumps({"cases": [{k: c.get(k) for k in ("name", "canonical_bytes", "result", "error", "error_phase", "seconds_since_start")} for c in data["cases"]], "measurements": len(measurements), "service_exit_code": data["service_exit_code"], "elapsed_seconds": data["elapsed_seconds"]}, indent=2))

if __name__ == "__main__": run()
