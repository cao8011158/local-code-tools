# Batch 4：代码变化后的增量更新

## 当前状态
2026-10-31 当前暂停：类切片独立通过；跨仓库候选发现旧Jedi搜索环境隔离问题及新模块遮蔽失效遗漏，独立定向3 failed/2 passed。候选仅归档patch，未应用远端生产代码；需要用户确认是否限定修复核心解析接入环境。详见阶段43及crossrepo-paused-report.md。
2026-10-31 最新：类与实例方法限定局部更新1ca7ca32cf5e0b816eee95a01956417308f38407已推送；第1/3轮独立审阅545 passed、25 skipped（26.45秒）。构造器字段变化与绑定方法参数变化全字段对照通过；0/20无关类文件时仅解析a/b。Batch4仍待跨仓库及完整功能验收，未合并。以下保留历史状态。
2026-10-31 最新：906dd60e9b17a2607983cd0bcac9f4eda07db288已推送；限定普通函数/直接导入/回调局部更新第1/3轮独立审阅通过，526 passed/25 skipped，另两项独立检查分别通过。实际查询走索引，3→43文件时仅解析a/b，查询4次、相关行3条保持不变。类、多代码仓库等仍全量，实际业务全范围增量未完成，不合并。
2026-10-31 当前开发：限定普通函数/直接导入/回调的Python局部更新已接入公开build，开发验证517 passed/25 skipped。提交前检查发现跨多代更新的分析预算上界丢失，需要限定修正；未提交新实现、未合并，不构成正式审阅通过。
2026-10-30 最新：同Python捕获复用实现9e8dbb34a5f99788351a91b918fd3cc57ff7945a已推送，经本切片第1/3轮独立审阅，511 passed/25 skipped（18.47秒）；独立文档仓库更新不再解析Python。Python源码修改的局部分析尚待接入，Batch4仍未完成、未合并。
2026-10-30 新进展：阶段35完成解析前的严格同Python捕获复用开发，待固定提交后的独立审阅。只覆盖Python仓库捕获完全不变（含独立文档仓库变化）；Python变动后的依赖局部重分析仍未接入，Batch4未完成。
2026-10-30 当前状态：版本引用修复已完成限定独立验证（v5 29/29）；正式构建已保存可反查依赖索引，e1500d2c35a960dd0688871f1ac6daa659f5e886经第二轮独立审阅，508 passed/25 skipped。真正局部解析与完整增量接入尚未完成，未合并。
最新进展：实现提交14d4e7581ffdb7309ba619741ded91fd75bfad9a已推送；已接入有证明的有限查询单元复用、HNSW未变化分区复用与导入依赖索引。完整Python依赖局部分析、图差分与最终验收仍未完成，未合并。
最新进展：未解析导入LOOKUP_IN依赖切片已实现并完成SQLite/Neo4j独立验证，实现提交b345475259b951dbcb18fd3a97982fb1c1a9afb8已推送；完整增量分析仍未实现，未合并。
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

## 阶段7：远端固定提交与独立切片结论
实现提交b345475259b951dbcb18fd3a97982fb1c1a9afb8已推送到feat/incremental-index-updates，远端ref核对一致；18个本地文件逐一匹配远端Git blob SHA，无差异。目标feat/local-code-tools-import未改动。
固定远端实现后的快速回归：479 passed、25 skipped，13.39秒，exit0（lookup-remote-fast.log）。真实Neo4j最终定向1 passed/7.94秒；独立PROFILE两种规模各两条查询通过。查询测试没有调用Embedding API。
结论：用户本轮指定的命名未解析导入及LOOKUP_IN关系切片已实现并通过独立检查。不是整个Batch4验收或正式review，完整batch正式review仍0/3，不合并。剩余必须完成：正向成功导入/重导出等完整依赖捕获、影响闭包与分析复用、图/向量索引差分接线、统一发布与恢复、全量构建差分和规模验收。现有真实图和Drive包未迁移。
本轮未确认生产P0/P1；两处新增Neo4j测试错误和一次跨编辑指纹冲突均保留原日志，修正后通过。没有将开发自测计为独立正式审阅，也没有将完整源码重算包装成增量分析。

## 阶段8：继续Batch4与环境恢复
用户授权“好的 请继续”。远端head6376f87a736abffcef766b02760b0dece5fa3631未变化。恢复固定提交的代码、测试、文档和Batch4记录：复用106个已有匹配文件，下载72个缺失文件并验证Git blob SHA；未恢复不相关历史review文件。
恢复环境检查：478 passed/25 skipped/1 failed（register_mcp测试所需项目.venv链接缺失）；恢复指向已有可用环境的本地链接后该测试通过。未修改注册生产代码。该运行与开发编辑交叠，不作为冻结基线/合并证据。

## 阶段9：HNSW分区复用辅助实现开发完成（未提交）
开发子Agent GPT-6 SOL medium；新增lct/dense_update.py与tests/test_dense_update.py。
按(repository,kind,is_test)定位旧分区；输入向量、节点映射、模型及HNSW设置相同且旧产物校验通过时，复制既有.npy/.json/.usearch，避免重新构建HNSW。变化分区明确重建，不声称逐向量原地增量。旧版本不变，无API调用。
开发自测4项使用真实USearch通过，Ruff通过。覆盖新增/删除/修改、分区序号变化、损坏回退、参数变化以及24个无关分区不被打开。详见dense-development.md/targeted.log。首次交付时公共build尚未接入；另一开发Agent正在集成，尚未独立审阅/推送。

