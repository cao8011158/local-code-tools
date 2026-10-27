"""Isolated analyzer worker. No project imports, embedding client or persistent index I/O."""

import argparse
import importlib.metadata
import json
import logging
import sys
import time
from pathlib import Path

from syntax import normalize

ROOT = Path(__file__).resolve().parents[2]


def current(plan):
    """Run current parser on frozen source; only the synthetic drivers are closed."""
    sys.path.insert(0, str(ROOT))
    from lct.extract import python_nodes
    from lct.graph import Graph

    nodes = []
    asts = {}
    modules = {}
    identities = {}
    for source in plan["sources"]:
        f = dict(source, is_test=False)
        ns, trees = python_nodes(f)
        nodes.extend(ns)
        asts.update(trees)
        mod = ns[0]["qualname"]
        for n in ns:
            identities[n["node_id"]] = (
                mod + ":" + ("<module>" if n["kind"] == "module" else n["qualname"])
            )
            modules[n["node_id"]] = source["repository"] + ":" + source["path"]
    repos = [dict(r, closed_world=r["name"] == "synthetic") for r in plan["repositories"]]
    graph = Graph(nodes, asts, repos)
    edges, info = graph.build()
    raw = []
    for e in edges:
        target = e["target"]
        if target and target.startswith("boundary:external-or-excluded:"):
            target = normalize(target.split(":", 2)[2], [])
        elif target in identities:
            target = identities[target]
        raw.append(
            dict(
                e,
                source=identities.get(e["source"], e["source"]),
                target=target,
                source_key=modules.get(e["source"]),
            )
        )
    observations = []
    for site in plan["sites"]:
        matching = [
            e
            for e in raw
            if e["kind"] == "CALLS"
            and e["source_key"] == site["source_key"]
            and (e["line"], e["column"]) == (site["line"], site["column"])
            and e["expression"] == site["expression"]
        ]
        observations.append(
            dict(
                id=site["id"],
                adapted_relation="CALLS",
                raw=matching,
                targets=sorted(
                    {
                        e["target"]
                        for e in matching
                        if e["target"] and not e["target"].startswith("boundary:")
                    }
                ),
                native_contexts=sorted({e["source"] for e in matching}),
                native_site_recorded=bool(matching),
                asserted_certain=any(e["status"] == "resolved" for e in matching),
                uncertainty="Native statuses retained; fixed-point convergence is not completeness proof.",
            )
        )
    return dict(
        tool="current",
        version="1.0.0",
        info=info,
        nodes=[dict(id=identities[n["node_id"]], kind=n["kind"], line=n["start"]) for n in nodes],
        observations=observations,
        raw_edges=raw,
        semantics="Native CALLS, IMPORTS, INHERITS and CONTAINS",
    )


def jedi_run(plan):
    """Query the callee expression at supplied syntax positions; keep candidate semantics."""
    import jedi

    jedi.settings.cache_directory = plan["cache_dir"]
    project = jedi.Project(
        plan["project_root"],
        sys_path=plan["search_paths"] + sys.path,
        smart_sys_path=False,
        load_unsafe_extensions=False,
    )
    enumeration_errors = []
    scripts = {}
    nodes = []
    modules = [s["module"] for s in plan["sources"]]
    # Definition enumeration over all files; target inference only at annotated positions.
    for source in plan["sources"]:
        key = source["repository"] + ":" + source["path"]
        script = jedi.Script(code=source["text"], path=source["absolute"], project=project)
        scripts[key] = script
        nodes.append(
            dict(id=source["module"].removesuffix(".__init__") + ":<module>", kind="module", line=1)
        )
        try:
            names = script.get_names(all_scopes=True, definitions=True, references=False)
        except Exception as exc:
            names = []
            enumeration_errors.append(
                dict(source_key=key, error=type(exc).__name__ + ": " + str(exc))
            )
        for n in names:
            if n.type in ("function", "class"):
                nodes.append(
                    dict(
                        id=normalize(n.full_name, modules),
                        kind=n.type,
                        line=n.line,
                        raw_full_name=n.full_name,
                    )
                )
    observations = []
    for site in plan["sites"]:
        raw = []
        error = None
        try:
            positions = site.get("reference_positions", [(site["end_line"], site["end_column"])])
            inferred = []
            for line, column in positions:
                inferred.extend(scripts[site["source_key"]].infer(line, column))
            for n in inferred:
                raw.append(
                    dict(
                        name=n.name,
                        full_name=n.full_name,
                        type=n.type,
                        description=n.description,
                        line=n.line,
                        column=n.column,
                        module_path=str(n.module_path) if n.module_path else None,
                    )
                )
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
        targets = sorted(
            {
                normalize(n["full_name"], modules)
                for n in raw
                if n["type"] in ("function", "class") and n["full_name"]
            }
        )
        observations.append(
            dict(
                id=site["id"],
                adapted_relation="INFERRED_CALLEE_CANDIDATE"
                if site["kind"] != "reference"
                else "INFERRED_REFERENCE_CANDIDATE",
                raw=raw,
                targets=targets,
                native_contexts=[],
                native_site_recorded=False,
                adapter_site_recorded=True,
                asserted_certain=False,
                error=error,
                uncertainty="infer results have no exhaustiveness/soundness/call-edge guarantee; syntax owner and location supplied by adapter.",
            )
        )
    return dict(
        enumeration_errors=enumeration_errors,
        tool="jedi",
        version=importlib.metadata.version("jedi"),
        nodes=nodes,
        observations=observations,
        raw_edges=[],
        semantics="Inferred names at AST supplied positions, never native CALLS",
    )


