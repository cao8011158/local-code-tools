# B4-REL-01：相对导入接线独立审阅，第 1/3 轮

2026-10-31。**本项通过，整个 Batch 4 未完成、不合并。**

检查提交 `4e3637905078984294b16c97bb30bac185c5a249`，tree `8ce3c30399457b51c601b57880a313d20f0f0278`；基线 `7b08cf6340a120d8773992847915327e61f0d3d2`，分支 `feat/incremental-index-updates`。开发子 Agent GPT-6 SOL / medium 实施，主 Agent 独立审阅，未修改生产实现。远端 SHA 已核对，564 个恢复文件按 Git blob 校验；262 份无关历史审阅制品未恢复，所需生产和测试源码齐全。测试后再次核对无变化。

## 先扩大真实样例，避免孤立样例通过冒充实际可用

从同一 SM 固定提交 `a7b0804d5635e185a79ff3c1d1fa6241c2b858fe` 取得 `_execution.py`、`combat.py`、`dnd_runtime.py`、`item_package.py`、`service.py`、`world_containers.py`，全部通过文件长度、SHA-256 和 Git blob 核对。加上原三个文件组成九文件**部分捕获**，不是完整应用。

AST 和模块解析器审计证明：`service.py` 的 `.availability`、`item_package.py` 的 `.item_units` 可以由已有 `Graph.import_request_module()` 正确规范化；认证和新增依赖选择却没有使用这项能力。与此同时，六个文件分别还含未覆盖的外部依赖、枚举/联合注解、模块赋值、控制流、装饰器或多重继承。未捕获的 `rules_adapter` 等模块只能保留 boundary，不能伪装成已捕获定义。

修复后同一九文件审计仍为 `full_certificate=null`，分别认证的仍只有原三个文件。这是明确保留的限制，**不宣称相对导入修复已让九文件实际局部更新**。基线诊断、逐文件原因及可重跑脚本见 `actual-related-admission-audit.md/json`、`audit_actual_related_admission.py`，本提交后的结果见 `actual-related-admission-after-relative.log`。

## 已关闭的接线缺口

`simple_python.py::_certify_v4()`、`_certify_common()` 不再直接拒绝所有相对 `ImportFrom`，而是先用已有解析器得到完整包名，再验证唯一实际捕获的 provider、允许的依赖绑定、选中范围、AST 和精确导出。`component_policy()` 使用同一个完整请求连接模块。

`python_incremental.prepare()` 也规范化当前源码中的相对导入，并把新 provider 及包上下文加入闭包。只改认证而不改这里，会漏掉旧图尚未连接的新导入目标，因此两处必须一起接通。

生产仅两文件，合计 +26/-10。未改 Graph/Jedi、值流或 SQLite schema。保留 v6 标记：旧获准形状语义不变，新实现仍受 program-hash 兼容门禁保护；此前不获准的相对形状才新增准入。没有放行 `from . import name`、star、越界层级、缺失/排除 provider、相对字典值流或任意复杂 Python。相对 `.dataclasses` 不能使用绝对标准库 helper 的豁免。

## 独立验证

| 检查 | 结果 |
|---|---|
| 固定旧代码上的独立用例 | **5 failed、6 passed / 1.38 秒**，失败均为相对形状无法认证；原始日志保留 |
| 修复后的独立预检 | **12 passed / 2.67 秒**；下行固定提交集合已包含，不重复计数 |
| 固定远端快速回归及独立边界 | **689 passed、32 skipped / 47.90 秒，退出码 0** |
| 测试后内容核对 | 564 文件相符，两生产文件未变化 |

独立用例包含 `.base`、`..mid`、别名、同名其他包隔离、provider 修改、调用者改为另一 provider、0/20 无关文件、真实 `errors.py` 加**合成**相对导入调用者。实际解析次数：三层相关链解析三个文件；改变导入目标后连同旧/新 provider 共四个；真实 errors 与合成消费者更新两个。无关文件未解析。未变捕获再次构建解析零个文件。

每次与新目录的完整重建比较 catalog nodes/edges 和 sidecar 的 sites、query_observations、import_dependencies、import_requests、analysis_reads、analysis_watches、value_nodes、value_edges、value_reads 全部记录。发布前故障保持旧 current 和旧记录，重试与完整重建一致。

`FileDependencies.importers(repository, 'pkg.base')` 在真实 SQLite 上执行 `EXPLAIN QUERY PLAN`，证明先用索引 SEARCH，无 SCAN。增加 20 组无关相对导入后，每次仍一条 SQL、一个相关文件；首次和重复读的 VM 计数分别保持不变。构造 FileDependencies 的全 artifact 校验属于必要准备，不计入单次查找，也没有宣称整个构建常数成本。此项未改变数据库实现，没有启动 Neo4j 或把 SQLite 结果冒充 Neo4j 性能证据。

32 项跳过中 31 项需 owned Neo4j 服务，1 项为可选旧真实缓存。没有付费 API、全业务图构建、业务代码执行或 Drive 操作。完整命令在 `relative-import-independent-evidence.json`，原始输出在 `relative-import-independent-suite.log`。

## 预检失败和测试材料修正

独立性能用例首版得到 1 failed、11 passed，因为错误要求首次与重复 SQL 执行 VM 计数完全相同，实际为 21/16。每次都只执行一条目标查询、返回一个文件。原用例和日志保留；现在分别比较首次/重复路径在无关规模增长下是否不变，并验证重复读取稳定。没有修改生产或降低无关规模局部性要求。

开发快速结果 615 passed、27 skipped 来自缺少原跟踪文件 `tests/test_dictionary_import_receiver.py` 的材料目录。提交前从已校验旧副本补齐，内容与远端原文件一致，补跑为 **618 passed、27 skipped / 34.29 秒**。正式审阅恢复的是完整生产/测试集合。没有将早期不完整目录的结果当作远端完整回归。

旧 v5 三文件诊断测试继续作为历史快照保留，不执行其中已被 v6 替代的“必须回退”断言；本轮延续上一轮的替代理由和实际局部/full 对照，没有为本项再删除业务断言。

## 裁决与剩余工作

当前没有确认的未解决阻塞，本项第 1/3 轮审阅通过。相对导入接线已关闭，真实复杂模块的局部准入尚未关闭。整个 Batch 4 仍不能合并。

下一步应围绕这批真实模块，审计解析器的读取、查找失败、候选集合与外部边界，列出统一依赖证据仍缺哪些入口，并使证据驱动准入和重算。不能把每个真实文件再堆成一个放宽白名单的例外。完成实际局部分析之后，还需统一图/检索版本发布、失败与恢复的端到端验收。
