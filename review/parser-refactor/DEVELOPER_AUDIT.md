# Jedi capability audit (read only)

Observed on materialized production tree `60085dc0158d6ae26b21dfabddafa0d6b5ef9a3b`, with `PYTHONPATH=. .venv/bin/python`, Jedi 0.20.1. Each probe passed captured source strings to `tests.test_python_pipeline.analyze` and independently called `jedi.Script(code=source, path=...).infer(line, end_column)` on AST call functions. No captured source was executed. `Graph` targets below are `resolution_decision` and public `sites` from those same sources. Scope is small reproductions, not a completeness claim for Jedi.

| Probe call expression | Raw Jedi `infer` result | `map_name` / Graph Jedi target | Graph local target | Public selected target and decision |
| --- | --- | --- | --- | --- |
| `target()` | `target` function | exact captured `target` | `target` | `target`, matching signals |
| `cb()` after `cb=target` | `target` function | exact captured `target` | `target` | `target`, matching signals |
| `cb()` after `if flag: cb=a; else: cb=b` | `a`, `b` functions | exact captured `a`, `b` | `a`, `b` | `a`, `b`, matching signals |
| `handler()` in `run(handler)` with `run(target)` | `target` function | exact captured `target` | `target` | `target`, matching signals |
| `fn()` in `invoke(fn=a)` with `invoke()` | `a` function | exact captured `a` | `a` | `a`, matching signals |
| `factory()()` where `factory` returns `target` | `target` function for outer callee | exact captured `target` | `target` | `target`, matching signals |
| `handlers['go']()` for local literal dict | `target` function | exact captured `target` | `target` | `target`, matching signals |
| `R[key]()` for local `{'a':a,'b':b}` | `a`, `b` functions | exact captured `a`, `b` | `a`, `b` | `a`, `b`, matching signals |
| `self.handler()` after `__init__` assigns `self.handler=a` | `a` function | exact captured `a` | `a` | `a`, matching signals |
| `self.target()` method | `target` function | exact captured `C.target` | `C.target` | `C.target`, matching signals |
| `R['go']()` after `register('go', a)` mutates global `R` | empty | no mapped target | `a` | `a`, finite association with missing Jedi signal |
| `a()` before `a=1` in same function | `a` function | exact captured `a` | empty | empty, tested semantic rule `unbound-local-before-assignment` |
| decorated `target()` where `@decorator` returns `wrapper` | `wrapper` function (`full_name=None`) | exact captured `decorator.wrapper` | empty | `decorator.wrapper`, partial association conflict retained with unknown |

The unbound-local probe has an independently known Python lexical rule: assignment makes `a` local throughout the function, and calling it before assignment raises `UnboundLocalError`. This is a concrete, narrow reason to exclude that Jedi target. The global registration case is a concrete missing Jedi result, so a source association is needed. The decorated binding probe supports retaining the mapped Jedi wrapper and uncertainty; it does not prove Jedi incorrect.

## Integration locations

- `lct/python_analysis.py:959-1040`: `query` calls `Script.infer` or `Script.goto(follow_imports=True)`, maps each raw Name through captured path and exact token, then **adds `jedi-inference-not-exhaustive` to every non-goto callable/class/instance result**. That generic reason is an analyzer policy, not a Jedi-reported uncertainty. The raw records preserve tool names, types, paths, mapping, and mapped target.
- `lct/python_analysis.py:817-958`: `map_name` validates exact captured definitions and imports; this mapping and version/source boundaries are needed even when targets are accepted directly. Statement and subscript receiver mapping recursively call custom `resolve` in some cases.
- `lct/graph.py:347-352`: every selected call site queries Jedi, resolves the same callee locally, then adjudicates. `lct/python_analysis.py:3066-3145` compares target sets and can override, union, or add unknown; the common matching-signal case has already performed both target analyses. `caller_atoms` at `lct/python_analysis.py:2227-2239` repeats local resolution/query/adjudication to recover bound receiver metadata for parameter flow.
- Local resolution dispatches through lexical reaching (`1141`, `1211`, `1334`), actual arguments (`2241`), return bodies (`1253`, `1314`), instance/member effects (`1429`), and container slots (`2743`, `2413`). The fact that these calls produce useful `unit_supports`, subscriptions, write provenance, receiver bindings, and uncertainty does **not** establish a need to let their duplicate target inference decide every covered call.
- `container_slots` at `2544-2545` unions origin-indexed scopes with all `_slot_fallback_scopes` for every read. In a separate known probe, a literal dictionary lookup whose raw Jedi target was already exact nevertheless checked 102 scopes with 100 unrelated fresh private local writers; broadening the syntactic whitelist is not a substitute for a tool-first source recording design. Verify any replacement against the current unit support/subscription and update equality gates.

## First bounded refactor proposal

1. Split a call site into **target observation** (Jedi raw, exact captured mapping, boundaries), **source evidence collection** (producer/read/negative membership, receiver context, effect uncertainty), and **target exceptions**. For the tested exact mapped, non-conflicting cases above, select the Jedi candidate set directly. Preserve all raw records and mapping identity; do not infer completeness merely from Jedi returning a target.
2. Initially admit only direct names and simple lexical aliases with exact mapped captured definitions and no local unbound/deleted binding, plus literal local dictionary entries when source tracking can record the exact origin and writer/read subscription without the current all-fallback-scope target search. Preserve the existing resolver as the exception path for the proven unbound rule and missing Jedi global registry, and preserve conservative behavior for decorators/descriptors/unknown results. For bound methods, keep receiver metadata extraction separately; raw Jedi definition alone does not encode allocation.
3. Add a source-only evidence walk for admitted cases (actual argument/default/return source support and matched container read/write membership) so the existing sidecar dependency contract, unknown reasons, and fresh-versus-incremental public graph equality remain intact. Measure `executed_queries`, resolver entries, scope/event checks and produced support/subscription sets; compare full and incremental results under unrelated writer growth. If source collection still recursively recomputes every target, the performance claim remains unproven and the admission should not expand.

Do not apply a global rule that ignores a conflicting local result: the unbound-local example proves a precise exception. Do not replace `jedi-no-result` with a target by spelling or global candidate search. The observed Jedi parameter/return/dictionary behavior makes the broad custom target inference a candidate for reduction, while source dependency recording and demonstrably missing semantics remain necessary.
