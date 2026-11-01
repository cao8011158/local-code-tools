# LO-2 独立审阅，第1/3轮：需要修改

检查远端提交 `40a53497ee93ec265887c2b9d1b8347f921cf5f5`（tree `512927e6c1b7f08780c8249f70ce0b4dffbbae76`），基线 `8fef684ac0491e2be34601ed2979a2edccacfa9b`；目标 `feat/local-code-tools-import` 仍为 `e3db45fcf1362f0a26e0ab7760b12b4fd408ce64`。486个物化文件逐一匹配远端blob，另添加一份root独立namespace反例作为外部审阅harness，不改变被测生产源码。实施者与主审独立。

独立固定副本运行主快速套件和root语义/行为控制：**724 passed /2 failed /27 skipped /1 deselected /100.98秒，exit1**；另两项namespace反例均失败/0.99秒。开发者此前699/254通过保留为其当时自测；新审阅反例不得倒写为已通过。

## 已验证行为

warm没有转入无selected_owners的冷引擎；普通/未知回调、实际存储写入→getter返回→终端调用、有效partial值流、截断初次分析、文件/定义增删、包导出、缓存损坏/版本不兼容保留旧current等既有控制通过。图目标、UNKNOWN与来源事实回归通过；生产冷建图确实使用全部新owner的同一候选索引路径。首次83文件/规模未由本轮证明。

## LO2-OWNER-GRANULARITY（P2，当前LO-2引入，阻塞）

provider.work函数体修改；consumer.run调用work，consumer.unrelated只调用other.leaf。期望仅重新分析run及必要模块元数据，实际unrelated也被选择/查询。模块顶层import、函数内部import均复现。另新增provider.later定义/新增provider模块两种情况，只有run消费later，同文件unrelated仍被误选。四个反例调用目标均正确；问题是违背批准的具体消费函数粒度，而不是调用边缺失。

根因：changed-file种子含module；expand_dependencies对任何selected module无条件调用importers/requesters，再将这些文件的全部new_trees加入集合。相同宽化也存在初始namespace请求者筛选；selected模块不等于命名空间输出改变，文件级请求者不等于该文件所有函数都消费目标。循环内反复扫描所有new_trees也使索引消费者退化。

修复要求：区分文件重新解析种子、具体producer变化、namespace/binding事实失效；普通函数体变化沿unit支持/读取定位消费owner。新增/删除/重导出/负查找用实际绑定/请求点对应owner，不按整个导入文件重算。复用缓存AST/来源位置补齐必要import消费信息，并建立一次性的owners_by_file/module定位表，禁止每个namespace循环扫描全集。保留budget0存储分离/参数写入和pin两向变化，不以放松无关函数断言修复。

尤其要继续支持函数内import：部分owner更新时，旧import_requests没有owner位置，当前mixed-import-request-order保护不能靠选中所有同文件函数规避。应保持未选函数的请求支持，仅替换受影响请求；若需规范化私有物理ordinal，必须在冷/热两条生产出口一致规范化并证明绑定结果/查询消费者不依赖其顺序，保留全部实际请求与来源关系。

源码docstring/注释仍有“ordinary full build runs / falls back to full”旧描述，应随修复改为当前局部策略，避免误导后续维护；不改写旧审计历史。

当前无已确认P0/P1或外部核心故障。LO-2正式用1/3轮，修复后进入第2/3轮；暂停依赖本批的LO-3验收和合并。已有LO-1审阅保持通过，其历史不重置。


# 第2/3轮：需要修改

固定远端 `ee19b841cc0012ddaeab2d22e83c81183b8d5d25`，tree `005826290e0c445ea5bf327f33f9703fb6c381e8`；父提交为第1轮候选。508物化文件初始blob核验，生产源码随后保持不变；root定义上下文harness补充一例并修正一个不成立的预期，作为外部审阅测试执行。

主快速+root已有控制 **730 passed /3 failed /27 skipped /1 deselected /114.41秒，exit1**。随后fresh核对并纠正默认参数断言后，四个定义上下文变体 **4 failed /1.89秒**。原始错误断言/失败日志与更正均保留，不能把不支持的前端精度当成局部问题。

已确认第1轮普通函数体、顶层/函数内导入、负查找、简单别名和原无关默认回调反例通过；owner/site/绑定/ordinal处理有效，原先文件级fanout已移除。

## 仍阻塞：两项实际漏更新和两项过度选择

