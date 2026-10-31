# Batch 4：代码变化后的增量更新

## 当前状态
2026-10-31：阶段89，B4-REL-01相对导入接线开发完成，未提交；生产2文件+26/-10，定向12 passed、相关69 passed，快速615 passed/27 skipped/34.43秒。主Agent基线5 failed/6 passed，待固定提交独立审阅0/3。真实九文件仍受其他独立规则限制，不合并。[开发报告](relative-import-development.md)。

2026-10-31：阶段88，真实关联九文件AST审计完成；新增6文件全部还有独立语法/依赖阻挡，不能把原3文件通过当全库通过。现有Graph可正确定位相对导入，但认证与新增依赖选择未复用其结果，下一步限定补齐该接线，仍不放宽复杂语法。正式新切片review0/3，未合并。[诊断](actual-related-admission-audit.md)。

2026-10-31：阶段87，常见Python v6规则及认证组件候选索引07b6b6c48d7921f2802c00ef62192e849e2371eb经独立第1/3轮通过：665 passed、32 skipped/46.06秒。固定真实三个文件改availability只解析1个、复用2个；增加20无关文件仍只解析1个，全部语义表与full一致。真正相关调用者仍重算，危险写法保留回退，0/200调用位置证明索引读取。整个业务库及Batch4端到端尚未验收，不合并。[本轮审阅](common-certificate-independent-review.md)。

2026-10-31：阶段83，实际跨模块读取记录ea0d0563d19d50d1ee08efd889e583a614f072c1独立第1/3轮通过；633 passed/32 skipped，独立6 passed。返回体/已知成员/匹配传参/精确Jedi目标已记录并接入索引消费者；schema2仍partial，真实业务3文件仍full，Batch4未完成、不合并。[本轮审阅](observed-semantic-reads-independent-review.md)。

2026-10-31：阶段80，Neo4j字典值流投影4a2bcf827e33eb393de5b288260ee63321734dd9独立第1/3轮通过；快速619 passed/31 skipped，真实服务集合13 passed，另发布/反向分页与大记录分片各1 passed。基于已认证SQLite接入新图/官方只读MCP，未扩展解析语法，未更新业务图/Drive，Batch4未完成、不合并。[本轮审阅](value-projection-independent-review.md)。

2026-10-31（北京时间）：阶段77，字典模块与普通调用者混合准入fc12a03044ce8c4288d22d55a830a50ab3426a7a独立第1/3轮通过，613 passed、25 skipped/35.66秒。A->B->C/D已能局部重算，0/20无关文件与producer-only字典保留，公开和中间图表与full一致。仅simple_python.py上下文修复，未改模型/数据库/解析器。Batch4未完成、不合并。[本轮审阅](mixed-dictionary-independent-review.md)。

2026-10-31（北京时间）：阶段74，跨文件固定字符串key字典函数值切片cf4b0fbac0e11f18d53f7dbff1be8b1e40cd6505经第1/3轮独立审阅通过：599 passed、25 skipped/34.65秒。原A/B跨文件更新及删除/新增/失败恢复与full一致；0/20无关producer-only文件仍只解析A/B，实际反查SQL每项1行、18/15 VM步保持。新增关系已在内部SQLite图接入实际增量选择，尚未投影Neo4j/MCP，复杂语法仍有限定回退，Batch4未完成、不合并。[实际小图](dictionary-flow-example.md) · [本轮审阅](dictionary-flow-independent-review.md)。

2026-10-31（北京时间）：阶段71，DICT-IMPORT-01跨文件字典接收者映射修复已推送ad5b96c12e8b4ae362985bff9db69b4c7ee4d767，经独立第1/3轮审阅565 passed、25 skipped/24.82秒。字典身份已能正确追踪到second，但本提交没有新增生产字典/条目图节点或开放v5增量准入。未完成草稿保留并归档，Batch4未完成、未合并。[本轮审阅](dict-import-receiver-independent-review.md)。

2026-10-31（北京时间）：阶段67，函数值依赖设计契约、项目专用Skill和差距清单已完成并通过限定独立第1/3轮审阅。固定提交cc3c02d82b8f6046b5e6cb6494ef57cc23da132b，仅文档/Skill/审阅材料，无生产或测试变更；未运行pytest。Batch4仍未完成、未合并。

本轮导航：[设计契约](../../docs/FUNCTION_VALUE_DEPENDENCIES.md) · [现状差距](FUNCTION_VALUE_GAP_AUDIT.md) · [独立审阅](function-value-doc-independent-review.md) · [Skill演练原文](function-value-skill-forward-output.md)。详见阶段65—67。

### 历史状态快照（按原文保留，不代表当前状态）
最新：阶段63，容器分析读取依赖/未来writer订阅的partial sidecar开发完成，557 passed、25 skipped，待固定远端独立审阅。尚未把partial记录当作增量准入，Batch4未完成。
最新：阶段61，固定eb5ff65局部容器写入候选索引限定修复独立第1/3轮通过，563 passed、25 skipped/30.89秒。0/30无关写入下实际检查2scope/3事件不变。整体依赖驱动准入仍未完成、未合并。
最新：阶段60，局部容器写入scope索引开发完成，550项快回归通过、25跳过，待固定远端独立审阅。Batch4未完成，未合并。
最新：阶段58，5dd7ed4潜在子模块依赖索引限定修复独立通过；生产tests547通过、25跳过，独立边界适配旧索引断言后6通过。全局slot_scopes读取与整体依赖准入仍待处理，未合并。
最新：阶段57，通用潜在子模块查找索引修复开发完成；18项定向与547项快速回归通过，待固定远端独立审阅。仍保留全捕获认证，Batch4未完成、未合并。
最新：阶段55，真实item_units限定扩展25d415f第1/3轮独立审阅通过；561 passed、25 skipped，另历史/边界31 passed（有重叠）。仅支持已认证捕获；整个Batch4未完成、未合并。
2026-10-31 最新：阶段52完成真实源码小范围独立验收；2 passed（1.59秒），正确回退和旧版保护有效，但改1文件仍解析3/3，业务代码变更后的局部分析目标未达到。生产未改、未合并；不能把测试通过误称增量能力通过。以下历史保留。
2026-10-31 最新：用户授权缓存时间修复已实现并推送，固定ee6bbb9a72dbd8dd08129ede23e9d4a271dcdaa6第2/3轮限定审阅通过；570 passed、25 skipped（30.53秒）。未启用修复的独立对照2 failed，启用后通过；包上下文遗漏关闭。整个Batch4尚待功能验收，未合并。以下为历史记录。
2026-10-31 最新：授权重构已提交d9ec，跨库第1/3轮review发现包上下文遗漏；限定整改19项通过，但快回归暴露Jedi0.20.1/Parso0.8.7缓存条目淘汰后被继续引用的KeyError。栈和实际淘汰已证实；候选以patch归档，暂停并请求将核心依赖缓存兼容性纳入范围。未开始第2轮正式review、未合并。
2026-10-31 最新：用户“把么现在要refactor 吗 如果需要就开始”已批准修正Jedi项目环境及遮蔽失效索引，恢复限定开发。基线39b6d0ab3e18e9a5642078bde8c71a23999cd599，分支feat/incremental-index-updates；此前暂停记录保留。
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

## 阶段44：用户授权限定核心接入修正，恢复开发
用户已明确要求开始refactor。范围仅每仓库Jedi搜索环境、复用既有包名/依赖版本规则、请求方模块反查索引及其跨库增量接入。沿用GPT-6 SOL medium开发、主Agent固定提交独立review；尚无跨库正式review完成。定向开发测试→快速回归→push后独立反例，禁止付费/真实全图/Drive操作。通过本切片不等于整个Batch4完成，不合并。

## 阶段45：跨仓库环境与索引限定重构开发冻结
2026-10-31，GPT-6 SOL medium。B4-CROSSREPO-PROJECT改为每请求仓库Jedi环境，B4-CROSSREPO-SHADOW补requester索引；祖先pkg.py/包__init__.py布局变动对照确有影响，保守完整回退并覆盖新增/删除，不伪装局部成功。
- 开发定向16 passed（6.05秒），快速全tests/536 passed/25 skipped（20.29秒），Ruff通过；原始日志已保存。开发未push，待root固定提交review。
- 5个生产文件、2个测试文件、1个契约文档；未改Jedi版本、未执行真实服务/API/Drive。完整清单和限制见crossrepo-development.md。