## 阶段10：公共build接线开发完成（未提交）
开发子Agent GPT-6 SOL medium完成：graph-sites.sqlite中索引化query_observations及import_dependencies/targets；storage.build在Python输入/config/program/runtime/pin语义相同才逐查询复用精确捕获定义的Jedi观察，重新生成公开版本证据。源码清单和旧证据在更新入口各做一次完整性检查；不是每次查询读取整份证据。
成功导入、缺失名称及重导出记录了模块依赖，module_import_dependents可按反向索引扩展；并不覆盖回调/隐式效果/Jedi内部全部依赖，不能用于跳过任意Python修改后的分析。Python修改仍明确full fallback。
HNSW helper已接入storage.build，新增复用/重建分区计数。开发全tests：488 passed/25 skipped，14.24秒；Ruff通过。docs提交复用和强制全量对照节点/边/站点一致；Python名称新增/删除/重导出/别名回调保持全量回退与对照一致。生产改动仅开发子Agent实施，主Agent开始独立验证。

## 阶段11：独立反例发现B4-QUERY-001（本step新增P2，未提交）
主Agent公开build检查：文档提交后3个HNSW分区复用/0重建、1次Jedi观察复用、0API请求；损坏旧query证据后回退新推断，两项通过（reuse-independent.log）。
另独立反例失败：捕获源码`selected=external_choice.choose(first,second)`不变，仓库外Python依赖从返回first改为second，再提交文档。新缓存仍给first，而强制全量给second；两者均possible/complete=false，无错误确定性认证，但候选过期。根因：只检查捕获源码与运行时版本，无法证明Jedi未读取外部依赖。属于本轮我方缓存准入错误，不归因Jedi上游。
按当前step P2权限修复：限制为有明确直接词法定义证明的Name查询，在捕获与复用两端检查；外部选择函数/别名/属性/参数等不能复用。每模块预计算绑定证书，禁止每个查询再次扫描模块。保留原失败日志reuse-external-probe-detail.log与独立复现测试，不以删除断言通过。正式完整Batch4审阅仍未开始。

## 阶段12：B4-QUERY-001修复开发完成并冻结（未提交）
开发子Agent GPT-6 SOL medium：每模块只遍历一次AST建立直接词法绑定证书；缓存写入/读取都验证。赋值/外部选择/导入别名/属性/参数/重复绑定等不满足证书，继续新推断。外部依赖选择first->second反例修复，保留原UNKNOWN语义。
进一步接入Python变动时的有限查询单元复用：旧新清单一次计算未改模块集合；仅这些模块中函数局部的嵌套定义直接Name查询可复用。模块全局定义和其他推断在Python变化时仍重新执行。真实jedi.Script.infer调用计数确认changed other.py执行，unchanged local.py符合证书的查询不执行；与强制全量节点/边/站点一致。新增jedi_queries_executed/reused计数，不把总query项数冒充真实推断次数。
开发冻结回归（含主Agent独立探针）：493 passed/25 skipped，16.14秒；Ruff通过。修复了依赖查询文件路径含#的URI处理。尚未提交，待主Agent固定内容验证。
限制不变：这是查询单元级复用，所有LCT resolve/adjudication以及当前公开版本证据仍重建，非完整局部分析；完整Batch4未完成，不合并。

## 阶段13：独立检查与B4-DENSE-002修复（未提交）
冻结代码主Agent复跑：493 passed/25 skipped，16.46秒（reuse-root-frozen.log）。这是前一冻结点，之后新增反例另记，不冒充最终通过。
主Agent新增实际公开prepare_only第二次dense build反例：UnboundLocalError，位置storage.build旧manifest变量仅在普通发布保护分支赋值。属于本step新引入P2，候选未发布，旧current保留。失败日志reuse-prepare-probe.log；稳定编号B4-DENSE-002。
开发子Agent按明确方案修复：复制旧catalog时同时取得old_folder与old_dense_manifest，初始化为None；HNSW helper使用这个成对来源，不依赖入口保护变量。新增prepare_only和on_candidate第二次build测试，前者旧current不变、后者callback获得旧版本后正常发布；均复用全部分区且0API请求。
修复定向含主Agent反例/发布/attach：13 passed，1.49秒，Ruff通过（dense-prior-fix-targeted.log）。再次冻结，待推送后独立回归。两个P2均处于本step自动修复范围，未确认P0/P1。完整Batch4正式review未开始，未合并。

## 阶段14：固定远端实现后的独立验证结论
实现提交14d4e7581ffdb7309ba619741ded91fd75bfad9a，分支feat/incremental-index-updates；27个变更文件Git blob SHA核对一致。最终独立命令：python -m pytest -q tests review/batch4-incremental/test_reuse_independent.py → 496 passed、25 skipped，19.74秒，exit0（reuse-remote-final.log）。本轮未启动真实Neo4j，没有付费API或真实图/向量重建，未改Drive包。
B4-QUERY-001 addressed：外部依赖变化候选first/second反例通过；缓存只接受绑定证书，原UNKNOWN语义保留。
B4-DENSE-002 addressed：prepare_only及on_candidate第二次dense构建通过，旧版本/发布条件按原契约保持。
独立公开build确认3个HNSW分区复用/0重建/0API，禁止Index构造仍成功；损坏旧推断缓存后重新推断，与强制全量对照一致。新增Python变动测试记录真实Jedi.infer：变化文件执行，未变化嵌套函数的合格查询跳过；公开节点、边、站点与强制全量一致。根Agent未改生产代码。
本阶段部分功能检查通过，但不是完整Batch4审阅通过，完整正式review仍0/3。剩余：全量LCT解析/判断还会执行；完整跨文件/回调/隐式影响依赖证书与安全复用未完成；Neo4j差分、完整统一发布恢复、真实规模与备份验收待完成。不合并，不将有限查询缓存冒充完整局部分析。

