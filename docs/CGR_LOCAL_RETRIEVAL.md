# 本地代码图和文档检索

在 local-code-tools checkout 中执行以下命令。项目的 `.venv` 包含 `lct`、Code-Graph-RAG 0.6.30 的 `cgr` 和 Jedi。首次 `up` 会下载固定版本的公开 UniXcoder 模型文件，后续推理离线进行。

```powershell
uv sync --locked
uv run --locked lct up --config configs/agentic-trpg.toml
```

配置以 TOML 文件为基准解析相对路径。`name` 标识 CGR 工作区，`mcp_prefix` 可单独指定 Codex 服务名称的前缀，省略时为 `lct_<name>`。`index_dir` 保存图、BM25、发布状态和刷新日志，`model_cache` 可在项目间共享。独立配置使用不同的 `name`、`mcp_prefix` 和 `index_dir`。为现有配置增加仓库或改变路径、排除范围时，使用新的 `index_dir` 建立新索引，可沿用该配置的 `name` 和 `mcp_prefix`。

Qdrant 可以是已经监听回环地址的服务；示例只配置 `qdrant.url`，不会安装或启动服务。若要让 `up` 在服务未运行时启动本机二进制，先从 [Qdrant v1.16.3 release](https://github.com/qdrant/qdrant/releases/tag/v1.16.3) 下载并解压适合系统的发行包，再同时配置 `qdrant.executable`（可执行文件路径）和 `qdrant.directory`（本地运行数据目录），例如相对于 TOML 的 `../.local/qdrant/qdrant.exe` 和 `../.local/qdrant`。客户端固定为 1.17.1。

另一份配置只需要至少一个代码仓库。文档仓库可选。下面的配置复用已有的本地 Qdrant 和模型目录。

```toml
name = "python_sample"
index_dir = "../.local/python-sample"
model_cache = "../.local/model"

[qdrant]
url = "http://127.0.0.1:6333"

[repositories.APP]
kind = "code"
name = "sample"
path = "../../python-sample"
exclude = [".venv", "tests", "dist"]
```

再次运行 `up` 复用已有索引。修改代码或 Markdown 后主动刷新。

```powershell
uv run --locked lct refresh --config configs/agentic-trpg.toml --project SM
uv run --locked lct refresh --config configs/agentic-trpg.toml --project RE
uv run --locked lct refresh --config configs/agentic-trpg.toml --project DOC
uv run --locked lct hybrid-search --config configs/agentic-trpg.toml --project trpg-state-machine "SessionMemory publication"
uv run --locked lct doc-search --config configs/agentic-trpg.toml --category contract "SessionMemory 原子发布"
```

`up` 写入 `$CODEX_HOME/config.toml`，默认是 `~/.codex/config.toml`；只管理当前配置的两个 MCP 条目，不修改其他条目的启用状态。Agentic TRPG 配置使用前缀 `lct`。重新启动 Codex 会话后，用 `lct_graph.list_projects` 查看 CGR 项目名，例如 `trpg-state-machine`。将这个名字作为 `project` 传给 `lct_search.hybrid_search` 或图查询。混合检索也接受 `SM` 等代码仓库配置别名，省略 `project` 时搜索全部已配置的代码仓库。从检索结果继续查图时，把结果的 `qualified_name` 和 `graph_project` 分别作为 `qualified_name` 和 `project` 传给 `lct_graph.callees`，并设置 `depth=2`。

官方 MCP 以 `--read-only --workspace` 启动，Codex 只暴露 `resolve`、`definition`、`context`、`callers`、`callees`、`list_projects`。补充 MCP 还暴露 `search_docs` 和 `refresh_index`。刷新使用配置别名。也可用 `python -m lct.entrypoint local-mcp --config <配置路径>` 单独启动补充 stdio MCP。

代码刷新统一调用 `.venv` 内的 `cgr start --repo-path ... --update-graph`，以 `GRAPH_BACKEND=sqlite`、`PYTHON_FRONTEND=jedi`、`CGR_EMBEDDING_PROVIDER=unixcoder` 和 `CGR_VECTOR_STORE_BACKEND=qdrant` 运行。Qdrant 按配置使用独立集合，按项目载荷过滤结果。补充索引从 CGR 节点批量读取函数和方法，图及向量通过核对后才发布 BM25。共享文件锁覆盖同一配置的代码刷新与混合查询。刷新失败会保留阶段及日志路径，并阻止读取失败的批次。维护该索引时使用 `lct refresh`，以保持这三份数据同步。

DOC 检索使用独立 SQLite FTS5，默认读取根目录和 `docs/` 下的 Markdown，含未提交修改。文件指纹不变时跳过切分和写入。代码 BM25 仅更新内容或位置发生变化的记录。候选返回 `slot` 与 `channels`，用于区分配额和两路命中情况。代码查询按 `top_k // 5` 计算 BM25 名额，候选读取量受已发布索引规模约束。

## 0.6.30 的运行边界

- Windows 上，`StructureProcessor._directories_to_derive` 的 `Path.rglob` 会在检查排除规则之前进入大型目录。带 `--exclude .test-tmp --exclude .worktrees` 的 SM 冷建图仍可在目录枚举阶段停留数分钟。可观察 `SM-refresh.log` 中 Pass 1 的进度，目录很大的开发 checkout 可与用于索引的干净 checkout 分开配置。
- CGR 的向量查询选取模块直接定义的函数及方法，以及模块内类等容器定义的方法。图中其余定义仍可走图工具。代码 BM25 使用同一份向量候选节点清单。
- CGR 向量使用最多 512 tokens 的函数或方法源码片段。Python docstring 位于片段内时参与嵌入。长签名、长 docstring 和长函数都可能被 token 窗口截断。
- MCP 本地协议调用不会调用托管模型。若在托管 Codex 会话中让 Agent 消费源码或文档摘录，这些工具结果会进入该会话的模型上下文。
