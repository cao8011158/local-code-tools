# 下一会话交接：纠正解析重构方向

更新时间：2026-11-02，Asia/Shanghai。本文包含用户最后纠正，优先于本目录之前的实施方案。

## 1. 用户当前明确目标

全面审查解析系统，正确使用 Jedi 已有能力，移除自研的函数目标推断及比较／覆盖链。不能把任务改成“保留旧解析器，逐个修补并保持旧行为”。

- Jedi 提供明确、适用的目标时，按其 API 契约直接消费；不再让自研 `resolve/adjudicate` 二次决定是否采纳、过滤或覆盖。
- Jedi 原始无结果、外部边界、映射失败、查询错误分别记录；未知不是“可能连接所有函数”，也不是默认启动另一套解析器的理由。
- 来源、回调参数、容器写入／读取及增量依赖仍需记录，但这些职责不能成为保留另一套目标推断器的借口。
- 有具体证据的工具能力缺口单独列明并与用户讨论，不默认恢复旧的补充解析／裁决机制。
- 不把“旧测试通过、输出与旧版相同”当成架构替换完成。旧测试、旧文档、所谓精度保证都需按当前目标重新审查。

此前用户批准的是整体审查与重构；此后再次纠正“为什么还在比较自研规则与 Jedi”。上个 Agent 已承认方向偏差，并暂停开发 Agent。请勿直接接着旧 PR-2 header 修补／PR-3 自研事实求解器方案继续。

## 2. 已保存的通用 skills

- `refactor-goal-boundaries`（重构目标与职责边界）：https://chatgpt.com/skills?skill_id=6ae7c21543c081919ffb280ef2987b1f
  四点：用户当前目标优先；先明确职责取舍；先判断机制是否应存在再修复；验收证明废弃机制退出真实流程。
- `prefer-proven-tools`：https://chatgpt.com/skills?skill_id=6ae77e82f4e8819181241d904da99786
  默认信任成熟工具，按文档理解输出；补充处理要有证据，禁止以严谨或保险为由擅自扩大含义。
- 实施与独立审阅继续使用 `batch-dev-review`、`locality-review`。不能把它们理解为必须保留旧机制或旧测试结果。

## 3. 仓库、分支和保存状态

仓库：`agentic-trpg/local-code-tools`

| 项目 | 当前核实值 |
| --- | --- |
| 工作分支 | `feat/local-only-updates` |
| 最新远端实现提交 | `1e265a9a6e087b87299940c6815f9957b8ceac37` |
| 对应 tree | `b550b2a5cf0785c3a28fc956b9220e1f56657a05` |
| 实际合并目标 | `feat/local-code-tools-import` |
| 目标当前 SHA | `e3db45fcf1362f0a26e0ab7760b12b4fd408ce64` |
| 合并状态 | 尚未合并，没有假定合并授权 |
| 累计阶段记录 | `review/batch4-incremental/STAGE_REPORT.md`，本地最新到阶段152 |
| 本次审计目录 | `review/parser-refactor/` |

旧工作环境：`/workspace/scratch/45363df3617b/local-only-work`。这是物化树，本地 Git 基线不是远端祖先；不要据其直接 push/reset。发布曾通过 GitHub Git-data API，在远端 base tree 上增量写入，并保留653个未物化历史文件。新会话优先从真实远端分支恢复，或逐 blob 核实已有物化树。

固定副本：`pr1-review2-fixed` 为 `f617682...`，`pr2-review1-fixed` 为 `1e265a9...`。Python 命令使用对应目录下 `PYTHONPATH=. .venv/bin/python`，防止导入旧的 editable 安装。

### 未提交的半成品，必须识别

用户暂停时，工作树 `lct/python_analysis.py` 有一份定义头绑定修补，尚未提交、未完成冻结验证。它不是远端 `1e265a9` 的内容。

