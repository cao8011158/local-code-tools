# 实际跨文件读取记录：独立审阅第1/3轮

2026-10-31（北京时间）。**限定切片通过；Batch4整体未完成，不合并。**

固定生产提交 `ea0d0563d19d50d1ee08efd889e583a614f072c1`，基线 `32ffdac36e0037ee6c62a6f2917b5dba79145854`，tree `29c285dcdb13b5b21931e8bcc854231d0523489f`，分支 `feat/incremental-index-updates`。开发子Agent实施，主Agent独立审阅，未改生产代码。506个文件与远端Git blob一致；262份无关历史review制品未恢复，所需生产和测试源码齐全。测试后再次核对四个修改的生产模块仍与远端一致。

## 解决了什么

此前 `analysis_reads` 只保存 `container-effects`，`FileDependencies.analysis_readers()` 的SQL也只取这个kind。现在增加统一 `_record_scope_read()`，保存：

| 读取类型 | 实际含义 | 归属/时机 |
|---|---|---|
| member-lookup | 读取某个已知类的成员，包括成员尚不存在 | 查找前，当前表达式所在模块依赖类所属模块 |
| return-body | 判断函数返回什么时读取函数体 | 枚举函数体前，使用者依赖函数定义模块 |
| parameter-origin | 判断形参收到什么时采用某个实际调用者 | 仅在函数/绑定方法/构造器精确匹配后，接收方依赖调用者模块 |
| jedi-target | Jedi结果精确映射到捕获的定义 | 首次、复用及缓存命中均记录；以查询自身scope为consumer |

没有把最外层分析者当成所有嵌套查询的消费者，也没有把排除的调用候选全记到目标函数上。self/未知/外部owner不伪造成跨模块源。预算仍共用20,000条记录/订阅，超限标truncated，且不修改调用目标、UNKNOWN或原有证据判断。

`Graph.build()`先完成值流证据计算，再导出最终读取清单，避免晚发生的读取丢失。相应工作计数现在包含这一步的实际工作。SQLite保持原表列和producer索引，写schema2/partial，schema1只接受旧container-effects；未知kind、记录计数错或截断均拒绝用于依赖读取。`analysis_readers()`按producer仓库/路径取全部支持kind，`python_incremental.prepare()`的实际闭包队列消费这些结果。没有删除v5全捕获门禁或把部分证据包装成完整准入。

## 独立验证

旧代码上的5个反例均失败：缺实际参数来源、返回体/缺失成员依赖、持久化/消费者接线及预算截断信号；**5 failed/1.64秒**，日志scope-reads-baseline-independent.log。候选初步5项通过，正式审阅固定以上远端源码。

| 验证 | 结果/命令范围 |
|---|---|
| 最终独立定向 | **6 passed/2.54秒**；test_scope_reads_independent.py，含参数来源、排除无关候选、缺失成员、0/20无关文件的实际更新、失败/旧视图/full全部记录对照、预算、真实索引读取 |
| 固定生产快速集合 | **633 passed、32 skipped/36.01秒，退出0**；仓库tests、开发定向、上述独立、历史容器/字典/类/跨库/源文件/值投影检查 |
| 真实业务三个文件 | 当前诊断复跑通过，仍full：3个文件、13sites、30Jedi；新旧观测跨文件读均0，full记录一致、旧版本保持；不称局部更新通过 |

快速集合：`python -m pytest -q -rs tests review/batch4-incremental/test_observed_semantic_reads.py review/batch4-incremental/test_scope_reads_independent.py review/batch4-incremental/test_analysis_reads_independent.py review/batch4-incremental/test_dictionary_flow_independent.py review/batch4-incremental/test_dictionary_local_independent.py review/batch4-incremental/test_value_index_independent.py review/batch4-incremental/test_import_receiver_independent.py review/batch4-incremental/test_changed_python_independent.py review/batch4-incremental/test_mixed_dictionary_independent.py review/batch4-incremental/test_value_projection_independent.py review/batch4-incremental/test_value_projection_binding_independent.py review/batch4-incremental/test_actual_source_current_diagnostic.py --tb=short`。32跳过为需服务或可选缓存条件，本轮没有实际Neo4j/MCP服务验证；上轮服务结果不冒充当前SHA的新验收。多条命令有重叠，不累加唯一测试数量。

0/20无关普通模块时，公开更新只解析caller/provider，反查确实经过analysis_readers；before_publish失败保留旧current及全部旧表，重试与新捕获full的nodes/edges/sites/import/query/value及analysis_reads/watches相同。缺失成员仍UNKNOWN，没有新编确定调用。记录预算为0时，公开节点/边/sites保持，truncated变真，读取不假装完整。开发的缓存命中、schema1和未知kind测试已独立复跑。

## 初次性能对照失败的原因及处理

首个审阅新造性能样例向图增加15组回调调用，初次快速结果 **632 passed、32 skipped、1 failed/43.87秒**；定向为5 passed/1 failed/4.22秒。断言要求无关规模增加后VM步数相同，实测26降至21。

定位发现这不是固定相关输入的对照：15组回调触发原解析器20,000次association预算，分析标analysis_limited=true，目标依赖中parameter-origin也少了一条。旧生产32ffdac的相同输入同样触顶（scope-reads-limited-fixture-baseline.log）。没有证实本切片引入误连/漏检，不能把这个样例当作无关数据下的相同K，也不能声称回调规模已通过。

只修改主Agent新增的性能样例：用15对跨模块函数引用来增加无关依赖记录，不引入新的回调调用候选；新增“分析未触顶”和“匹配记录数量相同”的硬断言，原步数相同断言保留。初始失败日志和旧测试版本在ea0d056提交中保留，没有删除或改松生产断言。随后定向和整套复跑通过；生产代码完全未变。

| 已知producer反查 | 无关对0 | 无关对15 |
|---|---|---|
| 全部analysis_reads行 | 3 | 18 |
| 匹配的依赖记录 | 2 | 2 |
| 去重消费者文件 | 1 | 1 |
| SQL条数 / SQLite VM进度步 | 1 / 26 | 1 / 26 |
| 实际计划 | SEARCH，覆盖索引analysis_read_producer | 相同 |

完整SQL/VM结果在observed-read-index-profile.json。FileDependencies打开时的artifact hash、表/数量/kind完整性校验是每次构建/打开证据的准备成本，未混入上表的一次目标查询；它仍可以读取完整证据，不称端到端构建O(1)。读取API没有新增全表扫描、逐目标序列化或复制。

## 文档核对与限制

发现文档仍有上一切片留下的“值关系没有投影Neo4j”绝对表述，已在报告提交中改为区分：SQLite sidecar的internal-sqlite-only存储标记，与已接通的可选native-value-v3发布绑定。这是文字更正，不改实现。

本轮是已观测语义来源的记录和实际消费者接线，**不是完整的跨单元依赖证明**。Jedi失败/未解析命名空间、未来新增调用者、其他隐式读取/动态边界仍未完整认证；已知类缺失成员只记录类所属模块，不宣称完整字段/命名空间订阅。schema2仍是partial，v5和旧回退保留。真实样例来自SM固定提交a7b0804d5635e185a79ff3c1d1fa6241c2b858fe，非最新main或全业务库。

确认无当前未解决阻塞，正式第1/3轮通过。没有付费API、业务源码修改、真实图重建或Drive操作。下一步仍要补充未找到/未来候选的证明，再按分析单元放开复用；当前不承诺任意真实业务修改局部化，Batch4整体未完成、不合并。
