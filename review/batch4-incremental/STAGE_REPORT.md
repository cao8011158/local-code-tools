# Batch 4：代码变化后的增量更新

## 当前状态
最新进展：未解析导入LOOKUP_IN依赖切片已实现并完成SQLite/Neo4j独立验证，待本次推送；完整增量分析仍未实现，未合并。
2026-10-30（北京时间）：已开始；新分支feat/incremental-index-updates，基线/目标feat/local-code-tools-import为fc857f395a381e5dfec9941d60ca685bcbe0b3fd。未合并；正式审阅0/3。用户授权：好 那开始batch 4；通过review自动merge授权延续。Batch3旧问题历史不重置。

## 验收范围
识别新增/修改/删除与版本/依赖变化；安全重算实际依赖闭包并保留UNKNOWN；向量输入未变不请求API，BM25/HNSW一致更新；SQLite/Neo4j统一版本发布，失败旧版可用；终端管理写入，官方MCP保持只读；全量构建差分、故障恢复和备份恢复。现有真实图/包不覆盖，开发先合成样例，不新增付费请求。

## 阶段1：只读架构诊断
开发子Agent GPT-6 SOL medium；主Agent核对实际源码。
- storage.build()每次extract(files)、Graph.build()全量分析；后续SQLite写入差分/向量缓存不等于分析增量。
- extract.extract()把整个仓库的文件摘要写进所有Python snapshot_id/version_id；Analyzer.site()也绑定整仓库snapshot_id。甚至同仓库Markdown变化也会改变Python证据身份。
- Analyzer.dependencies仅为本轮AST id递归，未覆盖跨构建负查找、未知调用候选、Jedi依赖或完整反向失效。parameter()/registry_arguments()涉及跨站点调用；不能只解析改文件或仅追已有CALLS。
- storage.activate仅发布本地current；Neo4j是显式namespace/version独立投影。需要候选准备与发布分离，绑定图指纹，旧图保持可读。
- 官方MCP显式参数不会自动跟随current；一次操作必须固定发布描述，并让首次向量/BM25搜索也接受相同version。

## 阶段2：变更规划器本地开发完成
新增lct/incremental.py、tests/test_incremental_plan.py、docs/INCREMENTAL_UPDATE.md。子Agent自测6 passed，Ruff通过（待保存原日志和主Agent复核）。不读取目录/运行解析/API；对任意改变明确full-capture，尚未接入build、不是完整增量实现。需要后续依赖追踪与版本身份设计，不能据此宣称Batch4完成。

## 正在开发
候选发布/操作级固定版本协调层；真实增量分析、HNSW差分与Neo4j增量尚未完成。原地投影迁移不用于新源码版本更新，避免更新失败使旧版不可读。

## 阶段3：发布协调层本地开发与冻结后快速回归
2026-10-30。开发子Agent GPT-6 SOL medium，尚未正式独立审阅、未合并。
- 新publication.py准备隔离图版本、校验marker后绑定manifest/summary再切current；图/指针提交确认丢失会重读确认。首次search_code/search_docs支持固定version，cursor冲突拒绝。
- 对已绑定版本，普通build/attach_dense/recover拒绝绕过协调。build拒绝前不再扫描解析；加入forbidden路径测试。
- 规划器修正同SHA的is_test变化与必要元信息缺失：11 passed in0.09s。
- 发布层开发定向：24 passed、8 skipped in4.30s；包含模拟图故障和离线真实SQLite/向量样例，不冒充真实Neo4j验证。
- 文件固定后的tests/快速回归：472 passed、24 skipped in13.53s，exit0；此前fast-preflight跨编辑运行，单独保留不作为最终证据。
- 仍缺真正增量分析、Neo4j差分、HNSW局部维护、真实服务与全量对照/恢复验收。新管理命令仍调用完整分析和新scope全导入，不能称增量完成。

## 核心设计决策
推荐方案A：保留现有公开仓库快照/version/site身份，新增私有文件语义键与跨快照依赖证明，发布时重绑定证据。方案B：公开version/site改文件级身份，降低无关身份变化，但需新schema及旧数据迁移；仍需完整依赖证明。具体字段、负查找和Jedi缓存限制见ANALYZER_DESIGN.md。两方案都不能直接复用当前resolve缓存或只沿现有CALLS判断影响范围。

