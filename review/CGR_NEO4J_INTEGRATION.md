# CGR / Neo4j 与 LCT 整合验证（2026-10-27）

这是**本地实现验收记录，不是独立代码审阅结论**。本轮只使用小型合成 Git 仓库、专用 Windows
原生 Neo4j 和隔离检索目录；未扫描或重建三个业务库正式索引。没有付费 Embedding / LLM 请求。
最终提交 SHA 在交付回复中列出，避免把自身提交 SHA 写入提交而循环依赖。

## 基线、代码绑定与修改边界

| 仓库 | 基线 | 工作分支 | 状态 |
|---|---|---|---|
| code-graph-rag | `4686c82b53b6745acd3a760599cb94d709a9ba79` / 0.3.18 | `fix/python-call-graph-accuracy` | 修复提交 `896c037f1a09cb8cdb3928204c9cd62a34887f20` 已先行推送 |
| local-code-tools | `9d5a54f9f8ecdd6f5ce6349a916c03522a1453a7` | `feat/cgr-neo4j-integration` | 在该基线增加独立 profile；包含此前上传实现，未退回旧审阅提交 |

LCT 的运行代码、测试和独立环境锁文件内容指纹：
`00047621c8fb061386c639c2d282664af3fe86106578993830f419b26b3d7f74`。
逐文件 SHA-256 见 [紧凑证据](CGR_NEO4J_INTEGRATION.json)。此指纹不包含报告本身。15 项完整套件对应停止脚本修复前指纹 `76003f38d4d8375852a58528e90b6df6fdd1ee4d16d9f8de673f24ea47702601`；
随后只修改 native 停止 helper，增加 2 项定向回归，并实际停止专用 JVM，未重跑完整套件。
检索、解析、发布代码未变；两批证据明确分开记录。
根 `lct/`、CLI、注册脚本及根依赖文件未改，原程序指纹仍为
`42ae0f3336e274d94aa6dbdcb59652f1dfbc5f97eab11602e6b45a17697a8c03`。
此前未提交的 `code_graph/` 保留在原位，未纳入本轮提交。

独立 `integration_env/pyproject.toml` 与 `uv.lock` 将 CGR 固定到上述完整 Git SHA。
最终环境通过 Git 安装；PEP 610 `direct_url.json` 记录了相同的 `commit_id`，无 editable 路径。
CGR 现有 checkout 的 Rust source 配置初次触发 MSVC 编译并因缺少 `link.exe` 失败；
`--no-sources` / 普通索引设置未解决该传递 source。最终使用显式 dependency override，固定
PyPI 的 Windows x64 / CPython 3.12 ABI3 `cgr-graph-rs==0.1.0` wheel 和哈希：
`ce20b6fe06c732745e23e1e6b76a0e69c75e2e188c1823b18c8b9fdd20766ebb`。
Python 解析修复仍来自固定 Git 提交；不是用 PyPI 旧 Python 实现替代 fork。

## 修复前后证据