def pyan_run(plan):
    """Read unculled USES and DEFINES; do not invent callsite coordinates or CALLS."""
    from pyan.analyzer import CallGraphVisitor

    logging.disable(logging.CRITICAL)
    modules = [s["module"] for s in plan["sources"]]
    graph = CallGraphVisitor.from_sources(
        [(s["text"], s["module"]) for s in plan["sources"]], cull_subsumed_edges=False
    )

    def export(n):
        return dict(
            full_name=n.get_name(),
            id=normalize(n.get_name(), modules),
            flavor=n.flavor.value,
            defined=n.defined,
            definition_line=getattr(n.ast_node, "lineno", None),
            filename=n.filename,
        )

    allnodes = [export(n) for bucket in graph.nodes.values() for n in bucket]
    raw = []
    for kind, mapping in [("USES", graph.uses_edges), ("DEFINES", graph.defines_edges)]:
        for source, targets in mapping.items():
            for target in targets:
                raw.append(
                    dict(kind=kind, source=export(source), target=export(target), callsite=None)
                )
    observations = []
    for site in plan["sites"]:
        matching = [e for e in raw if e["kind"] == "USES" and e["source"]["id"] == site["context"]]
        observations.append(
            dict(
                id=site["id"],
                adapted_relation="USES_CONTEXT_ONLY",
                raw=matching,
                targets=sorted({e["target"]["id"] for e in matching}),
                native_contexts=[site["context"]] if matching else [],
                native_site_recorded=False,
                asserted_certain=False,
                uncertainty="Context aggregate includes calls, references, annotations and bases; no use-site location or exhaustive target semantics. Never interpret these targets as this site's callees.",
            )
        )
    return dict(
        tool="pyan3",
        version=importlib.metadata.version("pyan3"),
        nodes=allnodes,
        observations=observations,
        raw_edges=raw,
        semantics="Native USES and DEFINES; no native callsites, CALLS, or certainty",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--tool", choices=["current", "jedi", "pyan3"], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import socket

    network_attempts = []

    def deny(self, *args, **kwargs):
        network_attempts.append("blocked")
        raise RuntimeError("Network denied in graph evaluation")

    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    start = time.perf_counter()
    result = {"tool": args.tool, "status": "error"}
    try:
        result = {
            **globals()[{"current": "current", "jedi": "jedi_run", "pyan3": "pyan_run"}[args.tool]](
                plan
            ),
            "status": "completed",
        }
    except Exception as exc:
        import traceback

        result.update(error=type(exc).__name__ + ": " + str(exc), traceback=traceback.format_exc())
    result.update(network_attempts_blocked=len(network_attempts), network_denied=True)
    result.update(
        seconds=time.perf_counter() - start,
        source_files=len(plan["sources"]),
        annotated_sites=len(plan["sites"]),
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("nodes", "observations", "raw_edges", "traceback", "info")
            }
        )
    )


if __name__ == "__main__":
    main()
