# CGR / 原生 Neo4j 整合 profile

这是待独立审阅的第一版小样例实现。CGR 依赖固定到完整提交
`896c037f1a09cb8cdb3928204c9cd62a34887f20`；不依赖本机 editable、另一个 checkout 或浮动 main。
正式 `lct/`、根目录依赖环境、已有真实数据库和个人 MCP 注册均保留。
本 profile 拒绝旧 `data/`、未标记非空目录、非本机实例及非 `lct-fixture-` 命名空间。
**正式全库构建和公网接入尚未开放**。

## 安装与无服务测试

需要 Windows、Python 3.12、Git 和 uv。Git checkout 仅提供源码、测试和审阅材料；不提供真实索引下载。
在仓库根目录执行：

```powershell
uv sync --project integration_env --locked
$py = (Resolve-Path integration_env/.venv/Scripts/python.exe).Path
& $py -B -m pytest -o addopts='' -q tests/cgr_integration/test_offline.py
```

该独立环境固定 Jedi 0.20.1、官方 Neo4j driver 6.4.1、官方 Neo4j MCP 1.6.1、MCP SDK 1.30.0。
完整传递依赖及制品哈希在 `uv.lock`。环境使用显式的依赖 override，固定 PyPI 发布的 Windows x64 / Python 3.12 ABI3
`cgr-graph-rs==0.1.0` wheel 及 SHA-256，保留 Python fork 的完整 Git SHA；
这避免上游 checkout 的本地 Rust source 覆盖触发 MSVC 编译。该环境目前仅验证 Windows x64。此 Python profile
不需要 Rust 编译器、其他语言 grammar、Memgraph、Docker 或 LLM。根项目环境不会被同步更新。
原工具的默认合成测试仍可使用根目录原锁文件单独安装运行，不能用这两个环境交叉替换依赖。

离线测试使用极小的合成 Git 源码，验证规范化节点、同一行 lambda、实际 BM25/HNSW 构建、
候选过滤、缓存、输入和模型失效、兼容性及原 Voyage 客户端的**模拟 HTTP 响应**。
`SyntheticEmbeddings` 只替换原批处理客户端的传输；向量和索引清楚标记 `synthetic_fixture=true`。
任何这些测试均不能证明真实语义检索质量。

## 准备独立 Windows 原生 Neo4j

