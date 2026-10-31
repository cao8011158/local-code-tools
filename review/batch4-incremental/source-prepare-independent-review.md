# Batch 4：同 Python 捕获复用，独立审阅第 1/3 轮

2026-10-30。固定实现提交 `9e8dbb34a5f99788351a91b918fd3cc57ff7945a`，本切片基线 `71da2eea831f6358287bc931e757851187ef8525`，分支 `feat/incremental-index-updates`。独立审阅者为未编写生产实现的主 Agent；开发者为 GPT-6 SOL medium。此前实验及依赖索引审阅历史不变。本次通过限定范围，不是 Batch 4 最终验收或合并许可。

## 结论

未发现本切片的阻塞缺陷。`build → _reuse_python_graph` 在全量 `extract` 之前判定；仅在 Python 文件集合、内容及所属仓库捕获身份保持相同，并且程序、配置、运行时、绑定和旧产物完整性匹配时复用。Python 源码改动、同代码仓库文档改动、旧格式缺少证据、旧证据损坏等情况保留完整分析路径。独立文档仓库变化和输入未变可以跳过 Python AST/Jedi 分析。

`split_graph` 新增 `node_order`，保留提取顺序，而非依赖 SQLite 行顺序。复用旧 Python 节点、非所属关系、sites、查询观察、导入依赖及请求；重新提取文档和构造所属关系。不重新绑定旧 Python 版本号，因为准入要求其版本身份本来就相同。旧版本不变，已有候选校验和原子发布流程保留。

## 固定源码与验证

独立副本 `/workspace/scratch/413372d9a5a5/lct-source-review`；164 个代码、测试、配置及历史支持文件逐项计算 Git blob SHA，与远端固定 tree 一致，测试后复核无差异。

命令：
```
/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python -m pytest -q tests review/batch4-incremental/test_source_prepare_independent.py
```

最终一次完整运行：**511 passed、25 skipped，18.47 秒，exit 0**。原始日志 `source-prepare-root-final-tests.log`。25 个跳过项不作为通过，未运行真实 Neo4j 或真实规模验收。

首次运行 2 failed/509 passed/25 skipped，因隔离副本遗漏 tools 与历史实验脚本；补文件过程中一次复制因冻结 graph_under_test.py 字节与远端不符而停止，紧接的第二次运行仍缺 v5.py（1 failed/510 passed/25 skipped）。最终从远端恢复准确文件、补齐全部支持脚本后重新跑完整套件。保留 `source-prepare-root-tests.log`、`source-prepare-root-complete-tests.log`；前两次不作为生产缺陷或通过证据。

## 独立边界证据

| 公开路径及输入 | 实测与断言 |
| --- | --- |
| `build`，独立文档仓库修改，代码库有 1 / 21 个 Python 文件 | 两组均 0 次 `python_nodes`；完整构建对照分别实际解析 1 / 21 个；节点、边、sites 全字段一致 |
| 同样输入，`fail_at=before_publish` | 当前版本指针仍为旧版本，旧节点/边/sites 完整不变；重试成功 |
| 同一代码仓库内 Markdown 修改 | 回退，实际解析该 Python 文件；新的节点/边/sites 与完整构建一致，旧版本不变 |
| Python-only 仓库先 prepend 函数完成全量更新，再改独立文档 | 复用生成的完整 embedding 输入列表与全量构建完全一致；仓库节点和所属关系没有遗漏 |

独立检查使用包装计数并继续执行原函数；无 provider 请求。开发测试另用拒绝调用探针确认命中路径不执行 `Graph.build`，覆盖 Python 编辑/增删、损坏 graph sidecar、私有导入/观察证据和旧版本；主 Agent 已阅读并在固定提交中复跑。

## 局部性与剩余范围

这里节省的是 Python 解析、AST/Jedi 上下文构造和关联分析。源 inventory、一次构建准入中的旧产物完整哈希/读取、完整节点边装配、向量输入生成、SQLite 对账及完整输出仍随输入或输出规模增长；未将这些标为局部查询。`incremental.analysis_scope` 明确记录模式、回退原因、解析/context 数、复用数与输出规模。`jedi_queries` 表示已复用分析中的历史查询总量，`jedi_queries_executed` 与关联执行量在复用时为零。

这一切片不使用文件依赖闭包来处理已改变 Python，也不启用 `file_incremental.py` 草稿；纯文档项目仍走原有完整路径。代码改变后的局部重分析、跨版本身份重绑定、真实图/索引统一增量发布及恢复验收仍未完成。没有调用 Voyage、启动 Neo4j、修改真实索引或 Drive 包。

下一步：接入 Python 变动的受影响文件选择与复用，继续以全量分析作独立对照，并单独统计必要的完整输出成本。不能据此次 511 项通过宣布 Batch 4 完成。
