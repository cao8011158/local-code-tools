"""Reproduce bounded analyzer experiments in a new, isolated output directory."""

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
from syntax import annotated, inventory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS = ("current", "jedi", "pyan3")


def sha(path):
    """Hash exact bytes, with no source or identity normalization."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    """Write experiment JSON only below caller-selected new output root."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(path, *args):
    """Git metadata or explicitly owned synthetic-repository setup; no business writes."""
    return subprocess.check_output(
        ["git", "-C", str(path), *args], text=True, encoding="utf-8"
    ).strip()


def synthetic():
    """Load frozen source files; no fixture is imported or executed."""
    sources = []
    for p in sorted((HERE / "fixtures").glob("*.py")):
        sources.append(
            dict(
                repository="synthetic",
                path="src/" + p.name,
                truth_path=p.name,
                absolute=str(p),
                module=p.stem,
                text=p.read_text(encoding="utf-8"),
                sha256=sha(p),
            )
        )
    truth = json.loads((HERE / "truth.json").read_text(encoding="utf-8"))
    labeled = [dict(s, path=s["truth_path"]) for s in sources]
    sites = annotated(labeled, truth, True)
    for site in sites:
        site["source_key"] = "synthetic:src/" + site["file"]
    return dict(
        sources=sources,
        repositories=[
            dict(name="synthetic", path=str(HERE / "fixtures"), head="frozen-source", status="")
        ],
        sites=sites,
        project_root=str(HERE / "fixtures"),
        search_paths=[str(HERE / "fixtures")],
    )


def cross(out, mode):
    """Create tiny owned Git repositories to test matched/mismatched dependency pins."""
    folder = out / ("cross-" + mode)
    re = folder / "re"
    sm = folder / "sm"
    (re / "src/dnd5e_engine").mkdir(parents=True)
    (sm / "src").mkdir(parents=True)
    (re / "src/dnd5e_engine/evaluation.py").write_bytes(
        (HERE / "fixtures/cross/evaluation.py").read_bytes()
    )
    (sm / "src/sm_client.py").write_bytes((HERE / "fixtures/cross/sm_client.py").read_bytes())
    git(re, "init", "-q")
    git(re, "add", "--", "src/dnd5e_engine/evaluation.py")
    git(
        re,
        "-c",
        "user.name=Synthetic fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Synthetic dependency identity",
    )
    head = git(re, "rev-parse", "HEAD")
    pin = head if mode == "matched" else "0" * 40
    (sm / "pyproject.toml").write_text(
        '[tool.uv.sources]\ndnd5e-engine = {git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="'
        + pin
        + '"}\n',
        encoding="utf-8",
    )
    sources = []
    for repo, base, path, module in [
        ("trpg-rules-engine", re, "src/dnd5e_engine/evaluation.py", "dnd5e_engine.evaluation"),
        ("sm", sm, "src/sm_client.py", "sm_client"),
    ]:
        p = base / path
        sources.append(
            dict(
                repository=repo,
                path=path,
                module=module,
                absolute=str(p),
                text=p.read_text(encoding="utf-8"),
                sha256=sha(p),
            )
        )
    source = sources[1]
    call = next(c for c in inventory(source)[0] if c["expression"] == "rule_evaluate")
    spec = next(
        r
        for r in json.loads((HERE / "truth.json").read_text(encoding="utf-8"))["cross_repository"]
        if r["mode"] == mode
    )
    site = dict(
        call,
        id="cross_" + mode,
        source_key="sm:src/sm_client.py",
        targets=spec["targets"],
        complete=spec["complete"],
        forbidden=spec.get("forbidden", []),
        kind="call",
        file="src/sm_client.py",
    )
    return dict(
        sources=sources,
        repositories=[
            dict(name="trpg-rules-engine", path=str(re), head=head, status=""),
            dict(name="sm", path=str(sm), head="synthetic", status=""),
        ],
        sites=[site],
        project_root=str(folder),
        search_paths=[str(re / "src"), str(sm / "src")],
        dependency_identity=dict(pin=pin, target_head=head, matched=mode == "matched"),
    )


