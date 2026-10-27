"""Export source-only phase-one evidence. Never reads config, real indices or business roots."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "python_graph"))

from syntax import annotated  # noqa: E402

from lct.extract import extract  # noqa: E402
from lct.graph import Graph  # noqa: E402


def sha(path):
    """Hash only the caller-selected source or frozen fixture bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """Export bounded oracle comparison and exact modified-source identities."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    frozen = ROOT / "experiments/python_graph"
    freeze = json.loads((frozen / "truth-freeze.json").read_text(encoding="utf-8"))
    assert all(sha(frozen / name) == value for name, value in freeze["sha256"].items())
    truth = json.loads((frozen / "truth.json").read_text(encoding="utf-8"))
    files = [
        dict(
            repository="synthetic",
            path="src/" + p.name,
            module=p.stem,
            text=p.read_text(encoding="utf-8"),
            is_test=False,
        )
        for p in sorted((frozen / "fixtures").glob("*.py"))
    ]
    nodes, trees = extract(files)
    edges, info = Graph(
        nodes,
        trees,
        [
            dict(
                name="synthetic",
                path=str(frozen / "fixtures"),
                head="frozen-source",
                closed_world=True,
            )
        ],
    ).build()
    byid = {n["node_id"]: n for n in nodes}

    def label(ident):
        n = byid[ident]
        return Path(n["path"]).stem + ":" + ("<module>" if n["kind"] == "module" else n["qualname"])

    labels = annotated([dict(f, path=Path(f["path"]).name) for f in files], truth, True)
    records = []
    for expected in labels:
        path = "src/" + expected["file"]
        if expected["kind"] == "reference":
            calls = [
                s
                for s in info["sites"]
                if byid[s["execution_owner"]]["path"] == path and s["line"] == expected["line"]
            ]
            actual = sorted(
                {
                    label(e["target"])
                    for e in edges
                    if e["kind"] == "REFERENCES"
                    and e["target"] in byid
                    and byid[e["source"]]["path"] == path
                    and e["line"] == expected["line"]
                }
            )
            records.append(
                dict(
                    id=expected["id"],
                    kind="reference",
                    targets=actual,
                    passed=not calls and actual == sorted(expected["targets"]),
                )
            )
            continue
        matches = [
            s
            for s in info["sites"]
            if byid[s["execution_owner"]]["path"] == path
            and (s["line"], s["column"]) == (expected["line"], expected["column"])
            and s["expression"] == expected["expression"]
            and s["kind"] == expected["kind"]
        ]
        assert len(matches) == 1, expected["id"]
        s = matches[0]
        actual = sorted(
            [label(t) for t in s["targets"]]
            + [b["full_name"].replace("json.loads", "json:loads") for b in s["boundaries"]]
        )
        passed = (
            actual == sorted(expected["targets"])
            and s["complete"] == expected["complete"]
            and s["unknown_origin"] is (not expected["complete"])
            and label(s["execution_owner"]) == expected["context"]
            and s["phase"] == expected["phase"]
            and not set(actual).intersection(expected["forbidden"])
        )
        records.append(
            dict(
                id=expected["id"],
                kind=s["kind"],
                site_id=s["site_id"],
                path=path,
                line=s["line"],
                column=s["column"],
                targets=actual,
                expected=expected["targets"],
                forbidden=expected["forbidden"],
                complete=s["complete"],
                unknown_origin=s["unknown_origin"],
                reasons=s["unresolved_reasons"],
                phase=s["phase"],
                execution_owner=label(s["execution_owner"]),
                lexical_owner=label(s["lexical_owner"]),
                passed=passed,
                evidence=s["evidence"],
            )
        )
    source_paths = [
        "lct/extract.py",
        "lct/graph.py",
        "lct/python_analysis.py",
        "lct/python_effects.py",
        "lct/python_access.py",
        "lct/storage.py",
        "pyproject.toml",
        "uv.lock",
        "requirements.lock.txt",
        "tests/test_core.py",
        "tests/test_python_pipeline.py",
        "tests/test_python_pipeline_gaps.py",
        "tests/test_python_review_regressions.py",
        "tests/test_python_review_round3.py",
        "tests/test_python_review_round4.py",
        "tests/test_python_effect_coverage.py",
        "tests/test_python_call_access.py",
        "lct/query.py",
        "experiments/python_graph/worker.py",
        "experiments/python_graph/tests/test_experiment.py",
    ]
    result = dict(
        branch=subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT)
        .decode()
        .strip(),
        start="9d5a54f9f8ecdd6f5ce6349a916c03522a1453a7",
        source_head_at_capture=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
        .decode()
        .strip(),
        source_sha256={p: sha(ROOT / p) for p in source_paths},
        frozen_sha256=freeze["sha256"],
        node_count=len(nodes) - 1,
        node_catalog=[n for n in nodes if n["kind"] != "repository"],
        analysis_limited=info["analysis_limited"],
        association_evaluations=info["association_evaluations"],
        jedi_queries=info["jedi_queries"],
        records=records,
        passed=sum(r["passed"] for r in records),
        total=len(records),
        frozen_contract_complete=all(r["passed"] for r in records),
        review_baseline="36b0ede83eb278f2af6079f2d2403493385d5a6b",
        former_gap_regressions="tests/test_python_pipeline_gaps.py; not inferred from frozen-only export",
        requests=dict(embedding=0, llm=0),
        scope="frozen synthetic only",
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("passed", "total", "node_count", "analysis_limited")}))
    return 0 if all(r["passed"] for r in records) and not info["analysis_limited"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
