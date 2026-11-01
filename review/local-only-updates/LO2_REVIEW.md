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