## 阶段15：现有关系驱动的文件级局部更新对照实验开始
2026-10-30。用户明确要求先验证现有边能否支持局部更新，不预设需要重写解析器。远端基线已核对为7f7780cdb4ab235040e790aee1046c80657623ad，分支feat/incremental-index-updates。
- 实验实现者GPT-6 SOL medium子Agent；主Agent独立核对实验有效性。只新增review/batch4-incremental/local-diff-experiment材料，不改生产流程，不调用付费API、不启动Neo4j、不更新真实图或Drive包。
- 局部路径以旧图端点索引、新增/修改文件的显式导入及新关系扩展文件范围，真实调用现有解析器。全量新版本只作为比较对象，禁止用于决定局部范围。
- 对比节点/关系/候选/UNKNOWN/完整性；记录解析文件、调用位置、Jedi执行次数和全域准备工作。失败保留，不把实验脚本执行成功当作局部更新验证通过。
- 这是方案实验，不是整个Batch4正式审阅；正式审阅仍0/3。此前关于依赖不足的推断以本轮证据修正。

## 阶段16：文件级对照实验开发完成，未提交
开发者GPT-6 SOL medium；基线7f7780cdb4ab235040e790aee1046c80657623ad。仅新增实验脚本/合成结果/说明，生产代码不变。
- 子Agent开发结果：13组中12组局部结果与全量语义结果一致；新建此前不存在的被导入模块1组不一致。该失败保留为方案边界，不修正式解析器。
- 已有目标模块、回调实参改变、返回对象、注册表、继承、重导出及新增导入等样例通过。20/100无关文件对照局部均分析2文件/2次Jedi，全量22/102文件和Jedi查询。
- 准备阶段仍遍历旧节点/边构造实验邻接索引，扫描新路径清单；合并完整输出有线性成本。结果不证明整个更新端到端仅局部工作。
- 实验比较语义字段、候选、UNKNOWN和完整性，未验证跨快照版本身份重绑定、完整证据字节一致性、实际SQLite发布/Neo4j投影。详见local-diff-experiment/REPORT.md。
- 接下来由主Agent独立审阅脚本、复跑并增加不同样例。尚非完整Batch4正式审阅，0/3不变。

## 阶段17：主Agent独立对照与根因验证完成
基线7f7780cdb4ab235040e790aee1046c80657623ad；21生产文件与远端blob逐项一致，未改生产代码。
- 复跑开发实验：13组中12组语义一致，1组新建缺失模块漏更新。
- 独立3组：多跳新增导入一致；共享辅助模块一致但21/21文件全量重算；缺失模块反例复现。
- 独立补充1组：初次旧源码记录导入名称反向索引，新增模块时按名称触发原导入者，2/3文件分析后与全量一致。确认该缺口来自未保存/利用明确import名称，不是该样例要求换解析工具。
- 方案限制：无条件双向闭包过宽；实验准备仍全量读旧节点/边，版本重绑定、完整证据、真实数据库更新未验证。未重跑无关全仓库测试，无付费API/Neo4j/Drive操作。
- 独立检查对象为方案实验，不是完整Batch4实现；正式Batch4审阅0/3，未合并。详见local-diff-experiment/REPORT.md、independent-results.json、supplement-results.json。

## 阶段18：用户授权继续生产接入
用户确认文件级增量方案后授权继续Batch4。基线63a26e5da50b7eca99e03aa377ff6d6a85393119，feat/incremental-index-updates。两个GPT-6 SOL medium开发子Agent分别负责缺失模块请求记录和文件级局部分析接入；不更换Jedi、不引入新细粒度求值引擎。
验收：公开build路径与强制全量对照（含真实Git提交变化），未知标记/目标/版本证据保持；缺失模块新增/删除、回调参数变化、无关扩容；持久索引和必要全域输出成本分开。未授权新增API调用，真实图/Drive包不覆盖。Batch4未完成，正式review0/3。

## 阶段19：缺失模块记录开发完成；用户要求先验证定向传播
开发子AgentGPT-6 SOL medium报告：graph.py和lookup测试已完成，87 passed、2 skipped；仍未提交、未独立验收。新增import_request_module/_import_requests与requester-scoped缺失模块边界，无实际模块则无LOOKUP_IN。详见absent-module-review.md。
用户进一步提出按具体变化与依赖方向传播，避免无条件双向扩展；授权先做第二次实验。文件级生产接入暂停，file_incremental.py仅为未完成草稿，不纳入已完成能力。缺失模块改动也暂不提交，实验必须明确其本地基线差异。
第二实验比较定向传播、原双向闭包、全量语义结果；不得用全量新图决定影响范围。记录全AST上下文准备与实际解析工作，循环收敛、返回值/参数变动和共享辅助模块为重点。继续不调用API、不改真实索引/Drive。

## 阶段20：定向传播实验开发完成，未提交
GPT-6 SOL medium子Agent完成directional-experiment脚本与冻结graph_under_test.py（包含本地缺失模块修复，明确不是远端63a26原图）。实验只修改Graph.build外层调用位置循环的选择，不修改Analyzer内部语义；保持全上下文用于回调推断。
- 开发报告：原8个限定样例与全量语义结果一致；新增3个样例中返回临时变量、关键字回调2个失败，返回字面量驱动分发表样例通过。
- 共享辅助模块20使用者：0/20外层调用点重审，实际Jedi20/40；完整21文件AST与非CALLS关系分析仍保留。不能称全部解析工作已局部化。
- 固定快照和脚本保留失败；没有生产接入、没有付费调用，下一步主Agent独立复跑审阅，正式Batch4review仍0/3。

