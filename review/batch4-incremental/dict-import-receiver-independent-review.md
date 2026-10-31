# DICT-IMPORT-01 独立审阅，第 1/3 轮

2026-10-31（北京时间）。结论：**限定导入映射修复通过；Batch 4 整体仍未完成，不合并。**

固定远端提交 `ad5b96c12e8b4ae362985bff9db69b4c7ee4d767`，父提交 `d455ec3710f3c3bc5ec385c76db94a8cc3ce38f9`，tree `deff0ac83d7aafe260574e1c19466bb73e839954`，分支 `feat/incremental-index-updates`。主 Agent 独立审阅开发子 Agent 的实现，没有修改生产实现。439 份审阅文件按远端 Git blob 校验，全部生产、测试材料齐全；262 份无关旧 review 制品未恢复。

## 问题与修复

发现于 Batch 4 字典增量切片，属于前序 Python 解析工作，编号 DICT-IMPORT-01，P2。它把确定的跨文件字典调用保守退为 UNKNOWN，未发现错误的 complete 认证。本 step 内按用户“继续”授权回溯修复，暂停依赖它的 v5 草稿；未丢弃草稿或重置历史问题的审阅次数。本新缺口的正式审阅为第 1 轮。

`from a import registry` 的 Jedi goto 指向 `registry['go']=second` 中接收者的 token。旧 `Analyzer.map_name()` 只识别 Name 赋值目标，不能将此 Subscript 接收者映射回创建的字典。Jedi 对最终调用已经找到了 second，LCT 自己的容器来源校验却丢失，导致 UNKNOWN 和未裁决冲突。

新分支仅在捕获文件、名称、行、UTF-8 列准确匹配，且接收者是 Subscript 的直接 Name、匹配唯一时，解析**写入之前**的绑定；只有唯一、无未知且依赖证明完整的 literal Dict 来源才接受。未知、歧义、自定义下标和非字典仍保持不确定。既有 Name 赋值映射不变。没有把写入值 second 当作字典，也没有仅凭字符串名字连接函数。原 `container_slots()` 和调用裁决继续负责计算目标、写入顺序和 UNKNOWN。

本改动沿用现有 captured-assignment 映射路径，没有宣称消除该路径原有的模块候选遍历；本轮是语义修复，非新的局部查询性能验收。没有修改 SQL、图 schema、MCP、Neo4j 或向量逻辑。

## 独立验证

| 检查 | 结果 |
| --- | --- |
| 未修复基线独立反例 | 3 failed、2 passed / 0.41 秒：直导入、别名、Unicode 失败；条件与自定义下标对照原已通过 |
| 未提交修复副本独立预检 | 5 passed / 0.41 秒，不冒充远端提交验证 |
| 固定远端快速仓库回归＋独立反例 | **565 passed、25 skipped / 24.82 秒，退出码 0** |

远端验证命令：`.venv/bin/python -m pytest -q -rs tests review/batch4-incremental/test_import_receiver_independent.py`，工作目录为按远端哈希建立的 `lct-import-receiver-review`。原始日志 [dict-import-receiver-independent-suite.log](dict-import-receiver-independent-suite.log)。565 包含新增独立 5 项，不能再与前述计数相加。25 跳过为 24 项需 owned Neo4j 服务、1 项需可选真实缓存；本轮未启动服务或使用真实业务图/API。

独立反例确认：导入及别名能得到 second；中文变量与同文件另一个字典不混淆；条件写入仍保留 first/second 候选及 UNKNOWN；自定义 __getitem__ 不被认证成普通字典。开发测试另覆盖重绑定与序列排除。未修改历史断言让测试变绿，无确认新增阻塞。

## 后续及未完成项

这修复了具体的跨文件容器来源映射，不等于所有动态导入/字典别名都完整支持。字典节点、条目节点、赋值/读取支持及其增量选择仍是另一个未完成切片；本提交没有新增这些生产图节点，也没有开放 v5。原来“同文件优先”的临时验收收窄不能替代最终跨文件目标，现在应在恢复草稿后重新纳入原 A/B 案例。

未完成草稿保留原位，另以 `dictionary-v5-incomplete-draft.patch` 与同名 JSON 描述保存为**审阅目录内恢复材料**，未放入生产路径，未认证为可用实现。它缺接线和测试，恢复前必须在本修复上重绑定/合并，不能覆盖新映射修复。原跨文件/同文件局部更新失败日志继续保留；本轮不将它们改写成增量验收通过。