- **LO2-DEFINITION-PHASE**：缺失provider出现后，类体方法默认值`cb=first`的`Runner REFERENCES first`在局部结果缺失，fresh存在。该方法`cb()`在局部和fresh均UNKNOWN，最初要求其必须CALL first的断言无效；已删除这个错误先验，保留真实引用边检查，fresh JSON证明local无Class reference而fresh有。原因是_loaded_names跳过整个嵌套FunctionDef，把应在class中执行的默认值/装饰器等header也跳过；方法被选中但class执行owner未选中。
- **LO2-CLASS-RECEIVER**：`Runner(Base).run -> self.handle()`初始Base缺失，新增provider.Base.handle后，namespace选择Runner类，但既有Runner.run不选。fresh调用目标为Base.handle，局部仍空。缺少“方法的隐式receiver/MRO依赖声明类上下文”的实际调度消费；仅按函数体出现Base这个名字无法发现。必须记录/消费类→方法分析上下文依赖（可用既有结构/来源机制，不是伪造CALLS），包括未知/预算截断时的前瞻覆盖。
- **LO2-OWNER-GRANULARITY继续开放**：全局import later出现时，函数内`later=other.leaf; later()`因同名被误当全局绑定消费者；名称筛选未处理Python函数局部参数/赋值/导入遮蔽。另`registry={'go':later}; run()->registry['go']()`旁边的`unrelated(fn=other.leaf):fn()`仍因ModuleC默认来源支持而被选择；模块某个binding变化不等于所有default/source site变化。容器消费者应更新，但其他来源的支持需保留。

明确修法：按现有Analyzer.inventory/header的执行阶段收集嵌套def的header到正确owner，独立处理函数body自由变量与编译期局部绑定；namespace消费者不要按单纯同名/整module支持选择。类解析上下文变化要沿显式上下文关系影响实例/类方法的receiver解析，保留open receiver UNKNOWN，不升级Jedi或强行给未观测方法默认调用添加target。Source支持按具体producer_site/表达式绑定证明是否受影响，既保留其他来源，又不把registry等组合值的依赖截断为只支持Name直接别名。

当前无P0/P1或外部核心缺陷确认。LO2正式已用2/3轮，下一轮为第3/3轮；依赖本批的LO3与合并继续暂停。各编号不重置轮次，原红例/错误测试预期/前序通过全部保留。

## LO-2 formal review 3/3 — passed

- Fixed remote `f13f934984f834ef957198c1782c36f85beda8de`, tree `c5ec6f28df739099c680eeb97d3e5545598469c0`, parent `ee19b841cc0012ddaeab2d22e83c81183b8d5d25`. 536 materialized files independently matched Git blob SHAs; 653 historical remote paths were not materialized and are preserved in the base tree. Frozen review directory `lo2-review3-fixed`; no production edits by reviewer.
- Reviewed the entire LO2 production delta (storage routing, initial all-owner seeding, owner import-site records, namespace invalidation, positive partial flow witnesses, limited-graph subscriptions, selected-source replacement and class/closure receiver context) as well as the tests/contracts. Normal warm build calls only the owner path. Incompatible/corrupt cache raises a clear error preserving current. UNKNOWN and analysis_limited are retained.
- Independent command: `.venv/bin/python -m pytest -q tests review/local-only-updates/test_semantic_contract_independent.py review/local-only-updates/test_local_only_flow_independent.py review/local-only-updates/test_namespace_granularity_independent.py review/local-only-updates/test_definition_context_independent.py --deselect tests/test_batch3_actual_acceptance.py::test_nine_original_bytes_limited_graph_bm25_and_attached_real_usearch --tb=short`. **741 passed, 27 skipped, 1 deselected, 108.51s; exit 0**. Raw `lo2-review3-root-suite.log`. This is an independent rerun, not additional 741 distinct cases.
- LO2-OWNER-GRANULARITY, LO2-CLASS-RECEIVER and LO2-DEFINITION-PHASE resolved by their original and root-cause variants. Unrelated same-file functions/defaults stay unselected; missing base now updates inherited method and returned lambda to Base.handle; class default REFERENCES updates; local/nonlocal shadow stays separate. The invalid earlier default-body assertion remains corrected against fresh UNKNOWN; no diagnostic-to-CALLS conflation.
- Required real83/end-to-end/scale validation is next LO3. This pass does not claim whole-project precision or all costs are local, and does not authorize merge. Reviews 1 and 2 and original logs remain unchanged.
