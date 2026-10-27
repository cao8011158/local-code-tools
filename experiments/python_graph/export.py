"""Export compact selected evidence, never full real graphs, source plans or databases."""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from syntax import inventory  # noqa: E402


def main():
    """Redact machine paths and retain selected native raw outputs plus aggregate counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = args.input.resolve()
    summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    for name, run in summary["runs"].items():
        plan = json.loads((base / name / "plan.json").read_text(encoding="utf-8"))
        run["source_file_counts_by_repository"] = dict(
            Counter(s["repository"] for s in plan["sources"])
        )
        for tool, item in run["tools"].items():
            raw_path = base / name / (tool + ".json")
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            item.update(
                raw_local_result_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                network_denied=raw.get("network_denied"),
                network_attempts_blocked=raw.get("network_attempts_blocked"),
                enumeration_errors=raw.get("enumeration_errors", []),
                native_relation_counts=dict(Counter(e["kind"] for e in raw.get("raw_edges", []))),
                native_node_record_count=len(raw.get("nodes", [])),
            )
            if tool == "current" and raw.get("status") == "completed":
                native = {
                    (e["source_key"], e["line"], e["column"], e["expression"])
                    for e in raw["raw_edges"]
                    if e["kind"] == "CALLS"
                }
                syntax = set()
                implicit = 0
                for source in plan["sources"]:
                    for call in inventory(source)[0]:
                        if call["kind"] == "implicit_decorator":
                            implicit += 1
                        else:
                            syntax.add(
                                (
                                    source["repository"] + ":" + source["path"],
                                    call["line"],
                                    call["column"],
                                    call["expression"][:400],
                                )
                            )
                item["native_position_coverage_against_syntax"] = dict(
                    explicit_syntax_calls=len(syntax),
                    explicit_calls_with_native_record=len(syntax & native),
                    explicit_calls_without_native_record=len(syntax - native),
                    implicit_bare_decorator_applications=implicit,
                    note="Position inventory only, no full repository target ground truth or accuracy claim",
                )
                item["analysis_info"] = raw.get("info")
            # Definition-time expected targets may appear under multiple use contexts.
            if name == "synthetic":
                targets = {"sample:make", "sample:decorate"}
                item["definition_time_raw_relations"] = [
                    e
                    for e in raw.get("raw_edges", [])
                    if (
                        e.get("target", {}).get("id")
                        if isinstance(e.get("target"), dict)
                        else e.get("target")
                    )
                    in targets
                    and e["kind"] in ("CALLS", "USES")
                ]
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    # Longest root first, support both separator spellings in serialized JSON.
    replacements = [
        (str(HERE.parents[1]), "<TOOL_ROOT>"),
        (str(HERE.parents[1].parent), "<WORKSPACE_ROOT>"),
        (os.environ.get("USERPROFILE", ""), "<USER_HOME>"),
    ]
    for original, replacement in replacements:
        if original:
            for variant in {original, original.replace("\\", "/")}:
                text = text.replace(json.dumps(variant)[1:-1], replacement)
    # Do not publish private untracked filenames; repository identities and dirty counts remain.
    data = json.loads(text)
    for run in data["runs"].values():
        for repo in run["repositories"]:
            status = repo.get("status", "")
            repo["tracked_change_entries"] = sum(
                not x.startswith(("##", "??")) for x in status.splitlines()
            )
            repo["untracked_entries"] = sum(x.startswith("??") for x in status.splitlines())
            repo.pop("status", None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output, args.output.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
