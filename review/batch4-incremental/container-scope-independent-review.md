# 局部容器写入候选索引：独立审阅第1/3轮

固定生产提交eb5ff65f0f236f898b4f2a055e079c6b8d75cfd6，分支feat/incremental-index-updates，远端SHA已核对。405份支持文件按远端Git blob匹配，全部非review跟踪文件可取得且一致；未包含旧file_incremental.py草稿。

结论：本次限定候选索引修复通过。保留前序审阅历史；整个Batch4仍未完成、未合并。

## 独立验证
固定提交快速仓库回归+新增独立反例+历史副作用/类/增量反例：563 passed、25 skipped，30.89秒，exit0。日志container-scope-root-fixed.log。25项跳过为服务/环境条件，不能当作Neo4j服务验收。

四项新独立用例单独输出计数：4 passed/0.39秒，包含在上述563项内，不相加。日志container-scope-root-counters.log。
- 从实际Graph.build进入Analyzer.container_slots，包装调用原始实现、记录EffectCatalog.before实际访问，不替代结果。0/30无关局部alias写入函数下，实际访问始终只有B.run与B模块2个scope、共3事件。固定B源码身份时B完整site记录相同，不仅比较target或计数器。
- 导入registry的别名写入仍保留other候选及UNKNOWN；local先为fresh literal再改绑到传入参数仍保留影响；动态键和嵌套闭包不能进入已证明隔离集合，原检查继续保留。
- 开发公开storage.build的0/20/100计数另外核读：准备scope0/20/100、目标候选2/2/2、事件3/3/3。主Agent独立实际调用计数与其一致；没有把一次准备或全量建图成本说成常数。
- 同源整图复用四个本次执行计数为0且sites不变；相关普通增量/类/参数回调历史反例通过。

旧实现独立基线1 failed、2 passed/0.53秒，失败为30个无关writer进入B的检查；两个相关写入对照通过。日志container-scope-root-baseline.log保留。本轮固定候选审阅未发现需要修复的回归。

## 根因与实现检查
此前container_slots每次直接遍历effects.slot_scopes全体，包括显然仅修改自身fresh literal的函数，并把无关NO_EFFECT写入B证明。现在初始化一次分类：仅完整scope能够证明fresh本地literal+顺序别名+常量键值、不逃逸时按已有容器来源身份入桶；其余scope保留fallback。查询取target桶、fallback、当前scope和owner；没有先对全集调用resolve/Jedi再过滤。原事件顺序、UNKNOWN和副作用处理未改。

静态准备按scope/直接语句一次处理，没有在每个查询中重建索引。新统计从真实循环计数；storage._reuse_python_graph复用路径清零本次执行量，局部graph的计数只代表该次选中的组件。

## 限制和下一步
这里只排除已证明与目标无关的局部literal写入；模块全局、参数、导入、未知调用、协议、控制区域及逃逸等仍可能进入较大的fallback候选集合。未宣称所有容器检查都已局部化。

simple_python.certify及python_incremental.prepare的整批准入限制未改变；真实完整业务仓库的依赖驱动局部更新仍未验收。后续需持久化必要分析依赖与不确定范围，并据此接入准入/复用；不能直接删除认证门槛。没有真实全库建图、付费Embedding、Neo4j服务、Drive或业务仓库修改。
