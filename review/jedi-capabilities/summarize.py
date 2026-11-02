"""Summarize raw observations without turning them into production expectations."""

from collections import Counter
import json
from pathlib import Path

from cases import BY_ID
from edge_paths import CASES as EDGE_CASES

ROOT = Path(__file__).resolve().parent


def normalized_query(query):
    result = {key: value for key, value in query.items()
              if key not in {"api_seconds", "results"}}
    result["results"] = sorted(
        [json.dumps({key: value for key, value in name.items()
                     if key != "metadata_seconds"}, sort_keys=True)
         for name in query["results"]])
    return result


def fingerprint(run):
    return sorted(json.dumps(normalized_query(query), sort_keys=True)
                  for query in run.get("queries", []))


def display(query):
    if query is None:
        return "—"
    if query.get("api_error"):
        return "API ERROR " + query["api_error"]["type"]
    if not query["results"]:
        return "空"
    values = []
    for name in query["results"]:
        value = (name.get("full_name") or name.get("name") or "?") + ":" + name.get("type", "?")
        if name.get("parameters_error"):
            value += "; params ERROR " + name["parameters_error"]["type"]
        values.append(value)
    return ", ".join(values)


def main():
    report = json.loads((ROOT / "observations.json").read_text())
    report["runs"].extend(json.loads((ROOT / "edge_paths.json").read_text())["runs"])
    cases = dict(BY_ID, **{case["id"]: case for case in EDGE_CASES})
    base = [run for run in report["runs"] if not run["config"] and run["order"] == "source_first"]
    groups = {}
    for run in base:
        groups.setdefault(run["case"], []).append(run)
    differences = []
    for ident, runs in groups.items():
        assert len(runs) == 2 and {run["repeat"] for run in runs} == {1, 2}
        if fingerprint(runs[0]) != fingerprint(runs[1]):
            differences.append(ident)
    queries = [query for run in report["runs"] for query in run.get("queries", [])]
    errors = [dict(case=run["case"], config=run["config"], order=run["order"],
                   marker=query["marker"], api=query["api"], error=query["api_error"])
              for run in report["runs"] for query in run.get("queries", [])
              if query.get("api_error")]
    metadata = [dict(case=run["case"], config=run["config"], order=run["order"],
                     marker=query["marker"], api=query["api"], target=name["full_name"],
                     error=name["parameters_error"])
                for run in report["runs"] for query in run.get("queries", [])
                for name in query["results"] if name.get("parameters_error")]
    primary = []
    for ident, runs in sorted(groups.items()):
        run = sorted(runs, key=lambda item: item["repeat"])[0]
        for query in run["queries"]:
            if query["api"] == "get_signatures" and query["marker"] != "end":
                primary.append(query)
    summary = dict(cases=len(groups), baseline_runs=len(base),
                   additional_controls=len(report["runs"]) - len(base),
                   all_runs=len(report["runs"]), core_experiment_seconds=report["seconds"],
                   run_status=dict(Counter(run["status"] for run in report["runs"])),
                   query_count=len(queries), api_counts=dict(Counter(q["api"] for q in queries)),
                   baseline_call_queries=len(primary),
                   baseline_call_nonempty=sum(bool(q["results"]) for q in primary),
                   baseline_call_empty=sum(not q["results"] and not q.get("api_error") for q in primary),
                   baseline_call_api_errors=sum(bool(q.get("api_error")) for q in primary),
                   baseline_repeat_differences=differences,
                   api_errors=errors, metadata_errors=metadata,
                   qualification="Observed API output, not a completeness, accuracy or runtime-execution guarantee.")
    (ROOT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = ["# Jedi 0.20.1：逐例原始结果索引", "",
             "本表由 observations.json 生成，不是生产目标规则、白名单或准确率测试。",
             "每个默认场景在独立进程中重复两次；源码、配置、坐标及所有原始结果见对应 JSON。",
             "空结果、API 异常、元数据异常和 instance 类型分开显示；不将它们都归为“不支持”。",
             "", "| 场景 ID | 类别 | 调用位置 get_signatures | 同位置表达式 infer |",
             "| --- | --- | --- | --- |"]
    for ident, runs in sorted(groups.items()):
        run = sorted(runs, key=lambda item: item["repeat"])[0]
        calls = [query for query in run["queries"] if query["api"] == "get_signatures"]
        inferred = [query for query in run["queries"] if query["api"] == "infer" and
                    query["marker"] in {"value", "callback_value", "base", "binding"}]
        call_text = "; ".join(query["marker"] + ": " + display(query) for query in calls)
        value_text = "; ".join(query["marker"] + ": " + display(query) for query in inferred)
        lines.append(f"| {ident} | {cases[ident]['family']} | {call_text or '—'} | {value_text or '—'} |")
    lines += ["", "## 重复及控制", "",
              f"- 默认场景重复差异：{differences or '无（完整记录 multiset；保留重复和参数内部顺序）'}。",
              f"- API 异常：{len(errors)} 次；分布及原始错误见 summary.json。API 异常不能计为空结果。",
              f"- 签名参数元数据异常：{len(metadata)} 次；已返回的签名目标仍保留。",
              "", "所有结论只适用于案例中的具体源码、版本、API、坐标和配置。"]
    (ROOT / "CASE_MATRIX.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in {"api_errors", "metadata_errors"}}))


if __name__ == "__main__":
    main()
