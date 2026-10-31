# 字典值流 Neo4j 投影：独立审阅第 1/3 轮

2026-10-31。结论：**本切片通过；整个 Batch4 未完成、不合并。**

固定远端提交 `4a2bcf827e33eb393de5b288260ee63321734dd9`，基线 `793ca38b6228d15047ed7eb2c69116ed61680fcc`，tree `1b405783d6d15545cee922357fee9d09cc8acd9c`，分支 `feat/incremental-index-updates`。主 Agent 审阅开发子 Agent 的修改，未修改生产代码。审阅副本480个文件按远端 blob 验证，生产/测试源码齐全；262份无关历史 review 制品未恢复，不冒充完整历史材料重验。

## 审阅的实现

- `load_snapshot()` 从完整校验的 immutable SQLite sidecar 读取已认证值节点、边、读取订阅。只有明确完整 coverage 才生成 `native-value-v3`；旧/部分证据保持四字段 v2 指纹并声明未投影。新增节点没有进入搜索或向量。
- 导入创建带类型标签的 `LCTValue` 和原始 `LCTValueEdge` 证据，原有函数复用 `LCTNode:Function`。`READS` 同时保存 consumer 仓库/路径，缺失 key 的 `present=false` 没有丢失。
- 分批写入继续受 owner/lease fencing 管理。完整标记之前逐条验证代码/值图、端点、标签、数量、订阅和分块证据。失败批次保留为隐藏候选，重试清理同 scope 后重建，旧完整版本保持可读。
- `publication._descriptor/_verify` 绑定实际格式和值流数量；实际 `bind_current()` 与 `resolve_current()` 在真实数据库上通过。完整旧 v2 scope 不被静默原地换成 v3，既有 v1→v2 维护保持可用。
- 官方只读 MCP 仍是官方进程。新增固定值节点/值关系/分片模板；每条语句有 namespace、version、完整标记和指纹条件。按已知值/函数 ID 定位后沿原生边读取，再用索引取得原始证据。代码查询不会把值流关系混进 CALLS 结果。

## 验证与原始失败

固定源码使用 `/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python`。审阅副本最初没有项目 `.venv` 路径，注册测试按设计拒绝执行：初次 **618 passed、30 skipped、1 failed，38.43秒**。该失败不是生产改动；保留原日志，不删断言。建立指向同一已有测试环境的 `.venv` 链接后，注册单项 **1 passed/0.25秒**，再完整复跑以下快速集合。

| 检查 | 结果 | 证据 |
|---|---|---|
| 仓库 tests + 六组历史独立检查 + 新独立检查 | **619 passed、31 skipped/37.25秒，退出0** | value-projection-independent-regression-final.log |
| Neo4j5.26.0/APOC5.26.0 环境：新独立集合、新生产定向、旧迁移、官方MCP | **13 passed/24.44秒，退出0**；其中6个为无需服务的离线断言，7个实际使用服务 | value-projection-independent-service.log |
| 实际发布描述 + 函数反向关系/分页 | **1 passed/6.94秒，退出0** | value-projection-binding-service.log |
| 70,000字符值记录的拒绝直接读取与完整分片恢复 | **1 passed/6.26秒，退出0** | value-projection-large-row-service.log |

快速集合命令：`python -m pytest -q tests review/batch4-incremental/test_dictionary_flow_independent.py review/batch4-incremental/test_dictionary_local_independent.py review/batch4-incremental/test_value_index_independent.py review/batch4-incremental/test_import_receiver_independent.py review/batch4-incremental/test_changed_python_independent.py review/batch4-incremental/test_mixed_dictionary_independent.py review/batch4-incremental/test_value_projection_independent.py review/batch4-incremental/test_value_projection_binding_independent.py --tb=short`。31项跳过包含26项仓库服务检查、1项可选真实缓存检查、4项额外 review 服务检查；并非31项都未被其他命令验证。超大记录检查随后单独新增和执行，没有将此前快速集合说成已包含它。不同命令存在离线用例重叠，不合计为唯一通过数。

真实服务主命令：设置 `LCT_TEST_NEO4J_URI/USER/PASSWORD/DATABASE` 后运行 `python -m pytest -q -s review/batch4-incremental/test_value_projection_independent.py tests/test_neo4j_value_projection.py tests/test_neo4j_projection_migration.py tests/test_official_mcp.py --tb=short`。补充两个测试分别在实际服务上运行。服务只含本轮合成数据，loopback监听；通过官方 `neo4j-mcp-server==1.6.1` 的真实 stdio 调用确认 read-cypher 可用、write-cypher 不暴露、传入 CREATE 被拒绝。此处没有把 scope 条件说成数据库权限隔离。

## 局部性证据

固定公开模板、目标 read 节点及相邻关系，数据库增加1000个不相关 LCTValue 节点（另一 namespace，各带2048字符属性，约2MiB）。执行真实 EXPLAIN 与只读 PROFILE。所谓首次/重复是导入后本次请求的首次与重复执行，不声称刷新过操作系统或数据库全部缓存。

| 实际请求 | 无关节点0：行/回复字节/DbHits | 无关节点1000：行/回复字节/DbHits |
|---|---|---|
| 完整标记/指纹 | 1 / 134 / 9 | 1 / 134 / 9 |
| 已知 read 的值流邻接 | 4 / 1582 / 54 | 4 / 1582 / 54 |

首次与重复结果相同。计划包含 `NodeUniqueIndexSeek`，关系路径使用目标原生邻接；没有 AllNodesScan/NodeByLabelScan。计数为查询执行计划的数据库命中，字节为返回行数据 canonical JSON，不把它冒充磁盘物理读取或整个 MCP 封装大小。完整操作符见 `value-projection-profile.json`。另验证从现有函数 ID 反向取得 VALUE/POSSIBLE_CALLS 支持，并用limit1分页无漏失；原代码查询保持只返回代码关系。

普通状态实际摘要小于8KiB，未调用完整图说明接口。模板最多16展示条目+1前瞻，超65,536字符的单条raw被抑制，8,192字符分片可还原。官方模板不承诺整个MCP回复64KiB总上限；沿用原合同，文档明确字符阈值与总字节预算的区别。导入完整校验及一次性序列化可以线性读取整份输入，不是普通按ID查询。

## 裁决、限制与下一步

本切片未发现确认阻塞，正式第1/3轮通过，没有调整原有业务断言制造通过。新报告/补充测试属于审阅证据；审阅的生产代码固定上述SHA。

仅覆盖现有已认证固定字符串key字典子集，没有新增对动态key、复杂条件/循环写入、任意参数/返回/闭包值流的增量认证。新投影尚未迁移旧真实业务图，也未建立/上传新Drive包或调用API。所有测试是合成源代码/小型服务，不构成真实业务规模验收。整个Batch4仍需确认真实业务变更能局部分析、与同捕获full一致，以及完整增量发布/恢复流程。分支继续保留，不合并。