## 阶段46：跨库第1/3轮正式review，需修复包上下文遗漏
固定提交d9ecf8538b0078b30edbf0e92dd2f78b2e85bbe4，远端核对一致；独立目录332个可用文件按远端blob核对，生产/测试/必要支持文件无缺失。快速回归及既有独立反例561 passed、25 skipped，33.15秒。
- B4-CROSSREPO-PROJECT同名完整包路径用例修复；不同包名正常对照保留。requester索引先前独立测量在0/20无关pairs时仍1相关行、3解析文件，正式固定测量将在整改后补齐。
- 新增同根因变体B4-CROSSREPO-PACKAGE-CONTEXT（P2）：本库已有未变化的包__init__.py或祖先pkg.py，调用方导入依赖库pkg.child。局部Graph只携带选择的AST源码，遗漏本库已有包边界；它的Jedi环境与完整构建不同。新增包时的fallback不能覆盖“包早就存在，本次只改caller”。独立探针确认edges/sites/import_dependencies/import_requests不一致，证据crossrepo-existing-package-probe.json及test_existing_package_context_independent.py。
- 明确修复：在闭包中通过现有module目录加入所选模块的包祖先，以及import请求在请求仓库/目标仓库中的祖先模块（含__init__与普通模块遮蔽），继续沿已有依赖扩展；只加入实际前缀上下文，不全仓库解析。不能放宽证据或抹去UNKNOWN；不更换Jedi。按当前step P2自行限定整改，再第2轮review，轮次不重置。
- 未合并、未调用付费或真实服务。完整通过数不掩盖独立新增失败。

## 阶段47：包上下文整改定向通过；核心依赖缓存问题人工介入
开发GPT-6 SOL medium完成resolver.modules索引前缀上下文，原2反例及正常provider包对照合计19 passed（5.52秒）。候选未应用远端生产，保存patch/哈希。
- 快回归两次6 failed/531 passed/25 skipped；单独contextlib6通过，固定d9ec536/25通过。保留失败，不改断言。
- 主Agent栈定位Jedi get_parso_cache_node对contextlib.py的缓存KeyError（-x:1 failed/442 passed/25 skipped，15.06秒）。纯观测Parso缓存>=600时实际淘汰contextlib，last_used年龄419741.6秒，保留阈值600秒（-x:1 failed/442 passed/25 skipped，14.16秒）。代码初始化/磁盘load时间语义与此一致。
- B4-JEDI-PARSO-CACHE为核心外部依赖缓存交互问题；未确认P0P1，但按skill核心依赖规则暂停扩大修复。建议独立最小复现+官方修复/有限兼容补丁评估，保持解析器和正确性断言，不以清缓存规避、不无界保留。
- 详细crossrepo-package-context-and-cache-report.md，第二轮正式review尚未开始，旧轮次保留，未合并/真实建图/API/Drive。

## 阶段48：用户授权Parso缓存有限修复；本地开发完成，未提交

2026-10-30 UTC。用户明确授权修复“新加载的旧文件缓存条目被错误判作不活跃”，不扩展一般Jedi生命周期设计。工作分支feat/incremental-index-updates，远端基线efc90d46bdd74e74325b0460c9578a4303b11d1b，生产合并目标d9ecf8538b0078b30edbf0e92dd2f78b2e85bbe4。当前目录非Git checkout；此阶段代码未提交/推送，正式第2/3轮review尚未开始。

- Parso 0.8.7精确版本包装原`_set_cache_item`：插入前只刷新`last_used`，包括新解析和真实磁盘pickle恢复；原函数仍负责达到600时清理超过600秒的旧条目。`change_time`及源码修改失效保留，Analyzer构造Jedi Script前幂等安装，版本不支持时显式失败。pyproject直接pin 0.8.7、uv.lock元数据同步，旧requirements.lock.txt已pin；现有包上下文候选保持。
- 定向84 passed/3.87秒；全tests/539 passed、25 skipped/23.35秒（exit0）；随后仅新增版本guard测试，最终定向含跨库94 passed/6.42秒（exit0），Ruff通过。完整日志`parso-cache-development-fast.log`、`parso-cache-development-targeted.log`及Ruff日志。`uv lock --offline`因本地uv缓存缺Jedi 0.20.1未能解析，手动对齐现有lock元数据；没有将其称作锁定解析成功。
- 真实Parso冷解析、pickle恢复、600项触发下新旧淘汰、源码修改失效和安装幂等/版本失败均有项目测试。包装每次插入O(1)刷新，不增加全局遍历；原阈值O(N)扫描依旧。未验证十分钟以上仍活跃Jedi引用或完整真实规模，兼容补丁不作此保证。
- 详细实现、持有者/成本、允许文件与限制见`parso-cache-development.md`。未启动真实服务、付费API、真实图或Drive，未合并；下一步由主Agent固定候选提交并独立第2轮review。

## 阶段49：跨库整改第2/3轮独立审阅通过，缓存误删关闭
2026-10-31，固定ee6bbb9a72dbd8dd08129ede23e9d4a271dcdaa6，远端核对一致。开发定向94 passed；完整自测539 passed/25 skipped后新增版本guard测试，最终独立回归覆盖全部：570 passed/25 skipped、30.53秒、exit0。
- B4-JEDI-PARSO-CACHE及B4-CROSSREPO-PACKAGE-CONTEXT关闭。真实冷解析/磁盘恢复/620文件清理及源码改变检查通过；停用修复的原行为对照2 failed、0.73秒，均KeyError，原始证据保留。
- 357个支持文件按远端blob核对。初次传输大源码被截断，在验收前追加提交恢复并核对；未使用截断代码验收。报告parso-cache-independent-review.md，日志parso-cache-root-fixed/unpatched.log。
- 新增兼容层单次插入O(1)，原过期清理保留；不提高阈值、不全局刷新时间、不改变源有效性。版本固定0.8.7，不扩展长期缓存生命周期承诺。
- 第2轮通过，不开启第3轮；整个Batch4未完成、未合并。没有真实服务、付费、建图和Drive操作。

## 阶段50：恢复真实源码增量验收，先核实支持范围
2026-10-31，用户“好的 继续”授权推进真实源码增量/完整构建对照、索引一致性及恢复验收。远端基线dd2f34084b5ed11182890b4917efba56f9d1e4de，固定生产ee6bbb9。已通过的跨库缓存整改保持第2/3轮通过，不重置。
- GPT-6 SOL medium子Agent执行有限真实源码审计与可复现小范围对照；主Agent独立核对实现。无正式生产修改、真实全库构建、付费调用或Drive操作。
- 已从实现确认两处未完成：storage.build仅在整个捕获满足simple-python-v3时生成认证，prepare先要求该认证；Neo4j import_snapshot仍分批写入完整新版本，尚非差量投影。这些是现有已声明限制，不把语法回退称为错误图。
- 本轮先测真实支持范围、具体回退原因及结果一致性；再确定最小后续实现。不能以合成样例通过宣布业务增量完成。

## 阶段51：真实源码诊断样例交付，局部更新验收未通过
2026-10-31，GPT-6 SOL medium完成可独立复现的3模块真实源码样例，来源SM提交a7b0804d5635e185a79ff3c1d1fa6241c2b858fe；按blob/SHA256记录原始字节，源码随测试打包，不依赖临时工作区。开发定向1 passed、1.26秒。没有生产修改，尚未推送本轮证据。
- availability.py只修改context=context为context=None；更新仍full-graph，reason=previous-simple-python-certificate-unavailable，重新解析3/3文件、分析13站点、执行30次Jedi查询。完整记录等于独立完整重建，旧版保持不变。测试通过意味着复现和安全回退正确，不表示局部更新目标通过。
- 80份可用历史归档生产模块的单文件认证均未通过；70份含相对/星号导入，48份含类基类/装饰器，44份含函数注解/装饰器等（类别交叉、非完整失败归因）。不代表最新main或完整仓库。
- 下一步主Agent核验远端原始源码与固定LCT提交，独立复跑；不能删除安全门槛来制造局部通过。

## 阶段52：真实源码能力验收独立核验，确认尚需实现
2026-10-31，固定生产ee6bbb9、证据基线dd2f340。主Agent从GitHub固定SM提交a7b0804逐字核验3份样例，独立运行诊断和新增无变化/失败对照：2 passed，1.59秒，exit0。
- 代码不变时0次Python解析；修改后仍因previous-simple-python-certificate-unavailable全量3文件；与完整重建记录一致，旧版不变；发布前注入失败保留旧指针，重试成功。只覆盖小范围lexical本地流程，不包括Neo4j/dense/真实全库。
- 结论：回退正确性通过，业务源码局部分析性能目标未达。不是Jedi不支持这些源码，而是当前simple-python-v3认证范围过窄且要求整个捕获通过。80份归档单文件认证还受缺失导入上下文影响，不作为完整业务覆盖率结论。
- 后续修复具体归属simple_python.certify、storage.build认证持久化、python_incremental.prepare。必须在明确依赖证明后扩展真实语法与按分析单元认证，不直接删除全局准入条件。无新生产修改，不复跑无关全量回归，跨库第2轮通过结论保留。本轮是能力验收诊断，未伪造新修复review。