[修改前 native 输出](https://github.com/agentic-trpg/code-graph-rag/blob/896c037f1a09cb8cdb3928204c9cd62a34887f20/docs/reviews/python-accuracy-before.json)、
[修改后 native 输出](https://github.com/agentic-trpg/code-graph-rag/blob/896c037f1a09cb8cdb3928204c9cd62a34887f20/docs/reviews/python-accuracy-after.json)
是实际 GraphUpdater 的 11 个最小复现、默认/Jedi 两种模式（解析真实，持久化 sink 为 mock）。
真实 Neo4j 写入和 MCP 在 LCT 集成测试中另行验证，不能用 sink mock 代替。

| 问题 | 修改前 | 修改后 / 验证边界 |
|---|---|---|
| 字典、列表存函数 | 可能发出模块 CALLS | 只产生 REFERENCES；固定键调用 target、动态键保留两个候选 |
| 分支赋值 | 只保留最后文本赋值 | 分支合并候选；无条件覆盖仍清除旧目标 |
| lambda / 嵌套函数 | target 归到 factory/外层 | 独立 lambda 和 inner owner；同一行多个 lambda 节点不同 |
| 默认参数 make() | 归到函数体或重复 | 定义阶段、外层执行 owner；函数体调用单独记录 |
| 方法内裸 work() | 可连到同类 A.work | 无合法词法绑定则保留未解析；self / 类属性 / super 正例保留 |
| classmethod 描述符 | Jedi 当作外部而丢失 | 拒绝描述符 artifact 后，仅按真实源码锚点 goto 映射；外部判断保留 |
| staticmethod 回调 | 参数可能按 self 处理 | 普通回调参数；已知与未知来源同时保留 |
| 重导出 / 别名 | 默认模式曾漏掉 | 默认值传播与 Jedi 均能保留项目内候选 |
| 无法确定目标 | 容易静默遗漏或假确定 | 每个 CallSite 保留位置、owner、阶段、拒绝原因和未知来源；exhaustive=false |
| 进程间关系遍历顺序 | 相同快照可能触发内容冲突 | 关系、观察与内容校验规范排序；不同 PYTHONHASHSEED 和实际 MCP 子进程更新通过 |

[冻结 39-site 逐项结果](https://github.com/agentic-trpg/code-graph-rag/blob/896c037f1a09cb8cdb3928204c9cd62a34887f20/docs/reviews/python-frozen-results.json)
保留了独立人工预期，没有用工具输出改写答案。每种模式的 37 个 closed-truth site 上：
TP=37、FP=0、FN=1，precision=1.0、recall=0.973684；39 个标注位置均记录，没有确定性声明。
FN 为仓库外 `json.loads`：边界和位置保留，但没有伪造仓库内定义节点。该严格统计包含这一外部
目标预期。它不是全库准确率，也不证明反射、任意装饰器或动态 Python 都能可靠解析。

## 实际接入接口和节点身份

新增 CGR **integration API v1**，没有假设原内部函数就是稳定 SDK：

- `codebase_rag.integration.api.build_snapshot`：显式 Python 文件列表、固定源码字节、各仓库
  HEAD/status、dirty 内容身份、规范节点/关系、未解析观察、文件变化和上游 parser fingerprint。
- `integration.neo4j.Neo4jGraph`：官方 driver；CGScope / CGSnapshot / CGNode / CGObservation
  命名空间写入、约束、计数校验、源码复核、事务内当前图替换和 CAS 发布。
- 原 native GraphUpdater 的 Python CALLS/REFERENCES 也消费同一 profile。其他语言路径保留。

LCT 的 `cgr_adapter/` 不解析 Python、不调用旧 `lct.extract.python_nodes` / `lct.graph.Graph`。
它映射规范化节点并直接复用 `lct.embedding.Embeddings` 批处理/缓存与客户端、
`embedding_texts` / `chunks`、`lexical.add_document/rank`、`Query` 的分层候选过滤、BM25、
分区 HNSW、精确余弦、RRF 和签名分页。函数向量输入采用 CGR 的精确 source，修正仅按整行
读取 lambda 的问题；docstring 和所属 module/class 背景来自这份新目录，不生成 LLM 摘要。
DOC 继续用原章节分割器，只进入 BM25，不伪装成 CGR Python 节点。

`CGNode.node_id == retrieval.graph_node_id == retrieval.node_id`；不使用 Neo4j 内部数值 ID。
ID 含图快照和 repository/path/kind/qualified-name/occurrence 身份；重定义和同一行 lambda 可区分。
移动、重命名或新快照允许产生新 ID。旧映射不进入新 SQLite/BM25/HNSW；测试核对旧文件图节点
消失，并比较更新结果与同一源码状态重新构建的节点/关系和向量输入。
DOC 独立 ID 绑定 Python+DOC source snapshot，`graph_node_id=null`。

## 发布与查询边界

区分 Python code snapshot、Python+DOC source snapshot、graph snapshot、build key、唯一构建尝试
version，以及 EMPTY / BUILDING / PUBLISHED / FAILED / STOPPED。绑定清单记录完整 CGR SHA、
CGR 与 LCT 程序文件指纹、旧检索程序指纹、schema/format、模型/维度、输入模板、BM25 分词器、
HNSW 配置、输入哈希、各仓库提交与具体文件哈希。源码在图提交前和最终发布前复核。

统一入口按以下顺序执行：LCT OS 锁拒绝新查询并排空本入口 → 停止归属匹配的官方 HTTP
进程和旧连接 → SHOW TRANSACTIONS 等待数据库请求结束 → 官方驱动更新图 → 新节点映射、
新 BM25/HNSW 和经完全相同输入/配置核对的缓存向量 → 制品完整性校验 → 图 build marker、
文件指针与发布状态切换 → 恢复官方入口。不是跨存储 ACID，不要求 Community 多数据库。

实际测试观测到长 read-cypher 数据库事务后才触发维护，旧 HTTP 请求被终止，数据库请求
排空后才更新并恢复。LCT 进行中的查询持有同一锁；写者取不到锁时不改发布状态/图。
阶段故障和重启后，查询明确拒读，成功重试后才开放；不将跨存储部分写入伪装成已回滚。

**官方自由 Cypher 不执行 expected_version，也不持有 LCT 文件锁**。强制边界是受监督的 HTTP
进程维护窗口。当前命名空间旧节点在事务中替换，历史 metadata 与其他命名空间可保留；自由
查询应自行指定 namespace / CGScope.active。直接 Bolt、其他不受管理的 MCP、任意跨 namespace
或历史 metadata 的拼接不在此版本保证内。只读本身不等于版本隔离，也没有生产权限隔离证明。

## 执行结果和复现

| 验证 | 结果 |
|---|---|
| CGR 最终选定回归（8 个文件） | 52 passed / 0 failed / 3 skipped；3 个因缺少 JavaScript parser |
| 独立固定 Git 依赖安装 | 成功；101 包解析、99 包安装，PEP 610 full commit 已核对 |
| LCT 最终固定依赖环境套件 | **15 passed / 0 failed / 0 skipped，135.52 秒** |
| 原客户端模拟 Voyage HTTP | payload、1024 维、truncation=false、批处理和精确缓存命中验证通过；网络已 mock |
| 新增/修改/删除/重命名，模型/输入失效 | 合成 fixture 隔离索引验证通过；显式 scope 清单随样例变化更新 |
| 完整重建对照 | 同一固定源码的规范化节点、关系、输入对照通过；不含全业务库比较 |
| 故障 | graph、after_graph、retrieval、before_publish、restart，失败拒读及重启重试通过 |
| 官方 MCP 1.6.1 HTTP | 实际 get-schema / read-cypher 成功；无 write-cypher，read-cypher 写入尝试被拒绝 |
| LCT MCP HTTP | 实际 status / RRF / get_nodes / update / expected_version 错误通过；未认证 HTTP 401 |
| 提交校验 | CGR 实际 pre-commit/commit-msg 全部通过；无 --no-verify；LCT ruff/格式与 staged audit |
| 停止 helper 收尾修复 | 2 passed；实际专用 JVM 停止成功；未按名称结束其他 Java/控制台进程 |
| 远端全新下载副本 | 4 项离线复现通过，复用既有固定依赖环境，未重复安装 |
| 全上游套件、CI、真实检索质量、ChatGPT 远程接入 | **NOT RUN**，不以本地小样例替代 |

逐测试状态、版本和文件哈希见 [紧凑 JSON](CGR_NEO4J_INTEGRATION.json)，
实际两端工具输出摘要见 [MCP JSON](CGR_NEO4J_MCP.json)。它们不含数据库或凭据。

完整 Windows 依赖、原生启动、合成样例、HTTP 认证、停止/恢复说明见
[integration_env/README.md](../integration_env/README.md)。核心命令：

```powershell
uv sync --project integration_env --locked
$py = (Resolve-Path integration_env/.venv/Scripts/python.exe).Path
& $py -B -m pytest -o addopts='' -q tests/cgr_integration/test_offline.py
# 先用 prepare_cgr_fixture.py 指定新输出目录及专用 native 实例生成配置。
$env:LCT_NATIVE_TEST_CONFIG = 'C:/SET/ISOLATED/config.json'
& $py -B -m pytest -o addopts='' -q tests/cgr_integration --basetemp=.tmp/review-cgr-tests
```

CGR 独立复现：在与 LCT 并列的 CGR checkout（核对上述完整提交）执行以下命令。
`--with` 固定补充上游测试 hook 所需的 pytest-xdist，不解除 CGR Git 版本固定：

```powershell
uv run --project ../local-code-tools/integration_env --locked --with pytest-xdist==3.8.0 python -B -m pytest -o addopts='' -q -rs codebase_rag/tests/test_python_snapshot_api.py codebase_rag/tests/test_python_accuracy_profile.py codebase_rag/tests/test_python_frontend.py codebase_rag/tests/test_python_nested_functions.py codebase_rag/tests/test_python_scope_bound_names.py codebase_rag/tests/test_python_inheritance.py codebase_rag/tests/test_python_factory_return_chain.py codebase_rag/tests/test_python_cross_file_advanced_patterns.py
```

其 3 个 JavaScript case 本轮未执行，未记为通过。
新安装若未设置 native 配置，Native 测试会显式 skip；默认离线测试不需要 Neo4j、真实索引或 key。

## 原生依赖与维护过程的已知失败

使用 [Neo4j 官方 Windows ZIP](https://dist.neo4j.org/neo4j-community-5.26.12-windows.zip)
122465149 字节，SHA-256 `d8f4fc840bd8108ae811a960910208b63b5d75b1f837ed4ec837b5b8d8e268ab`；
Adoptium JRE 21.0.12.1+1 的已下载 ZIP 48999141 字节，SHA-256
`d35f31e712f0fcf6ac5a093edc90204fbff22f720ba3950bd09d331d5e621636`。
Neo4j 包内 APOC 5.26.12 core 初次 schema 调用缺少 Guava；补充
[Maven Central Guava 33.4.8-jre](https://repo.maven.apache.org/maven2/com/google/guava/guava/33.4.8-jre/guava-33.4.8-jre.jar)
3023797 字节、SHA-256 `f3d7f57f67fd622f4d468dfdd692b3a5e3909246c28017ac3263405f0fe617ed`
后，实际官方 schema 查询通过。APOC 安装按[官方说明](https://neo4j.com/docs/apoc/current/installation/)。
这些二进制均在忽略的本机目录，未上传。

此前也发现过候选集合无序导致跨进程快照内容冲突，已规范化并增加跨 PYTHONHASHSEED 及实际
MCP 更新回归。每次修复后的必要复跑已保留最终结果，不把中途失败或旧报告重标日期当作通过。
CGR ty 验证安装了其锁定版本的检查依赖；pydantic-ai 的临时版本漂移已纠正到 2.53.0。

## 保留检查、未完成项与正式建图门槛

53 个已有数据/索引/缓存/备份文件 SHA-256 与本轮开始基线一致；77 个原跟踪文件除明确授权
修改的 README/.gitignore 外一致。三个业务库的分支、完整提交、工作区状态均与开始时一致：

| 仓库 | 分支 / HEAD | 原有未跟踪条目 |
|---|---|---|
| agentic-trpg | main / ac2a0e41ec99bcc78d4fa608287fb4e7ea7fd436 | 2，保留 |
| trpg-state-machine | main / 4166e52f0809ae80ba1694295bb0739acec76bd8 | 2，保留 |
| trpg-rules-engine | main / ab276fffc5ff02a973e1c767543e712dd0897451 | 1，保留 |

本版可以进入独立审阅，**不能宣称已经具备正式全量建图和远程服务条件**：

1. 更新目前是显式文件 scope 的新快照、全范围关系复核及命名空间图替换，BM25/HNSW 重建；
   变化清单由文件哈希差异产生。新 API 复用了上游 parser fingerprint，native GraphUpdater
   原测试路径保留上游扫描/变化检测；**尚未接入上游完整增量缓存/provenance 发布管线**，
   新增/删除文件目前需更新显式 scope。不能称为已完成高效自动增量分析。
2. Python 任意反射、monkey patching、动态导入、复杂装饰器/元类、异常控制流及跨仓库多版本
   依赖仍需更广的人工标注与验证；本轮没有真实三库调用图准确率或性能证据。
3. 旧实库节点、关系、BM25/HNSW 从未直接沿用。旧向量缓存的全量迁移审计和重算数量统计
   **NOT RUN**；下一阶段必须按新解析输入和模型配置逐项核对，变更输入不得复用旧向量。
4. 实例当前限定 helper 拥有的 loopback 合成命名空间；生产凭据分权、非本机读者/写者、
   跨 namespace 自由查询、远程 TLS/OAuth/ChatGPT 接入及全量成本门槛未验证。
5. 本轮未检验硬断电/文件系统故障/所有进程 kill 时序；已测试指定阶段异常、重启拒读和恢复。
   不把这些有限故障注入扩展为跨存储 ACID 或任意崩溃安全声明。

未 merge、未修改业务仓库、未调用付费接口、未创建 Release、未上传真实数据库或密钥。
完成代码与报告推送后停止，等待独立审阅，不自动进入正式建图。

停止脚本最初安全拒绝 Windows conhost 子进程。收尾修复只忽略归属树中的系统 conhost、
让其随 JVM 退出，不直接结束它；对其他未知子进程仍在任何终止前拒绝。新增定向回归及实际
停止验证通过。此次后续修复单独提交，保留首次上传历史。
