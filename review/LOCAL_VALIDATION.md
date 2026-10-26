# 本次源码上传的本地验证

实际执行时间：`2026-10-26T22:40:07Z`（UTC；本地日期2026-10-27）。**本地验证，不是独立代码审阅结论。**

被测源码提交：`b3e6fd7ae26b1c64299bfa371bfbee87f7ef37e4`。运行核心指纹：`42ae0f3336e274d94aa6dbdcb59652f1dfbc5f97eab11602e6b45a17697a8c03`，与已有实库相同。原lct实现、锁、CLI入口及注册脚本逐字节未变；新增测试和只读验收工具不重写检索行为。

最终报告提交只补充本报告及JSON/XML。被测源码/测试仍对应上述提交；逐文件SHA-256和实际命令见local-validation.json。

## 实库身份，数据不上传

索引 `20261026T215543-7961d6f6d2`，工具1.0.0，schema=1、format=1、template=`source-docstring-v1`、tokenizer=`camel-snake-latin-han-uni-bi-v1`。

模型：`{'dimension': 1024, 'dtype': 'float', 'model': 'voyage-code-4'}`；HNSW：`{'connectivity': 32, 'expansion_add': 128, 'expansion_search': 128}`；度量：`cosine; normalized float32; exact uses dot product`。配置指纹 `6c92b69311cbc88e2581c5c779ea058cc65faf6791c2bc18ddb6b384406a82ea`；源码内容根 `244958da7016f00a1fc0b510d8c5b46171cff831c484ddf15bb7ed0026dccaa7`。本次只读重算源码与索引匹配：True。

| 仓库 | 提交 | 本次工作目录状态 |
| --- | --- | --- |
| agentic-trpg | `ac2a0e41ec99bcc78d4fa608287fb4e7ea7fd436` | `main`；tracked changes=0，untracked entries=2；保持原状 |
| trpg-state-machine | `4166e52f0809ae80ba1694295bb0739acec76bd8` | `main`；tracked changes=0，untracked entries=2；保持原状 |
| trpg-rules-engine | `ab276fffc5ff02a973e1c767543e712dd0897451` | `main`；tracked changes=0，untracked entries=1；保持原状 |

路径用`<WORKSPACE_ROOT>`脱敏，私人未跟踪文件名省略；提交、指纹和测量值没有改写。

## 新执行结果

| 检查 | 实际结果 |
| --- | --- |
| 当前checkout无key离线pytest | 35 passed、1 skipped，exit 0；unit-tests.xml |
| 干净clone安装 | uv sync --locked --offline成功；新环境，无原config/data/reports/workspaces |
| 干净clone无key离线pytest | 35 passed、1 skipped，exit 0；clean-checkout-unit-tests.xml |
| 跳过项 | 明确需要已有真实历史缓存的opt-in测试；不能记作通过 |
| 合成示例 | 实际构建BM25/图/HNSW并跑BM25/dense/RRF及DOC；API请求0；不是质量证据 |
| 实库代码和DOC检索 | 完成11个查询、33个渠道观测，仓库/层级过滤通过；入口排名见下表 |
| 分页 | 下一页绑定同一索引版本；has_more只代表候选集 |
| node_id源码定位 | current_weight当前文件哈希匹配，保留行号及内容指纹 |
| 图查询 | current_weight→own_weight；有限解析样例、basis/status和未解析统计均保存 |
| HNSW/精确检索 | 26组K=10/50；平均99.38%，最低96% |
| 实际stdio MCP | initialize、tools/list及五个工具调用通过，覆盖模块/类/函数 |
| 真实数据保护 | 23个受保护文件前后SHA-256相同；原51个文件集合成员/大小/mtime保持 |
| 隔离变更/删除/移动、不兼容、发布失败、进程中断/恢复 | 临时合成Git仓库和索引中通过；没有改真实库制造故障 |
| 新Embedding/真实索引重建 | 未运行；按用户指令禁止，API台账未变 |
| 三业务仓库 | HEAD、分支、origin和工作目录状态均与任务开始一致 |

默认运行：`uv sync --locked`，然后`python -m pytest -q tests`；合成示例：`python -m tests.synthetic_demo --output <新目录>`。不需要真实数据或key。实库只读命令见README，缓存缺失即拒绝。完整命令见JSON。

实库/MCP以tools/readonly_cache.py替换验收进程的缓存I/O为mode=ro并禁止API；生产源文件、排名/归一化/过滤不改。SQLite生成了SHM和空WAL协调旁文件，留在本地并忽略；没有删除或移动原文件。

## 指定入口的Top10排名

| case | BM25 | dense | RRF |
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

这是复用问题的本地观测，不是穷尽相关性真值。>10不表示返回项全部错误；Q05的query_cell包装入口漏检，但相关query_area实现可在前列。Q30扩展的dense第1入口在RRF Top10丢失，不能宣称RRF稳定优于单路或新索引优于历史实验。

调用边状态：`{'boundary': 3149, 'possible': 4977, 'resolved': 4053, 'unresolved': 10342}`。静态传播有轮数/深度/工作量上限，反射、插件、任意装饰器和复杂对象流仍可能未解析。

## 上传与历史边界

只上传实际源码、锁、问题/预期入口、合成样例和紧凑材料；不上传真实节点/图数据集、向量、索引、缓存、备份、压缩包、虚拟环境或本机配置。此前目标私有仓库为空，没有提交/分支/Release/附件，数据库从未进入其历史。此次不创建Release，不改写历史或force push，不合并分支。

historical/保留旧报告原日期及原件/脱敏副本SHA-256，不将旧测试改日期当作新测试。首次干净clone自定义--basetemp父目录缺失导致测试命令失败；创建该临时父目录后在相同提交重跑通过，没有修改实现。

未验证：新的Embedding API行为、全新电脑/所有平台、多人吞吐、独立人工审阅或远程CI。明确跳过项和检索/静态图限制均保留。