- 当前 SHA256：`3fcfc6ae93d8daa9d7d1952f6cd3d8910491c34f5ee7ccbc5d85043afbec22c4`。
- 完整差异另存 `PAUSED_UNCOMMITTED_HEADER_PATCH.patch`。
- 文件清单／哈希：`PAUSED_UNCOMMITTED_FILES.json`。
- 另外三个运行文件 graph/storage/unit_incremental 与固定远端一致。

不要丢弃半成品，也不要自动继续旧方案。先按新目标决定哪些部分仅服务来源记录、哪些应退出目标决策。

## 4. 已经做了哪些修改

### 之前已完成的 JD-1

取消按每个函数逐个扫描未知调用池；保留未知调用与原因，使用实际已观察的目标定位调用者。修正自研 UNKNOWN 无依据清除已知 Jedi 目标的问题。`60085dc0158d6ae26b21dfabddafa0d6b5ef9a3b` 为本次整体重构的起点。

### PR-1：只迁移了简单名称／别名

- `da91cfd...` 第一轮发现共享来源链反复定位；12层共享别名、20次调用从旧版32次查找变成260次。
- `f617682cf8d7046421fccd4884ebeed3a38e40f2` 修复共享后缀复用，恢复32次；来源按消费者记录。
- 第2轮独立审阅通过，794 passed、27 skipped、1 deselected；真实两消费者 first→second→缺失→first 局部更新及旧视图通过。
- 这只是部分路径迁移。中央 `adjudicate` 仍保留，不等于完成用户的架构替换目标。

### PR-2：容器来源／事件索引和原始工具结果缓存

最新提交 `1e265a9...`，生产主要改了：

- `lct/python_analysis.py`：按容器 origin 索引写入与相关调用／事件；简单字典读取使用已映射 Jedi 目标；隔离索引准备与消费者来源记录；原始 Jedi 观察与上下文映射缓存分离。
- `lct/graph.py`：部分工具优先分支与计数。
- `lct/storage.py`：相同捕获复用时清零新增工作计数。
- `lct/unit_incremental.py`：新 owner 没有旧树时，也进行 prospective writer origin 查询，修复新增文件写入不触发负读取消费者的问题。

确有性能证据的改进：

- 无关私有字典写入与同模块 noop 调用增长时，每次容器读不再枚举它们。
- 热更新 N0/20/100 无关调用时，选中 owner 均4，实际 Jedi 均1、query入口均2。曾经出现的1/21/101重复查询已修复。
- 一次 AST／索引准备、源文件挂载、哈希与完整快照序列化仍会随捕获规模增长，不能宣称整体 O(1)。

开发冻结98项定向、810项快速通过。固定远端独立快速810 passed、27 skipped、1 deselected，154.11秒；但下面的独立反例失败，因此 PR-2 正式第1轮为 **changes_required**，并未通过。

这些改进可逐项评估复用；不能因为它们通过测试，就保留不符合当前目标的旧目标解析／裁决机制。

## 5. 为什么暂停：正确 Jedi 结果被自研覆盖

完整源码都已提供的最小例子：

```python
def first(): pass
def second(): pass
def third(): pass

handlers = {'go': first}
old = handlers

def sentinel(x=(handlers := {'go': second})):
    pass

handlers['go'] = third

def run():
    old['go']()
```

`old` 仍指向第一个字典，因此目标是 `first`。Jedi 实际也返回且精确映射 `first`。自研来源规则漏掉默认参数中立即执行的赋值，把后来对新字典的 `third` 写入归到了旧字典，标记完整，并通过 `tested-semantic-rule` 排除 `first`、选择 `third`。

原 `f617682` 同样错误，不能将其当成正确基准。已确认问题：`PR2-DEFINITION-HEADER-ORIGIN`，P2。代码位置：`Analyzer.named_bindings` 跳过定义头，新的 `_index_module_literal_bindings` 也漏计这些绑定。

旧方案准备补上 header，再保留原来的比较／覆盖链。**用户明确指出这仍在维护要废弃的机制。当前优先任务是移除目标裁决权；来源身份是否正确是独立义务，不能反过来决定是否接受 Jedi。**

