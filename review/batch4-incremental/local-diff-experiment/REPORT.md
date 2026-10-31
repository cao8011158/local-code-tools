# Bounded local-diff graph experiment

This is a test harness in the staged copy, not a production implementation. It calls the real `python_nodes` and `Graph.build` on captured text. No paid API, external service, Git checkout, or production code is touched. Run from the staged copy root:

```bash
PYTHONPATH=. /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch4-incremental/local-diff-experiment/run.py
```

`results.json` retains detailed mismatches, including site decisions, unknown flags, completeness, edge status/basis, and examples. `summary.json` is the compact run output. The new full build is constructed **after** the candidate and is never passed to closure, namespace lookup, or candidate analysis.

## Method and measured result

The candidate starts from changed/deleted paths. A SQLite index of **old** cross-file edges supports both incoming and outgoing traversal for `CALLS`, `IMPORTS`, `LOOKUP_IN`, `INHERITS`, references, and other genuine relations. `CONTAINS` does not connect files via their repository root. Old unresolved-import boundary ownership is recovered from its `IMPORTS` edge and joined to `LOOKUP_IN`. New files in the capture get a path-to-module inventory; imports in affected new source are parsed cheaply and looked up by exact module name, including a named submodule. In this bounded harness the effective expansion is the old-edge closure plus explicit imports iterated to a fixed point before analysis. The partial graph only contains included files, so its discovered-target step does not independently discover excluded files; arbitrary semantic edge discovery is not implemented. Old untouched outputs are merged with new outputs.

| Fixture | Match | Candidate analyzed files / full | Candidate Jedi / full |
| --- | ---: | ---: | ---: |
| direct change | yes | 2 / 2 | 2 / 2 |
| deletion | yes | 1 / 1 | 2 / 2 |
| return receiver in B | yes | 3 / 3 | 5 / 5 |
| callback from A to B (caller switches handler) | yes | 2 / 2 | 3 / 3 |
| missing name in existing module resolved | yes | 2 / 2 | 2 / 2 |
| **new module resolves an old import** | **no** | **1 / 3** | **0 / 2** |
| added import between disconnected files | yes | 2 / 2 | 2 / 2 |
| reexport | yes | 3 / 3 | 3 / 3 |
| inheritance | yes | 2 / 2 | 3 / 3 |
| registry value switches handler | yes | 2 / 2 | 2 / 2 |
| 20 unrelated files, each with a call | yes | 2 / 22 | 2 / 22 |
| 100 unrelated files, each with a call | yes | 2 / 102 | 2 / 102 |
| dynamic `getattr` unknown | yes | 2 / 2 | 3 / 3 |

For the new-module failure, old `b.py` imports `missing_mod.new_handler` while `missing_mod.py` does not exist. The old graph has no captured namespace and no `LOOKUP_IN`; adding that file seeds only itself. Reusing `b.py` leaves its import unresolved and its call unknown, while the full graph resolves both. The failure is preserved deliberately. A reverse lookup index over *unresolved imports to absent module names*, built from old captured source, would be needed; existing graph edges alone do not suffice.

The noise fixtures demonstrate bounded semantic work for this edit, **not constant total work**. The experiment preparator reads the complete old edge/node output to build its SQLite index and inventories all 22 or 102 new paths. It does not semantically parse unrelated source; the unchanged old graph must already exist. The `examined_import_file_count` metric counts cheap AST import parsing attempts in closure (2 for both noise cases), while `preparatory_full_path_inventory` counts global path entries. File-attempt, site, Jedi, old-edge/node and path-inventory counts for every fixture are in `results.json`. Bidirectional closure can also pull an entire large connected component through shared helpers, so these cases do not establish minimality.

## Boundaries and fidelity

Comparison retains multiplicity, logical nodes and source spans/fingerprints, site targets, UNKNOWN/completeness/reasons and resolution decision, and meaningful edge status, target and metadata. Opaque `site_id`, `edge_id`, snapshot/version IDs, and detailed raw evidence are excluded from equality. Reused old nodes/edges still carry their original version IDs; this harness does **not** correctly rebind them to a new repository snapshot or regenerate all target version references. A production candidate must solve this separately. The local graph may itself use a different closed-world universe, finite association budget, and Jedi environment from full analysis. These fixtures do not prove soundness for arbitrary dynamic imports, monkey-patching, plugin registries, many-to-many components, or budget saturation. Dynamic `getattr` preserves its observed unknown in the included two-file fixture, but no complete guarantee follows from it.

No project-wide timing or production migration claim is made. The result supports a narrower conclusion: old bidirectional graph edges plus exact new import namespaces give useful local work reduction, but **existing relations alone are insufficient** for an absent-module-to-present transition, and snapshot/version rebinding remains unsolved.

## 主Agent独立复核（2026-10-30）

- 核对本地21个lct/*.py的Git blob SHA，与远端7f7780cdb4ab235040e790aee1046c80657623ad一致；生产代码未改。
- 独立复跑run.py：13组，12组语义对照一致，1组不一致。脚本退出0只表示实验完成，不表示13组全通过。原始结果results.json与rerun.log保留。
- 独立脚本independent_probe.py增加3组：新增导入多跳传播一致；共享辅助模块结果一致但21/21文件全部分析、41/41次Jedi；新增此前缺失模块再次复现漏更新。
- 针对缺失模块，独立实验额外从旧源码一次性记录导入模块名→导入者（2文件、2条名称记录），按新增模块名建立关联；随后局部分析2/3文件，2次Jedi，语义结果与全量一致。补充仅在实验内，未修改生产解析器。不是完整负依赖机制的验收。
- 这证明当前确认的缺口可通过保存已有import语法信息解决，无需据此替换Jedi。粗粒度关系追踪可行，但无条件双向连通分量会过度扩展，需要变化类型/方向/输出变化停止传播规则。
- 没有运行全仓库回归：只增加独立实验材料，生产21文件完全不变；运行了本实验及独立反例。未测试实际Neo4j更新、事务发布、真实仓库规模、跨仓库绑定、版本身份重绑定。
- 没有宣称全图字节一致：normalized白名单比较节点主要字段、边及调用点语义；原始evidence、版本身份和部分展示元数据不在本轮比较范围。测试采用固定captured头，不代表真实Git切换。
- 生产接入之前仍需保证旧邻接/导入名索引在初次建立及修改时维护，不在每次更新时全图重建。当前实验的准备和结果合并阶段有全域线性处理，已计数。

独立复现：
```bash
PYTHONPATH=. /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch4-incremental/local-diff-experiment/independent_probe.py
```

结论：支持继续验证文件级增量方案；不是可合并的生产实现，也不是整个Batch4验收。保留原先失败，不把补充实验成功倒写为原方案通过。
