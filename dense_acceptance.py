"""Real current-corpus HNSW recall and isolated incremental vector acceptance.

All paid inputs use the existing global cache and ledger. Fixture builds run
strictly offline after copying authentic cached vectors; no random vectors exist.
"""

import argparse
import copy
import json
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np

from lct.common import ROOT, ToolError, atomic, config, inventory, load
from lct.embedding import Embeddings, vector_key
from lct.extract import embedding_texts, extract
from lct.query import Query
from lct.storage import build, current


def hnsw_acceptance(c):
    """Measure each configured hierarchy/filter before TopK, using true current vectors."""
    q = Query(c)
    folder, m = q.snapshot()
    assert m["dense_ready"]
    observations = load(ROOT / "reports/retrieval-observations.json")["observations"]
    cases = [o["case"] for o in observations if o["mode"] == "dense"]
    assert cases
    rows = []
    cache = Embeddings(c)
    try:
        for case in cases:
            v = cache.get_many([case["query"]], "query", offline=True)[0]
            v = v / np.linalg.norm(v)
            for kind in (
                ("module", "class", "function") if case["level"] == "all" else [case["level"]]
            ):
                for count in (10, 50):
                    approximate = q.dense(folder, m, v, kind, [case["repo"]], count)
                    exact = q.dense(folder, m, v, kind, [case["repo"]], count, exact=True)
                    recall = len(set(approximate) & set(exact)) / len(exact) if exact else 1.0
                    rows.append(
                        dict(
                            case=case["id"],
                            repository=case["repo"],
                            kind=kind,
                            k=count,
                            exact_count=len(exact),
                            approximate_count=len(approximate),
                            recall=recall,
                        )
                    )
                    assert len(approximate) == len(exact)
        # Full-eligible candidate count verifies per-level retrieval is not filtered global TopK.
        v = cache.get_many([cases[0]["query"]], "query", offline=True)[0]
        v = v / np.linalg.norm(v)
        for spec in m["partitions"]:
            repo, kind = spec["repository"], spec["kind"]
            want = min(1000, spec["nodes"])
            got = q.dense(folder, m, v, kind, [repo], want)
            assert len(got) == want, (repo, kind, len(got), want)
    finally:
        cache.close()
    out = dict(
        index_version=m["version"],
        metric=m["metric"],
        hnsw=m["hnsw"],
        comparisons=rows,
        mean_recall=float(np.mean([r["recall"] for r in rows])),
        min_recall=min(r["recall"] for r in rows),
        zero_additional_api_requests=True,
        filtered_candidate_capacity_checked=True,
    )
    atomic(ROOT / "reports/current-hnsw-recall.json", out)
    assert out["mean_recall"] >= 0.95 and out["min_recall"] >= 0.8
    return out


SOURCE = '''"""Isolated maintained vector validation module."""
def calculate_weight(value):
    """Read current container weight."""
    return value + 1

class Box:
    """Hold an explicit weight value."""
    def total(self, value):
        """Return current total weight."""
        return calculate_weight(value)

def untouched(value):
    """Keep unrelated value unchanged."""
    return value
'''


def initialize_fixture(c):
    """Create an owned isolated source root without changing a project repository."""
    folder = ROOT / ".tmp" / ("dense-incremental-" + uuid.uuid4().hex[:10])
    if folder.exists():
        raise ToolError(
            "Fixture already exists; preserve evidence and select a new fixture directory"
        )
    source = folder / "sample"
    (source / "src").mkdir(parents=True)
    (source / "docs").mkdir()
    (source / "src/sample.py").write_text(SOURCE, encoding="utf-8")
    (source / "docs/guide.md").write_text(
        "# Fixture\nLocal vector acceptance only.\n", encoding="utf-8"
    )
    for args in (
        ["init", str(source)],
        ["-C", str(source), "config", "user.name", "Local Validation"],
        ["-C", str(source), "config", "user.email", "local@example.invalid"],
        ["-C", str(source), "add", "src/sample.py", "docs/guide.md"],
        ["-C", str(source), "commit", "-m", "isolated fixture"],
    ):
        subprocess.run(["git", *args], stdin=subprocess.DEVNULL, capture_output=True, check=True)
    fixture = copy.deepcopy(c)
    fixture["data"] = str(folder / "data")
    fixture["repositories"] = [dict(name="isolated-sample", path=str(source), code_roots=["src"])]
    fixture["embedding"]["historical_cache"] = "none"
    fixture["_path"] = str(folder / "config.json")
    atomic(fixture["_path"], {k: v for k, v in fixture.items() if not k.startswith("_")})
    return fixture, source


