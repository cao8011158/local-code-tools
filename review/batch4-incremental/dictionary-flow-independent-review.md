# 跨文件字典函数值切片：独立审阅第 1/3 轮

2026-10-31（北京时间）。结论：**限定切片通过；Batch 4 未全部完成，不合并。**

固定提交 `cf4b0fbac0e11f18d53f7dbff1be8b1e40cd6505`，父提交 `87acde8e3f726560eb6e1d17da136e16dd8c9fdc`，tree `2b761e04afb951fa84baab969df8a1bfb226bafa`；工作分支 `feat/incremental-index-updates`。主 Agent 独立审阅子 Agent 的实现，没有修改生产代码。远端引用核对一致；454 份审阅副本文件匹配远端 blob，全部生产与测试源码齐全。262 份无关历史 review 制品未恢复，未拿缺失材料作本轮证据。

## 实现与消费者核对

- `value_flow.capture_shape/evidence` 对支持的字典、字符串 key、声明/导入/别名、直线写入及固定 key 调用保存有来源的内部节点和边。实际目标仍由 Analyzer 计算，结构支持必须与实际 subscript 和公开 site 结果一致。不能用缺失 witness 建完整证据。缺 key 的条目是 `present=false` 的可订阅地址。
- `Graph.build` 导出私有模型；`storage.build/split_graph` 将它从公开 graph 摘要移出，写入 `graph-sites.sqlite` 的 value_nodes/value_edges/value_reads。manifest 仅保存版本、覆盖、数量和 internal-sqlite-only 声明，不携带图数组。现有函数节点、搜索层级、向量和 Neo4j 公开图投影未被替换。
- `FileDependencies.entry_ids_for_file/value_readers` 先按目标文件/条目索引定位；`get_value_nodes/get_value_relations` 按 ID 索引，最多 100 项并显式报告 has_more。partial/预算不足的影响集合不可冒充完整返回。打开时的完整性哈希和数量校验是一次完整快照检查，与这些实际查询的成本分开记录。
- `python_incremental.prepare` 确实调用这些反向入口，并保留已有文件/导入、module analysis readers 和一次性 capture-wide watcher 扩展。旧证据用于删除和缺失 key 新增；没有仅存表不接消费者。Broad watcher 的扩大范围是保守依赖，不能宣称此版所有更新都按 key 精确局部。
- 内部逻辑 ID 不含整仓库 snapshot；不可变版本目录提供隔离。选中记录重建，未改 source-verified owner 的记录保留，旧 read.site_id 通过已有映射更新；越过选中边界、旧/缺/partial 模型或超预算回退完整分析。相同捕获保留证据，发布失败保持旧指针。
- v5 保留原支持范围并增加有限字典结构；数值 key 暂不准入，以免错误拆分 True/1/1.0。动态/条件/循环/逃逸等路径不靠放宽 UNKNOWN 取得性能。普通 v4 调用者从 modeled 字典模块导入函数仍有 mixed 准入回退，文档没有将其称为已完成。
- `Analyzer.explain` 的稳定兄弟遍历排序修复输出顺序，不改变目标、UNKNOWN 或证据内容。根优先、截断标记和直接排列对照保留；没有在测试比较器中删除证据字段。

## 独立验证

命令：`.venv/bin/python -m pytest -q -rs tests review/batch4-incremental/test_dictionary_flow_independent.py review/batch4-incremental/test_dictionary_local_independent.py review/batch4-incremental/test_value_index_independent.py review/batch4-incremental/test_import_receiver_independent.py review/batch4-incremental/test_changed_python_independent.py`。

结果：**599 passed、25 skipped，34.65 秒，退出码 0**。其中仓库测试 570 项；额外 29 项为独立和历史检查。25 跳过为 24 项需要 owned Neo4j 服务、1 项需要可选真实缓存，本轮均未启动。原日志 [dictionary-flow-independent-suite.log](dictionary-flow-independent-suite.log)。开发者 27 项、570 项和本轮结果分别记录，不重复相加。

| 独立检查 | 结果 |
| --- | --- |
| 原跨文件 A/B + 0/20 无关普通文件 | 只解析 A/B；替换/删除、缺失→存在→缺失、失败重试与同捕获 full 的 nodes/edges/sites/import/query 证据逐项一致 |
| 同文件 + 0/20 无关文件 | 只解析 registry 文件，旧版不变；相同捕获不解析 Python |
| 两个字典同 key 与别名 | 容器身份不同；别名不复制容器；读到正确 entry 和 callable |
| 0/20 无关 producer-only 字典 | 仍只解析 A/B；无关语义记录保留；新快照公开和内部语义表均与 full 相同 |
| 真实索引查询 | 每条目标查询 1 次 SQL、返回 1 行；SEARCH value_reads 主键索引，无 SCAN；两条查询 VM 步数 18/15，随无关增长保持不变 |
| 重复全局准备 | 一次 prepare 只读一次 slot-writer-universe 订阅；不在队列循环重复读同一集合 |
| 内部关系页 | 小 limit 显式 has_more；100 上限；节点超限拒绝；没有静默省略并声称完整 |
| 不支持操作 | return/传出字典、update、动态 key、条件写入走 full；完整结果与独立 oracle 一致 |

固定提交实际计数输出另用 `pytest -q -s review/batch4-incremental/test_value_index_independent.py` 导出：2 passed / 0.87 秒，**已经包含在 599 内**。原始 [dictionary-flow-fixed-locality.log](dictionary-flow-fixed-locality.log)。计数只涵盖真实 API 查询，不包含构造器全文件哈希、初始 full 建立、必要旧证据合并与输出序列化；这些可为 O(N)。

## 人工可查看的实际小图

同一固定提交、临时合成源码、离线 lexical 构建、禁止 provider 调用。实际输出 **7 个内部节点、11 条关系，引用 2 个既有函数节点**。声明与导入指向同一个字典，两次赋值都保留，后一次赋值连接本次读取，公开调用目标为 second。

见 [dictionary-flow-example.md](dictionary-flow-example.md) 和原始 [dictionary-flow-example.json](dictionary-flow-example.json)。这是内部 SQLite 中间图，不是 Neo4j 投影或远程 MCP 验收。

## 结论、失败历史与剩余工作

本轮没有发现新的确认阻塞，没有通过修改根测试或忽略语义字段制造通过。开发时一次 before 整数 sentinel 排序 TypeError、一次旧 v4 硬编码断言失败均保留日志并说明；后续目标和独立全量对照通过。原来 A/B 增量失败已在本提交关闭，但不把它扩展成任意 Python 已支持的声明。

剩余：whole-capture 结构准入与 mixed 调用者仍限制真实业务局部更新；复杂函数值传递和动态写入未统一接通；旧 broad watcher 会扩大扇出；内部中间关系尚未投影到 Neo4j/MCP；真实业务规模、整合发布和恢复仍待完整功能验收。当前工作分支保留，整个 Batch 4 不合并。本轮无付费 API、真实业务全图、服务启动或 Drive 操作。
