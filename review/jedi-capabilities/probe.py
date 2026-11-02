"""Reproducible public Jedi API experiment; never imports LCT or fixture modules."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import jedi
import parso

from cases import BY_ID, CASES

MARKER = re.compile(r"«([a-z_0-9]+)»")
SETTINGS = ("fast_parser", "dynamic_array_additions", "dynamic_params",
            "dynamic_params_for_other_modules")


def prepare(source):
    output, marks, end = "", {}, 0
    for match in MARKER.finditer(source):
        output += source[end:match.start()]
        label = match[1]
        if label in marks:
            raise ValueError("Duplicate marker " + label)
        marks[label] = (output.count("\n") + 1, len(output.rsplit("\n", 1)[-1]))
        end = match.end()
    return output + source[end:], marks


def environment():
    return dict(python=sys.version, executable=sys.executable,
                jedi=jedi.__version__, parso=parso.__version__,
                settings={key: getattr(jedi.settings, key) for key in SETTINGS},
                platform=sys.platform, code_execution="Script only; unsafe extensions disabled")


def identity(name, root):
    path = str(name.module_path) if name.module_path else None
    if path and Path(path).is_relative_to(root):
        path = "$CAPTURE/" + str(Path(path).relative_to(root))
    return dict(name=name.name, full_name=name.full_name, type=name.type,
                module_path=path, line=name.line, column=name.column)


def worker(case, config, order):
    for key, value in config.items():
        if key not in SETTINGS:
            raise ValueError("Unknown experiment setting")
        setattr(jedi.settings, key, value)
    report = dict(case=case["id"], family=case["family"], note=case["note"],
                  config=config, order=order, environment=environment(),
                  docs=case["docs"], sources={}, queries=[], syntax_errors=[])
    with tempfile.TemporaryDirectory(prefix="jedi-capability-") as temporary:
        root = Path(temporary)
        jedi.settings.cache_directory = str(root / ".jedi-cache")
        prepared = {}
        for path, source in case["files"].items():
            code, markers = prepare(source)
            prepared[path] = code, markers
            included = path not in case.get("omit", [])
            report["sources"][path] = dict(code=code, markers=markers, captured=included,
                sha256=hashlib.sha256(code.encode()).hexdigest())
            if included:
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(code, encoding="utf-8")
        libraries = [entry for entry in sys.path if entry and
                     ("site-packages" in entry or "python" in entry.lower())]
        paths = [str(root), str(root / "src")] + libraries
        project = jedi.Project(root, sys_path=paths, smart_sys_path=False,
                               load_unsafe_extensions=False)
        report["project"] = dict(sys_path=["$CAPTURE", "$CAPTURE/src"] + libraries,
                                 smart_sys_path=False, load_unsafe_extensions=False,
                                 cache_directory_isolated=True)
        scripts, requests = {}, []
        for path, (source, markers) in prepared.items():
            if path in case.get("omit", []):
                continue
            scripts[path] = jedi.Script(code=source, path=root / path, project=project)
            for error in scripts[path].get_syntax_errors():
                report["syntax_errors"].append(dict(path=path, line=error.line,
                                                     column=error.column, message=str(error)))
            for label, position in markers.items():
                apis = (["get_signatures"] if label in {"call", "end"} or label.startswith("call_") else
                        ["get_references"] if label.startswith("ref") else ["infer", "goto"])
                requests.extend((path, label, api, position) for api in apis)
        if order == "calls_first":
            requests.sort(key=lambda request: request[2] != "get_signatures")
        elif order == "reverse":
            requests.reverse()
        for path, label, api, (line, column) in requests:
            row = dict(path=path, marker=label, api=api, line=line, column=column,
                       source_line=prepared[path][0].splitlines()[line - 1], results=[])
            started = time.monotonic()
            try:
                names = getattr(scripts[path], api)(line, column)
                row["api_seconds"] = round(time.monotonic() - started, 6)
            except Exception as error:
                row["api_error"] = dict(type=type(error).__name__, message=str(error))
                row["api_seconds"] = round(time.monotonic() - started, 6)
                report["queries"].append(row)
                continue
            for name in names:
                try:
                    item = identity(name, root)
                except Exception as error:
                    row["results"].append(dict(identity_error=type(error).__name__))
                    continue
                if api == "get_signatures":
                    metadata_started = time.monotonic()
                    try:
                        item["parameters"] = [dict(identity(parameter, root), kind=str(parameter.kind))
                                               for parameter in name.params]
                    except Exception as error:
                        item["parameters_error"] = dict(type=type(error).__name__, message=str(error))
                    item["metadata_seconds"] = round(time.monotonic() - metadata_started, 6)
                row["results"].append(item)
            report["queries"].append(row)
    return report


def invoke(ident, config, order, repeat, timeout):
    argv = [sys.executable, str(Path(__file__).resolve()), "--worker", ident,
            "--config", json.dumps(config), "--order", order]
    started = time.monotonic()
    try:
        process = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return dict(case=ident, repeat=repeat, config=config, order=order,
                    status="timeout-unverified", seconds=round(time.monotonic() - started, 4))
    if process.returncode:
        return dict(case=ident, repeat=repeat, config=config, order=order,
                    status="harness-error", exit_code=process.returncode,
                    stderr=process.stderr, stdout=process.stdout)
    result = json.loads(process.stdout)
    result.update(status="observed", repeat=repeat, seconds=round(time.monotonic() - started, 4),
                  stderr=process.stderr, exit_code=process.returncode)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--config", default="{}")
    parser.add_argument("--order", default="source_first")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--controls", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(BY_ID[args.worker], json.loads(args.config), args.order)))
        return
    if not args.output:
        parser.error("--output is required")
    selected = args.only or list(BY_ID)
    runs = [(ident, {}, "source_first", repeat)
            for ident in selected for repeat in range(1, args.repeats + 1)]
    if args.controls:
        affected = ["dict_register", "dict_cross_module_write", "dict_getter_cross_writer",
                    "registered_callback_composition", "list_cross_module_append",
                    "recursive_parameters", "classmethod"]
        runs += [(ident, {}, "calls_first", 1) for ident in affected]
        runs += [(ident, {"fast_parser": False}, "source_first", 1) for ident in affected]
        runs += [("callback_positional", {"dynamic_params": False}, "source_first", 1),
                 ("callback_cross_module", {"dynamic_params_for_other_modules": False}, "source_first", 1),
                 ("list_append", {"dynamic_array_additions": False}, "source_first", 1)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    observations = []
    started = time.monotonic()
    with args.output.with_suffix(".jsonl").open("w", encoding="utf-8") as journal:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            pending = {pool.submit(invoke, *run, args.timeout): run for run in runs}
            for future in as_completed(pending):
                result = future.result()
                observations.append(result)
                journal.write(json.dumps(result, ensure_ascii=False) + "\n")
                journal.flush()
                print(json.dumps(dict(done=len(observations), total=len(runs), case=result["case"],
                                      status=result["status"], seconds=result.get("seconds"))), flush=True)
    report = dict(environment=environment(), case_count=len(selected), run_count=len(runs),
                  seconds=round(time.monotonic() - started, 4),
                  source_files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__), Path(__file__).with_name("cases.py"))},
                  runs=sorted(observations, key=lambda item:
                              (item["case"], json.dumps(item["config"]), item["order"], item["repeat"])))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [run for run in observations if run["status"] != "observed"]
    print(json.dumps(dict(output=str(args.output), cases=len(selected), runs=len(runs),
                          incomplete_runs=len(failures), seconds=report["seconds"])), flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