## 阶段53：开始真实纯校验函数的限定增量支持
2026-10-31，用户“好的 继续”授权完善当前增量能力；基线c91c066a0fbdc47141f48db7b5b9ac5d2af071ba，分支feat/incremental-index-updates。先前跨库/缓存整改第2轮通过保留，不因新功能重置。开发GPT-6 SOL medium，主Agent独立审阅。
- 直接允许同库任意未认证文件复用仍缺少非干扰证明，本轮不删除全捕获准入。实现第一项可证明扩展：真实item_units.py使用的明确内置类型守卫、纯表达式和受限re.fullmatch调用；其余不支持的代码仍全量回退。
- 操作符可能触发自定义协议，不能仅增加AST类型白名单。必须按短路顺序识别明确类型守卫，内置名/模块名覆盖不得误认证；保留原分析器UNKNOWN及完整性输出。证书版本变更，旧证书安全回退。
- 验收：原始真实源码（隔离副本修改）、0/20无关已支持模块、调用者反向依赖、同名re.py和内置名覆盖反例、完整记录对照、旧版不变；定向→快速回归→固定提交独立review。无付费/Neo4j/真实全库/Drive。本切片不等于真实SM全部局部更新完成。

## 阶段54：真实校验模块限定扩展开发完成，待固定提交审阅
GPT-6 SOL medium完成simple-python-v4，生产仅修改simple_python.py，新增真实item_units定向测试并更新契约。全捕获认证仍保留；不支持的同库文件未实现隔离。尚未推送、未合并。
- 最终定向29 passed/6.64秒；快速全仓库543 passed、25 skipped/21.83秒发生在最后helper绑定限制前，不能冒充最终候选回归，主Agent将补跑。
- 修改真实叶子1/21文件解析；存在导入调用者时2/22，均复用20文件，六类图证据与完整重建一致。旧证据不变；新增re.py覆盖触发安全回退。基线正例失败证据保留。
- 新增类型守卫必须按执行顺序成立，内置名覆盖、守卫后未知调用、helper逃逸、动态指数等拒绝认证。无Jedi重写、无付费、Neo4j、真实全库或Drive操作。详见actual-item-unit-development.md。下一步固定远端候选独立审阅。

## 阶段55：限定扩展独立审阅第1/3轮通过
固定25d415f55b37a51992bb3fd8ae7550b702ba52df，远端核对一致，88份生产/测试/配置blob一致。最终快速回归加新增反例561 passed、25 skipped/23.79秒；历史/边界31 passed/7.55秒，部分重叠。完整审阅actual-item-unit-independent-review.md。
- 无关文件0→20，公开build实际解析始终1文件、Jedi始终11次；后者复用20文件，六类图证据与完整重建一致。带导入调用者2/22，新增re.py安全回退。
- 首次两项失败原始日志保留：测试环境缺.venv链接及主Agent零无关文件时错误要求局部计数。补齐环境、按实际合理全量唯一文件路径修正独立测试后通过；生产代码未改。
- 不支持同库代码仍阻止局部复用，整个Batch4未完成、不合并。未运行真实服务、全库图或付费/Drive操作。下一步解决真实语法及按分析单元复用的依赖证明。

## 阶段56：依赖驱动准入调查完成，确认两个可复现缺口
用户要求按真实依赖判断局部复用，而非逐业务文件放宽语法。固定生产25d415f、最新证据c09fd56，GPT-6 SOL medium执行有限full/full反例，主Agent追踪实现。当前生产安全门槛仍保留，未发生错误局部发布。
- B中from pkg import foo，旧无namespace pkg/foo.py；新增该文件后B的Jedi观测和完整性变化。现有import_requests仅记录pkg，新增pkg.foo不能反查B；没有现有跨文件边可补救。不能拿有直接import边的普通缺方法案例冒充缺口。
- 无导入关系A新增局部字典下标写入，B读取自己registry回调时container_slots会遍历全局slot_scopes。B的目标未变但完整分析证据新增A的NO_EFFECT检查；旧文件图闭包没有这条分析读取依赖。
- 本轮实施第一项通用查找键/反向索引修复，保留原import请求记录及仓库身份、祖先范围判断和旧格式回退。第二项先保留实证，不擅自重写解析器、删除证据或把所有文件标为可复用。整个Batch4仍未完成。

## 阶段57：潜在子模块查找依赖修复开发完成
GPT-6 SOL medium在c09fd56基线完成通用indexed-v2依赖键。import_requests保留原样，新增import_lookup_keys保存原模块名及from导入潜在子模块名，使用lookup_repository/module和source_repository/module/source_path索引。importers/requesters及祖先布局检测实际消费新键。旧v1或缺少新表/索引显式回退。
- 开发定向18 passed/5.10秒，快速全仓库547 passed、25 skipped/26.82秒。原无依赖反例和全局slot_scopes反例脚本/输出保存。尚未推送本轮，待主Agent固定提交独立review。
- 初版派生定义名让2项跨库用例不必要回退，已改为只对未被同一文件精确base请求覆盖的后代查找执行祖先回退；实际SQL采用索引NOT EXISTS。真祖先布局变化仍回退。
- 全捕获simple-python证书未删除；无init跨库namespace根潜在provider归属尚不完整，保持原版本绑定回退，不跨任意仓库猜测。全局slot_scopes读取依赖问题仍待处理。无付费、真实服务或Drive操作。

## 阶段58：潜在子模块依赖索引第1/3轮独立审阅通过
固定远端5dd7ed4dbbc742149978f06fc69c79a3c24e28b3，390份支持文件blob匹配。联合回归552 passed、1 failed、25 skipped/27.79秒；唯一失败是历史独立测试写死旧表/索引名，生产tests547项均通过。保留原始日志，按新SEARCH计划适配断言后独立6 passed/2.69秒，无生产修改。
- namespace反例旧版0/25无关文件均无法反查，修复后均能查到caller；实际SQL均SEARCH。0/100无关导入时2次查询各1行，VM42/44；公开跨库遮蔽0/20对噪声仍解析3文件、查询结果1行，VM87/88。没有把索引开启前完整性哈希算成局部读取。
- 修复仅补齐潜在子模块反向键，未删除simple认证，namespace案例仍全量但依赖反查已正确。全局slot_scopes依赖/跨库namespace根归属及业务总体局部准入仍未完成。详细module-lookup-independent-review.md。未合并，无全库/服务/付费/Drive。

## 阶段59：开始局部容器写入候选索引修复
用户“请继续”授权处理Analyzer.container_slots全局slot_scopes读取。基线40e15d328ddae8996c3d4e352b40190d07de5fba（生产5dd7ed4），仍在feat/incremental-index-updates。按batch-dev-review/locality-review，GPT-6 SOL medium子Agent实现、主Agent独立审阅。
- 基线已实证A无关系局部字典写入进入B的NO_EFFECT证明。候选设计为一次性写入scope来源索引：能证明仅指向本函数局部literal的写入按来源身份归类，无法排除的scope保留fallback；查询目标取相关bucket、未知scope、当前scope及owner，不在每次查询前全量resolve/过滤。
- 不按变量名猜测排除；保留别名、参数、导入registry、调用逃逸和协议UNKNOWN。不修改simple-python认证、不开放未经证明的全库局部更新。
- 定向先证0/20/100无关局部writer下目标检查量，准备索引O(N)单列；相关写入/历史副作用对照、一次快速回归、固定远端独立review。无付费/服务/Drive/合并。

## 阶段60：局部容器写入候选索引开发完成
GPT-6 SOL medium实现：Analyzer初始化EffectCatalog后一次构建局部literal来源桶及fallback集合，container_slots取目标桶、fallback和scope/owner。仅完整函数体可证明fresh literal/别名/常量键值且无逃逸的写入scope入桶；模块、参数、导入、未知调用/控制协议等仍保留原检查。不修改simple-python及增量准入。
- 公开build 0/20/100无关local writer：准备scope数0/20/100，目标候选scope2/2/2、事件3/3/3，覆盖required3/3/3；准备成本明确单列。旧全局反例的A事件不再进入B证明，目标/完整性保持。
- 历史定向251 passed/4.42秒，最终复用指标接线6 passed/2.26秒，快速全仓550 passed、25 skipped/27.09秒，ruff通过。identical复用四个本次执行指标置0，site不变。
- 变更python_analysis.py、graph.py、storage.py少量接线及测试/契约/证据。开发报告container-local-scope-development.md。尚未推送本轮；接下来主Agent固定提交独立审阅。不确定scope仍可能大范围检查，不宣称全库局部分析完成。

## 阶段61：局部容器写入索引独立第1/3轮审阅通过
固定eb5ff65f0f236f898b4f2a055e079c6b8d75cfd6，405份支持文件按远端blob核对，全部非review文件齐全。快速回归加独立/历史反例563 passed、25 skipped/30.89秒；新4项计数用例输出4 passed/0.39秒（已包含在563内）。
- 实际Graph.build/Analyzer路径中0/30无关局部alias writer，EffectCatalog.before只访问B.run与B模块，共2scope/3事件；固定B身份完整site记录相同。导入别名、参数重绑保留other候选及UNKNOWN；动态键/闭包保留fallback。
- 原基线1 failed、2 passed/0.53秒与修复后日志保存。本轮未发现新阻塞，细节container-scope-independent-review.md。
- 未消除所有未知scope检查，未修改整批simple认证；后续仍需持久化真实分析依赖/不确定范围并接入增量准入。无真实全库、服务、付费、Drive或合并。

