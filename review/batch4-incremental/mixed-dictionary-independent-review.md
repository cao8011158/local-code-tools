# 字典模块与普通调用者混合准入：独立审阅第 1/3 轮

2026-10-31（北京时间）。结论：**限定修复通过，Batch 4 尚未完成，不合并。**

固定远端提交 `fc12a03044ce8c4288d22d55a830a50ab3426a7a`，父提交 `f86acd211948b53f13e8eccb8605b24e31a4b7ae`，tree `83ea64223456c142fd58487957c6187e78226e42`；工作分支 `feat/incremental-index-updates`。主 Agent 独立审阅开发子 Agent 的实现，未修改生产代码。468 份副本文件与远端 blob 一致，所有生产/测试源码齐全；262 份无关历史 review 制品未恢复，不影响本轮验证。

## 根因与修改

此前结构验证已认可 A 的字典和 B 的读取，但 `_certify_v4(plain_files)` 把普通模块列表 C/D 当成所有可引用模块。普通 C 从 B 导入 run，因为 B 不在 plain_files 而被拒绝，导致整批缺证书、更新退回 full。已有调用边和反向索引不是本问题的缺口。

生产只修改 `simple_python.py`：私有 helper 增加 `selected_context=None`，默认仍使用自己的 files；只有 mixed 分支先通过 `capture_shape` 后，才传入本次实际捕获的完整 Python 模块上下文，继续只检查普通模块的函数体。目标模块、实际 AST、直接 FunctionDef/ClassDef 导出、Graph 精确导入/绑定和原有函数体检查保持。公开 certify 接口、CERTIFICATE 版本、解析器、value-flow 模型、schema、SQL、Neo4j 和向量未改。没有伪造 AST、跳过 provider 或把字典对象当成普通可调用导出。

## 独立验证

未修复基线：**3 failed、3 passed，1.87 秒**。失败为 0/20 无关文件下 A/B/C 局部更新及双层 C/D 调用者；逃逸、缺 provider 和缺 export 的拒绝对照原已通过。原日志 [mixed-dictionary-baseline-independent.log](mixed-dictionary-baseline-independent.log)。

固定提交命令：`.venv/bin/python -m pytest -q -rs tests review/batch4-incremental/test_mixed_dictionary_independent.py review/batch4-incremental/test_dictionary_flow_independent.py review/batch4-incremental/test_dictionary_local_independent.py review/batch4-incremental/test_value_index_independent.py review/batch4-incremental/test_import_receiver_independent.py review/batch4-incremental/test_changed_python_independent.py`。

结果：**613 passed、25 skipped，35.66 秒，退出码 0**。仓库测试 578 项，额外独立/历史检查 35 项。不能再与开发者 48 项或旧结果相加。25 跳过为 24 项需 owned Neo4j、1 项需可选实库缓存；未执行服务或真实业务全图验收。完整日志 [mixed-dictionary-independent-suite.log](mixed-dictionary-independent-suite.log)。

| 验证 | 结果 |
| --- | --- |
| A 字典目标变化，B 读取，C 普通调用 | 0/20 无关文件下只解析 A/B/C，未重解析无关 producer-only 字典 |
| 缺失 key 新增，两层普通调用者 | 只解析 A/B/C/D，结果与同捕获 full 相同 |
| 多代删除与发布失败 | 旧指针/记录保持，重试仍局部，结果与 full 相同 |
| 完整结果对照 | catalog nodes/edges、sites、import/query 证据、value_nodes/value_edges/value_reads 均一致 |
| 不支持路径 | 缺 module/AST/export、字典逃逸、provider 重绑定、动态/条件写入仍 full 回退 |
| 原行为 | 既有字典、别名、回调、索引与旧视图独立检查全部通过；默认 helper 行为未改变 |

本修复没有改数据库语句或查询结构；实际范围证据来自公开 build 的 extraction 调用计数和全表语义对照。已有真实索引/分页独立检查在固定提交上复跑通过，不将它称为本轮新增索引优化。必要 inventory、既有完整性校验和输出序列化仍可以是全量工作。

## 裁决与剩余工作

未发现本轮新增确认阻塞。原来的 mixed 普通调用者限制已在上述范围内关闭，不再把它当成所有 C/D 都必须 full 的限制。没有改旧行为断言来制造通过；未运行 API、服务、真实业务仓库建图或 Drive 操作。

这不扩大到任意 Python 语法：动态/数值 key、复杂写入、其他函数值传递结构仍有准入边界；中间关系尚未投影 Neo4j/MCP，真实业务端到端增量、发布和恢复仍待 Batch 4 整体验收。当前分支继续保留，不合并。