def real(workspace):
    """Read configured source scope from three checkouts; no index/cache access."""
    sys.path.insert(0, str(ROOT))
    from lct.common import inventory as source_inventory
    from lct.extract import module_name

    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    for repo in config["repositories"]:
        repo["path"] = str(workspace / repo["name"])
    files, repos, fingerprint = source_inventory(config)
    sources = []
    search = []
    for repo in config["repositories"]:
        for code_root in repo["code_roots"]:
            search.append(str(Path(repo["path"]) / code_root))
    for f in files:
        if not f["path"].endswith(".py"):
            continue
        module = module_name(f["path"])
        if f["path"].endswith("/__init__.py"):
            module += ".__init__"
        sources.append(
            dict(f, module=module, absolute=str(workspace / f["repository"] / f["path"]))
        )
    truth = json.loads((HERE / "real_truth.json").read_text(encoding="utf-8"))
    for s in truth["sites"]:
        source = next(
            f for f in sources if f["repository"] == s["repository"] and f["path"] == s["file"]
        )
        assert source["sha256"] == s["sha256"], "Source drift: " + s["id"]
    for proof in truth["proof"]:
        assert sha(workspace / proof["repository"] / proof["file"]) == proof["sha256"], (
            "Source proof drift"
        )
    return dict(
        real_examples=True,
        sources=sources,
        repositories=repos,
        sites=annotated(sources, truth, False),
        project_root=str(workspace),
        search_paths=search,
        inventory_fingerprint=fingerprint,
    )


