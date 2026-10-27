# 本地代码检索与 Code Graph

2026-10-27。工具程序和数据库保存在独立本地目录，三个项目仓库仅保存本说明和入口。
该工具帮助开发者从当前源码定位实现，不参与游戏运行、不改变规则或状态权威。
索引不是架构契约；架构、范围和实现证据仍分别以 Module Contracts、MVP Scope 和当前源码为准。

本批经明确授权使用真实 Voyage API，当前三库代码向量、BM25、图、dense／RRF 和 MCP
均已实际运行。26组当前语料 HNSW／精确检索比较平均召回99.38%、最低96%；隔离样例
验证成员说明更新、向量复用及新增／删除／移动。检索仍有Top10漏检，RRF未稳定优于单路；
这些观测不构成独立评测或优于历史实验的证明。具体版本和完整结果以本地验收报告为准。

## 安装位置与最少操作

本机工具目录通过环境变量自行设置；例如将 `$env:LCT_ROOT` 设为自己的工具包绝对路径。
运行配置为工具包的 `config.json`，也可用 `--config <配置文件>` 或 `LCT_CONFIG` 指定。
配置中的三个 repository path 指向实际要检索的工作目录，不能仅凭分支名确定源码版本。

```powershell
$py = Join-Path $env:LCT_ROOT '.venv/Scripts/python.exe'
$entry = Join-Path $env:LCT_ROOT 'local_code_tools.py'
& $py $entry status --refresh
& $py $entry search-code 'ContainerService' --repo trpg-state-machine --level class --mode bm25
& $py $entry search-docs '实例字段 局部准入' --category contract
```

`status --refresh` 明确检查当前文件和 Git 身份；代码变化后执行 `update`。
普通查询只报告最近检查的时间和结果，不每次遍历所有文件，也不未经检查声称最新。
仅需精确文件定位的小修改可以直接用 `rg` 和读源码，无须先调用检索。

## 工具包与环境

工具包 1.0.0 包含 Python 程序、共享 CLI/MCP 查询核心、测试、配置、`pyproject.toml`、
`uv.lock`、可导出的依赖清单、`reports/` 和 `data/`。环境独立于 SM/RE 的游戏依赖。

```powershell
# 在工具目录建立环境，Python 3.12；迁移时重新创建，不复制虚拟环境作为运行保证。
uv sync --locked
# 从环境提供已有的 VOYAGE_API_KEY，不写进配置、报告、命令参数或 Git。
& .venv/Scripts/python.exe local_code_tools.py estimate
& .venv/Scripts/python.exe local_code_tools.py build
& .venv/Scripts/python.exe local_code_tools.py update
& .venv/Scripts/python.exe local_code_tools.py update --offline
```

`estimate` 不发网络请求。`build` 和 `update` 使用同一候选构建路径，均复用未改变的向量。
`--offline` 缺向量即报错；`--lexical-only` 可明确构建没有 dense 的 BM25/图版本，
状态会标记 `ready_without_dense`，dense/RRF 请求报缺失，绝不伪造向量。

真实向量使用 Voyage `voyage-code-4`、1024 维、float、`truncation=false`，代码输入为
`input_type=document`，查询为 `query`；Markdown 只建立 BM25，不发往向量接口。
沿用旧实验每百万 token 0.12 美元的配置费率和 400 次请求／保守 1500 万 token／2 美元上限。
这是本地预算控制和估算费率，实际用量取 API 响应，账户账单或免费额度不作推断。
每次尝试先持久预留预算；限流/部分服务错误有限重试，未知网络结果保留预留。
认证和明确费用错误停止。已缓存批次可断点复用；服务不承诺请求幂等，丢响应可能造成重复费用。

## 纳入范围

默认纳入三库根目录的 Python/Markdown 文件、`docs/`，及配置列出的代码根：
SM 的 `src/`、`examples/`、`scripts/`；RE 的 Engine、SRD Data、Bridge、Demo 各 `src/`，
以及 `examples/`、`scripts/`。不存在的目录跳过。根目录的新增源码和纳入根内未提交文件也会被索引。
文档库的私有 `docs/FIRST_BLUSH_MVP_REQUIREMENTS.md` 明确排除。

默认排除测试；`include_tests` 可显式开启各测试根，每个节点保存 `is_test`，查询默认再排除测试。
测试入口不等同生产入口。排除 `.git`、虚拟环境、缓存、`node_modules`、`dist`、`build`、
`.worktrees`、`.test-tmp`、`.evaluation-worktree`、`experiments`、生成目录、vendor/third_party
及符号链接。项目外工具目录不属于任何项目索引根，无需修改项目 `.gitignore`。
准确文件清单、各库统计和 Git/内容身份保存在每个版本的 `manifest.json`。

## 节点、说明与定位