## 阶段62：开始持久化容器分析读取依赖及未来候选订阅
用户“请继续”授权。基线9dad3d1def60dc850dd379bbb61756fdd7c6c6c4，固定生产eb5ff65，GPT-6 SOL medium开发、主Agent独立审阅。
- 实际container_slots consumer模块到候选producer模块的container-effects读依赖；即使当前fallback为空仍保存slot-writer-universe/all-captured-python订阅，以覆盖未来新增不确定writer。读取关系不是CALLS，递归copy按实际scope形成可传递链；明确仅partial，不涵盖全部resolve/Jedi内部依赖。
- 独立SQL表及反向索引，manifest只摘要；完整构建、相同输入复用、既有局部组件准备均保留/替换记录。旧格式不冒充新证据，不接入新局部准入、不删除simple证书。
- 去重记录总预算20000；截断显式标记，新反查接口不可把截断记录当完整返回。完整分析继续，合并后预算亦校验。
- 定向实证实际读取/零旧候选订阅/新增writer/孤立writer排除、嵌套copy链、SQL实际索引与无关记录扩容、旧格式/失败恢复；一次快速回归后固定提交独立审阅。无全库/服务/付费/Drive/合并。

## 阶段63：部分分析依赖持久化开发完成
GPT-6 SOL medium完成Analyzer实际container读取记录与全capture writer订阅；graph-sites.sqlite独立reads/watches表及反向索引，indexed-v3、schema1、coverage=partial，manifest仅数量/截断摘要。预算20000共享一处常量，超限仍完整分析但新反查API显式不可用。
- 完整构建/identical保留记录；现有local路径通过纯merge helper维护，选中consumer替换，保留旧记录需端点存在且验证，跨selected producer或未重算的全capture watcher存在则回退full。没有把新API用作增量准入。
- 定向31 passed/7.85秒、快速全仓557 passed、25 skipped/25.06秒、ruff通过。嵌套copy B->A->C链、原无图边读取、孤立writer无依赖、未来订阅、记录预算、旧格式、失败发布均有测试。真实certified local验证零记录；非空merge用纯helper单测，未伪造已发布证书。
- 生产变更python_analysis.py、graph.py、storage.py、python_incremental.py及新测试/契约。不改simple证书，不宣称完整Python/Jedi依赖覆盖。尚未推送本轮，下一步主Agent固定远端独立审阅。无全库/服务/付费/Drive/合并。


## 阶段64：部分分析依赖持久化独立第1/3轮审阅通过
固定远端358b63f4c07a8e847b74345eb1a214804e415e14，tree6dc999e3846145be5b19091efea8decec2a1baa1，416份文件blob核对，全部非review文件齐全。主Agent仅修正自己的测试，未改生产代码。
- 联合回归571 passed、1 failed、25 skipped/31.58秒；557项仓库测试全部通过。失败是独立用例读取已被默认两版保留策略淘汰的版本；保留日志，改查仍保留的上一版本后3 passed/1.08秒，计数重叠，未把首次整套称为全绿。
- 实际公开build验证未来writer订阅、无普通图边的实际读取、失败发布、identical复用、删除过时读取及旧视图隔离。预算降到1仍保持nodes/edges/sites完全相同，截断仅影响依赖证据可用性。
- 0/40无关模块，目标/异库负对照共2次真实API查询、目标1行、SQLite VM均38步；均SEARCH覆盖索引，无SCAN。构造器全量完整性哈希单独说明。
- 完整结论analysis-read-independent-review.md；本限定补充通过，Batch4仍未完成，未合并。尚未将partial记录用于增量准入，其他分析依赖与真实业务局部/全量对照仍需完成。无服务、付费、全库或Drive操作。


## 阶段65：函数值依赖统一契约与项目Skill开始
用户确认“好的 请开始工作”。当前限定交付为设计契约、仓库内code-graph-dependency-change Skill、现有实现差距清单与入口链接；不改解析器生产代码，不建图、不调用付费API、不合并。
- 仓库agentic-trpg/local-code-tools，分支feat/incremental-index-updates，基线4b76e06793e1a3700575e33a67eb7b4de5c5a681、tree27a30a8962a2642437d6a98fcb0dc080554c3840；目标分支仍feat/local-code-tools-import，整个Batch4尚未满足合并门槛。12份关键生产/文档blob已与远端核对。
- GPT-6 SOL medium开发子Agent编写，主Agent独立审阅。使用batch-dev-review/locality-review及Skill Creator的内容规范，用户明确要求仓库专用，不改/安装个人全局Skill。
- 对函数定义、字典身份+key条目、写入/调用位置、参数/返回/属性/闭包等记录身份与关系；未知范围订阅、来源支持、别名、顺序/分支、旧新差异及工作队列传播明确契约。循环次数和任意Python运行时精确预测不在目标内。
- 审计必须区分已保存已消费、已保存未用于闭包、确认缺失、尚未核验；不因为缺细粒度节点就声称旧粗粒度关系完全无用。仅文档/链接/frontmatter/真实源码核验，不重跑几百项业务测试。


## 阶段66：统一契约、仓库Skill与差距清单开发完成
GPT-6 SOL medium子Agent完成限定文档交付，尚未提交/推送，未合并。基线4b76e06793e1a3700575e33a67eb7b4de5c5a681，分支feat/incremental-index-updates。
- 新增docs/FUNCTION_VALUE_DEPENDENCIES.md、FUNCTION_VALUE_GAP_AUDIT.md、.agents/skills/code-graph-dependency-change/SKILL.md和AGENTS.md；README及INCREMENTAL_UPDATE增加入口，开发记录function-value-doc-development.md。契约覆盖条目身份、写入/调用来源、未知范围、循环非计数、删除支持与依赖传播；明确仅待实现，不改生产/测试/schema/投影。
- 差距逐类核对变量/字典/列表/属性/参数默认值/返回闭包/lambda/绑定方法/partial/装饰器注册及动态查找；把已有粗边与缺持久证据分开。现有EffectEvent和site证据复用；partial能力仅标未验证。
- 开发者检查相对链接、YAML frontmatter及测试名称AST引用，均通过；无可执行代码变更，未运行pytest。主Agent独立初检发现旧历史review脚本的本地材料与远端不同，已排除上传，基树保持远端原字节；所有本地已有生产/测试blob与远端一致。
- 下一步固定远端文档提交后独立检查及新上下文Skill演练；不安装个人全局Skill、不启动服务、无API/建图/Drive。


## 阶段67：统一契约与项目Skill第1/3轮独立审阅通过
2026-10-31（北京时间）。固定远端cc3c02d82b8f6046b5e6cb6494ef57cc23da132b、tree3a9f3570947794151564d18e4d78b3395995bc62。远端差异恰为9份文档/Skill/证据文件，lct/、tests/及依赖文件未变。审阅副本425份blob核对，全部生产/测试材料齐全；262份无关旧review制品未恢复，不影响本轮范围。
- 设计契约明确函数定义复用、条目身份与Python键相等语义、未知范围、赋值/调用来源与多来源支持、顺序/分支、循环不计次数、失败/新增依赖、旧新差异和依赖传播。已实现和待实现明确区分，partial记录不能作完整准入证书。
- 独立静态检查：10相对链接、15完整测试函数引用AST及额外短引用、YAML元信息通过；实际源码确认prepare消费adjacent/importers/requesters/certify，但不调用analysis_readers/watchers选择闭包。新增节点不自动生成向量或改变检索层级。原始function-value-doc-independent-checks.json保存。
- 新上下文GPT-6 SOL medium只读演练使用固定副本的项目Skill，对同名key的两个字典、别名、条件覆盖、未知key、删除/新增和多来源清理给出正确的限定计划；明确当前回退、未实现和向量边界，无生产编辑/测试/API。演练只是指引可用性证据，不是增量实现验收。
- 本限定文档交付通过，无确认阻塞，未合并。无需运行无关全仓pytest；不重用旧测试数字作为本轮通过数。下一批先设计并实现已知字典+常量key+写入/读取来源的最小贯通切片，再单独验证新增/删除/未知范围、全量对照及查询索引；参数/返回等后续扩展，不全面重写解析器。


