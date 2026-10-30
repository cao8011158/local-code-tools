# 限定 Python 局部更新：独立审阅第 1/3 轮

2026-10-31。实现提交 `906dd60e9b17a2607983cd0bcac9f4eda07db288`，切片基线 `c4c22ec6d617395321fe2641da90e4d7a1e96de4`；分支 `feat/incremental-index-updates`，合并目标仍是 `feat/local-code-tools-import`。未合并。主 Agent 未编写生产实现，负责本次固定提交独立审阅。此前三轮实验和其他切片记录保留，本次不重置旧问题的轮次。

## 结论与范围

本切片通过限定范围审阅，未发现阻塞缺陷；B4-LOCAL-BUDGET 的多代上界丢失已关闭。**Batch 4 未完成，实际三个业务仓库的 Python 更新尚不能据此宣称局部化。** 新路径要求整个 Python 捕获属于单代码仓库，且此前通过严格语法认证；普通函数、明确的已捕获函数导入、有限位置/关键字参数回调可用。类、装饰器、注解、动态调用、未解析/外部导入、多代码仓库、其他未认证语法、Python 与文档同时变化等均保留完整分析。模块顶层当前也只允许导入和函数定义；认证范围比一般 Python 仓库窄。

## 实现核对

- `storage.build → python_incremental.prepare` 位于完整提取之前，首先验证程序/配置/运行时、捕获清单、旧 catalog 与依赖 sidecar 完整性。
- 从变更文件沿 `FileDependencies.adjacent/importers` 的实际索引查询，以及本次源码的新导入取得文件闭包。选中文件通过唯一 `python_nodes` 路径各解析一次；其余文件不创建 AST/Jedi 上下文。
- `simple_python` 在完整构建时认证旧捕获；当前更新只验证选中闭包，并核对旧认证清单。未覆盖的语法回退，不删除 UNKNOWN 或强行认证完整。
- 旧节点按持久化提取顺序恢复。`extract.definition_version` 是完整/增量共用的版本公式；`RebindContext` 允许以两份捕获源码摘要匹配代替重复 AST 比较，同时检查定义身份、位置、指纹及旧版本。未知引用格式拒绝复用。site、edge 身份和嵌套定义版本同步更新，旧版本不可变。
- `association_evaluations` 记录本轮实际工作，`association_bound` 单独跨局部/同捕获复用传递；累计超预算或缺证据回退完整分析。该保护不构成任意语法的全局依赖证明，不能放宽语法认证。
- 失败与发布仍经过原候选流程；没有启用旧 `file_incremental.py` 草稿。

## 独立验证

审阅副本 `/workspace/scratch/413372d9a5a5/lct-changed-review`，开始时 172 个相关代码、配置、测试及支持文件按 Git blob 与远端核对。测试后生产/已有测试均保持固定内容；唯一预期变化是独立审阅测试新增返回函数变体，作为后续证据提交，未改变生产实现。

| 检查 | 结果 |
| --- | --- |
| 固定提交 `tests/` ＋四份独立测试文件 | **526 passed、25 skipped，24.16 秒，exit 0** |
| 新增：函数返回值经关键字参数转交第三个文件 | **1 passed，0.65 秒**；只解析 a/b/c，全部结果等于完整构建 |
| 新增：公开 build 中实际依赖查询及无关关系扩容 | **1 passed，1.02 秒**；见下一节 |

完整命令：
```
PYTHONPATH=. /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python -m pytest -q tests review/batch4-incremental/test_changed_python_independent.py review/batch4-incremental/test_source_prepare_independent.py review/batch4-incremental/test_evidence_reuse_independent.py review/batch4-incremental/test_dependency_store_independent.py
```

原始日志：`changed-python-root-fixed-tests.log`、`changed-python-root-return-check.log`、`changed-python-root-access.log`。未把开发结果重复计数，也不把上述三次运行合并冒充一次完整回归。25 个跳过项仍是未验证。

独立测试比较节点、边、sites、query_observations、import_dependencies、import_requests 的完整 JSON 字段，包括版本/身份、UNKNOWN 和完整性信息；未删除版本字段后再判定通过。验证了回调目标 first→second、旧版保留、再次变更、发布前失败及重试、新导入使旧独立文件进入闭包、返回函数与关键字回调。此前同捕获复用、向量输入顺序、源证据拒绝、迁移/恢复及依赖索引检查一起复跑。

## 局部访问证据

公开调用 `build` 内部实际执行的两类 SQL 由 trace 获取，再对原语句执行 SQLite `EXPLAIN QUERY PLAN`；同时用进度处理器记录实际 VM 指令。没有替换查询函数的返回结果。扩大无关导入关系而非只增加空文件。

| 数据 | Python 文件数 | 实际解析 | 依赖查询次数 | 返回相关行合计 | 实际 VM 指令合计 |
| --- | ---: | --- | ---: | ---: | ---: |
| 无额外无关依赖对 | 3 | a/b 两个文件 | 4 | 3 | 138 |
| 增加 20 对无关导入/调用文件 | 43 | a/b 两个文件 | 4 | 3 | 141 |

计划使用 `file_adjacency` 源主键、目标索引、`import_request_lookup` 的 SEARCH；未扫描整张依赖表。3 条 VM 指令差异属于此次索引数据规模变化的实测，不宣称严格常数时间。之前0/20无关单文件对照也只解析a/b，新导入时扩展到a/b/u。

必须保留的成本：inventory、捕获摘要、旧产物完整哈希、读取并重绑定完整输出记录、生成完整候选及数据库对账仍随全量输入/输出增长。上述局部性证明仅针对依赖定位和 Python 解析/关联范围，不是所有更新成本都只随两个文件变化。未进行真实规模、Neo4j 或付费向量验收。

## 后续

下一步需要将认证和依赖处理扩展到实际业务仓库使用的类、方法及跨仓库情形，或者明确接受那些情况的完整分析回退；当前不能将这一决定冒充用户已接受的最终范围。然后完成真实图与检索索引统一增量发布、恢复及规模验收，才具备 Batch 4 最终合并条件。没有修改真实数据库、Drive 包或调用付费接口。