## 阶段21：定向实验第一版独立复查（需要修改实验）
主Agent复跑：11组开发样例9组一致/2组不一致；3组独立写法变体均不一致，其中关键字参数和返回局部变量与开发反例同类，不计为3种额外独立根因。
明确根因：schedule只比较return表达式AST、只记录位置实参、只访问顶层函数体，分别遗漏返回绑定变化、关键字实参、模块顶层传参。它尚未充分测试用户所指的实际解析结果变化驱动传播。
给开发者精确指令：保留v1；通过真实Analyzer.resolve比较修改函数的新旧返回结果；包括关键字和模块级调用变化；记录额外summary解析成本，禁止借新全量图确定范围。只做有边界的实验修正，不接生产。Batch4整体正式review仍0/3；本实验独立复查第1次。

## 阶段22：定向实验第二版开发完成，未提交
子Agent新增v2.py，保留v1原文件/失败结果。改为真实Analyzer.resolve比较新旧返回结果；调用形状包含关键字和模块级调用；返回传播逐个比较调用者的新旧summary，包含经局部变量转发。
开发者复跑15组均语义一致，覆盖上一版写法缺口及局部变量转发。仍为受限实验：全新旧AST上下文用于summary准备，选择性阶段仍全局非CALLS处理；未作生产接入。开发者承认主Agent额外同类对象字段改变反例失败。
下一步主Agent固定脚本独立复跑并归纳剩余边界，不继续无限扩充实验。

## 阶段23：定向实验第二次独立复核完成，保留边界
固定v2后根Agent复跑：15/15语义匹配；独立新增2组1匹配/1不匹配。三文件经局部变量转发返回值传播正确；返回同类Box但cb字段由first改second仍漏更新。
根因在实验direct_return_values摘要只比较类型/目标等，没有覆盖对象字段，不能据摘要相同认证不受影响。建议未证明等价的对象/容器返回沿消费者保守传播，后续验证；本轮不扩展新引擎。
共享helper实验降低外层调用点和Jedi查询，但旧新summary全AST准备和非CALLS全局处理仍在，不能声称生产级局部更新完成。
实验脚本、冻结graph_under_test及原始v1/v2失败结果独立保存；只推送实验材料及累计报告，不推送未完成的生产接入。没有新API/真实图构建/Drive修改，未合并。整个Batch4未完成。

## 阶段24：返回对象状态传播v3开发完成，未提交
2026-10-30。分支feat/incremental-index-updates，远端基线7398cab6b651f27b21ac2114fd89614d4f066587。GPT-6 SOL medium子Agent实现；只新增v3实验及证据，不改生产代码。
- 根因：相同(kind,target)并不能证明返回对象的字段相同。新增state_may_escape；修改函数或受影响调用者返回未证明完整的值时，沿原有CALLS调用者方向继续传播；可证明的简单常量保持停止。
- 定向命令：PYTHONPATH=. /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch4-incremental/directional-experiment/v3.py，退出0；20/20组与全量语义对照一致，日志v3-run.log。包含15组旧样例、两组旧独立样例及3组新样例，有重复根因，不称20种独立机制。
- 修改只涉及v3.py、v3-results.json、v3-run.log、v3-development.md四个新增实验文件。v1/v2失败记录保留。共享helper仍0/20外层调用点、20/40选择性阶段Jedi；新旧21+21 AST准备和全局非CALLS成本仍在。
- 未验证构造函数/方法单独改变、正式版本重绑定、真实数据与数据库发布；未调用付费API、未更新真实图或Drive。接下来第三次独立实验审阅；整个Batch4未完成。

## 阶段25：固定提交后的第三次独立实验审阅，暂停自动修复
检查4560aee34db12ad01192bdeb0986d414c37ba846，v3.py与远端Git blob逐字节一致。根Agent复跑20/20开发样例匹配；独立3组2匹配/1失败。字段提取再转交正确；丢弃对象返回常量会在中间函数停止；仅修改Box.__init__字段而factory原文不变时仍漏选b.py。
- B4-DIR-STATE已关闭；B4-DIR-SEED为P2实验覆盖遗漏，非发布图退化。根因在direct_functions只找顶层函数，方法变动未加入传播起点。旧图已有CONTAINS Box→__init__、CALLS factory→Box及run→factory，可据此扩展，不要求换解析工具。
- 已明确尚未执行的修复：完整qualname对齐包括方法；构造器字段变化映射到所属类，反向找构造调用者，再使用已修复的对象状态传播。详细证据和限制见directional-experiment/v3-independent-review.md。
- 本实验承接阶段21/23共3次独立审阅，停止第四轮自动修复；不以Batch4最终审阅尚未开始重置该循环。请求人工批准后才能继续。
- 只跑定向实验，不跑无关全仓库测试；未修改生产解析流程、未调用Voyage、未重建真实图或Drive包，未合并。

## 阶段26：用户批准三轮后的限定构造器修复
用户回复“好的 请继续”，授权处理B4-DIR-SEED，承接此前3次实验审阅，不重置轮次。基线8313de4636fade59dd199a11214e75900381e84f，分支feat/incremental-index-updates。
开发者继续使用GPT-6 SOL medium。限定实验v4：完整qualname对齐方法；变化构造器映射到所属类并反向查找创建者，沿v3规则继续。保留v1-v3、生产接入暂停，不新增付费请求、不更新真实图。定向覆盖原20组、上一轮3独立反例、构造器及同名方法隔离。主Agent另检查经方法返回转交和30个无关文件对照。完成后进行用户授权的追加独立复核，不自动开启无限修复循环。