统一目录包含 Repository、Module、Class、Function（兼容检索层，含方法、嵌套函数和 lambda）、DocumentSection。
Python 的 `node_type` 精确区分 module/class/function/method/lambda；不另建检索解析器。
第一阶段接口和未完成验收见 [报告](../review/PYTHON_PIPELINE_PHASE1.md)。本轮未重建真实索引。
代码节点记录仓库、相对路径、限定名、父节点、源码范围、签名、docstring、内容及文件指纹。
`node_id` 为仓库／路径／类型／限定名／作用域出现序号组成的逻辑身份，不写回源码。
同一文件同名定义不会互相覆盖；普通行号移动不改变身份，插入更早的同名定义可能改变序号。
重命名或移动通常按删除旧节点、新增节点处理，不承诺通用重命名识别。
`node_version` 和 `index_version` 标识某次不可变索引中的节点版本。

模块向量包含路径、模块说明和直接成员名称／签名／首段说明；类向量包含所属位置、类说明、
基类和方法签名／首段说明，不重复成员完整函数体。说明确定性取现有 docstring 首个非空段，
最多 240 字符；成员按源码顺序最多 80 个、8 KiB，模块／类说明最多 10 KiB。
函数向量包含保留 docstring 和注释的源码，以及必要路径、owner/module 简短背景。
源码已有的函数 docstring 不再拼接一次。不调用生成式 LLM，也不维护独立摘要。
函数正文按行切为最多 22 KiB 的块，单行过长按 UTF-8 安全边界切分；各块仍归原函数。
连同背景低于保守的 32K 字节输入上限；预算是字节上界，不冒称精确 tokenizer 计数。

Markdown 在代码围栏外按 ATX/Setext 标题层级切分，保存标题路径、anchor、分块、行号与指纹。
长章节按空白段落边界细分，不切开连续表格或代码围栏；超长原子块保留并标记。
DOC 分类可筛选 `contract`（文档库现行文件）、`implementation`、`history`（review/progress/
acceptance 等）和 `experiment`。分类是路径规则，不代表每句话的决定状态；仍须阅读日期及正文。
默认 scope 排除了实验目录，所以 experiment 分类在默认语料中可能为空。

## 搜索与分页

以下 dense／RRF 示例要求 `index_status` 中 `dense_ready=true`；未建向量时使用 BM25。

```powershell
& $py $entry search-code 'SessionMemory publish 回滚' --level module --mode dense
& $py $entry search-code 'ContainerService' --level class --mode bm25 --repo trpg-state-machine
& $py $entry search-code 'RulesetBinding 固定输入' --level all --mode rrf --candidates 50 --limit 12
& $py $entry search-code 'evaluate attack' --repo trpg-rules-engine --exact --mode dense
& $py $entry search-docs 'SQLite COMMIT RAM 发布' --category contract --limit 5
& $py $entry get-nodes '<搜索返回的 node_id>' --version '<index_version>'
& $py $entry relations '<node_id>' --type CALLS --direction out --depth 2
& $py $entry relations '<node_id>' --type CALLS --direction in --depth 1
& $py $entry relations '<node_id>' --type CONTAINS --direction in
```

CLI 和 MCP 使用同一查询核心。BM25 使用 k1=1.2、b=0.75；分词拆分 CamelCase 和 snake_case，
英文转小写，中文逐字及重叠双字，不仅按空格切中文。倒排项落盘，查询只读匹配 posting。
RRF 常数 60，保留各渠道排名及当前候选池中的 BM25 独有项；不接付费 reranker/LLM 重排。
`all` 按独立层级排名轮流返回，不把不同层级原始分数直接相比较。

HNSW 是向量近邻结构，与源码 Code Graph 不同。采用 USearch、cosine、归一化 float32，
connectivity=32、expansion_add=128、expansion_search=128；按 repository/kind 独立分区。
过滤发生在候选生成阶段，不从小的全局 TopK 再筛层级。长函数去重不足时扩大分块候选。
精确基线使用相同归一化向量的点积，可以用 `--exact` 验证近邻召回。

默认返回 node_id、类型、限定名、首段说明、文件位置、渠道排名、索引版本和最近新鲜度检查；
不返回全部候选源码。`get_nodes` 按需批量读取索引快照，并重新核对当前文件哈希。
`live_file_matches=false` 表示旧行号不再保证对应当前文件；返回源码仍明确来自固定索引。

候选数最多每层 1000，单页最多 100。`next_cursor` 绑定版本和查询条件，后续使用相同参数传入
`--cursor`。`has_more` 仅说明这个有界候选池还有内容，不代表已经穷尽仓库。
更新后旧游标读取仍保留的版本；版本已清理则明确报过期，不悄悄跳到新版本。

## 图关系与可信边界

图使用 Python 标准库 AST 和有界 points-to 数据流，不导入或执行 SM/RE 模块。
记录 CONTAINS、IMPORTS、CALLS、INHERITS 和 REFERENCES。AST 提取统一节点和调用位置；
Jedi 0.20.1 在私有捕获源码副本中解析名称；LCT 按源码定义位置验证映射，并处理有限的
顺序赋值、分支候选、绑定方法、显式回调实参和字面容器关联。没有单调 fixed-point/Flow 执行器。