def measure(tool, plan_file, output, timeout):
    """Bound subprocess runtime; sample working-set RSS, explicitly not exact peak."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for name in list(env):
        if name.upper().endswith(("API_KEY", "API_TOKEN")):
            env.pop(name)
    command = [
        sys.executable,
        "-B",
        str(HERE / "worker.py"),
        "--tool",
        tool,
        "--plan",
        str(plan_file),
        "--output",
        str(output),
    ]
    log = output.with_suffix(".log")
    start = time.perf_counter()
    rss = 0
    max_processes = 0
    timed_out = False
    with log.open("w", encoding="utf-8") as stream:
        proc = subprocess.Popen(command, stdout=stream, stderr=stream, env=env, cwd=ROOT)
        ps = psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                tree = [ps] + ps.children(recursive=True)
                sampled = []
                for member in tree:
                    try:
                        sampled.append(member.memory_info().rss)
                    except psutil.Error:
                        pass
                rss = max(rss, sum(sampled))
                max_processes = max(max_processes, len(sampled))
            except psutil.Error:
                pass
            if time.perf_counter() - start > timeout:
                for child in ps.children(recursive=True):
                    child.kill()
                proc.kill()
                timed_out = True
                break
            time.sleep(0.025)
        proc.wait()
    measured = dict(
        command=[
            "<EXPERIMENT_PYTHON>",
            "-B",
            "experiments/python_graph/worker.py",
            "--tool",
            tool,
            "--plan",
            "<ISOLATED_PLAN>",
            "--output",
            "<ISOLATED_OUTPUT>",
        ],
        wall_seconds=time.perf_counter() - start,
        sampled_peak_rss_bytes=rss,
        rss_scope="sum of launcher + actual worker + live child processes; sampled, shared pages may be counted twice",
        sampled_max_processes=max_processes,
        rss_sampling_seconds=0.025,
        returncode=proc.returncode,
        timeout_seconds=timeout,
        timed_out=timed_out,
    )
    if not output.exists():
        write(
            output,
            dict(
                tool=tool,
                status="timeout" if timed_out else "environment_error",
                error=log.read_text(encoding="utf-8")[-2000:],
            ),
        )
    result = json.loads(output.read_text(encoding="utf-8"))
    result["measurement"] = measured
    write(output, result)
    return result


def compare(plan, result):
    """Separate native calls, name-inference candidates and context-only uses metrics."""
    if result["status"] != "completed":
        return dict(status=result["status"], error=result.get("error"))
    obs = {o["id"]: o for o in result["observations"]}
    records = []
    tp = fp = fn = 0
    false_certainty = []
    context_errors = []
    site_missing = []
    pyan = result["tool"] == "pyan3"
    for site in plan["sites"]:
        o = obs[site["id"]]
        expected = set(site["targets"])
        actual = set(o["targets"])
        extra = (
            sorted(actual - expected) if site["complete"] and site["kind"] != "reference" else []
        )
        missing = sorted(expected - actual)
        if not pyan and site["kind"] != "reference" and site["complete"]:
            tp += len(expected & actual)
            fp += len(actual - expected)
            fn += len(expected - actual)
        if not site["complete"] and o["asserted_certain"]:
            false_certainty.append(site["id"])
        if not pyan and o["native_contexts"] and site["context"] not in o["native_contexts"]:
            context_errors.append(site["id"])
        if site["kind"] != "reference" and not o["native_site_recorded"]:
            site_missing.append(site["id"])
        records.append(
            dict(
                id=site["id"],
                location=dict(file=site["file"], line=site["line"], column=site["column"]),
                expected_context=site["context"],
                phase=site["phase"],
                kind=site["kind"],
                expected_targets=site["targets"],
                expected_exhaustive=site["complete"],
                adapted_relation=o["adapted_relation"],
                actual_targets_or_context_uses=o["targets"],
                missing_witnesses=missing,
                extra_call_candidates=extra if not pyan else None,
                forbidden_call_target_overlap=sorted(actual & set(site.get("forbidden", [])))
                if not pyan
                else None,
                native_contexts=o["native_contexts"],
                native_site_recorded=o["native_site_recorded"],
                asserted_certain=o["asserted_certain"],
                uncertainty=o["uncertainty"],
                raw=o["raw"],
                error=o.get("error"),
            )
        )
    metric = (
        None
        if pyan or plan.get("real_examples")
        else dict(
            meaning="native CALLS target pairs"
            if result["tool"] == "current"
            else "AST-position inferred callable candidate pairs, NOT complete call-graph accuracy",
            scope="complete manually labeled synthetic callsites only; real partial examples do not yield repository accuracy",
            tp=tp,
            fp=fp,
            fn=fn,
            precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn) if tp + fn else None,
        )
    )
    return dict(
        status="completed",
        bounded_target_metric=metric,
        pyan_metric_reason="USES lacks callsite/call-vs-reference semantics; call precision/recall not applicable"
        if pyan
        else None,
        false_certainty_sites=false_certainty,
        wrong_native_execution_context_sites=context_errors,
        missing_native_callsite_ids=site_missing,
        records=records,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    out = args.output.resolve()
    assert not out.exists(), "Output directory must be new"
    out.mkdir(parents=True)
    freeze = json.loads((HERE / "truth-freeze.json").read_text(encoding="utf-8"))
    for p, h in freeze["sha256"].items():
        assert sha(HERE / p) == h, "Frozen truth changed: " + p
    plans = {
        "synthetic": synthetic(),
        "cross-matched": cross(out, "matched"),
        "cross-mismatched": cross(out, "mismatched"),
    }
    if args.workspace:
        plans["real"] = real(args.workspace.resolve())
    summary = dict(
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_commit=git(ROOT, "rev-parse", "HEAD"),
        source_status=git(ROOT, "status", "--short", "--branch"),
        truth_freeze=freeze,
        python=sys.version,
        platform=sys.platform,
        experiment_files_sha256={
            p.relative_to(ROOT).as_posix(): sha(p)
            for p in sorted(HERE.rglob("*"))
            if p.is_file() and p.suffix in (".py", ".json", ".toml", ".lock")
        },
        runs={},
    )
    for name, plan in plans.items():
        folder = out / name
        folder.mkdir(exist_ok=True)
        plan.update(cache_dir=str(folder / "jedi-cache"))
        plan_file = folder / "plan.json"
        write(plan_file, plan)
        total_calls = sum(len(inventory(s)[0]) for s in plan["sources"])
        entry = dict(
            source_files=len(plan["sources"]),
            syntax_calls=total_calls,
            annotated_sites=len(plan["sites"]),
            repositories=plan["repositories"],
            tools={},
        )
        print(name, entry["source_files"], "files;", total_calls, "syntax calls", flush=True)
        for tool in TOOLS:
            result = measure(tool, plan_file, folder / (tool + ".json"), args.timeout)
            comparison = compare(plan, result)
            entry["tools"][tool] = dict(
                version=result.get("version"), measurement=result["measurement"], **comparison
            )
            print(
                tool, result["status"], round(result["measurement"]["wall_seconds"], 3), flush=True
            )
        if name == "synthetic":
            truth = json.loads((HERE / "truth.json").read_text(encoding="utf-8"))
            required = {
                Path(f).stem + ":" + n
                for f, names in truth["required_nodes"].items()
                for n in names
            }
            for tool in TOOLS:
                raw = json.loads((folder / (tool + ".json")).read_text(encoding="utf-8"))
                present = {n["id"] for n in raw.get("nodes", [])}
                entry["tools"][tool]["missing_required_nodes"] = sorted(required - present)
        summary["runs"][name] = entry
        write(out / "summary.json", summary)
    print("Results:", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