## 阶段27：用户批准的v4构造器修复开发完成，未提交
开发者GPT-6 SOL medium，基线8313de4636fade59dd199a11214e75900381e84f。仅新增v4.py和结果/日志/开发报告四文件，生产代码未改。
- definition_index用(path,完整qualname,kind)匹配定义；__init__变化沿CONTAINS找到所属类，再沿已有CALLS反向找到构造者；新增构造器映射到旧类；调用者返回摘要不再截断qualname。
- 定向命令PYTHONPATH=. <venv>/bin/python review/batch4-incremental/directional-experiment/v4.py，exit0；严格对照26/27匹配。旧20组及上一轮3组独立反例均匹配；新增构造器、跨文件同名方法和常量返回对照匹配。
- 同一文件两个类的隔离样例仍strict equal=false：仅12处嵌套version_id不同，调用目标、UNKNOWN、complete及其他字段一致。保留原失败，不删字段或重算无关调用者掩盖。正式版本重绑定未完成，不称27/27全通过。
- 下一步推送限定实验后独立复核；此为用户批准的三轮之后追加验证，不重置历史。无API、真实图或Drive操作。

## 阶段28：用户批准后的追加独立复核完成
检查dc8fa9b35bd3b398a7071ac676abf132a1f94d06，v4.py远端blob与本地一致；22个相关文件核对一致或仅换行差异。前三轮记录不变，本次是人工批准后的追加复核。
- B4-DIR-SEED限定构造器修复已通过；旧对象状态反例保持通过。独立复跑27组严格26/27一致；新增方法转交及30无关文件两组均通过，断言exit0。
- 30无关文件下只重审a/b共3个外层调用点、4次选择性Jedi；仍有32+32全AST准备和候选全局非CALLS分析，不能称端到端局部化。
- B4-DIR-PROVENANCE明确保留：同文件另一类消费者目标和所有非版本字段相同，但12处嵌套version_id仍旧；逐路径证据已保存，不删除比较、不把结果记成27/27。版本重绑定未实现。
- 详见directional-experiment/v4-independent-review.md、v4-proof-version-differences.json和原始日志。此次限定修复结束，未继续扩大到正式版本/发布实现；未合并、未调用付费API或改真实索引。

## 阶段29：用户授权版本引用修复与后续正式接入；开发完成
基线6f153214c253b6106b43202aff04d70ab7474723，feat/incremental-index-updates。GPT-6 SOL medium开发子Agent完成lct/evidence_reuse.py、定向测试及v5实验；正式storage/graph入口尚未接线。
- RebindContext每对捕获准备一次身份索引，按(repository,path,完整qualname,kind)定位；定义检查按ID记忆，避免每条记录重复扫全表。核对旧版本、AST/指纹/位置，限已知引用格式；失败则重分析所属文件，旧记录不变。
- 开发定向8 passed；v5严格限定语义比较29/29一致（保留v4原失败）。同文件未受影响的另一类调用者可以复用，旧12处版本引用已更新。
- 开发tests/回归502 passed/25 skipped；这是含既有未提交graph修复的开发副本，主Agent将另准备固定远端源码副本复核。无路径限定pytest因实验目录缺psutil/冻结脚本相对导入在收集阶段失败，日志保留，不称全仓库通过。
- 明确成本退化：变化helper的旧证据引用了变化定义，保守拒绝全部20消费者，21/21文件、20/20外层调用点、40/40 Jedi；不继续沿用v4节省数字。全AST准备仍在；外层site/edge身份未在实验中全面重绑定，不能称生产完成。
- 并行只读接入检查已完成，报告integration-plan.md。正式入口仍全量extract+Graph.build，草稿期待的file_adjacency/import_requests表未持久化，不直接启用。需顺序补齐依赖索引、解析前分流、有效性证书及版本发布；没有确认外部核心依赖故障。
- 接下来固定远端后独立验证。未调用付费API或改真实图/Drive。

## 阶段30：版本引用修复固定提交后独立复核通过限定范围
检查ac8bfd31f0d007d5cb17a9c508e90c5e21199644。独立副本恢复远端graph.py和lookup测试，排除原副本两份未提交文件；75个lct/tests文件按Git blob核对。
- 独立运行v5：29/29限定语义比较一致。新增3项独立测试通过：篡改旧版本证据后所属c.py真正重新分析并与fresh结果一致、旧对象不变；跨仓库同路径同名定义不混淆；0/1000无关节点增长下连续10次复用均只做1次相关定义匹配。
- 固定远端tests/加独立测试首次因未复制experiment truth样例收集失败，补齐17个远端样例文件后运行502 passed/25 skipped/1 failed，18.18秒；唯一失败是隔离副本缺少.venv链接导致MCP注册脚本拒绝启动。补齐现有环境链接后仅复跑此项1 passed（日志v5-root-registration-retry.log）。未修改实现来消除环境失败；不将多次结果伪装为单次完整通过。
- B4-DIR-PROVENANCE的12处嵌套定义引用问题，在已验证可复用的限定场景已解决。helper索引一次准备，多条记录复用；未知格式、错误旧版本、定义变动/移位均拒绝。
- 尚未接入storage的实际增量路径，外层site_id/edge_id以及完整跨快照身份仍属后续正式接线工作。调度器影响范围仍为实验限定假设；全AST准备、全局非CALLS工作未消除，共享helper变化的保守重审成本已如实报告。
- 第二步已开始：开发持久化import_requests/file_adjacency和索引查询，未启用file_incremental草稿。未付费、未改真实图/Drive、未合并；历史审阅与用户授权保留。