def incremental_acceptance(c, offline=False):
    """Real vectors prove input-driven reuse, owner updates, deletion and publication safety."""
    fixture, source = initialize_fixture(c)
    global_cache = Embeddings(c)
    stages = []
    previous_inputs = {}
    query = "current total container weight Box"
    try:
        qv = global_cache.get_many([query], "query", offline=offline)[0]

        def prepare_and_build(label):
            nonlocal previous_inputs
            files, _, _ = inventory(fixture)
            nodes, _ = extract(files)
            texts = embedding_texts(nodes, files)
            inputs = {t["node_id"]: t["input_hash"] for t in texts}
            changed = [
                t["node_id"] for t in texts if previous_inputs.get(t["node_id"]) != t["input_hash"]
            ]
            removed = sorted(set(previous_inputs) - set(inputs))
            before = global_cache.ledger()
            available_before = {
                t["text"]: global_cache.lookup(t["text"], "document") is not None for t in texts
            }
            values = global_cache.get_many([t["text"] for t in texts], offline=offline)
            local_cache = Embeddings(fixture)
            try:
                for t, v in zip(texts, values):
                    local_cache.db.execute(
                        "insert or replace into vectors values(?,?,?,?,?)",
                        (
                            vector_key(c["embedding"], t["text"], "document"),
                            "document",
                            v.tobytes(),
                            "verified-global-voyage-cache",
                            0,
                        ),
                    )
                local_cache.db.execute(
                    "insert or replace into vectors values(?,?,?,?,?)",
                    (
                        vector_key(c["embedding"], query, "query"),
                        "query",
                        qv.tobytes(),
                        "verified-global-voyage-cache",
                        0,
                    ),
                )
                local_cache.db.commit()
            finally:
                local_cache.close()
            result = build(fixture, offline=True)
            after = global_cache.ledger()
            new = sum(not value for value in available_before.values())
            stage = dict(
                stage=label,
                index_version=result["version"],
                changed_vector_nodes=changed,
                removed_vector_nodes=removed,
                new_vector_inputs=new,
                global_api_attempts=after["attempts"] - before["attempts"],
                global_usage_tokens=after["usage_tokens"] - before["usage_tokens"],
                offline_build=result["embedding_run"],
                index_diffs=result["incremental"],
            )
            assert (
                result["embedding_run"]["requests"] == 0
                and result["embedding_run"]["new_vectors"] == 0
            )
            # Query all three retrieval modes using authentic cached query/document vectors.
            reader = Query(fixture)
            for mode in ("dense", "bm25", "rrf"):
                found = reader.search_code(query, mode=mode, candidates=10, limit=2)
                assert found["results"]
            stages.append(stage)
            previous_inputs = inputs
            atomic(ROOT / "reports/real-incremental-progress.json", stages)
            return result

        first = prepare_and_build("initial")
        reader = Query(fixture)
        paged = reader.search_code(query, mode="dense", candidates=10, limit=1)
        assert paged["has_more"]
        old_cursor = paged["next_cursor"]
        old_id = next(nid for nid in previous_inputs if ":function:calculate_weight#" in nid)
        original_stable = next(
            value for key, value in previous_inputs.items() if ":function:untouched#" in key
        )
        changed_source = SOURCE.replace(
            "Read current container weight.", "Read updated current container weight."
        ).replace("Return current total weight.", "Return current total mass including its parts.")
        (source / "src/sample.py").write_text(changed_source, encoding="utf-8")
        prepare_and_build("member-docstrings-and-owner-inputs")
        changed = stages[-1]["changed_vector_nodes"]
        assert any(":module:" in n for n in changed) and any(":class:" in n for n in changed)
        assert original_stable == next(
            value for key, value in previous_inputs.items() if ":function:untouched#" in key
        )
        assert stages[-1]["new_vector_inputs"] <= len(changed)
        assert (
            reader.search_code(query, mode="dense", candidates=10, limit=1, cursor=old_cursor)[
                "version"
            ]
            == first["version"]
        )
        old = reader.get_nodes([old_id], version=first["version"])["nodes"][0]
        assert not old["live_file_matches"] and "Read current container weight." in old["source"]
        (source / "src/added.py").write_text(
            'def added(value):\n    """Read added container weight."""\n    return value\n',
            encoding="utf-8",
        )
        prepare_and_build("addition")
        (source / "src/added.py").unlink()
        prepare_and_build("deletion")
        assert stages[-1]["new_vector_inputs"] == 0 and stages[-1]["global_api_attempts"] == 0
        with Query(fixture).db(Path(fixture["data"]) / "versions" / current(fixture)) as db:
            assert not db.execute("select 1 from nodes where path='src/added.py'").fetchone()
            assert not db.execute(
                "select 1 from postings p left join nodes n using(node_id) where n.node_id is null"
            ).fetchone()
            assert not db.execute(
                "select 1 from edges e left join nodes n on e.source=n.node_id where n.node_id is null"
            ).fetchone()
        (source / "src/sample.py").rename(source / "src/moved.py")
        prepare_and_build("move-without-rename-inference")
        before_failure = current(fixture)
        try:
            build(fixture, offline=True, fail_at="before_publish")
        except ToolError as exc:
            assert "Injected" in str(exc)
        else:
            raise AssertionError("Expected injected interruption")
        assert current(fixture) == before_failure
        assert Query(fixture).search_code(query, mode="dense")["results"]
        crash_code = """import os,sys
from lct.common import config
import lct.storage as storage
real=storage.atomic
def crash(path,value):
    if path.name=='current.json': os._exit(17)
    return real(path,value)
storage.atomic=crash
storage.build(config(sys.argv[1]),offline=True)
"""
        crashed = subprocess.run(
            [sys.executable, "-c", crash_code, fixture["_path"]],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert crashed.returncode == 17
        assert current(fixture) == before_failure
        assert Query(fixture).search_code(query, mode="dense")["results"]
        prepare_and_build("resume-unchanged")
        assert stages[-1]["global_api_attempts"] == 0 and stages[-1]["new_vector_inputs"] == 0
        try:
            reader.search_code(query, mode="dense", candidates=10, limit=1, cursor=old_cursor)
        except ToolError as exc:
            assert "expired" in str(exc)
        else:
            raise AssertionError("Expired cursor silently changed versions")
        out = dict(
            stages=stages,
            all_embeddings_authentic=True,
            budget_scope="global production ledger and compatible cache; fixture builds offline",
            old_cursor_stable_then_expired=True,
            old_source_snapshot_preserved=True,
            failed_publish_preserves_dense_version=True,
            real_process_exit_17_before_dense_publish=True,
            unchanged_vectors_reused=True,
            owner_inputs_updated=True,
        )
        atomic(ROOT / "reports/real-incremental-acceptance.json", out)
        return out
    finally:
        global_cache.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Require already authentic cached fixture/query vectors",
    )
    args = parser.parse_args()
    c = config()
    recall = hnsw_acceptance(c)
    incremental = incremental_acceptance(c, offline=args.offline)
    print(
        json.dumps(
            dict(
                hnsw_mean_recall=recall["mean_recall"],
                hnsw_min_recall=recall["min_recall"],
                hnsw_comparisons=len(recall["comparisons"]),
                incremental_stages=len(incremental["stages"]),
                all_real_vectors=True,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
