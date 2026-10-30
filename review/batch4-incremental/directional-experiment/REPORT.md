# Bounded directional scheduling experiment

Run `PYTHONPATH=. /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch4-incremental/directional-experiment/run.py` from the project root. The independent probe uses `independent_probe.py` in the same directory. `results.json` and `independent-results.json` hold complete normalized differences. The engine is pinned as `graph_under_test.py` (SHA-256 `636bb84f2466b61059ced30193fb104882e77b8ed65435e64e76ae9d86898cce`), a copy of the local uncommitted `lct/graph.py` at experiment time, including the absent-module work. This is **not** a claim about the remote production baseline.

The candidate captures all new Python nodes/ASTs, constructs the real Analyzer with its complete site inventory, and runs the copied Graph.build with exactly one research-only guard on its *outer* site loop. All other Graph.build passes run across every file. It reuses old CALLS edges and site records for files omitted by that guard, while non-CALLS edges and nodes come from the new full-context pass. The comparison oracle is an independent fresh full build after selection; its graph is never input to the candidate. The older bidirectional component harness is run separately on the same fixtures.

The selector seeds changed paths; for direct function return-expression AST changes it follows old CALLS **backward to callers**, then through functions forwarding a call return, with a visited set. For changed positional call arguments inside direct functions it follows old CALLS **forward to callees** whose bodies invoke a parameter. Added/deleted modules or changed top-level direct function names select static syntax importers on either side. No other changes are certified. The selector does not compare semantically resolved summaries; its source-shape heuristics are deliberately incomplete, and its successful fixtures establish only bounded behavior.

| Case | Directional match | Outer sites directional/full | Jedi queries directional/full | Component match; site attempts |
|---|---:|---:|---:|---:|
| Shared helper, 20 importers, unused local literal | yes | 0/20 | 20/40 | yes; 20 |
| Positional callback replacement | yes | 2/2 | 3/3 | yes; 2 |
| Direct return object replacement, receiver downstream | yes | 3/3 | 4/4 | yes; 3 |
| Body unused local literal, one importer | yes | 0/1 | 1/2 | yes; 1 |
| Module deletion | yes | 1/1 | 2/2 | yes; 1 |
| New previously absent module | yes | 1/1 | 2/2 | **no**; 0 |
| Transitive forwarded return | yes | 4/4 | 6/6 | yes; 4 |
| Return change in call cycle | yes | 2/2 | 4/4 | yes; 2 |
| Return value changed via local assignment | **no** | 1/3 | 2/4 | yes; 3 |
| Keyword callback argument replacement | **no** | 1/2 | 3/3 | see JSON |
| Selector return literal used by callable registry | yes | 2/2 | 3/3 | yes; 2 |

The separate independent probe found **three independently supplied failing variants (two overlap the developer failure categories)**: keyword callback replacement, return through a changed local binding with unchanged `return chosen` syntax, and module-level callback invocation replacement. Each missed one changed CALLS edge and one site record; the stale old target replaced the fresh target. These are correctness failures, not acceptable UNKNOWN results. The direct return literal selector example is a counterexample to treating any body literal change as irrelevant: `handlers[selector()]()` changes its target, so the return-expression rule correctly selected its consumer.

The one meaningful saving measured is 20 versus zero *outer* sites for a shared helper's irrelevant local assignment, with 20 versus 40 actual Jedi queries. All 21 files still receive AST capture, Analyzer setup, and non-CALLS passes; association evaluations were 20 in both runs. Thus the experiment does not establish proportional file parsing, relation rebuild, end-to-end runtime, or general query savings. Component attempts count repeated parses, while directional `full_ast_context_files` counts a single global context load, so these are different denominators. The fresh full normalized comparison preserves nodes, all relation kinds, call targets, completeness, UNKNOWN, reasons and resolution decisions; it excludes opaque IDs and capture/version IDs. Reused old site/edge IDs and provenance are **not** validated as production-safe here.

For an implementation, unsupported or unproven AST forms (keyword/star arguments, return-through-local assignments, module-level calls, indirect dataflow, dynamic binding, reexports, aliases, decorators, classes and contextual effects) require a conservative full fallback until a sound changed-summary and dependency certificate exists. A successful fallback was not implemented or measured here. No production files were edited by this experiment.

## Bounded v2 refinement (separate from frozen v1)

