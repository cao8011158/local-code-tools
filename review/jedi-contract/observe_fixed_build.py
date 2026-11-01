"""Public fixed-source build with passive periodic counters; no hot-path query wrapper."""
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from lct.python_analysis import Analyzer
from lct.storage import build
from tests.synthetic_support import forbid_provider

workspace = Path(sys.argv[1])
config = json.loads((workspace / "acceptance-config.json").read_text())
config["data"] = str(workspace / "observed-data")
started = time.monotonic()
main_id = threading.get_ident()
active = []
done = threading.Event()
original = Analyzer.__init__


def emit(stage, **values):
    print(json.dumps(dict(stage=stage, seconds=round(time.monotonic()-started, 2), **values)), flush=True)


def init(a, *args, **kwargs):
    emit("analyzer_init_start")
    result = original(a, *args, **kwargs)
    active.append(a)
    emit("analyzer_init_end", sites=len(a.sites))
    return result


def sample():
    while not done.wait(15):
        values = {}
        if active:
            a = active[-1]
            values = dict(preparing=a._preparing_sites, prepared=a.site_queries_prepared,
                          query_entries=a.query_entries, jedi_executed=a.executed_queries,
                          candidate_calls=a.candidate_calls, candidate_visits=a.candidate_visits,
                          unknown_bucket_visits=a.candidate_unknown_bucket_visits,
                          preparation_reentries=a.preparation_candidate_reentries,
                          budget=a.budget, memo=len(a.memo),
                          supports=len(a.unit_supports), subscriptions=len(a.unit_container_subscriptions),
                          writes=len(a.unit_container_writes), raw_counts=dict(a.raw_query_counts))
        frame = sys._current_frames().get(main_id)
        stack = []
        while frame is not None and len(stack) < 10:
            stack.append(dict(file=Path(frame.f_code.co_filename).name,
                              function=frame.f_code.co_name, line=frame.f_lineno))
            frame = frame.f_back
        emit("progress", counters=values, innermost_first=stack)


threading.Thread(target=sample, daemon=True).start()
try:
    with forbid_provider(), patch.object(Analyzer, "__init__", init):
        result = build(config, offline=True, lexical_only=True)
    (workspace / "observed-result.json").write_text(json.dumps(result, indent=2))
    (workspace / "observed-config.json").write_text(json.dumps(config, indent=2))
    emit("finished", version=result["version"], graph=result["graph"])
finally:
    done.set()
