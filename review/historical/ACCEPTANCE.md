# 本地代码工具包：最终真实验收

2026-10-27（Asia/Shanghai）。**已完成本批本地工具包、真实向量建库和指定验收。** 这不表示静态图可穷尽Python动态行为，也不表示检索效果优于历史实验。

工具包：`<TOOL_ROOT>`，版本 **1.0.0**。当前完整索引 `20261026T215543-7961d6f6d2`，兼容完整前版 `20261026T215350-daca0c3372`；程序指纹 `42ae0f3336e274d94aa6dbdcb59652f1dfbc5f97eab11602e6b45a17697a8c03`。

## 授权与范围

用户已明确授权将纳入的Python源码、现有docstring/注释和结构背景发送至既有Voyage endpoint，使用voyage-code-4/1024。Markdown未请求向量，不生成LLM摘要，不维护旧实验独立摘要。此前因自动审批要求直接确认的阻塞已解除；旧阶段报告保存在history/，不代表当前状态。

索引覆盖给定三个主工作目录的实际字节和Git身份（不是仅看HEAD），不是本次文档工作树。445个文件；测试默认排除，私有冒险文档、实验、虚拟环境、临时工作树、生成目录、第三方依赖和符号链接排除。每版manifest保存完整文件列表。

| 仓库 | 索引main提交 | Module | Class | Function | DOC section |
| --- | --- | ---: | ---: | ---: | ---: |
| agentic-trpg | `ac2a0e41ec99bcc78d4fa608287fb4e7ea7fd436` | 0 | 0 | 0 | 534 |
| trpg-state-machine | `4166e52f0809ae80ba1694295bb0739acec76bd8` | 90 | 330 | 1098 | 673 |
| trpg-rules-engine | `ab276fffc5ff02a973e1c767543e712dd0897451` | 196 | 515 | 1662 | 681 |

Repository=3；总节点5782。代码节点3891个，真实向量块3895个；每个模块、类、函数均有向量，长函数块仍归原节点；六个HNSW分区按仓库／层级组织。DOC章节1888个，只建立BM25。

关系总数34026：`{"CALLS": 22521, "CONTAINS": 5779, "IMPORTS": 5286, "INHERITS": 440}`。21780个去重调用位置的状态：`{"boundary": 2805, "possible": 4580, "resolved": 4053, "unresolved": 10342}`。

三个主checkout保留原有未跟踪内容，main本地与远端提交未变；本批文档在独立平行工作树修改。

## 真实API、费用和缓存

本轮新增 **88次请求，88次成功**，新增响应usage **1,037,055 token**；新增保守预留5,070,088。无新增认证、限流、计费或传输错误。

按继承配置每百万token 0.12美元计算：本轮usage估计 **0.124447美元**，本轮保守预留上界0.608411美元（小于授权约0.61美元）。继承台账累计186次尝试、预留10,834,261 token，累计预留费用上界1.300111美元，低于400请求／1500万token／2美元上限。以上不是账户实际账单或免费额度确认。

首个三库建库：78个真实成功批次，3895个新document向量；查询和隔离增量验证均使用同一全局台账。真实API响应校验模型、维度、顺序、有限数值和非零向量后缓存，没有随机占位。缓存键包含模型、dimension、dtype、input_type、truncation=false和输入文本哈希。未记录供应商不可变模型修订，兼容以这些已配置字段为界。

当前缓存：kind=`{'document': 3911, 'query': 12}`，origin=`{'historical-compatible': 6, 'voyage-api': 3917}`。旧实验相容query向量按完全相同输入复用；没有复制旧摘要充当新源码说明。无API密钥值落盘。

## HNSW与精确检索

当前语料 **26组**（层级／仓库过滤及K=10/50）与相同归一化float32向量的精确余弦比较：平均召回 **99.38%**，最低 **96%**。各层级的完整可用候选容量检查通过，不从很小的全局TopK再筛。指标只描述本批查询的近邻召回，不是语义相关性或独立质量评估。

度量：`cosine; normalized float32; exact uses dot product`；HNSW=`{'connectivity': 32, 'expansion_add': 128, 'expansion_search': 128}`，USearch实现，与Code Graph不同。详见current-hnsw-recall.json，历史60条query向量smoke仅是历史辅助证据。