证据：`pr2-header-origin-alias-{baseline,candidate}.log`、`PR2_REVIEW.md`、`PR2_EVIDENCE.json`、独立测试 `test_definition_default_rebinding_does_not_mutate_earlier_alias`。

## 6. 已确认的能力边界和另一个缺口

直接 Jedi0.20.1 测试已证明：普通字典字面量、直接下标写入、first→second替换、简单别名、回调参数、默认值、返回函数、普通方法等可以给出目标。不能默认再用自研引擎重算。

`infer` 容器接收者通常返回 `builtins.dict` 类型；`goto/get_references` 返回名称位置／引用，不能直接当成跨别名、参数、返回值的统一 allocation ID。具体数据在 `PR2_PROBES.md/.json` 与 `pr2_probe.py`。这些证据说明来源记录需求，不能用来授权第二套目标裁判。

另一个已复现、原版本也有的组合缺口：

```python
def first(): pass
def execute(callback): callback()
R = {}
def register(key, fn): R[key] = fn
register('go', execute)
def run(): R['go'](first)
```

旧自研补充能给出 R['go']→execute，但 execute 中 callback 没连到 first；这两个位置的原始 Jedi 结果都为空。原 PR-3 草案拟增加自研已证明调用事实索引和选择性重算。**该草案已因用户纠正而暂停，不应默认实施。** 新会话应重新核对 Jedi 的正确用法、列出实际能力缺口，与用户讨论需要的能力边界。证据：`pr3-composed-callback-{baseline,preflight}.log`、`PR3_DESIGN.md`。研究稿不是批准的实现方案。

## 7. 下一会话应如何继续

1. 先阅读并执行新 skill 和用户纠正，重写职责取舍清单，明确 Jedi 为目标解析提供者，旧系统哪些路径应退出。
2. 从 `Graph.build`、`Analyzer.query/map_name/resolve/adjudicate/caller_atoms` 及参数、返回、字段、容器路径追踪真实调用。不要仅删方法名或重命名为“来源收集”，却继续执行相同推断。
3. 按工具 API 的真实契约消费输出与映射节点；区分无结果、外部边界、映射失败和工具错误。保留一次观察的复用与实际输入变化后的失效。
4. 将必要来源／增量记录独立出来；检查这些记录确实被反向查询／调度消费。保留普通更新的函数级局部路径，不恢复白名单准入或自动全量回退。
5. 按新契约审查旧测试。实际入口应证明旧目标推断、比较／覆盖链已退出；正向功能、错误边界、来源依赖、负读取、新增／删除写入、旧视图及发布失败仍需验证。
6. 再安排分批实施和独立审阅。不能仅继续旧 PR-2/PR-3 待办、修到旧回归全绿。

历史审阅不能抹掉：JD-1第2轮通过、PR-1第2轮通过、PR-2第1轮要求修改；更早LO2第3轮通过。用户纠正后需明确新实施边界，不能通过改编号重置原问题整改链。

## 8. 未完成的规模验收

完整 SM 输入来自 `agentic-trpg/trpg-state-machine` 的 `a7b0804d5635e185a79ff3c1d1fa6241c2b858fe`：83个src/**/*.py，共1,207,159字节，已逐blob/SHA256固定。旧环境在 `task-evidence/sm-full-fixed`，来源记录 SOURCE_PROVENANCE.json。

完整83首次图尚未完成，因此后续warm／查询整体验收也未完成。之前180/240秒限时未完成；90秒cProfile因显著测量开销，只走到456调用准备、457真实Jedi、尚无容器检查，不能证明剩余耗时都来自容器或Jedi有缺陷。不要盲目延长相同长测或提高20k预算。

旧 JD-1 九文件保存快照比较曾通过，但新重构runtime的九文件完整生命周期未完成；旧输出不能冒充新代码验收。快速回归中明确deselect的就是这个昂贵用例。

常用快速命令见最新 `pr2-warm-fixed-fast.status.json`；要核对当前 SHA、实际输入及测试契约后再运行。整体建图、正确性和性能均不得宣称全部完成。
