"""Count actual candidates under simultaneous unrelated unknown-call/method growth."""
import argparse
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from lct.common import program_hash
from lct.python_analysis import Analyzer
from tests.test_python_pipeline import analyze, site


def measure(root, noise):
    source = ("def first(): pass\ndef work(callback): callback()\n"
              "def driver(): work(first)\n" + "".join(
                  f"class C{i}:\n def work(self): pass\n"
                  f"def noise_{i}(obj_{i}): obj_{i}.work()\n" for i in range(noise)))
    returned = dict(all=0, unknown_noise=0)
    real = Analyzer.candidate_sites
    def watch(a, function):
        for candidate in real(a, function):
            returned["all"] += 1
            if a.nodes[candidate["execution_owner"]]["qualname"].startswith("noise_"):
                returned["unknown_noise"] += 1
            yield candidate
    with patch.object(Analyzer, "candidate_sites", watch):
        result = analyze(root, {"source.py": source}, closed=False)
    assert site(result, "callback", "work")["names"] == {"first"}
    nodes = {n["node_id"]: n["qualname"] for n in result[0]}
    unknowns = [s for s in result[2]["sites"]
                if nodes[s["execution_owner"]].startswith("noise_")]
    assert len(unknowns) == noise
    assert all(s["unknown_origin"] and not s["targets"] and not s["complete"] for s in unknowns)
    assert returned["unknown_noise"] == 0
    keys = ("candidate_site_queries_prepared", "candidate_calls", "candidate_visits",
            "candidate_unknown_bucket_visits", "jedi_query_entries", "jedi_queries_executed",
            "jedi_query_cache_hits", "jedi_raw_result_counts", "candidate_preparation_reentries")
    return dict(unrelated_unknown_calls=noise, unrelated_same_named_methods=noise,
                counted_actual_candidate_returns=returned,
                preserved_unknown_sites=len(unknowns), metrics={k: result[2].get(k) for k in keys})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="jd1-candidate-work-") as temporary:
        rows = [measure(Path(temporary) / str(n), n) for n in (0, 20, 100)]
    assert len({r["counted_actual_candidate_returns"]["all"] for r in rows}) == 1
    output = dict(program_hash=program_hash(), rows=rows,
                  limitations=["Actual candidate returns are counted by wrapping, not replacing, the real generator.",
                               "Initial frontend queries grow with source sites; this is not a warm update measurement.",
                               "No captured business code or provider is executed. Timing is not used as a correctness assertion."])
    args.output.write_text(json.dumps(output, indent=2))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