## 阶段31：正式接入前的持久依赖索引开发完成，未提交
GPT-6 SOL medium开发子Agent修改storage.split_graph/build并新增FileDependencies，图解析采用此前保留的缺失模块请求修复；尚未启用file_incremental。
- graph-sites.sqlite保存import_requests和实际跨文件file_adjacency，正反方向索引；显式请求清单和nodes均提供才标记indexed-v1。旧版本/未提供清单的默认split_graph不冒充完整索引。
- build消费并移除私有_import_requests；源模块归属校验、摘要和sidecar校验和沿用现有候选发布流程。两个文件共同导入外部json不虚构文件关联；只有LOOKUP_IN边界源通过IMPORTS归属映射到已捕获目标。
- 开发较早全tests/504 passed/25 skipped，最终标记边界补充后定向11 passed，Ruff通过；最终固定源码仍待主Agent独立回归。详见depstore-development.md及depstore日志。
- public build合成验证缺失模块请求持久化、目标新增后关系、旧版本可读、双向查询、35个无关文件及SQLite索引计划；未测完整增量调度、真实Neo4j/规模/发布统一增量。
- 本批接入只建立正式流程可消费的数据，不宣称停止全量解析。未付费、未更新真实图/Drive，下一步独立审阅。

## 阶段32：持久依赖索引第一轮独立审阅，需要修复迁移兼容
检查d293038208f4c2c19a78f603772950a564c5a31f。独立回归出现两个可确认P2迁移/恢复失败：dependency_store可用性标记加入graph，迁移重建sidecar时删除，违反原graph完全保留契约，恢复也拒绝。B4-DEPSTORE-MIGRATION为本step新引入，候选未合并，已给开发者明确修法：标记移到顶层快照元数据，保留graph原内容和旧断言。
原回归另有进程中断后program_hash不匹配；检查发现独立副本graph.py/lookup测试意外回到旧基线，不符合固定提交，故整次运行不作为最终固定提交通过证据。已重新恢复并核对新blob，单独复查中断测试；不把这一项直接归因为生产缺陷。原日志depstore-root-tests.log保留。
依赖索引本身的已知ID查询、缺失导入及常见边界定向通过，但最终证据待固定修复后重跑。三轮上限适用于本持久化切片整改链（当前1轮），历史定向实验轮次及人工批准保持，不重置旧问题。

## 阶段33：迁移标记整改开发完成
开发者将dependency_store改为顶层快照元数据，FileDependencies跟随读取，graph保持原样；没有修改management或放宽graph相等断言。定向迁移/依赖索引/查询复用13 passed、2.86秒，Ruff通过。接下来固定修复提交后第二轮独立审阅。

## 阶段34：持久依赖索引第二轮独立审阅通过限定范围
检查修复提交e1500d2c35a960dd0688871f1ac6daa659f5e886。独立副本用正确候选文件固定后运行tests/及4项主Agent独立检查：508 passed、25 skipped，18.21秒，exit0；复核76个lct/tests文件与远端Git blob。先前两次因审阅副本旧文件覆盖产生的指纹失败不计作实现缺陷或通过证据，原日志保留。最终日志depstore-root-fixed-tests.log。
- B4-DEPSTORE-MIGRATION已关闭：标记位于快照顶层，graph内容保留；迁移和备份恢复原严格测试通过。
- 真实public build保存缺失模块请求及实际跨文件关系；旧版本不变，未捕获目标不伪造边；已存在目标但名称缺失时，IMPORTS+LOOKUP_IN仍能反向定位请求者。
- 实际FileDependencies.adjacent/importers执行语句经trace提取，EXPLAIN QUERY PLAN显示源/目标及请求名称索引SEARCH；SQLite进度处理器实测VM指令。0→100无关文件（均带额外无关导入/调用关系）下，adjacent冷/热53/39步，importers冷/热20/17步，两组完全相同，每次只返回1条。独立定向1 passed、0.90秒，日志depstore-root-fixed-plans.log。
- 上述计数不包含打开快照时的一次完整sidecar哈希校验；该校验用于构建/更新准入，连接复用后查询不重做。不把查询局部性推广为整个build局部。完整输出、inventory、AST准备、Graph分析目前仍全量。
- 本切片通过，但Batch4未完成、不合并。版本引用helper只在实验接入；下一具体工作是在extract之前接入受影响范围选择，并实际复用未受影响分析/身份，完整统一发布和真实验收仍待完成。此轮未开启付费API、Neo4j服务或真实图/Drive更新。

## 阶段35：解析前同Python捕获复用开发完成，未提交
开发子Agent GPT-6 SOL medium；基线71da2eea831f6358287bc931e757851187ef8525，分支feat/incremental-index-updates，合并目标仍为feat/local-code-tools-import（fc857f395a381e5dfec9941d60ca685bcbe0b3fd）。
- storage.build在extract之前调用_reuse_python_graph：Python源文件及所属仓库整个捕获身份相同，程序/配置/运行时和依赖绑定匹配、旧产物校验通过，才复用Python节点、关系和证据。独立文档仓库重新提取文档并重建所属关系；代码仓库本身的文档改变仍回退全量。
- 保留Python-only仓库节点；graph-sites新增node_order，保存原提取顺序，防止SQLite行顺序改变模块成员摘要和向量输入。源码文本摘要按文件准备一次，不逐定义重复哈希。旧格式缺少顺序表则回退。
- 开发定向18 passed（4.42秒）；迁移/恢复相关12 passed；最终tests/507 passed、25 skipped（16.20秒）；Ruff通过。原始日志及source-prepare-development.md保留。生产修改限storage.py；新测试test_source_prepare.py；没有启用旧file_incremental草稿。
- 主Agent开发期间额外4项独立样例通过（1.99秒），尚不作为固定SHA正式审阅：0/20无关Python文件下文档变动均零Python解析；发布前失败保留旧版本；同代码仓库文档修改回退；先插入函数后复用仍保持完整构建的向量输入。
- 本路径仍做必要全量inventory、旧产物校验、节点/边装配及输出；不是Python文件发生变化后的局部调度。没有Python的纯文档项目仍走原路径。无API、真实图、Neo4j或Drive操作；下一步推送并独立审阅，本切片不等于Batch4完成。