使用专用的新目录，不能指向用户已有数据库。已验证 Neo4j Community **5.26.12**、
[Adoptium JRE](https://adoptium.net/temurin/releases/) **21.0.12.1+1**、发行包自带 APOC **5.26.12 core**。
官方 MCP 的 `get-schema` 需要 APOC；本发行包的 schema 过程还需要 Guava **33.4.8-jre**。
下载链接和 SHA-256 见整合报告。下载、解压 JRE 与 Neo4j Windows ZIP，保持各自独立目录。
不安装系统服务，不改变账户密码，不需要 Docker。Java 进程只监听 loopback。

```powershell
# 所有路径显式设置为专用测试目录；Guava 从官方 Maven Central 下载。
& $py -m cgr_adapter.native --home C:/SET/neo4j-community-5.26.12 `
  --java-home C:/SET/jdk-21.0.12.1+1-jre --state C:/SET/private-native-state `
  --guava-jar C:/SET/guava-33.4.8-jre.jar
```

helper 核对 Neo4j 5.26.12、一个空的新数据目录或自己记录的实例；JRE 请按上述已测版本提供。随机生成的数据库认证
保存在 `--state/native-auth.json`，不要提交它或将其内容写入命令、报告、个人 Codex 配置。
Windows 通过隐藏 Java 进程运行，Neo4j Bolt 端口 17687，浏览器端口 17474。
重复启动必须通过实例标记和认证校验；它不会重置现有用户数据库密码。

## 创建合成样例并执行真实集成测试

```powershell
& $py tools/prepare_cgr_fixture.py --output-root .tmp/my-cgr-review `
  --native-home C:/SET/neo4j-community-5.26.12 `
  --auth-file C:/SET/private-native-state/native-auth.json
$profile = (Resolve-Path .tmp/my-cgr-review/config.json).Path
$env:LCT_NATIVE_TEST_CONFIG = $profile
& $py -B -m pytest -o addopts='' -q tests/cgr_integration `
  --basetemp=.tmp/my-cgr-native-tests
```

集成测试使用新的 Git fixture、专用数据目录和唯一命名空间，实际运行 Windows Neo4j 及两个
独立 HTTP MCP。测试端口 18888/18889；请勿并行运行本集成套件。缺少显式原生配置时，
Native 测试会标记 **SKIPPED / NOT RUN**，不会把 mock driver 当作真实 Neo4j 通过。
临时目录均不能替换成真实 `data/`。样例和所有索引都可留在忽略目录供检查，无自动清理真实数据。

## 独立启动两个 HTTP MCP

```powershell
# 首先发布一个完整的合成版本；此命令拥有并启动官方只读 MCP。
& $py -m cgr_adapter.cli $profile update
# 为 LCT MCP 设置随机的、至少 24 字符的 token（通过进程环境，不写入配置）。
# $env:LCT_HTTP_TOKEN = <YOUR_RANDOM_SECRET>
& $py -m cgr_adapter.server $profile
```

使用 `mcp.http.example.json` 的客户端模板：官方服务对每次 HTTP 请求使用 Neo4j Basic
认证，LCT 使用 Bearer token。`get-schema` / `read-cypher` 来自官方可执行文件；不注册
`write-cypher`。LCT 只提供检索、节点源码、状态和统一更新。没有 MCP 聚合代理，也不启动
CGR 聊天、shell、编辑或 MCP server。不要在另一个终端自行启动不受监督的官方进程；维护
程序会拒绝占用目标端口的未知进程。

```powershell
& $py -m cgr_adapter.cli $profile status
& $py -m cgr_adapter.cli $profile stop
# STOPPED/FAILED/BUILDING 需要 update 重新校验后发布；不会直接开放旧检索结果。
& $py -m cgr_adapter.cli $profile update
# 已 PUBLISHED 但官方进程停止时可做完整制品校验后恢复：
& $py -m cgr_adapter.cli $profile resume
```

停止 LCT HTTP 进程使用其终端 Ctrl+C。`stop` 首先把查询状态设为 STOPPED，再停止官方
进程并排空数据库请求。停止专用 native JVM 使用 `& $py -m cgr_adapter.native --stop --home C:/SET/neo4j-community-5.26.12 --state C:/SET/private-native-state`。
Native JVM 的停止仅针对 helper 记录的 PID、创建时间/命令、home
归属明确匹配的专用测试进程；不要用按名字杀死全部 Java 的命令。重启未完成状态保持拒读，
重新 `update` 会重新捕获源码并验证；保留失败候选和缓存，不假装完成跨存储回滚。

## 版本和维护保证

CGR API v1 给出唯一 Python 节点目录、源码提交/dirty 字节身份、关系与证据。LCT 不再解析
Python；它只映射 `CGNode.node_id`，复用原 BM25、分区 HNSW、精确检索、RRF、分页和 DOC
章节分割。函数向量输入使用 CGR 的精确源码（尤其 lambda 的列范围），复用原 docstring，
不生成 LLM 摘要。DOC 仅进入独立 lexical 通道，不伪装成 CGR Python 图节点。

源码身份区分 Python code snapshot、Python+DOC source snapshot、graph snapshot，以及
包含完整 CGR commit / 双方程序指纹 / 检索配置的 build key 和唯一构建尝试 version。
Git commit 与未提交字节同时记录；分支名不能替代提交。每次重建 BM25/HNSW 和节点映射，
仅完全相同输入及配置的向量可命中缓存。合成和真实缓存物理分区隔离。
正式路径禁止发送任何新 Embedding：`synthetic_fixture=false` 构建只允许命中已有缓存。

维护开始先锁住/排空 LCT 查询，关闭官方进程及旧 HTTP 连接，排空 Neo4j 进行中事务，
再通过官方 driver 更新图，生成检索制品并验证，最后切换绑定与指针、恢复官方入口。
Neo4j 的当前命名空间节点在一个事务内替换；不假定 Community 任意多数据库或跨存储 ACID。
任一步失败，已发布状态不提前推进，两个入口保持不可查询，直到显式重试成功。

**保证边界**：官方自由 Cypher 不会执行 LCT 的 expected_version 校验；只读也不等于版本隔离。
维护窗口强制关闭受监督的 HTTP 入口，并等待已经发出的数据库请求结束；排空失败不写图。
维护后当前命名空间仅保留当前图节点；旧 metadata 和其他命名空间可能仍存在。查询应显式
限定 `namespace` 和 `CGScope.active`。任意 Cypher 自行跨 namespace/历史 metadata 拼接、
不受管理的 Bolt 客户端或另一个 MCP 不在全局版本保证内。这是专用本机实例的第一版方案，
不能将其称为生产权限隔离、零停机或 ChatGPT 远程接入验证。

远程 HTTP/TLS、OAuth、凭据分发、正式数据迁移和授权付费向量构建仍需要下一阶段设计与验证。
本轮未公开公网服务、未注册插件、未修改个人 Codex 配置、未构建三个业务库正式索引。