## 阶段68：字典函数值最小贯通切片开始
2026-10-31（北京时间）。用户“请继续”。远端基线d455ec3710f3c3bc5ec385c76db94a8cc3ce38f9、treec11e0b5edc81d902791b66168432ea7e9cf5a48f，仍用feat/incremental-index-updates，整个Batch4不合并。按AGENTS、新项目Skill、batch-dev-review/locality-review执行；GPT-6 SOL medium开发，主Agent独立审阅。
- 本轮目标：已知literal字典+常量key，保存来源明确的写入、条目、读取/调用关系，并让公开build的受影响闭包实际使用反向记录；不能只有持久化。复用当前container_slots/EffectEvent/site的解析结果，不替换解析器。
- 首版限结构可证明的直接literal/别名/固定key读写；非逃逸检查及显式捕获导入。条件/循环/dynamic/逃逸等复杂写入保守full回退，不提升完整性。新证据版本化，旧/缺/截断full回退；原module reads/watches仍按实际证明范围选择，不虚报key级精确性。
- 新中间记录在内部SQLite关系图表，明确尚不投影Neo4j；不改函数/类/模块检索层级，不自动向量化。完整/identical/local保存重绑定，删除使用旧依据，失败不动current。
- 验证：公开build初建/相关修改/删除新增与独立full同捕获对照；别名/异字典/未支持逃逸/等值key、旧格式/截断/失败发布；0/20无关普通文件及实际SQL索引计数。定向与相关历史反例通过后一次快回归，固定远端再独立review。无API、服务、真实业务图或Drive操作。

阶段68范围澄清（实现前）：原跨文件模块literal写入→导入读取路径的完整Analyzer已有unknown-container-origin/unadjudicated-jedi-lct-conflict，不能在保持原语义时伪造确定目标。开发者原始probe将保留；本轮不扩大到修复该既有解析限制。首个必须通过的贯通验收改为同文件registry写入/读取，明确记录这一调整；跨文件setit候选+UNKNOWN仅在可证明范围内附加。
- 主Agent原A/B期望局部检查在0/20无关文件下2 failed/0.93秒，日志dictionary-flow-baseline-independent.log保留；没有隐藏或倒写为通过。新同文件基线0/20对照同样2 failed，新增test_dictionary_local_independent.py作为首版验收，原跨文件检查另存为未通过限制，不冒称实现。


## 阶段69：按用户澄清返回前序解析缺口DICT-IMPORT-01
用户询问import找不到字典是否应建字典节点，并在解释后要求“那么请继续”。容器节点+条目节点保留；但图节点不能替代正确的导入绑定映射。主Agent有限诊断已定位自有代码根因，不是Jedi能力缺失。
- 发现批次Batch4字典增量切片，所属既有Python解析（前序Batch1），P2：确定示例被保守UNKNOWN，未证实错误complete。当前step内允许回溯修复；暂停依赖此路径的v5接入，未完成候选原位保留，不合并。此次新问题整改链尚未开始正式review，不重置历史问题轮次。
- 实证：Jedi goto把from a import registry定位到a.py第4行registry["go"]=second的registry token。Analyzer的captured assignment映射只接受ast.Name赋值目标，不接受Subscript的接收者，产生unmapped-captured-definition；之后unknown-container-origin和冲突拒绝。Jedi对最终调用本身已给出second。
- 明确方案：只识别准确文件/行/UTF8列的Subscript目标直接Name接收者，解析此写入之前的接收者绑定；不把写入值second当成字典，不按名字全局猜测，不放开未知/歧义来源。后续仍由container_slots检查写入及不确定性。
- GPT-6 SOL medium在独立基线副本lct-function-contract-review仅改python_analysis.py与新定向测试；主Agent单独推送/审阅该修复，之后再恢复未完成value-flow候选。无删除草稿、服务、API、业务图或合并。


## 阶段70：DICT-IMPORT-01限定开发完成，待推送独立审阅
GPT-6 SOL medium在独立基线副本完成：Analyzer.map_name对Jedi精确定位的Subscript直接Name接收者，先找写入之前的唯一、完整literal Dict来源，再返回字典身份。未把slot值当容器，不放开序列、未知/自定义/歧义来源。既有Name赋值映射不改。仅python_analysis.py生产修改和新test_dictionary_import_receiver.py。
- 开发者定向106 passed/日志保存、ruff通过；其中包含主Agent独立用例但不算独立执行结果。主Agent独立基线3 failed、2 passed/0.41秒；修复后独立5 passed/0.41秒（未提交副本预检），涵盖直导入、别名、Unicode列/两个字典、条件不确定性和自定义下标。固定远端后的回归仍待执行。
- 尚未推送/未合并；未完成value-flow/v5草稿暂停原位保留，不夹带上传。未新增服务/API/图构建，下一步单独固定修复SHA并独立第1轮review。


## 阶段71：DICT-IMPORT-01固定提交独立第1/3轮审阅通过
2026-10-31（北京时间）。远端ad5b96c12e8b4ae362985bff9db69b4c7ee4d767、treedeff0ac83d7aafe260574e1c19466bb73e839954，439份blob核验、全部生产/测试材料齐全。主Agent未改生产；固定提交快回归加独立反例565 passed、25 skipped/24.82秒，退出0。565已含独立5项，不与开发106或预检重复相加。
- DICT-IMPORT-01关闭：Jedi精确token定位到字典写入接收者时，LCT先解析写入前的唯一literal Dict，再使用原slot/调用裁决。直导入/别名/Unicode/异字典正确，条件与自定义下标保留不确定性。既有模块候选映射遍历未改，不虚报整体性能优化。
- 无新确认阻塞、无放宽历史断言。旧原始基线3失败2通过、开发定向106、主Agent预检5与远端快回归日志分别保存。25跳过均条件缺失，不是通过；无服务/API/真实图/Drive。
- 下一步恢复节点+关系+增量接线草稿，先合入本修复，再将原跨文件A/B实例重新纳入验收。草稿未上传到生产路径；review内dictionary-v5-incomplete-draft.patch/JSON仅恢复材料，标明缺接线、测试和兼容验证，不可自动应用。本限定修复通过，整个Batch4未完成、不合并。


## 阶段72：恢复字典关系与跨文件增量贯通实现
2026-10-31（北京时间）。用户“请继续”。远端基线87acde8e3f726560eb6e1d17da136e16dd8c9fdc、tree0d50bc09752b1b85ffce0a2ef7505eeed75c90d0；分支feat/incremental-index-updates。DICT-IMPORT-01已通过，不再次修改其认证规则。GPT-6 SOL medium开发子Agent恢复未完成草稿，先精确合入已审阅map_name修复，主Agent独立review。
- 必须重新纳入原跨文件A/B：A只有字典声明/写入也可成为生产者，B的导入及别名读取指向同一字典身份与key条目；不再以同文件替代跨文件目标。已知常量字符串key、结构可证明无逃逸写入先贯通，复杂写入显式full回退。
- 保存容器/条目/写入/读取调用及来源边，缺失key条目表示可订阅地址、非实际存在证明；不允许缺witness却标完整。prepare实际消费entry/reader反向索引及必要旧module读/范围订阅。完整/identical/local重绑定、版本/缺/截断证据和失败发布均在门槛内。
- 新中间图仍明确internal-sqlite-only，不自动向量化、不进入函数/类/模块检索层级；Neo4j投影未接入不可冒称。原scope/root独立A/B、同文件、逃逸/条件/动态key和发布失败测试保留，另验证实际索引/预算/回复边界。无API、服务、业务全图、Drive；未合并。


## 阶段73：跨文件字典函数值最小贯通开发完成
2026-10-31（北京时间）。GPT-6 SOL medium完成并冻结，基线87acde8e3f726560eb6e1d17da136e16dd8c9fdc、分支feat/incremental-index-updates；尚未推送/未合并。已合入DICT-IMPORT-01，原A/B跨文件验收重新接通。
- value_flow.py及graph/storage/analyzer/simple_python/prepare接线：内部容器、条目、声明/导入/别名binding、写入、读取调用节点；BINDS/USES_BINDING/ADDRESSES/WRITES/VALUE/REACHES/READS/POSSIBLE_CALLS，复用原函数节点。缺失key表示订阅地址present=false。逻辑ID不含仓库snapshot，固定版本存储隔离；保留未改producer-only证据，旧read.site_id安全重绑定。
- simple-python-v5仅开放已知literal字典/字符串key/直接导入别名/直线写入等可证明结构，严格无逃逸。prepare实际消费entry/read反向索引和原module读/全capture订阅（每轮一次）；缺/旧/partial/超预算完整分析，不放宽UNKNOWN。复杂条件、动态/数值key、跨库及mixed通用传递调用等仍有full回退限制。
- 最终开发定向27 passed/7.13秒，快回归570 passed、25 skipped/26.14秒，ruff通过；原2个before整数sentinel TypeError与旧v4硬编码断言失败日志保留。explain证据兄弟顺序不稳定已按源码稳定排序，目标和UNKNOWN内容不变，直接排列对照与实际full对照通过。
- 主Agent独立预检2 passed/1.02秒，0/20无关producer-only字典不扩解析范围，语义表及公开结果与full相同；实际反向SQL SEARCH、每次1行、VM17/16不变，watcher只查询一次。预检不是固定远端独立review，下一步固定提交后完成第1轮。
- 仅内部SQLite中间图，尚未投影Neo4j或MCP，不自动向量化。未改实际RE/SM或业务库；无API、服务、真实业务全图和Drive。完整开发报告dictionary-flow-development.md，Batch4仍未完成。