## 阶段36：解析前同Python捕获复用，固定提交第1/3轮审阅通过限定范围
检查9e8dbb34a5f99788351a91b918fd3cc57ff7945a；远端分支已核对，164个实际测试依赖文件按Git blob核对一致。独立完整命令tests/及test_source_prepare_independent.py：511 passed、25 skipped，18.47秒，exit0。没有把开发自测或此前环境失败混入通过数。
- 独立0/20无关文件对照：代码库分别1/21个Python文件，独立文档变动均零Python解析；强制完整对照分别解析1/21个。节点、边和sites全字段一致。
- 发布前失败保持旧指针和旧图；同代码仓库文档变化按版本规则回退；Python-only仓库保留仓库节点；先在文件前插入函数后再复用，完整向量输入顺序和内容仍与全量相同。
- 第一次隔离回归缺tools和历史实验支持，第二次仍缺v5.py；补齐远端文件后最终完整回归通过。三次原始日志保留，不把环境缺项归因为代码缺陷。冻结实验文件从远端blob恢复，最后全文件校验一致。
- 本切片没有确认阻塞缺陷；不合并。已有版本引用/依赖索引的历史轮次保留，本次是新接入切片第1轮，不重置历史失败链。详细报告source-prepare-independent-review.md。
- 下一工作仍是Python真正变化时，沿依赖定位受影响范围并实际重分析/复用；全量图输出和统一发布验收另行完成。真实图、Drive、付费接口均未操作。

## 阶段37：限定Python变化后的局部更新开发完成，提交前发现预算记录缺口
2026-10-31。上一轮证据提交c4c22ec6d617395321fe2641da90e4d7a1e96de4已成功挂到分支，作为本轮基线。开发者GPT-6 SOL medium，未提交新实现。
- 新simple_python认证只接受单代码仓库、普通函数、明确的已捕获导入及有限参数回调；类、装饰器、未解析/外部导入、多代码仓库等完整分析。全量构建保存认证，更新时不重新解析未变化文件进行认证。
- python_incremental.prepare在extract前沿FileDependencies索引及新导入找关联文件，每个选中文件只解析一次；复用其余文件节点及证据，通过共享definition_version更新身份和经过源码摘要验证的RebindContext重绑定证明、site/edge身份。包含旧产物校验、候选失败旧版可读、真实执行计数和完整输出计数。
- 开发最终tests/加主Agent新增独立样例517 passed/25 skipped，18.43秒；Ruff通过。0/20无关文件两组只解析a/b；新导入使范围增至a/b/u。节点、边、sites和私有观察/导入记录与全量构建全字段一致，第二代更新及失败重试通过。不是固定SHA正式审阅。
- tests/test_source_prepare.py一处旧全量路径预期调整：新增符合认证的简单模块现在可以局部分析；原有结果正确性断言保留。先前两次Ruff/开发过渡失败日志保留。主Agent在固定旧提交运行新增3项检查，均因全量解析无关文件失败，基线日志已保存。
- 提交前主Agent发现B4-LOCAL-BUDGET（P2，本step新实现）：局部构建把association_evaluations记为本轮执行量，但下一代把它当作整个图的预算上界，丢失前代保留部分的成本。开发者确认。需另存并传播保守上界，不修改实际执行计数；超界回退完整分析，补近上限和连续更新定向测试。
- 本轮尚无固定提交正式review，未重置此前实验/切片轮次。不更新真实图/向量/Drive、不调用付费接口。开发报告changed-python-development.md；先修预算记录，再推送审阅。

## 阶段38：B4-LOCAL-BUDGET限定整改开发完成，待固定提交审阅
2026-10-31。新增graph.association_bound记录保守累计上界：完整分析初始化，局部更新累加本轮实际量，同捕获复用保留上界；association_evaluations仍是当轮真实执行量。缺失上界或累计超过20000回退完整分析。该预算防护不单独证明任意Python的依赖隔离，严格语法范围限制仍保留。
- 定向6 passed、1.94秒：完整→局部→同捕获复用→再次局部，上界不丢失；近上限拒绝局部候选。
- 最终tests/加独立改动样例518 passed、25 skipped，18.53秒；Ruff通过。日志changed-python-budget-targeted/fast/ruff.log，说明changed-python-budget-fix.md。
- 开发冻结；主Agent下一步推送并按固定SHA独立审阅。本次为正式审阅前整改，未重置其他整改链或宣称Batch4最终通过。无真实数据/服务/付费操作。

