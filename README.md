# Agentic TRPG Local Code Tools 1.0.0

这是独立私有源码审阅仓库，包含真实的解析、Code Graph、检索、增量版本管理、CLI 和 stdio MCP 实现。
**本仓库不提供真实数据库、节点目录数据、图数据、向量、索引或 Release 附件。**
Git checkout 用于审阅、开发和合成测试。本机已有完整工具包保留在原位置，上传不会重建或删除它。

## 安装

需要 Python 3.12、Git 和 uv：

```powershell
uv sync --locked
# Windows
.venv/Scripts/python.exe -m pytest -q tests
# macOS/Linux: 将上述解释器替换为 .venv/bin/python
```

本分支继续修复独立审阅发现的 Python 解析问题，原两项 gap 保留为严格回归测试。
本批仅处理方法效果适用条件与字典复制不确定性；保留既有字段、工厂阶段和快照行为。
解析控制使用开放输入模式。
本批不启动 MCP 或构建真实索引。实际结果、范围和剩余限制见
[第一阶段报告](review/PYTHON_PIPELINE_PHASE1.md)。

另有可选的 [Neo4j 投影](docs/NEO4J_FULL_GRAPH.md)（[API 与 CLI](docs/NEO4J_SMALL_GRAPH.md)）：
从已发布 SQLite catalog/manifest 分批导入固定版本，完成校验后原子发布；失败候选
不可查询，同输入重试清理后从头导入。未接入现有 MCP 或向量检索。安装可选
`neo4j` 依赖组后使用独立 `python -m lct.neo4j_graph` 管理入口。已知节点的图查询可使用 [官方 Neo4j MCP read-cypher 模板](docs/OFFICIAL_NEO4J_MCP.md)；投影迁移与索引维护仅在终端离线执行。

默认测试不需要 `config.json`、真实索引、API key 或三个业务仓库；测试配置和生成数据库放在临时目录。
Embedding API 被测试夹具禁止调用。一项使用已有真实历史缓存的测试默认跳过，只有显式
`--run-local-index` 才启用；它依然只读已缓存向量，不发送网络请求。

## 无数据库、无 API key 的完整合成示例

```powershell
.venv/Scripts/python.exe -m tests.synthetic_demo --output .tmp/review-demo
```

输出目录必须尚不存在。示例创建极小的临时 Git 源码库、BM25/图/HNSW 索引，并通过实际查询核心
运行 BM25、dense、RRF 和 DOC 查询。`tests/fixtures/synthetic/vectors.json` 与
`tests/synthetic_support.py` 明确将向量标为 **SYNTHETIC-TEST-ONLY**。
它们是确定性的测试数据，没有语义检索质量含义，也不是 Voyage API 的输出。
不要将这些数据复制到真实索引或拿来声明真实召回率。

`tests/test_synthetic_dense.py` 另验证过滤、分层、精确/HNSW一致性、分页、源码定位、关系、
变更/删除/移动和候选发布失败；`tests/test_lifecycle.py` 覆盖版本不兼容、真实进程中断和恢复。
生成的合成数据库不会进入 Git。

## 真实本地使用

```powershell
Copy-Item config.example.json config.json
# 编辑 config.json，替换 C:/REPLACE_WITH_YOUR_WORKSPACE，并设置本地 data 目录。
# VOYAGE_API_KEY 只通过进程环境提供，不写入配置或 Git。
.venv/Scripts/python.exe local_code_tools.py estimate
.venv/Scripts/python.exe local_code_tools.py build
.venv/Scripts/python.exe local_code_tools.py search-code 'ContainerService' --level class --mode rrf
.venv/Scripts/python.exe register_mcp.py
```

`build`、缺少输入缓存的 `update`、首次未缓存的 dense/RRF 查询会调用 Embedding API；需要单独授权和费用预算。
`update --offline` 缺失向量会明确拒绝，不伪造结果。`acceptance.py`、`dense_acceptance.py` 和
`protocol_acceptance.py` 是已有本机验收入口，默认要求配置/真实索引，有些路径可能申请缺失查询或文档向量；
不能把它们当成默认离线测试。`dense_acceptance.py --offline` 禁止申请新向量。

已有完整 lexical 版本需要追加向量而不重新解析源码时，使用
`local_code_tools.py attach-dense --version <当前版本> --expected-program-hash <原版本program_hash> --offline`。
它仅从已发布 catalog 的捕获源码重建 embedding 输入，读取缓存，创建新版本并原子发布；
`--offline` 缺向量即拒绝，去掉该参数才允许在配置预算内请求 Voyage。程序升级导致旧版本
`program_hash` 不同，必须显式提供旧哈希；schema、配置、模型、HNSW 和校验和仍严格验证。
源码新鲜度沿用旧版本上次检查时间，不执行实时目录扫描。

本次上传的只读实库验证命令为：

```powershell
.venv/Scripts/python.exe tools/validate_local_index.py --config config.json --output .publication/local-validation.json
```

它必须已有匹配的真实索引和缓存，缓存缺失即拒绝，不调用 Embedding、不重建或更新索引。
索引路径、工具程序指纹和源码版本有严格绑定；移动目录或更换配置可能返回不兼容。
保留原始 manifest 的身份，不要手改哈希。需要迁移时，先配置正确路径，再由工具支持的更新流程
重建派生索引并复用相容缓存；这不属于本次上传任务。
MCP 注册保存的是本机绝对解释器/入口，换电脑后须安装依赖、设置路径和环境变量，再运行注册脚本。

## 主要实现

| 路径 | 实际职责 |
| --- | --- |
| `lct/extract.py` | Python AST/嵌套节点、签名、现有docstring输入、Markdown章节 |
| `lct/graph.py` | CONTAINS/IMPORTS/CALLS/INHERITS、别名/赋值/回调/字典传播和依赖边界 |
| `lct/neo4j_graph.py` | 已发布 SQLite 小图的可选 Neo4j 导入与固定版本查询 |
| `lct/embedding.py` | 真正的Voyage客户端、内容键缓存、限额、有限重试和断点复用 |
| `lct/lexical.py` | 中英/标识符分词与持久BM25 posting |
| `lct/storage.py` | 节点目录、差异更新、HNSW、候选版本、原子切换及恢复 |
| `lct/query.py` | dense/精确/BM25/RRF、过滤、固定版本游标、源码与图扩展 |
| `lct/cli.py` / `local_code_tools.py` | 共享核心CLI |
| `lct/mcp_server.py` / `register_mcp.py` | stdio MCP五个工具及幂等本机注册 |
| `lct/management.py` | 真实备份打包、校验恢复和有界清理；不在本次调用 |
| `tests/` | 无API回归、小型合成数据、合成索引示例 |
| `review/` | 脱敏历史验收及本次本地验证；不是独立审阅意见 |

## 证据和限制

使用说明见 [docs/USAGE.md](docs/USAGE.md)。本次验证见 [review/LOCAL_VALIDATION.md](review/LOCAL_VALIDATION.md)，
历史实测见 [review/historical/ACCEPTANCE.md](review/historical/ACCEPTANCE.md)。报告保留实际日期、内容指纹和索引版本；
旧报告不会因重新上传而变成新测试。向量数组、真实节点数据库和完整图数据不随报告提交。

静态分析有递归/工作量上限，动态反射、任意装饰器、插件和复杂流仍可能未解析。
中文检索有指定入口漏检，RRF不稳定优于单路；旧问题复用不是独立评测。
不将本地通过的测试称为独立代码审阅或新的远程CI结论。
