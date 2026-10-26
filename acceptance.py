"""Current-corpus retrieval observations; failures are reported, not hidden as test success."""

import json
from collections import Counter, defaultdict

from lct.common import ROOT, atomic, config, load
from lct.query import Query
from lct.storage import manifest


def main():
    c = config()
    q = Query(c)
    status = q.index_status(refresh=True)
    assert status["status"] in ("ready", "ready_without_dense"), status
    old = {x["id"]: x for x in load(ROOT / "tests/fixtures/historical-questions.json")}
    cases = []
    truth = {
        "Q01": ("src/trpg_state_machine/world_containers.py", "ContainerService.current_weight"),
        "Q05": ("src/trpg_state_machine/environment.py", "EnvironmentService.query_cell"),
        "Q30": ("src/trpg_state_machine/service.py", "StateMachine.resume_session"),
    }
    for ident, target in truth.items():
        for lang in ("zh", "expanded"):
            cases.append(
                dict(
                    id=ident + ":" + lang,
                    query=old[ident][lang],
                    level="function",
                    repo="trpg-state-machine",
                    expected_path=target[0],
                    expected_name=target[1],
                )
            )
    cases += [
        dict(
            id="module",
            query="world_containers ContainerService weights",
            level="module",
            repo="trpg-state-machine",
            expected_path="src/trpg_state_machine/world_containers.py",
        ),
        dict(
            id="class",
            query="ContainerService",
            level="class",
            repo="trpg-state-machine",
            expected_name="ContainerService",
        ),
        dict(
            id="identifier",
            query="ContainerService current_weight",
            level="function",
            repo="trpg-state-machine",
            expected_name="ContainerService.current_weight",
        ),
        dict(
            id="RE",
            query="evaluate RuleEvaluationRequest ruleset",
            level="function",
            repo="trpg-rules-engine",
            expected_name="evaluate",
        ),
        dict(
            id="mixed",
            query="SessionMemory 发布 publish rollback",
            level="all",
            repo="trpg-state-machine",
        ),
    ]
    observations = []
    modes = ["bm25"] + (["dense", "rrf"] if status.get("dense_ready") else [])
    for case in cases:
        for mode in modes:
            found = q.search_code(
                case["query"], case["level"], [case["repo"]], mode, candidates=50, limit=10
            )
            rows = found["results"]
            assert all(n["repository"] == case["repo"] for n in rows)
            assert case["level"] == "all" or all(n["kind"] == case["level"] for n in rows)
            hits = [
                i
                for i, n in enumerate(rows, 1)
                if (not case.get("expected_path") or n["path"] == case["expected_path"])
                and (not case.get("expected_name") or n["qualname"] == case["expected_name"])
            ]
            observations.append(
                dict(
                    case=case,
                    mode=mode,
                    expected_rank_at_10=hits[0]
                    if hits and (case.get("expected_name") or case.get("expected_path"))
                    else None,
                    top=rows,
                )
            )
    docs = q.search_docs(
        "实例字段 局部准入", repositories=["agentic-trpg"], category="contract", limit=10
    )
    assert docs["results"]
    folder, m = manifest(c)
    with q.db(folder) as db:
        nodes = [
            json.loads(row[0])
            for row in db.execute(
                "select data from nodes where path='src/trpg_state_machine/world_containers.py' and json_extract(data,'$.qualname')='ContainerService.current_weight'"
            )
        ]
        assert len(nodes) == 1
        nid = nodes[0]["node_id"]
        site_status = defaultdict(set)
        for (raw,) in db.execute("select data from edges where kind='CALLS'"):
            e = json.loads(raw)
            site_status[(e["source"], e["line"], e["column"], e["expression"])].add(e["status"])
    source = q.get_nodes([nid], version=m["version"])["nodes"][0]
    assert source["live_file_matches"] and "self.own_weight" in source["source"]
    relations = q.get_relations([nid], ["CALLS"], "out", max_edges=100)
    own = [
        e
        for e in relations["edges"]
        if e["target"] and "ContainerService.own_weight#" in e["target"]
    ]
    assert own
    evidence = dict(
        current_source=dict(
            node_id=nid,
            path=source["path"],
            start=source["start"],
            end=source["end"],
            content_fingerprint=source["content_fingerprint"],
            live_file_matches=True,
        ),
        outgoing_own_weight=own,
    )
    # Search has no source bodies by default; output and all-level layer separation are explicit.
    assert all("source" not in row for obs in observations for row in obs["top"])
    result = dict(
        status=status,
        observations=observations,
        doc_results=docs["results"],
        source_graph_evidence=evidence,
        call_site_status=dict(
            Counter(
                "resolved"
                if "resolved" in states
                else "possible"
                if "possible" in states
                else "boundary"
                if "boundary" in states
                else "unresolved"
                for states in site_status.values()
            )
        ),
        limitations=[
            "Historical questions are reused, not an independent comparison. Current truth was checked against source, old line numbers ignored.",
            "Chinese-only BM25 may miss English docstrings; inspect per-query results.",
            "Current dense/RRF/HNSW code-corpus acceptance pending explicit Voyage source-transfer approval."
            if not status.get("dense_ready")
            else "No comparison superiority over historical experiment claimed.",
        ],
    )
    atomic(ROOT / "reports/retrieval-observations.json", result)
    print(
        json.dumps(
            {
                "version": m["version"],
                "cases": len(cases),
                "observations": len(observations),
                "ranks": [
                    {k: v for k, v in obs.items() if k not in ("top", "case")}
                    | {"case": obs["case"]["id"]}
                    for obs in observations
                ],
                "call_site_status": result["call_site_status"],
                "source_graph_verified": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