## 阶段39：限定Python局部更新固定提交第1/3轮独立审阅通过
2026-10-31，检查906dd60e9b17a2607983cd0bcac9f4eda07db288。开始时172个实际支持文件按远端blob核对；独立回归526 passed、25 skipped，24.16秒。新增返回函数经关键字回调传递反例1 passed、0.65秒；实际public build索引查询扩容1 passed、1.02秒。三次运行分别记录，不合并伪装一次总通过。
- B4-LOCAL-BUDGET关闭：当前执行量与跨代上界分开，局部/同捕获/再次局部保持上界，超界回退。
- 0/20无关文件下回调变更只解析a/b；新导入扩展a/b/u；返回函数跨三个文件传递时解析a/b/c。节点、边、sites、私有观察及导入依赖/请求全字段等于完整构建，包含版本、UNKNOWN和完整性字段。
- public build中trace实际SQL，再EXPLAIN并记录VM指令：3→43个Python文件（增加20对真实无关导入关系），依赖查询仍4次、返回仍3行，解析仍2文件；VM总计138→141。使用源主键、目标索引与请求索引SEARCH。完整产物读取/哈希/装配成本仍全量，未掩盖。
- 本切片限定通过，不等于实际项目全面增量。整个捕获必须满足单代码仓库严格语法认证；类/装饰器/注解、未解析或外部导入、多代码仓库等仍完整分析。后续需要覆盖实际业务用法，完成真实统一发布/恢复/规模验收，Batch4才可合并。
- 详细changed-python-independent-review.md及三份root日志已保存。固定生产代码未改；独立测试追加返回函数反例和访问计数文件属于审阅证据。未调用API、未改真实图/Drive，未合并。

## 阶段40：跨仓库后续接入点只读诊断完成；类支持开发进行中
2026-10-31，基线a052f88d25646ee515523053898fe77463dbc526。GPT-6 SOL medium只读子Agent完成具体接点分析，无实现改动/真实数据/API操作，详见crossrepo-next-plan.md。
- 后续复用Graph.imported既有本库优先和精确pin规则；闭包使用(repository,path)和现有跨库索引。RebindContext路径字符串需要改为带仓库身份。绑定状态变化继续完整回退，不能只删除单仓库限制。
- source_snapshot非Git目录不能自动通过现有工作区干净性检查；不得直接拿head字段替代证明。后续需要明确处理这一契约边界。
- 当前类支持开发对照已定位B4-CLASS-MARKER（P2，既有我方解析组件）：共享AST Load/Store标记被按scope所有权过滤并参与clock，导致无关文件改变真实事件的证据编号。调用目标未见差异，完整JSON比较正确阻止误报通过。主Agent核对EffectCatalog.visit后批准仅跳过无执行意义的上下文/运算符标记，保留实际事件顺序与UNKNOWN。
- 类支持新增3项固定旧提交基线均因仍全量解析失败（1.34秒），日志class-component-root-baseline.log。正式类切片审阅尚未开始，旧审阅轮次不变。

## 阶段41：类与实例方法局部更新开发完成，未推送
2026-10-31。开发者GPT-6 SOL medium；基线a052f88d25646ee515523053898fe77463dbc526，分支feat/incremental-index-updates。
- simple-python-v2支持普通类、构造器self字段、明确工厂返回对象及保存的绑定方法；未知参数属性、继承/装饰器/反射等仍完整回退。
- B4-CLASS-MARKER仅跳过无执行意义的AST标记；主Agent固定旧实现独立复现1 failed、1 passed（0.30秒），完整日志保留。
- 开发快速回归543 passed、25 skipped，21.50秒；Ruff通过。独立样例0/20无关类文件下均只解析a/b且完整记录等于全量构建；此处为开发者复跑，尚非固定SHA独立review。
- 生产改动仅simple_python.py和python_effects.py，测试调整类的正向/继承回退边界并增加标记、实例返回和错误接收者反例。详细class-component-development.md。
- 下一步推送固定代码并独立审阅；没有生成真实图、调用API或操作Drive。整个Batch4尚未完成。

## 阶段42：类与方法切片固定提交第1/3轮审阅通过
2026-10-31，1ca7ca32cf5e0b816eee95a01956417308f38407，远端核对一致。独立固定目录回归545 passed、25 skipped，26.45秒，exit 0。
- B4-CLASS-MARKER关闭；真实操作和before顺序保留，旧反例修复，不以删除证据字段取得通过。
- 构造器字段first→second、保存绑定方法后的回调变更、factory().cb结果和完整分析全字段一致。0/20无关同名类文件不扩大a/b解析范围。旧版本保持原样。
- 生产实现、完整闭包调用链和准入边界已审阅；未知动态语法仍完整回退。此结论不覆盖多Python仓库，不证明全量产物装配变为常数成本。
- 详见class-component-independent-review.md与class-component-root-fixed.log。下一步接入已有跨仓库绑定规则；不合并整个Batch4，无真实数据/API/Drive操作。

## 阶段43：跨仓库开发暂停，未开始正式review
2026-10-31，开发者GPT-6 SOL medium。限定候选未通过，生产远端仍保留已通过类切片；本地改动归档为patch，不直接推送生产路径。
- 固定旧版扩容基线3 failed/1 passed（1.43秒）；冻结候选主Agent独立3 failed/2 passed（2.11秒）。精确绑定回调和dirty回退通过；同名跨库局部性、新增本库遮蔽失败。
- B4-CROSSREPO-PROJECT：Analyzer.__init__合并所有仓库根到同一个Jedi Project，导致候选错库，后置校验保留UNKNOWN；没有错误确定目标证据，P1怀疑已撤回，确认P2精度/局部性问题。旧证据重绑定正确拒绝并完整回退。建议请求仓库独立Project、复用既有精确依赖授权根；涉及旧核心解析语义，按skill请求人工确认。
- B4-CROSSREPO-SHADOW：旧导入请求只按provider查找，新增本库同名模块找不到consumer。需补请求方+模块名反查索引并扩展闭包，或明确保守回退；当前step内P2，不允许忽略错误结果。
- 具体复现、修复位置、验证方案和归档见crossrepo-paused-report.md；原始root日志及诊断JSON已保留。未运行真实服务/付费/Drive。历史review轮次保留，无正式跨库review完成、无合并。
