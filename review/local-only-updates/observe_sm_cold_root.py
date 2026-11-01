"""Read-only observers around the real public cold builder; no analyzer shortcuts."""
import ast
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from lct import graph, storage
from lct.python_analysis import Analyzer
from tests.synthetic_support import forbid_provider

workspace = Path(sys.argv[1])
config = json.loads((workspace / "acceptance-config.json").read_text())
config["data"] = str(workspace / "observed-data")
started = time.monotonic()
main_id = threading.get_ident()
done = threading.Event()


def emit(stage, **values):
    print(json.dumps(dict(stage=stage, seconds=round(time.monotonic()-started, 2), **values)), flush=True)


def observe_stack():
    while not done.wait(20):
        frame = sys._current_frames().get(main_id)
        stack = []
        while frame is not None:
            stack.append(dict(file=Path(frame.f_code.co_filename).name,
                              function=frame.f_code.co_name, line=frame.f_lineno))
            frame = frame.f_back
        emit("current_python_stack", innermost_first=stack[:12])


real_init, real_query = Analyzer.__init__, Analyzer.query
query_count = 0


def init(self, *args, **kwargs):
    emit("analyzer_init_start")
    result = real_init(self, *args, **kwargs)
    emit("analyzer_init_end", sites=len(self.sites), selected_mode=self._selected_owner_mode)
    return result


def query(self, scope, expr, *args, **kwargs):
    global query_count
    query_count += 1
    index = query_count
    now = time.monotonic()
    if index <= 3 or index % 100 == 0:
        emit("query_start", attempts=index, executed=self.executed_queries,
             owner=self.nodes[scope]["qualname"], expression=ast.unparse(expr), budget=self.budget)
    result = real_query(self, scope, expr, *args, **kwargs)
    if time.monotonic()-now > 5:
        emit("slow_query_end", attempts=index, duration=round(time.monotonic()-now, 2),
             owner=self.nodes[scope]["qualname"], expression=ast.unparse(expr))
    return result


def phase(name, original):
    def wrapped(*args, **kwargs):
        emit(name + "_start")
        result = original(*args, **kwargs)
        emit(name + "_end")
        return result
    return wrapped


threading.Thread(target=observe_stack, daemon=True).start()
try:
    with forbid_provider(), patch.object(Analyzer, "__init__", init), \
            patch.object(Analyzer, "query", query), \
            patch.object(graph, "value_flow_evidence", phase("value_flow", graph.value_flow_evidence)), \
            patch.object(storage, "split_graph", phase("split_graph", storage.split_graph)):
        result = storage.build(config, offline=True, lexical_only=True)
    (workspace / "acceptance-config.json").write_text(json.dumps(config, indent=2))
    (workspace / "first-build-result.json").write_text(json.dumps(result, indent=2))
    emit("finished", version=result["version"], graph=result["graph"])
finally:
    done.set()