## 阶段74：跨文件字典切片固定提交独立第1/3轮审阅通过
2026-10-31（北京时间）。固定cf4b0fbac0e11f18d53f7dbff1be8b1e40cd6505、tree2b761e04afb951fa84baab969df8a1bfb226bafa，454份文件blob校验，全部非review源码/测试齐全；262份无关旧review制品未恢复。主Agent未改生产。
- 一次快回归+原跨文件8项、同文件7项、索引2项、导入5项及既有callback独立检查，599 passed、25 skipped/34.65秒。独立真实索引计数输出另2 passed/0.87秒，已包含于599不可累加。固定提交上每项反查1条、1次SQL、SEARCH主键索引，VM18/15在0/20无关producer-only字典下不变；watcher一次，公开build只解析A/B。构造器完整性哈希/计数与必要O(N)序列化另列，不冒称全部处理O(1)。
- 实际生成合成内部图7节点/11关系，引用2个已有函数节点；声明和导入指同字典，go条目保存两次写入，仅后一次REACHES调用，实际目标second。dictionary-flow-example.md/JSON保存实际数据与图示；非Neo4j截图、非付费调用。
- 原失败日志与限制如实保留：开发证据顺序和before sentinel已修，旧v4字面断言改为当前CERTIFICATE常量，未放宽行为断言；root原局部更新失败对照在本提交已通过。无新确认阻塞。
- 仅支持的字典结构切片通过；数值/动态key、复杂写入、同库普通模块导入modeled字典模块函数的mixed路径等仍可能full回退，旧broad watch影响扇出仍在。其他函数值流/真实业务范围准入、Neo4j中间关系投影和完整功能验收尚未完成。未合并、无服务/API/真实业务图/Drive。


## 阶段75：字典模块与普通调用者混合准入修复开始
2026-10-31（北京时间）。用户“那么请继续”。基线f86acd211948b53f13e8eccb8605b24e31a4b7ae、treee5779a7193e9d2be4231aa1a5d601f096f5cc762，仍用feat/incremental-index-updates。适用AGENTS/项目Skill/batch-dev-review/locality-review，GPT-6 SOL medium开发、主Agent独立审阅。
- 已定位：certify的字典结构验证已覆盖A/B，但plain_files仅包含C等普通模块，_certify_v4把这个列表误当整个可引用上下文，所以C导入B.run被拒绝，初建缺整批证书，后续走full。不是缺CALLS边或解析工具无法跟踪。
- 限定方案：给私有v4校验helper传入已通过字典结构验证后的完整当前模块上下文，保持默认行为/公开certify接口和所有源码/导出/AST/绑定/函数体校验。只验证普通模块函数体但允许引用已验证的字典模块定义；不伪造AST、跳过目标验证或放开逃逸。
- 允许生产仅simple_python.py，新mixed组件测试和小型文档状态/开发记录；不改解析器、schema、模型节点、Neo4j或向量。公开A/B/C与可选D、多代修改/删除/新增key、失败旧视图及full对照；0/20无关普通与producer-only文件不解析；未支持provider/export/escape仍full。
- 主Agent已新增独立test_mixed_dictionary_independent.py及基线日志；下一步开发定向、一次快回归、固定提交后独立第1轮review。整个Batch4未完成、不合并，无服务/API/业务全图/Drive。

阶段75独立基线：3 failed、3 passed/1.87秒，A/B/C及双层普通调用者仍全量；逃逸、缺provider、缺export三个拒绝对照原已通过。mixed-dictionary-baseline-independent.log保留。

## 阶段76：字典模块普通调用者准入开发完成
GPT-6 SOL medium已冻结，尚未推送/未合并。生产仅修改simple_python.py：私有_certify_v4增加selected_context=None，默认仍按自身files确定上下文；mixed分支先通过capture_shape，再传入本次捕获的完整模块集合，仍验证普通模块体和真实目标module/AST/导出/精确绑定。公开certify接口、模型/schema/解析器/索引不变。
- 新test_mixed_dictionary_components.py，INCREMENTAL_UPDATE小型状态更新及开发报告/日志。开发最终定向48 passed，快回归578 passed、25 skipped，ruff通过；原A->B->C/D、0/20无关文件/producer-only复用、替换/新增key、失败旧版与full对照通过；未支持AST/export/provider/rebinding/dynamic/condition/escape均保持回退。
- 下一步固定远端后主Agent独立第1轮审阅，实际耗时见原始日志与开发报告。整个Batch4仍未完成，不合并；无服务/API/真实业务图/Drive。


## 阶段77：普通调用者混合准入固定提交独立第1/3轮审阅通过
2026-10-31（北京时间）。固定fc12a03044ce8c4288d22d55a830a50ab3426a7a、tree83ea64223456c142fd58487957c6187e78226e42，468份文件blob核验，全部非review源码/测试齐全；262份无关历史review制品未恢复。主Agent未改生产，远端仅simple_python.py生产差异。
- 一次固定提交快回归+新mixed6项与历史独立29项，613 passed、25 skipped/35.66秒，退出0。仓库578，额外35，不与开发48重复累加。原基线3 failed/3 passed保留，修复后全部通过，无新增确认阻塞。
- 源码核查：完整上下文仅在capture_shape成功后传给私有helper，默认行为与公开API不变；真实module、AST、直接导出、精确导入绑定及普通函数体检查均保留，没有跳过危险provider或字典逃逸。图/SQL/模型身份/向量/Neo4j均未改。
- 实际公开build：0/20无关文件下仅解析A/B/C，缺key新增可沿两层调用者解析A/B/C/D；修改/删除、失败重试和保留旧版与独立full的公开、query/import及value表均相同。未支持provider/export/AST/重绑定/动态/条件/逃逸仍安全full。反向索引与watcher路径沿用并通过既有独立检查，未声称新SQL性能改造。
- 无API、服务、实际业务全图或Drive。本限定问题关闭，整个Batch4仍待更复杂函数值流、动态key等准入、Neo4j中间关系投影及真实业务整体验收，不合并。

## 阶段78：字典值流 Neo4j 投影开始（尚未提交，正式 review 0/3）

- 仓库 `agentic-trpg/local-code-tools`；分支 `feat/incremental-index-updates`；核对远端基线 `793ca38b6228d15047ed7eb2c69116ed61680fcc`。Batch4 继续，尚未合并。
- 本轮目标：把已认证 SQLite 中保存的容器、条目、绑定、赋值、读取及其已有函数引用投影到 Neo4j；通过官方只读 MCP 的明确查询模板读取，不新增自定义写 MCP。
- 设计：旧版四字段 v2 指纹和查询默认行为保持；有完整已认证值流证据的新快照使用显式 v3 投影，指纹同时覆盖值节点、边和读取订阅。旧版/部分证据明确标为未投影，不冒充完整空图。
- 已确定修改范围：neo4j_graph.py 导入/验证/分批写入、publication.py 发布绑定、official_mcp.py 定向模板及相应测试/文档。解析器、增量准入、搜索层级、向量不在本轮修改范围。
- 实现：既有开发子 Agent；主 Agent 负责契约、真实小型服务、固定提交独立审阅和推送。保留三轮上限/P0-P1 人工介入规则。
- 验证计划：旧 v2 兼容、v3 完整性/故障/重试/旧视图、已知 ID 与函数反向关系、官方 MCP 只读边界、实际 Neo4j 5.26 EXPLAIN/PROFILE 与无关数据扩容；快速全仓库回归。环境已找到既有 Neo4j 5.26.0 分发，真实服务尚未启动或验证。
- 不重建业务全图、不调用 API、不修改 Drive 包。本轮尚无测试结果，开发自测与独立 review 后分别追加。

## 阶段79：Neo4j 字典值流接线开发完成（本地冻结，未提交）

- 基线/分支同阶段78，正式 review 仍为0/3。开发子 Agent 已停止生产代码修改，待主 Agent 推送固定提交。
- load_snapshot() 在完整已认证记录上生成 v3 指纹；分批导入 LCTValue 节点及其关系，函数端点复用现有函数节点。发布前检查新增记录、边、端点、标签、订阅、数量和分块证据。
- publication.py 绑定实际投影格式/值流计数；official_mcp.py 新增明确值节点/值关系/分片只读模板。原代码图 v2 指纹不变，v2/v3 代码关系查询分离，完整旧 scope 不原地改成 v3。
- 开发定向：12 passed/0.62秒。真实 Neo4j5.26/APOC 提交前验证：7 passed/15.99秒；最后两项校验补充后定向复跑：6 passed/10.13秒。快速全仓库：581 passed、27 skipped/24.80秒（早于最后两项校验补充，固定提交后主 Agent 将再跑）。
- 独立指纹检查预检3 passed，仅确认反例可执行，不计正式 review。新增独立检查尚待在固定提交上完整执行。
- 变更：3个生产模块、3个文档、1个测试模块，另开发报告/日志/主 Agent 独立检查；实际差异统计见 value-projection-change-stat.json。
- 限制：仅投影既有已认证字典子集；未扩展解析器/准入/向量/搜索层级，未重建业务图或调用API。整个Batch4未完成、不合并。
- 下一阶段：推送并核对远端，按固定源码运行独立快速回归、真实服务、官方MCP及EXPLAIN/PROFILE。