## 当前源码检索观察

复用Q01/Q05/Q30的中文及英文扩展，增加模块、类、标识符、RE和混合层级问题。11个查询、33个渠道观测；10个有指定入口的case，混合case不虚构标签。指定入口回到当前源码核对，历史行号不作为真值。

| case | BM25指定入口排名 | dense排名 | RRF排名 |
| --- | ---: | ---: | ---: |
| Q01:zh | >10 | 4 | 4 |
| Q01:expanded | 2 | 3 | 3 |
| Q05:zh | >10 | >10 | >10 |
| Q05:expanded | 5 | >10 | >10 |
| Q30:zh | >10 | 2 | 2 |
| Q30:expanded | >10 | 1 | >10 |
| module | 1 | 1 | 1 |
| class | 1 | 1 | 1 |
| identifier | 1 | 1 | 1 |
| RE | 1 | 1 | 1 |

这里的>10仅指指定入口未在Top10，不代表所有返回项都错误。Q05的query_cell包装入口未进dense Top10，但其实际授权/可见性实现EnvironmentService.query_area在第3位，已读取当前源码验证。Q30英文扩展dense第1的resume_session在RRF Top10丢失，说明RRF未稳定优于单路。模块、类、current_weight标识符和RE evaluate在三个渠道均为第1。

扩大到完整候选页后，Q01/Q05/Q30扩展查询分别可查看13/18/17条BM25独有项及两个渠道排名；不是默认Top10中强行预留配额。DOC现行契约章节、仓库／层级过滤、all按层级轮流返回、node_id源码读取和CALLS→own_weight均实际执行。见retrieval-observations.json、channel-rank-acceptance.json和q05-alternate-entry-evidence.json。

## 真实向量增量与版本一致性

| 隔离首轮阶段 | 新向量输入 | 全局API请求 |
| --- | ---: | ---: |
| initial | 5 | 1 |
| member-docstrings-and-owner-inputs | 4 | 1 |
| addition | 2 | 1 |
| deletion | 0 | 0 |
| move-without-rename-inference | 5 | 1 |
| resume-unchanged | 0 | 0 |

修改成员说明时，4个变化输入覆盖相关module/class/function，未变化函数输入保持相同且不重请求；新增文件只请求新增module/function，删除不请求；移动按删除旧身份/新增路径处理，不假装通用重命名识别。旧节点、posting、边和向量分区映射一致清理。首轮计数见real-incremental-first-run.json。

同样6阶段又在最终程序下强制offline重放，全部复用真实缓存。候选发布前受控异常和独立进程os._exit(17)均保持旧dense/图/BM25版本可读，OS锁释放后恢复重建；旧游标先读保留版本、后在清理后明确过期；旧源码按索引快照返回并标记live_file_matches=false。见real-incremental-acceptance.json。

最终主索引两次offline更新均 **3895缓存命中、0新向量、0 API请求**；节点／倒排／边差异均0。保留当前及前一完整dense版本，二者与最终程序/config兼容。图与SQL posting按差异维护；AST传播和候选HNSW在更新时重建，不宣称所有更新计算严格局部。

## 运行验收

| 检查 | 实际结果 |
| --- | --- |
| pytest本地非网络回归32项 | exit 0，32.46秒；unit-tests.xml |
| Ruff lint与format --check | exit 0 |
| 真实HNSW/精确检索及真实增量6阶段 | 通过；没有随机向量 |
| MCP initialize、tools/list及五个工具 | 通过；stdout仅合法JSON-RPC |
| MCP三个层级dense/RRF | 六次真实调用通过 |
| 独立Codex会话 | index_status + dense/function + RRF/class均成功，dense_ready=true；codex-dense-events.jsonl |
| 本机MCP注册 | 绝对Python/入口路径，幂等；其他配置保留，配置旁有可恢复备份 |
| 缺失、格式/程序不兼容、源码漂移 | 明确状态/错误，不冒充最新 |
| 临时Git样例的新增/删除/移动、分页和进程中断 | 通过；未修改业务源码制造测试 |
| Engine/Data不同pin及目标新增Python | 分别核对且fail closed回归通过 |
| 备份/恢复/拒绝覆盖/校验损坏 | 本地回归通过；最终实包另记backup-result和backup-verification |
| RE严格MkDocs | exit 0，8.45秒，复用原锁定环境，站点在工具目录 |
| 新Markdown链接、围栏及git diff --check | 通过 |

