# Batch 4：代码变化后的增量更新

## 当前状态
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