每个位置单独保存候选 targets、unknown_origin、complete、completeness_basis、工具证据和原因，
并区分 lexical_owner/execution_owner/phase。Jedi 推断本身不证明完整性；
普通项目输入默认开放，只有合成测试显式声明 closed_world。
旧 resolved/possible/boundary/unresolved 是兼容投影，不能代替位置记录：
唯一已知目标加未知来源仍是 incomplete，零目标也可能是静态无效调用。
复杂 MRO、任意装饰器和动态容器行为保持未知；原两项失败验收现保留为严格回归；具体结果与边界见报告。

SM 的 RE pin 与旁边 RE checkout 分开核对。不匹配时保留带原因的依赖边界，
不制造通往另一个版本的精确调用边。当前 pin 查 SM `pyproject.toml` 和索引 manifest。
关系查询可选类型、in/out/both、深度（最大4），并限制节点、边、输出字节；
`truncated=true` 表示触及上限，不能把有限输出当完整调用闭包。

## 一致性、增量与恢复

清单同时记录工具源码/锁指纹、schema、索引格式、模板、分词、Embedding 模型/维度、
各仓库 HEAD、实际路径、dirty 状态、纳入文件内容根指纹及完成时间。
启动/查询检查程序和索引兼容性；不兼容需 rebuild，缺失/不完整有明确状态。
不只比较 HEAD：修改、新增、删除、移动文件都会改变内容清单。

更新持有 OS 释放的独占写锁，先在候选目录解析和组装，校验 SQLite、全部产物哈希和
构建前后源码一致后原子替换 current 指针。图、BM25、向量来自同一捕获版本；
失败候选不影响当前可读版本。向量按完整模型/输入设置和文本哈希复用；相容旧实验缓存
只在文本完全相同才命中，旧独立摘要不作为新模板输入。函数说明变化也更新相关模块／类输入。
删除旧节点及其 posting/边；节点／边／倒排按差异维护。AST/Jedi 关系分析和候选 HNSW 在更新时
重建，不宣称所有更新计算都严格局部，但未变化向量不重请求 API。查询不做这些构建工作。

```powershell
& $py $entry recover '<保留的完整版本>'
& $py $entry backup
& $py $entry restore '<backup.zip>' '<不存在的新目录>'
& $py $entry gc
```

默认保留当前及至少一个完整旧版本，备份最多两份；`gc` 清理不被保留版本引用的文档向量，
查询向量最多保留512项。失败重跑复用已落盘向量；恢复前校验所有文件哈希。
备份打包程序、配置、锁、测试／报告、完整版本、向量缓存和用量台账，排除虚拟环境、
工作树、密钥和 Codex 配置备份。restore 验证成员路径和哈希，仅写入不存在的新目录。
新机器修改 repository/data 路径、建立环境并重新 build/update 和注册；路径身份改变会要求重建，
兼容文本向量仍可复用。不要假定复制 `.venv` 可跨机器运行。

## MCP 注册和调用

```powershell
& $py (Join-Path $env:LCT_ROOT 'register_mcp.py')
codex mcp get agentic_trpg_local_code --json
# MCP 协议入口（平常由 Codex 启动，无需手工常驻）：
& $py $entry mcp
```

`register_mcp.py` 注册一个管理三库的 stdio 服务，使用工具目录中的绝对 Python/入口路径。
重复执行相同配置不会重复添加；替换同名项前在 Codex 配置旁保存可恢复备份（最多2份），
按 TOML 语义验证其他配置不变。只保存 `VOYAGE_API_KEY` 环境变量名称，不保存值。
stdout 仅用于 MCP 协议，日志走 stderr，无 FastAPI/公网 HTTP 服务。
新注册工具可能需要重开 Codex 会话才能发现；协议测试不等同当前旧会话已刷新。
本地 `reports/` 的真实验收记录区分协议层调用、独立 Codex 调用和检索质量。

| 工具 | 主要参数 |
| --- | --- |
| `index_status` | `refresh=false`；true 触发当前源码清单检查 |
| `search_code` | query, level, repositories, mode, candidates, limit, cursor, exact, include_tests |
| `search_docs` | query, repositories, category, candidates, limit, cursor |
| `get_nodes` | node_ids（最多50）, include_source, version, max_bytes |
| `get_relations` | node_ids（最多20）, relation_types, direction, depth, max_nodes, max_edges, max_bytes, version |

## 工具不可用时

直接在正确仓库用 `rg -n '标识符' src packages apps docs`、`rg --files` 和源码读取。
先核对 cwd/branch/HEAD/dirty、依赖 pin 和权威文档；不把过期结果或历史实验答案当当前真值。
检索测试问题复用不构成新独立评测，不因本地测试通过宣称优于历史实验或远程 CI 已通过。
源码位置、近邻召回、静态图解析边界和实际问题检索结果分别见本地验收报告。