## 阶段80：Neo4j 字典值流投影独立第1/3轮通过

已提交并推送 `4a2bcf827e33eb393de5b288260ee63321734dd9`，远端核对一致。480份文件按Git blob验证；生产代码由开发子Agent完成，主Agent只加独立测试/证据。

- 快速回归初次618 passed、30 skipped、1项环境失败（审阅副本缺少.venv）；补齐同一环境路径，失败单项0.25秒通过；全套复跑619 passed、31 skipped/37.25秒。历史失败日志保留。
- 真实Neo4j5.26/APOC环境定向集合13 passed/24.44秒（含6个离线用例），官方MCP实际读取成功、写入探针被拒绝。
- 实际bind_current/resolve_current、函数反向值关系及limit1分页1 passed/6.94秒；超大值节点按分片完整恢复1 passed/6.26秒。
- 真实EXPLAIN/PROFILE：0/1000无关节点，标记读取9 DbHits/1行/134字节，关系查询54 DbHits/4行/1582字节，首次/重复保持，无全标签或全节点扫描。仅同数据库另一namespace的扩容，不冒充业务规模。
- 已确认：完整v3指纹绑定所有值数组，别名/缺失key/读取订阅/现有函数端点未丢失，分批失败保持不可查询且可重试，旧图保持，v2查询与迁移兼容。
- 限制：现有已认证语法范围未扩大，真实业务增量及整流程恢复仍待Batch4验收，未重建业务图/向量或更新Drive。整个Batch4不合并。完整报告及原始操作符见value-projection-independent-review.md、value-projection-profile.json。

## 阶段81：当前真实源码回归诊断完成（无生产修改）

- 远端基线已核对 `32ffdac36e0037ee6c62a6f2917b5dba79145854`，分支 `feat/incremental-index-updates`，Batch4尚未完成、不合并。
- 本轮继续使用batch-dev-review、locality-review及项目Skill；开发诊断子Agent为GPT-6 SOL/medium，主Agent独立核对源码。保留既有各修复链的正式审阅轮次；当前诊断不冒充开发或正式review通过。
- 样例：SM固定提交a7b0804d5635e185a79ff3c1d1fa6241c2b858fe的availability.py、errors.py、item_units.py，校验源hash；不是最新业务main或完整业务库。
- 实际命令：python -m pytest -q review/batch4-incremental/test_actual_source_current_diagnostic.py -s；1 passed/1.37秒，退出0。临时修改availability中context=context为context=None；新旧记录与独立full一致、旧版本保持，但更新仍解析3/3文件、13site、30Jedi，未达到局部分析目标。
- 定位：simple_python.certify要求全捕获通过；python_incremental.prepare在进入反向索引闭包前即因整体证书缺失而退出。item_units单独通过v5，availability关键字专用参数/多层字段委派未认证；errors的dataclass、继承、property、注解及外部导入未认证。
- 更深缺口：实际Analyzer会读取调用者候选、字段/成员、继承、返回等信息，持久化analysis_reads目前只记录容器写入检查；不足以证明未认证文件可安全复用。不能删除全捕获门禁，也不能因已有CALLS/IMPORTS表就宣布所有隐含读取已覆盖。
- 已保存新诊断脚本、日志和结果，未覆盖历史证据。无API、业务源码修改、Neo4j导入、Drive或生产变更。下一步主Agent收敛可执行的最小依赖证明/接线方案，不直接向开发者派发泛泛的“扩展所有语法”。详见real-source-current-diagnostic.md。

## 阶段82：实际跨文件读取统一记录与消费者接线开发完成（尚未提交）

- 基线32ffdac36e0037ee6c62a6f2917b5dba79145854，分支feat/incremental-index-updates，当前新增读取记录整改链正式review0/3。开发者GPT-6 SOL/medium；主Agent未改生产实现。
- 新统一helper记录member-lookup（包括已知类缺失成员）、return-body、精确匹配后的parameter-origin和精确Jedi定义目标；consumer取当前求值作用域而非最外层调用，排除没有采用的候选，缓存命中也保留必要记录。
- Graph先完成值流证据计算再导出最终读取清单；SQLite使用schema2/partial，兼容schema1旧容器记录，拒绝未知kind。analysis_readers不再只读container-effects，实际prepare队列按已有索引消费全部支持类型。
- 未删除v5全捕获门禁，未把partial改成complete，未新增搜索/向量/Neo4j类型，没有修改调用目标/UNKNOWN规则。负Jedi查找、未来调用者集合和其他未覆盖读取仍是后续缺口。
- 开发定向150 passed；局部性集合7 passed，0/40无关记录查询均走覆盖索引、37 VM步；新增4项定向通过。最后快速集合593 passed、27 skipped/26.80秒。真实3文件诊断1 passed，仍full，未将其称为局部更新通过。
- 主Agent独立反例在固定旧源码5 failed/1.64秒；当前候选预检5 passed/2.27秒，尚不计正式review。
- 变更4个生产模块+1个文档，新增开发/独立检查、诊断和日志；统计见observed-read-change-stat.json。下一步推送固定远端并独立审阅，不合并整个Batch4。

## 阶段83：已观测语义读取记录独立第1/3轮通过

- 已推送并核对ea0d0563d19d50d1ee08efd889e583a614f072c1；506文件按Git blob验证，所需源码齐全；主Agent未改生产实现。
- 独立定向6 passed/2.54秒；最后快速集合633 passed、32 skipped/36.01秒，退出0。0/20无关文件公开更新仍只解析caller/provider，完整表记录与full一致，失败和旧视图保持。
- 初次对照1failed被保留：15回调对触发原有20k预算（旧代码同样触顶），不是固定K。只修正主Agent新增测试的无关数据构造，并保留步数断言，加入未触顶和相同匹配条数检查；没有改松生产断言。
- 实际SQLite反查：依赖表3->18条，匹配记录2条、返回文件1个、SQL1次、VM26步保持；覆盖索引SEARCH，无全表扫描。
- 新增读取在实际prepare闭包消费；schema1兼容、未知kind/截断拒绝、缓存命中保留依赖均通过。字段、返回值、参数来源记录仍是部分覆盖，没有开放任意业务模块复用。
- 真实SM三文件复跑仍full、3AST/13site/30Jedi，full一致且旧版保持；没有把这项当局部化通过。当前还需补未找到/未来调用者等完整依赖证明和分析单元准入，整个Batch4不合并。
- 附带修正文档将SQLite sidecar存储状态和可选Neo4j v3发布状态混为一谈的旧文字；生产模块不变。完整总结、失败原因、命令和证据见observed-semantic-reads-independent-review.md。

## 阶段84：常见Python规则扩展及候选上下文反例定位（未提交）

- 本轮基线已核对db4ec71a03403e7e7a3c01d0f9645e864b6b76ca，分支feat/incremental-index-updates。用户授权“好的 请继续更新”；目标是给真实三个文件中的安全常见写法建立局部更新规则，保留full对照与P0/P1/三轮上限，当前正式review0/3。
- 开发子AgentGPT-6 SOL/medium。初始v6结构规则能够认证三文件并只解析availability，但full对照的一个site证据不一致：局部trace3步、full16步，coverage缺口重复量不同。候选未推送，未删除证据字段来制造通过。初始失败材料保存在common-certificate-initial-counterexample.md及初始日志。
- 根因定位为参数/接收者分析遍历整份候选调用位置，导致不连通模块中的候选检查被混入关联证据。主Agent限定方案：只有实际整批AST通过闭合语法认证时，才按精确捕获导入关系建立双向模块组件，并对普通候选与构造器兜底使用同一组件范围。未认证/不明确情况保持原全范围行为，不按同名猜测、不忽略unknown。
- 初步原型现在0/20无关文件均只解析availability一个文件，复用其余2/22文件，与full节点/边/site证据相同；尚待边界、失败和独立固定提交审阅，不构成通过声明。
- 未修改业务源码、未调用API/Drive/Neo4j服务；本轮仍在开发，不合并Batch4。

## 阶段85：v6常见写法与认证组件候选索引首版开发完成（未提交）