初期修复的SQLite连接关闭、MCP中Git继承stdin、启动全库完整性校验过慢等问题已通过最终程序验证。普通查询只检查兼容性/产物存在和大小；完整校验保留在发布、备份和恢复。新鲜度检查由build或显式status(refresh=true)触发，普通查询仅报告最近检查，不遍历全部源码。

## 图与其他限制

- 静态数据流为12轮、表达式深度6和每轮工作量上限；当前未达全库固定点。保留已知possible和unknown，不能声称完整Python调用图。反射、任意装饰器、插件和复杂对象流仍有限。
- Engine和SRD Data pin分别核对；匹配HEAD时还检查未提交／新增Python。当前SM pyproject.toml及uv.lock均固定a011eba3...，与RE ab276ff...不同，所以不产生跨错版本精确边。第三方只保留边界，不索引其源码。
- 搜索是有界候选，has_more不代表穷尽仓库；RRF与中文检索仍有指定入口漏检，不宣称新索引优于历史实验。
- Embedding API写入按共享台账和锁串行；并发申请锁时可明确busy，未验收多用户吞吐。预算耗尽、认证或未知网络结果都保留可恢复缓存和明确错误。
- 供应商不可变模型修订、实际账户账单未核实；没有付费reranker、生成式摘要或游戏运行集成。
- 未修改SM/RE业务代码、docstring、依赖、Schema或规则，没有运行或冒称新的游戏全套／远程CI通过。

## Git与下次使用

| 仓库 | 工作分支 | 最终提交 | push |
| --- | --- | --- | --- |
| agentic-trpg | `docs/local-code-retrieval-tools` | `c7ebb7eab6b795f8bc1b998898db1c8be5dcd2b2` | 远程SHA一致 |
| trpg-state-machine | `docs/local-code-retrieval-tools` | `366f3f46e00bb12de9e38c6fea3e299555fa5b44` | 远程SHA一致 |
| trpg-rules-engine | `docs/local-code-retrieval-tools` | `333d625f8df633c85164eae22cbff128a612182a` | 远程SHA一致 |

仅五份Markdown进入项目Git：DOC的AGENTS/LOCAL_CODE_TOOLS/SYSTEM_OVERVIEW，SM与RE各自AGENTS。所有工具实现、测试、锁、图、向量、索引和报告在项目外。没有合并工作分支到main。

最少步骤：重开Codex会话，调用index_status后即可search_code（默认RRF）；当前旧聊天未热刷新，但独立Codex已实测。源码改动后执行update。

```powershell
& "<TOOL_ROOT>\.venv\Scripts\python.exe" "<TOOL_ROOT>\local_code_tools.py" status --refresh
& "<TOOL_ROOT>\.venv\Scripts\python.exe" "<TOOL_ROOT>\local_code_tools.py" search-code "ContainerService current_weight" --repo trpg-state-machine --mode rrf
```

迁移使用backup/restore：包内含程序、测试/问题材料、配置、依赖锁、真实向量缓存、两个完整索引及使用说明；排除密钥、虚拟环境和工作树。新机重建环境、修改路径、更新并重新注册，不假定复制venv可运行。备份最多两份，索引版本有界；gc清理不被保留版本引用的文档向量并限制查询缓存512项。详见USAGE.md。

## 最终实包校验

`<TOOL_ROOT>\data\backups\local-code-tools-20261026T220336.zip`，192,539,736字节；SHA-256 `a72c90ec211d5756035c7daf98524cd8a5ee6620e424d9c8a53d0bd5929dceab`。从ZIP逐项重读验证128个产物哈希，包含两个完整dense版本和24个向量二进制产物，确认无API密钥值、虚拟环境或工作树。完整核心及真实验收程序、锁和独立使用说明均在包内。包内验收报告为打包时版本；本节与backup-verification.json在打包后补充。
