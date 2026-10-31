# 常见 Python 规则与候选索引：独立审阅第 1/3 轮

2026-10-31。**本切片通过；Batch 4 整体尚未完成，不合并。**

检查提交 `07b6b6c48d7921f2802c00ef62192e849e2371eb`，tree `ca228fab009ddf7bc563d66c02a51913428d8051`；基线 `db4ec71a03403e7e7a3c01d0f9645e864b6b76ca`，分支 `feat/incremental-index-updates`。开发子 Agent GPT-6 SOL / medium 实施，主 Agent 独立审阅，未修改生产实现。远端内容恢复后，534 个现有文件均通过 Git blob 校验；262 份无关历史 review 制品未恢复，生产和所需测试完整。测试后重复校验无内容变化，四个修改的生产文件也与待提交报告的工作区一致。

## 用户关心的结果

此前，`simple_python.certify()` 没有批准 `availability.py` 的关键字专用参数和多层 self 字段，以及 `errors.py` 的受限 dataclass、Exception 和 property。整个捕获必须通过，因而修改一个文件也回退为全量分析三个文件。`item_units.py` 原有单文件规则可以通过，但不能单独解除整批回退。

现在增加有边界的 `simple-python-v6` 规则。对固定 SM 提交 `a7b0804d5635e185a79ff3c1d1fa6241c2b858fe` 的这三个文件：

| 验证输入 | 实际结果 |
|---|---|
| 改 availability 的 `context=context` 为 `context=None` | 重新解析 availability 一个文件，复用另外两个 |
| 再增加 20 个无关文件，同样修改 | 仍只解析一个，复用另外 22 个 |
| 增加真正导入 AvailabilityRuntime 的调用者 | 解析 availability 和调用者两个文件 |
| errors 的标量默认值改变，存在导入消费者 | 解析 errors 和消费者两个文件 |
| 跨文件回调参数从 first 改成 second | 两个相关文件重新分析，结果与完整重建一致 |
| 发布前注入失败，再重试 | 失败保持旧 current 和旧记录；重试结果与完整重建一致 |
| 捕获完全不变，再次构建 | 不重新解析 Python 文件 |

独立对照不只比较最终调用边：比较 catalog 的 nodes/edges，以及 sidecar 的 sites、query_observations、import_dependencies、import_requests、analysis_reads、analysis_watches、value_nodes、value_edges、value_reads 全部记录，保留旧快照隔离。

## 实现与边界审阅

- `simple_python.certify()` 保留原严格规则和字典切片，增加受限常见写法：关键字专用参数、关键字标量默认值、内置标量名或 None 注解、self/已知本地对象字段链、精确冻结 slots 标量 dataclass、直接 Exception 子类的 super 初始化、仅返回 self 字段链的只读 property。
- 自定义装饰器/继承、默认工厂、动态 getattr、不支持的注解和泛型没有被放行。捕获内 stdlib 同名遮蔽、helper/builtin 名称被覆盖、缺少模块 AST 等也拒绝认证。未知/不支持的捕获保持原全量候选行为。
- `Graph.build()` 用全部 catalog Python 模块参与认证，避免只证明碰巧有 AST 的部分模块。认证通过后，`component_policy()` 按精确捕获的显式导入建立双向连通组件；这不是任意以文件名相似或目录相同分组。
- `Analyzer.candidate_sites()` 和构造器兜底 `sites_for()` 使用同一个组件位置索引。已知相关组件先限制候选，再合并/排序；不先扫描全局再过滤。组件只遍历一次并共享成员集合；语法认证的命名空间上下文每次 certify 调用准备一次，而非每文件重复扫描。
- 0/200 个无关调用位置模块的独立 GuardList 禁止整表迭代：普通、构造器和 inflight 候选合计仅按索引读取 `3*K` 次，K 为相关组件位置数。新增未编入索引的位置时，返回原完整列表，不静默遗漏候选。
- `storage.py` 使用统一证书常量，旧 v5 不充当新语法的局部准入。未改公开节点/版本身份、值流 schema、Jedi 或 EffectCatalog。

## 失败证据与行为改变

开发首版只扩展语法时，局部与完整分析的一个 site 证据不一致：局部 trace 3 步、完整分析 16 步，coverage 的重复缺口数量也不同。原因是完整分析的参数/构造器候选检查把不连通模块混入证据。没有删除、去重或标准化这些语义字段来掩盖差异。

修复让已认证捕获的完整和局部分析都使用同一必需组件范围；未认证捕获不改变原候选范围。原失败日志 `common-certificate-real.log`、`common-certificate-real-initial.log` 和反例说明保留。随后旧快速回归还发现未认证 inflight 调用者要求返回同一个 `self.sites` 列表，已恢复这个兼容行为。最终固定提交上全部回归通过。

历史 `test_actual_source_current_diagnostic.py` 明确断言旧 v5 下三个文件必须回退全量，属于当时的诊断快照。本轮保留该文件及历史结果，未将其作为新 v6 的验收断言执行；新开发和独立用例以同一份源码、实际解析次数和完整记录对照替代。没有修改生产 tests 内的历史断言来制造通过。

## 独立验证

| 检查 | 结果 |
|---|---|
| 旧基线上的新真实局部能力断言 | 2 failed、9 deselected；旧证书不能批准三文件，原始日志保留 |
| 主 Agent 新增独立用例预检 | 11 passed / 3.34 秒；随后全部包含于下行固定提交回归，不累加计数 |
| 远端固定提交快速回归及独立边界 | **665 passed、32 skipped / 46.06 秒，退出码 0** |
| 测试后远端内容复核 | 534 文件相符；四个修改的生产文件未变化 |

32 项跳过中，31 项需要 owned Neo4j 服务，1 项为可选既有真实缓存。当前切片未修改 Neo4j/MCP 接口，未启动真实服务；不把此前服务结果冒充本 SHA 的新验收。原始命令和结构化结果见 `common-certificate-independent-evidence.json`，完整输出见 `common-certificate-independent-suite.log`。

## 裁决与下一步

没有确认的未解决阻塞，本切片正式第 1/3 轮审阅通过。当前结论限于闭合语法规则及固定三文件样例，**不是全业务库已实现任意局部更新**。无付费 API、真实业务图重建、业务源码修改或 Drive 操作。

接下来应扩大到有代表性的真实关联文件，先记录剩余回退的确切原因，验证局部结果、实际工作量及完整重建一致性；之后才进行 Batch 4 的检索/图版本发布与恢复端到端验收。本切片不合并，整个 Batch 4 完成后再按既有授权合并。