- 仍基于db4ec71，分支feat/incremental-index-updates，当前正式review0/3。新增有边界的关键字专用参数、标量注解/默认值、self字段链、冻结slots标量dataclass、直接Exception子类/super初始化与只读property；原严格及字典路径保留，证书升级v6。
- 只有实际整批AST通过闭合认证，Graph才建立精确导入连通组件；参数候选与构造器兜底用同一组件。未认证时保持原全候选行为，不删UNKNOWN或关联证据。完整性反例经此定位修复，真实三文件节点/边/site证据完整对照通过。
- 同时修正新准备成本：每个组件BFS一次、共享冻结成员集合；候选索引先与组件位置集合相交再合并/排序，构造器不扫描整份site；认证的命名空间/影子上下文只准备一次。0/200无关调用位置的GuardList证明已使用索引，未通过全量过滤冒充局部。
- 开发最后快速集合596 passed、27 skipped；真实0/20文件变化只解析1个、复用2/22；新增真正的调用者则解析2个，errors修改及不安全形式回退对照通过。尚未独立审阅。
- 提交前主Agent另要求三项收紧：全部catalog Python模块必须参与AST证明，COMMON禁止模块魔术定义，显式拒绝未支持的Python3.12类型参数。这是待完成的提交前修正，前述596不冒充已覆盖这些后续行。
- 独立旧基线实际两个真实局部更新反例均因旧v5证书失败，原始日志common-certificate-baseline-independent.log保留。主Agent已准备独立真实/回调/影子/候选局部性/失败恢复/full完整记录对照。当前不合并、无API/业务源码/Drive修改。

## 阶段86：提交前三项安全收紧完成（未提交，正式review0/3）

- 完成全部catalog Python模块参加证明、模块魔术定义拒绝、函数/类非空type_params拒绝；直接形参callback()作为调用目标允许，任意形参对象字段访问仍拒绝。
- 开发定向与主Agent反例预检合计33 passed/7.21秒；主Agent自己另跑11项独立预检全部通过/3.34秒。早期596全套通过发生在这些最后修改之前，固定远端后将由主Agent完整复跑，不挪用旧证据。
- 已冻结生产文件4个：simple_python.py、python_analysis.py、graph.py、storage.py；另文档、common规则测试及报告/日志。实际统计common-certificate-change-stat.json。主Agent未改生产实现。
- 明确范围：关键字专用参数/关键字标量默认值、标量内置名/None注解、受限self字段链、精确冻结slots标量dataclass、直接Exception/super初始化、只读无调用property。不是任意继承、装饰器、反射、泛型或函数默认工厂的准入。
- 下一步推送、核对远端并独立审阅，包括完整表证据/full/旧视图/失败恢复、跨文件回调、标准库影子、0/200候选索引和共享组件结构。不重建业务全图或调用付费API，Batch4尚不合并。

## 阶段87：常见规则远端固定后独立第1/3轮通过

- 开发已推送，未合并：分支feat/incremental-index-updates，提交07b6b6c48d7921f2802c00ef62192e849e2371eb，tree ca228fab009ddf7bc563d66c02a51913428d8051；基线db4ec71a03403e7e7a3c01d0f9645e864b6b76ca。主Agent独立审阅，未修改生产实现；534个恢复文件与远端Git blob一致，262个无关历史review制品未恢复，生产和所需测试齐全。
- 固定远端快速回归及独立边界665 passed、32 skipped/46.06秒，退出0。独立11用例包含在合计内，不重复相加；31跳过需Neo4j，另1为可选旧缓存，本轮未启动服务。测试后源文件再次核对无变化。
- 真实SM固定a7b0804三个文件的局部退回问题在此范围内解决：只改availability实际只调用python_nodes一次、复用另2个；增加20无关文件仍只解析1个/复用22个；有真正导入调用者则解析2个。错误类默认值及跨文件回调更新均与full全部语义表相同；发布失败保留旧版、重试和不变捕获通过。
- 关键原因为扩展语法本身不足以证明局部候选上下文；现已认证捕获的full/local共用精确显式导入组件，参数与构造器使用索引。0/200无关调用位置禁止全表遍历，实际按组件读取3*K；未知新增位置保守回到原完整候选。未删除UNKNOWN或证据字段。
- 原语法首版full不一致、兼容断言失败及修复记录均保留；旧test_actual_source_current_diagnostic.py是v5回退历史快照，不作为v6新断言执行，以新真实局部/full完整记录对照取代，详细说明见common-certificate-independent-review.md。
- 本切片第1/3轮通过；当前无确认阻塞。未改业务库/值流schema/Jedi，未调用付费API、Neo4j/MCP或Drive。下一步扩大到实际关联文件并记录剩余精确回退，再做Batch4完整发布/检索/恢复验收；尚不合并。

## 阶段88：扩大真实关联代码，先完成九文件准入诊断

- 远端分支feat/incremental-index-updates与上轮报告提交7b08cf6340a120d8773992847915327e61f0d3d2一致，生产基线仍07b6b6c。开发子Agent GPT-6 SOL/medium限定诊断、主Agent核对；未修改生产实现。
- 从同一SM固定a7b0804提交取得_execution、combat、dnd_runtime、item_package、service、world_containers六文件；逐个Git blob/SHA256与长度核对一致，保留provenance。加原三文件组成九文件部分捕获，不声称完整应用。
- 只读AST+Graph解析器+certify审计：九文件整体不认证，仅原三个分别认证。service第13行正确定位availability，item_package第6行正确定位item_units；rules_adapter等未捕获依赖保持boundary。共记录66个相对导入名称请求，不称66条都已解析关系。命令及结构化结果在actual-related-admission-audit.md/json与baseline.log；未启动Graph.build/Jedi或执行业务代码。
- 相对导入不是解析器不会：Graph.import_request_module已有规范化；simple_python两个谓词和component_policy仍直接拒绝/忽略level，prepare新增导入闭包只处理level0。其余外部依赖、枚举、联合注解、模块赋值、分支循环、装饰器及多重继承独立存在，不能只改相对导入就宣布这九文件能局部化。
- 下一步限定B4-REL-01：复用既有规范化结果接通严格/常见语法认证、组件与更新闭包。仍要求精确捕获provider/导出和合法层级，缺失/外部/星号保持拒绝，不改Jedi或广泛语法准入。验证双向实际相关选择、新导入切换、0/20无关文件、full全部语义记录、失败旧视图及非法边界。正式review0/3；无API/业务图/Drive/合并。

## 阶段89：相对导入认证/组件/新增依赖闭包开发完成，未提交

- 开发子AgentGPT-6 SOL/medium，基线7b08cf6340a120d8773992847915327e61f0d3d2，当前正式review0/3。仅改生产simple_python.py和python_incremental.py（+26/-10），新增相对导入测试143行、文档2行及证据，详细统计relative-import-change-stat.json。
- 严格/常见语法认证、组件和prepare均调用Graph.import_request_module取得完整请求，再沿现有精确捕获/pin解析。新引用provider及package上下文实际入队；不把相对dataclasses当stdlib，未改Graph/Jedi/value_flow/schema或v6常量，program_hash门禁保留。
- 开发先失败3/通过5，修复后定向12 passed、相关69 passed，冻结后快速615 passed/27 skipped/34.43秒，退出0。主Agent独立旧基线5 failed/6 passed/1.38秒，独立新增测试尚未作为通过证据。原始日志均保留；不同命令存在重叠，不累加。
- 覆盖.与..、别名、provider修改/新增provider、新旧版本和发布失败、0/20无关文件实际两文件解析、fresh full语义对照；from . import、star、越界、缺失provider、伪stdlib、相对字典仍拒绝。开发9文件诊断结论不因本小修改变：仍不认证。
- 下一步主Agent预检、提交推送、固定远端后的独立快速回归与反向查询索引/全部语义表验收。无付费API/完整业务图/Drive，未合并。

## 阶段90：提交前独立预检与测试材料补齐

- 生产实现保持冻结。主Agent12个独立用例预检通过/2.67秒，含旧基线5个失败能力断言、6个拒绝边界和新增索引读测试。尚未正式远端review，0/3。
- 性能用例首版1失败/11通过：误要求同库首次与重复读VM步骤相等，实测21/16。保留原用例/日志，改为分别比较冷/热路径在0/20组无关相对导入增长时计数不变，并保留重复读稳定和每次1条定向SQL/1行断言；不是改松无关规模门槛或修改生产。
- EXPLAIN证明已知完整模块pkg.base的逆查走索引SEARCH、无SCAN；逆查只返回mid。构造FileDependencies的全artifact完整性检查单列为必要准备，没有称整个build常数成本。
- 提交前发现staging遗漏原远端tests/test_dictionary_import_receiver.py；从上轮Git blob校验副本恢复，字节仍与原远端一致。开发615通过发生在少此文件的目录，不称完整远端集合；现在补跑补齐后的tests，结果另记。材料问题不算生产缺陷或完成正式review。
- 除获准两生产模块和文档外现有lct/tests/docs均与旧远端一致。原未跟踪file_incremental.py、历史graph_under_test.py不提交。下一步补齐门槛后推送和固定远端独立审阅；无API/全业务图/Drive/合并。

- 补齐原测试后的提交前快速集合完成：**618 passed、27 skipped/34.29秒，退出0**，日志relative-import-restored-fast-suite.log；较开发原目录增加3项原有测试，全部通过。生产未再改，准备推送。