Run `v2.py` with the same interpreter and `PYTHONPATH=.`; its independent output is `v2-results.json`. V1 `run.py`, `results.json`, and the independent probe's original results remain untouched. V2 still uses the pinned Graph implementation and fresh full builds only as comparison oracles. It instantiates the real Analyzer separately over *both* complete old and new AST catalogs, resolves the return expressions of changed top-level functions, and compares atom kind/target, reasons, proof sets and requirement completeness. Syntax changes to a return expression also count, since a changed literal can affect a downstream registry call without producing a callable return atom. It follows old caller edges, evaluates each caller's old/new return summary, and repeats through changed summaries using a visited-function worklist. Changed `ast.Call` shapes include keyword arguments and module-level calls; it conservatively inspects old outgoing targets and resolves new call sites in the new Analyzer context, then selects callees invoking a parameter. The latter broad scan can overselect and is not an exact changed-call-site certificate.

**All 15 v2 fixtures matched** the normalized fresh full graph: the original 11, the independent three (keyword callback, changed local return binding, module-level callback), and an added transitive return forwarded through a local binding. This repairs the observed v1 misses *within these fixtures*, not arbitrary source semantics. In the 21-file shared-helper case it still selects only the changed file's zero outer call sites; its selective graph pass makes 20 Jedi queries versus 40 for full. Summary preparation additionally captures **21 old + 21 new AST file contexts**, makes 2 summary evaluations and 2 associations (zero Jedi queries), before the separate 21-file graph pass. In the independent keyword case the preparation adds one new-context Jedi query to the selective pass's 5 (full uses 5); the local-forwarding case adds one query on each side to the selective pass's 6 (full uses 6). The JSON records all old/new context, query, association and summary counts, separate from the selective pass. Old summary recomputation could in principle be cached in a future design, but this prototype does not do so.

V2 remains a restricted hypothesis. It handles direct top-level function returns and known CALLS edges; it has no completeness certificate for arbitrary cross-file effects, reexports, mutation, context execution, keyword forwarding, dynamic dispatch, or changing node identities. Its candidate still rebuilds non-CALLS relations globally and reuses old opaque IDs without validation. An implementation would require explicit sound fallback to full analysis outside its proven domain; no such fallback was implemented or counted. The v1 failures remain recorded as research outcomes.

Root-authored `independent_v2.py` adds two further probes in `independent-v2-results.json`. A return forwarded through a local in an intermediate file **matches** and selects all three files. A factory returning the same `Box` class with a changed callback field **fails**: its resolved return atom summary remains the same class, so only the factory file is selected; one downstream CALLS edge/site retains the old callback. This demonstrates why equal return atoms are not a sufficient semantic-impact certificate for mutable or constructor-initialized object state. The failure is preserved without extending the v2 rules.

## 主Agent第二次独立复核

固定v2脚本后独立执行v2.py和independent_v2.py：开发/前轮回归15组均匹配；新增独立2组中，局部变量转发的三文件链匹配，同类返回对象字段变化不匹配。重叠写法不当作互不相同的全覆盖证据。命令退出0仅表示结果记录完成，不能称全部验收通过。原始日志root-v2-rerun.log、root-independent-v2.log。

剩余明确原因：direct_return_values只比较atom的kind/target等摘要，不能区分同一Box类型内的cb字段从first变为second。调度器据摘要相同停止传播，复用的调用候选仍指向first，全量结果指向second（两者均保留UNKNOWN）。这是实验的停止条件不足，不是Neo4j不能反向查找，也不证明需要换Jedi。

后续可行修正方向是：没有完整字段/状态依赖摘要时，不把对象类型相同视作结果相同；沿对应返回值消费者保守传播。是否能停止必须由与该消费者有关的语义信息决定。此方向尚未实现或测试，本轮不继续扩大到完整对象状态分析。

结论：定向传播在限定场景有实测支持；第二版尚不能作为通用生产更新调度器。它没有实现“所有关系都只局部重算”，准备AST、非CALLS及summary成本明确仍为全域/重复。固定图快照SHA见上文，其余解析器来自63a26e5da50b7eca99e03aa377ff6d6a85393119对应实现。正式lct/及storage接入未随本实验推送；缺失模块生产修改和file_incremental草稿仍留本地待后续处理。