## 阶段4：用户确认未解析导入的目标模块关系（2026-10-30）
用户批准原文：“好的 就这么设计 请继续”。保留统一整图版本，不修改公开节点版本规则；内部复用依据仍需补齐。
本轮实现切片：若能唯一确定被导入模块A，`from a import new_handler` 未解析时保留命名LCTBoundary，B通过IMPORTS指向它，占位节点通过LOOKUP_IN指向A；名称不单独充当唯一ID。未知/歧义模块及未匹配依赖pin不强行连到捕获模块。SQLite持久保存同一逻辑关系，Neo4j作为投影，非两套独立维护的事实。
工作分支feat/incremental-index-updates；远端核对检查点74f182b6dc58cf5c9848667f6cea19f482c316ba。开发子Agent GPT-6 SOL medium；正式review仍0/3。当前是依赖基础结构阶段，不宣称整个增量闭包、部分解析、HNSW和图差分完成。未授权新增付费调用；本轮不使用API、不覆盖真实索引或Drive包。

## 阶段5：未解析导入关联开发完成，尚未提交
实现者：GPT-6 SOL medium 子Agent。基于74f182b6dc58cf5c9848667f6cea19f482c316ba。
- Graph.import_lookup()/build()增加命名占位端点与LOOKUP_IN；相对导入、别名、仓库与pin边界明确，无法唯一定位模块时不强行连接。原Jedi解析结果及UNKNOWN原因保留。
- Query.get_relations()允许新关系并穿过这种占位端点；SQLite使用已有端点索引。Neo4j投影和官方只读查询模板提供name/module/repository/status/reason；精确每处原因保留在关系记录。
- 子Agent定向及受影响回归：36 passed、12 skipped，1.00秒（真实Neo4j未启动部分跳过）。Ruff graph/query/新增测试通过；其他两个文件有已存在导入顺序告警，未夹带修改。
- 主要修改6个文件及2份开发日志；没有付费API/真实业务图重建/Drive改动。原有成功导入依赖、重导出、回调与完整增量闭包尚未实现，不声称Batch4完成。
- 根Agent独立公开SQLite构建与查询检查通过：共享占位节点、旧版保留、成功解析转变；无关关系扩大10000条仍仅读取3条，实际计划命中edge_target。后续补真实Neo4j及固定提交验证。

## 阶段6：依赖切片独立验证（不是整个Batch4的正式审阅）
主Agent未修改生产实现，使用真实公开build/Query.get_relations与独立合成源仓库检查。
- SQLite实际计划：SEARCH edges USING INDEX edge_target (target=? AND kind=?)，仅相关结果排序；两跳返回3条。冷247 VM steps、热123；增加10000条无关关系仍123 VM steps/3条。旧版本关系不随新定义出现而改变。详见lookup-independent.py/log。
- Neo4j5.26真实PROFILE：LOOKUP_IN查询29 DB hits/1条；IMPORTS查询22 DB hits/1条。增加2000条无关关系后均相同，使用IndexSeek，无AllNodesScan/NodeByLabelScan。详见test_lookup_neo4j_independent.py和lookup-neo4j-fixed.log。
- 初次快速回归1 failed/478 passed/25 skipped：开发者最后编辑使构建与查询之间program_hash变化。冻结后479 passed/25 skipped，17.78秒。两份日志保留。
- 初次真实Neo4j1 failed/12 passed：新增测试混用逻辑endpoint与物理boundary_id；改测试，接口不变。第二次1 failed/8 passed：新EXPLAIN断言误按对象读取dict；实际投影、关系、元信息及主AgentPROFILE已通过，仅修测试访问方式。失败日志保留，待最终定向复跑。
- 未复用旧真实图数据，未调用Voyage，测试服务限1GiB heap，由launcher自动关闭。仅证明当前依赖切片，完整batch仍0/3正式review，不因本阶段通过宣称增量分析或合并就绪。

最终真实Neo4j定向复跑：1 passed in7.94s，exit0（lookup-neo4j-final.log）；限额服务已退出。
