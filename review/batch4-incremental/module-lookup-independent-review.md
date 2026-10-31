# 潜在子模块依赖索引：第1/3轮独立审阅

固定远端生产：5dd7ed4dbbc742149978f06fc69c79a3c24e28b3；分支feat/incremental-index-updates。390份本地支持文件按Git blob匹配，全部非review跟踪文件均可取得且匹配；不使用旧file_incremental.py草稿。

限定结论：indexed-v2潜在子模块查找依赖修复通过。整个依赖驱动准入/Batch4尚未完成，不合并。不是把全捕获认证删掉，也没有新增业务文件语法特例。

## 验证与初次失败
固定生产联合运行tests及独立反例：552 passed、1 failed、25 skipped/27.79秒。仓库tests全部547项通过；唯一失败为历史test_requester_access_independent.py将旧import_requests表名和旧索引名写死，与新索引不符。原始module-lookup-root-fixed.log保留。

只修改历史独立测试的计划断言：新数据访问必须SEARCH、必须用import_lookup_requester，允许相关子查询计划节点，仍禁止SCAN；保留公开build路径、重分析文件集合、完整重建对照和无关数据扩容断言。未修改生产。复跑全部本轮独立边界6 passed/2.69秒，日志module-lookup-root-boundaries.log。没有为测试名适配重新跑无关全仓库。

旧实现新独立namespace用例0/25无关模块均失败（2 failed/0.73秒），失败发生在无法反查pkg.foo。新实现两个场景均通过；别名chosen未当成模块名，其他仓库不误命中，完整重建caller从UNKNOWN变为捕获pkg.foo。该场景仍full-graph，明确未证明生产局部准入已开放。

## 实际局部查询证据
- 新模块查找：0/100无关导入时，实际两条SELECT每条返回1记录；SQLite VM步数42/44。EXPLAIN QUERY PLAN均为covering index SEARCH，无SCAN。module-lookup-query-probe.py及JSON可复现。测量在FileDependencies打开后，不包含构建或完整性哈希成本。
- 公开跨库遮蔽更新：0/20对无关调用/叶子模块时，均只解析调用方、本库新目标及绑定提供方目标3文件。两条依赖查询返回总计1条，实际VM步数87/88；祖先查询child范围及base存在性均走索引。结果与完整重建一致。
- 初版测量脚本曾错误要求VM步数严格相等，42/44已证明此要求过严；最终保留实际计数和索引/行数断言，不宣称固定常数或全流程O(1)。
- indexed-v1、缺表/列/索引与损坏artifact仍安全回退；原import_requests证据不改。首次构建索引以及完整输出写入本来需要处理全部记录，未将其冒充局部查询成本。

## 已知剩余问题与下一步
1. container_slots遍历全局effects.slot_scopes，A无导入/调用联系的局部写入也会进入B证据，目标虽未变但证据变。反例脚本/原始full/full输出已保存。本次不修该解析逻辑，不删除这些证据制造一致。
2. 无捕获root模块的跨库namespace潜在provider归属不完整，不能按任意仓库扩张。精确绑定变化仍回退全量。
3. 整批simple-python认证还在。下一阶段应定位并减少不必要的全局分析读取；对确需读取的依赖记录反向关系和新增候选范围，再用差分证明局部复用。

25跳过是服务/环境条件，不是Neo4j验收通过。没有运行真实全库、Neo4j服务、付费Embedding或Drive操作。当前没有本限定修复的未解决阻塞；原Batch4目标明确未通过，保留全部历史。
