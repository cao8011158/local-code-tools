# Python 代码关系分析工具选型与可靠性验证

**结论：目前没有一个候选满足可靠 CALLS 的直接接入条件。本次不选定正式调用图工具，不接入、替换或重建任何正式图。**

Jedi 可继续作为**名称/类型推断候选信号**试验，Pyan3 可继续作为 **USES/DEFINES 关系来源**试验；二者都不是经本实验验收的完整调用图。当前实现仍有基础错误连接和虚假确定性，不能作为标准答案。没有以统一 CALLS 名义混合三者输出。

本报告是本机实验结果，不是独立代码审阅结论，也不是远端 CI 结果。

## 1. 被测版本、范围和预先固定的标准

- 开始基线及远端最新源码均为 `6eeed5d58780907409399d2dfdddfc2b4084da4a`，工作区干净。新建 `experiment/python-graph-analyzer-evaluation`，没有回退、覆盖、合并或改写历史。
- 先读本仓库 README、实际 `lct/graph.py`、`extract.py`、`common.py`、已有图测试，以及 `review/LOCAL_VALIDATION.md`、历史验收和发布边界。祖先/工具仓库未发现另一个适用 AGENTS.md；SM 提供的约束用于保障只读业务仓库边界。
- **答案先于运行**：`46e80ba` 提交 39 个合成位置、11 个真实位置及原始 fixture；之后才添加并运行适配层。`truth-freeze.json` 保存 7 个文件的 SHA-256，后续每次运行必须相符。没有按结果删改难例。
- 本次最终完整测量的实验源码提交：`93977a8f0159cb89b10dede2c37f5f10201bb753`。该提交内实验代码内容指纹：`4fe697bcb4a7f9af02c4adda0a6379218bd8b9bd18d9ca2313633c40cc470872`，定义及逐文件值见 JSON 和 preservation 清单。最终材料提交仅调整实验说明并新增报告/实际输出；实验可执行代码保持被测版本，不把最终提交 SHA 循环写入自身。
- 正式程序内容指纹仍是 `42ae0f3336e274d94aa6dbdcb59652f1dfbc5f97eab11602e6b45a17697a8c03`，1.0.0；原 `lct/`、正式 MCP、根 pyproject/uv.lock 均未改。
- 最终完整运行开始：`2026-10-27T00:15:09.919100+00:00`；Python 3.12.14、Windows、独立 uv 环境。实验版本锁在 `experiments/python_graph/uv.lock`。本轮实验脚本已提交；运行时只有上轮生成的报告 JSON 尚未跟踪，不参与分析。

合成集合有 **44 个应存在的模块/类/函数/匿名函数节点，36 个标注调用（含一次隐式装饰器应用）、3 个纯引用位置**。完整 oracle 明确：合法目标、禁止目标、部分候选/未知输入、执行所属上下文和定义时/函数体阶段。参数已知用例采用明示的闭合合成驱动假设；混合/遮蔽参数及真实宿主回调保持开放未知。

字符串调用会报 TypeError、裸名称会报 NameError：这仍是应该记录的调用尝试，但不存在它们所误连的合法函数目标。函数参数绑定错误也不被适配层用来凭空改造目标。没有执行这些刻意无效的 fixture。

## 2. 官方来源、维护、许可证和输出语义

版本/发行日期/包 SHA-256 和官方仓库元数据见 [official_sources.json](../experiments/python_graph/official_sources.json)。截至本次核对：

| 候选 | 固定版本、维护证据 | Python / 许可证 | 原生输出及用途 |
| --- | --- | --- | --- |
| 当前自写 Graph | 本仓库 1.0.0，stdlib AST 有界单调 points-to | 正式程序要求 3.12；本仓库未提供独立 LICENSE 授权文件 | CALLS / IMPORTS / INHERITS / CONTAINS，含源位置和 status；有轮数/深度/工作量限制 |
| Jedi | 0.20.1，PyPI 2026-10-12 发布；官方仓库未归档，pushed_at=2026-10-25 | 包要求 >=3.10；安装包 LICENSE.txt 为 MIT | `get_names()`、`infer()`、goto/references；这里测试定义枚举及给定表达式位置的推断，不是完整调用图 |
| Pyan3 | 2.9.0，PyPI 2026-10-06 发布；Technologicat/pyan 未归档，pushed_at=2026-10-26 | 包要求 >=3.10,<3.16；发行包 SPDX 为 GPL-2.0-or-later，GitHub 自动标识 GPL-2.0 | functions/classes、USES/DEFINES；上下文聚合边没有实际 use/call 位置，不标注确定性 |

Jedi 的官方 [API](https://jedi.readthedocs.io/en/stable/docs/api.html) 和 [限制](https://jedi.readthedocs.io/en/stable/docs/features.html) 说明其名称推断/编辑器用途，推断会有复杂性上限。Python 约束核对自 [Jedi 0.20.1 发行包](https://pypi.org/project/jedi/0.20.1/)。原根项目锁的 Jedi 0.19.2 保持原状，本实验另装 0.20.1。

Pyan3 的 [官方仓库](https://github.com/Technologicat/pyan) 和 [2.9.0 发行包](https://pypi.org/project/pyan3/2.9.0/) 给出 uses/defines、静态 MRO、现代语法及输出能力。本实验使用 `CallGraphVisitor.from_sources(..., cull_subsumed_edges=False)`，保留原始聚合边，未安装 Graphviz；没有拿图形布局当作分析能力。正式接入前仍须核对许可证兼容边界。

[PyCG 原仓库](https://github.com/vitsalis/PyCG) 的 API 元数据确认 archived=true、最后 pushed_at=2023-11-26；本轮未选用它，也未声称任何未核实分支是维护中的后继者。没有为凑推荐增加第四个候选。仓库活动时间不是维护质量保证；跨 Python 版本兼容性没有由本次 3.12 运行外推。

## 3. 指标含义与完整失败记录

下面的 TP/FP/FN 只评价**有完整人工答案的合成调用位置上的目标集合**，不包含部分目标、纯引用、执行 owner 正误或全库准确率。当前实现采用原生 CALLS；Jedi 是“在语法位置查询到的 callable 候选”指标，两者语义不同。Pyan USES 不能给出调用位置，因此不计算 CALLS precision/recall，也不把所有 uses 强行投射为该处的调用。

| 候选 | TP / FP / FN | precision / recall | 未知来源被原生标为确定 | 所需节点覆盖 |
| --- | ---: | ---: | ---: | ---: |
| 当前 Graph 1.0.0 | 28 / 3 / 6 | 90.32% / 82.35% | 1 | 43/44 |
| Jedi 0.20.1 | 30 / 1 / 4 | 96.77% / 88.24% | 0 | 43/44 |
| Pyan3 2.9.0 | 不适用 | 不适用 | 0 | 44/44 |

- 当前 **3 个目标误连**分别为字符串→target、方法裸名→A.work、无条件重赋值后仍保留旧 target。另有 **1 个独立执行上下文错误**：lambda 内调用记在 lambda_factory；不能用 90.32% 掩盖它。
- 当前 **6 个正确目标遗漏**：跨文件注册表、staticmethod 回调、super、返回 lambda 的调用、裸装饰器应用和默认 make()。其中默认调用完全没被位置目录记录；隐式装饰器也没有原生 CALLS。
- 当前 callback_mixed 把 `[target + 未知来源]` 的已知部分标成 `resolved`，是关键验收失败。收敛到一个已知值不证明没有未知值。
- Jedi 的 **1 个错误候选**为 `A.construct()` 得到 `builtins.classmethod.__get__` 而非 `A.construct`；**4 个目标遗漏**为跨文件注册表、nested inner()、返回 lambda 的调用及该 classmethod。没有事后把描述符重新推断回方法。
- Jedi/Pyan 不输出“候选已穷尽”的证明，所以适配结果一律不声称确定。表中零“虚假确定标记”仅表示没有这种声明，**不代表它们证明了未知来源传播完整**。
- Pyan 在 `A.bare` 中仍产生对 `A.work` 的错误 USES。这是基础名称绑定错误；引用/函数体依赖聚合又使 USES 与 CALLS 无法等同。`reassignment` 使用过 target 是合法 USES，不能把它算成 Pyan 原生调用误连。

实际输出逐位置保留目标、上下文、位置、预期/差异、原始状态、用途和不确定性。每个位置都有记录；找不到候选明确保持未知/未解析，不能解释为无调用。

### 3.1 调用位置与执行阶段

当前合成语法有 38 个显式调用位置，原生目录保留 37 个；缺 make()。另有 3 个裸装饰器应用（含内建 staticmethod/classmethod），没有相应原生调用边。36 个标注调用中 34 个有原生位置记录，默认/裸装饰器缺失。匿名 lambda 节点也缺失，body 被归给外部函数。

Jedi 的 infer API 接收位置而非产生调用清单：适配层以 AST 给出 36 个标注调用及引用位置，然后查询全部位置，执行 owner/phase 也来自语法目录，不记成 Jedi 的原生调用图能力。`get_names` 未枚举所需 lambda 节点，仍记录缺失。

Pyan 的所有 USES 边均保留 `callsite=null`；目标节点的 definition_line 不是使用位置。它确实枚举了所需 lambda 节点及 lambda→target 的 USES，但这不等于回调调用能被解析。默认 make 和装饰器 decorate 同时出现在 module 和 decorated 的 USES 中，表示依赖聚合；如果转成 decorated 的函数体 CALLS，就会错误改变执行时机。该转换本次没有实施。

### 3.2 至少 17 类模式的结果

以下“Jedi 候选”“Pyan USES 命中”分别只描述其原生语义，均不代表确定 CALLS 通过。

| 模式 / fixture id | 当前 Graph | Jedi | Pyan3 |
| --- | --- | --- | --- |
| 1 普通直接 direct | 正确 CALLS | target 候选 | target USES |
| 2 函数别名 alias | 正确 CALLS | target 候选 | target USES |
| 3 同名字符串 string | **错误连 target/resolved** | str 实例，无函数候选 | 没有 target USES；仍无调用位置 |
| 4 已知回调 callback_known | target/resolved | target 候选 | 仅未知 argument，遗漏 target |
| 5 已知+未知 callback_mixed | **唯一 resolved 错误** | 仅已知 target 候选，未知是否被推断覆盖无证明 | 未知 argument，丢已知 target；不声明确定 |
| 6 字典固定/动态 dict_fixed/dynamic | 固定 target / 动态两个 possible | 固定 target / 动态两个候选 | 引用聚合含字典两个函数；无法区分固定键的实际调用 |
| 7 跨文件注册 registry | 未解析，遗漏 target | 未解析，遗漏 target | handlers USES，无 target 调用 |
| 8 导入别名/同名/遮蔽 import_alias/shadow | 别名正确；未知参数不误猜 | 相同已验证边界 | alias USES 正确；参数为未知 |
| 9 类/实例/静态方法 | 普通方法正确；**静态回调遗漏** | 静态回调有 target；**classmethod 描述符候选错误** | 类方法依赖可见；静态回调未知 |
| 10 方法裸名 bare | **错连 A.work** | 无 target，保留调用尝试 | **A.work 错误 USES** |
| 11 继承/super | 覆盖 Child.run；super 未解析 | Base.run 候选 | Base.run USES，非调用位置 |
| 12 嵌套/闭包/lambda/返回函数 | inner/返回 target 部分成功；lambda owner 错、lambda 调用漏 | 返回 target 成功；inner()、lambda 调用遗漏 | nested/lambda 节点和 body USES 可见，返回 lambda 的调用无证明 |
| 13 装饰器/默认调用 | **默认和隐式装饰器调用缺失** | AST 辅助下得到 make/decorate 名称 | module 与 function 双重 USES，不能推出执行阶段 CALLS |
| 14 分支/重赋值 | 分支两候选；**重赋值残留旧目标** | 两候选 / 只得 other | USES 保留两个引用，不能作为“最终调用” |
| 15 仓库外 json.loads | 显式 boundary，保留表达式 | json.loads 候选/stdlib 定义来源 | 未解析 loads USES，边界信息较弱 |
| 16 纯引用 assignment/container/factory_return | 不伪造 CALLS；不提供普通 REFERENCES 边 | 三处引用名称可查到 | target/other USES 可见，与调用不区分 |
| 17 SM→RE / 不同 pin | 匹配时连内部；错版时 boundary | 两种 pin 均可推断本地同名函数，不验证 pin | 两种 pin 均有本地 USES，不验证 pin |

## 4. 真实源码验证：按使用模式选，不按工具成功选

三个仓库均只读。扫描沿用配置模板的显式 code_roots，排除测试、worktree、第三方和生成目录；读取 Python 和元数据，不读真实节点数据库。架构文档仓库 code_roots=[]，因此 Python 数为 0，没有伪造第三个仓库的代码样例。SM 90 文件、RE 196 文件，共 286 文件。

| 仓库 | 实际 HEAD | 状态 |
| --- | --- | --- |
| agentic-trpg | `ac2a0e41ec99bcc78d4fa608287fb4e7ea7fd436` | `main`，tracked=0，untracked=2 |
| trpg-state-machine | `4166e52f0809ae80ba1694295bb0739acec76bd8` | `main`，tracked=0，untracked=2 |
| trpg-rules-engine | `ab276fffc5ff02a973e1c767543e712dd0897451` | `main`，tracked=0，untracked=1 |

个人未跟踪文件名脱敏，原文件与状态保留。SM 锁定 RE 为 `a011eba3ea2226e22d8081294ee38d3ec193b325`，并非上表 RE HEAD。所有跨仓库本地目标都应保留此身份差异。

先从源码选择不同语义类别：public sink 交付、可变命令/turn hook 注册表、lambda 执行时机、super 继承、局部构造及跨模块 classmethod。逐项人工预期及最小原文见 [real_truth.json](../experiments/python_graph/real_truth.json)，目标核对依据包括 `_LiveCombat.lifecycle = field(default_factory=TurnLifecycle)`、CombatComputation.emit 定义、from_application 定义和 SM uv pin。没有使用旧 graph 推导预期，也未用一次运行未覆盖路径来否定静态边。

位置中的列为 0-based，行 1-based；相对文件属于所列 source repository。

| ID | 文件与调用/引用位置 | 限定上下文 | 预期依据 |
| --- | --- | --- | --- |
| R01 | `src/trpg_state_machine/events.py:143:12` | `trpg_state_machine.events:EventRuntime.deliver_event` | Keyword-only external sink callback; targets cannot be enumerated. |
| R02 | `src/trpg_state_machine/commands.py:561:17` | `trpg_state_machine.commands:world_command_from_data` | Literal OPERATIONS and admission prove these two alternatives; table updates supply more. |
| R03 | `src/trpg_state_machine/rules_adapter.py:518:21` | `trpg_state_machine.rules_adapter:RulesAdapter._evaluate_dnd` | SM pins a011eba and local RE HEAD differs; imported name does not prove identity. |
| R04 | `src/trpg_state_machine/errors.py:20:21` | `trpg_state_machine.errors:StateMachineError.__init__` | Local lexical dataclass construction, represented by class node. |
| R05 | `src/trpg_state_machine/grid_maps.py:166:8` | `trpg_state_machine.grid_maps:ReadOnlyTopology.__init__` | GridTopology base belongs to pinned RE; current local RE is another revision. |
| R06 | `packages/dnd5e-engine/src/dnd5e_engine/live_attack_riders.py:343:4` | `dnd5e_engine.live_attack_riders:register_rider_hooks` | _LiveCombat.lifecycle has TurnLifecycle default factory; registration does not execute the lambda. |
| R07 | `packages/dnd5e-engine/src/dnd5e_engine/live_attack_riders.py:345:30` | `dnd5e_engine.live_attack_riders:register_rider_hooks.<lambda>` | Called in lambda body, not registration body. |
| R08 | `packages/dnd5e-engine/src/dnd5e_engine/turn_lifecycle.py:114:12` | `dnd5e_engine.turn_lifecycle:TurnLifecycle.run` | Public mutable per-instance hook registry can receive arbitrary host callbacks. |
| R09 | `packages/dnd5e-engine/src/dnd5e_engine/evaluation_shield.py:249:8` | `dnd5e_engine.evaluation_shield:ShieldComputation.emit` | Imported explicit base and MRO; first super.emit site in emit is annotated. |
| R10 | `packages/dnd5e-engine/src/dnd5e_engine/live_effect_lifecycle.py:43:39` | `dnd5e_engine.live_effect_lifecycle:register_effect` | Imported class has this actual classmethod definition. |
| R11 | `src/trpg_state_machine/commands.py:89:18` | `trpg_state_machine.commands:<module>` | OPERATIONS stores class object without constructing it. |

实际判断：

- R01 sink 与 R08 hook：目标不能穷举。当前保留 unresolved；Jedi 空结果；Pyan 有 aggregate 依赖/argument 标记。本实验仍记录两个调用位置，未解释成“不存在调用”。
- R02 命令分发：当前与 Jedi 均找到人工确认的 MoveActor/UnlockDoor；还有多个候选。Pyan 看到了 OPERATIONS 依赖但未到达这两个 class target。人工只给出部分目标，因此没有据此给全体候选打准确率。
- R03/R05 跨仓库：当前守住错版 boundary；Jedi/Pyan 指向本地 RE 的 evaluate/GridTopology.__init__。这是未经依赖身份验证的信号，不能标成实际 pinned RE 的确定调用。
- R04 局部 Issue 构造：三者均找到相应原生语义下的名称/使用。
- R06 注册方法：当前/Jedi 得到 TurnLifecycle.register；Pyan 只有未知 register 及相关依赖，未得到该目标。R07 lambda 内 expire：三者都出现目标名称，但当前把执行 owner 记在 register_rider_hooks，重现合成 lambda 上下文问题。
- R09 super.emit：当前遗漏 CombatComputation.emit；Jedi 名称候选及 Pyan USES 均含正确基类方法。
- R10 classmethod：当前/Pyan 得到 from_application 目标；Jedi 返回内建 classmethod.__get__，真实样例也复现描述符问题。
- R11 仅引用 MoveActor：没有任何适配结果将 Pyan USES 或 Jedi 引用候选升级为 CALLS；当前本来没有普通引用边。

当前在全扫描中报告 `fixed_point=false, analysis_limited=true, iterations=12`；所以此轮真实样例不能用来证明全库已收敛。只做语法位置盘点：21,789 个显式调用中当前记录 21,780 个，另有 166 个裸装饰器应用；这些是位置覆盖统计，不是目标准确率。**三个真实仓库没有完整人工关系真值，不报告全库 precision/recall。**

## 5. 实际耗时、内存及适配工作

| 范围 | 工具 | 包含启动的 wall time | 采样进程树 RSS 和 | 最大同时进程数 |
| --- | --- | ---: | ---: | ---: |
| synthetic | current | 0.576 s | 27.32 MiB | 2 |
| synthetic | jedi | 3.215 s | 108.57 MiB | 5 |
| synthetic | pyan3 | 0.539 s | 33.23 MiB | 2 |
| real | current | 11.421 s | 235.29 MiB | 2 |
| real | jedi | 34.795 s | 421.41 MiB | 5 |
| real | pyan3 | 20.420 s | 360.47 MiB | 2 |

每个候选用独立进程，默认 180s 上限。RSS 是以 25ms sleep 采样的 launcher+worker+辅助进程 working-set 之和，不是精确峰值，共享页可能重复计数；采样本身有开销。当前/Pyan 构建全部范围的内存关系，Jedi 枚举 286 文件定义但仅在 11 个真实标注位置推断，因此这些数字**不是等工作量排名或吞吐基准**。只测本机单次最终运行，未测所有 Python/平台、冷暖缓存重复统计或多人吞吐。

实际适配层分工：worker.py 收集候选原始对象、名称/位置映射和 JSON；syntax.py 只枚举语法/执行 owner；run.py 管理独立源计划、子进程、超时和观测；export.py 只选择已标注证据及聚合计数/脱敏。没有在适配层添加 points-to、回调传播、字典推断或描述符回推，然后归功于候选。

| 未来用途 | 可以使用的信号 | 缺失与接入成本 |
| --- | --- | --- |
| Jedi 辅助名称解析 | 直接/别名、简单方法、部分回调、super、引用处的定义来源 | 需要独立 AST 调用目录与执行阶段，正确项目 sys.path/依赖版本，稳定 node identity、原始来源、超时和错误预算；所有结果默认 possible。必须先调查 classmethod/inner/lambda/注册表失败和未知穷尽性，不能把“一个候选”升 resolved |
| Pyan USES/DEFINES 图层 | 定义/嵌套/匿名函数、引用与依赖、部分继承属性使用 | 必须保留独立关系种类，不能服务要求实际调用位置/阶段的 CALLS 查询；需修复或上游核对 bare 名称错误、注册表及参数数据流；若要 callsite，需上游提供事件/位置而非在适配层猜测；另核对许可证边界 |
| 当前 Graph 改进调查 | 已有原生位置、错版依赖边界、直接/映射部分解析 | 先分别修复字面量与前向注解混用、类词法作用域、默认/装饰器执行目录、staticmethod、未知来源传播、重赋值 kill、lambda owner；本轮未实施任何修复 |

这不是“小改输出格式即可获得可靠调用图”的情况；本实验采集适配并不等于生产接入完成。当前没有证据支持估算生产改造人日。先用冻结清单验证各项修复/上游响应、补充真实回调完整性研究，再决定是否引入分层关系提供器。若继续调查其他维护中的工具，必须重新核对维护者/版本/语言兼容并运行同样的先验标准；不直接切到归档 PyCG。

## 6. 验收门槛、执行成功与能力失败

进入正式 CALLS 阶段至少需要：基础误连为零；未知来源不冒充唯一确定；定义时与 body/lambda owner 正确；调用尝试位置完整且未解析可见；依赖源码版本绑定；注册表/回调不足明确暴露。**三者均未达到，所以不进入正式接入阶段。** Jedi/Pyan 可作为后续受限信号源候选，不能从它们没有确定性字段推导“可靠性已通过”。

- 最终合成、匹配 pin、错配 pin、真实源扫描共 **12 个候选进程 completed**；没有 timeout/skip，worker 的 socket connect 尝试计数均为 0，未调用付费 API。
- 实验框架 **7 passed，0 failed / error / skip / xfail**，JUnit 见 [python-graph-harness-tests.xml](python-graph-harness-tests.xml)。框架检查冻结答案、位置与 owner、真实候选执行、原始语义和失败保留；这些通过不表示候选能力验收通过。
- 只对新增实验脚本运行 ruff check/format；最终通过。没有运行正式检索测试、重建/更新索引、注册 MCP 或安装正式环境依赖。
- 早期非默认 `Jedi.fast_parser=False` 设置触发 get_names 的 KeyError；恢复默认并逐文件保留枚举异常后，最终全量重跑无枚举异常。这不算候选默认配置能力失败，也没有删除 fixture。
- 早期适配的同列嵌套调用碰撞、包 __init__ 前缀优先级以及 Windows launcher-only RSS 被发现后修正并完整重跑；上面的数值只使用 `93977a8f0159cb89b10dede2c37f5f10201bb753` 的最终结果，初步日志留在 ignored .tmp，不伪装成最终证据。
- 未验证：全库目标准确率、所有动态/反射/插件模式、其它工具或 PyCG 分支、跨 Python 版本、OS 级所有子进程网络抓包、远端 CI、独立人工审阅。worker 的 socket guard 不等于 OS 网络沙箱；没有供应商 key、Embedding 客户端入口或 API 台账变化。

## 7. 独立复现

在本仓库根目录运行；不需要真实数据库、缓存、API key 或正式环境：

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) '.tmp/python-graph/venv'
uv sync --locked --project experiments/python_graph
Remove-Item Env:\UV_PROJECT_ENVIRONMENT
$py = '.tmp/python-graph/venv/Scripts/python.exe'
& $py -B -m pytest -q experiments/python_graph/tests
& $py -B experiments/python_graph/run.py --output .tmp/python-graph/reproduce
```

输出目录必须尚不存在。复核同版本真实源码时，再用：

```powershell
& $py -B experiments/python_graph/run.py --output .tmp/python-graph/with-real --workspace D:\Projects\agentic-trpg --timeout 180
& $py -B experiments/python_graph/export.py --input .tmp/python-graph/with-real --output .tmp/python-graph/reproduced-evidence.json
```

真实样例/依据源码 SHA 不匹配会拒绝，不能在另一个版本上把旧答案当真；先保留原清单，再人工增补新的版本化标准。Unix 环境变量设置及 venv/bin/python 入口见实验 README。无 Graphviz、数据库或模型 API 的安装/运行前提。

## 8. 文件与保护结果

- [experiment README](../experiments/python_graph/README.md)、固定 uv.lock、39 位置 oracle/fixture、11 位置真实来源和冻结指纹均提交。
- [精简实际结果 JSON](python-graph-analyzer-evaluation.json) 保留全部标注结果及相应原始输出、版本、测量、源码内容指纹；完整 32K/68K 级关系、源码计划及临时 repo 仅留本地 .tmp，不上传完整真实图。
- [preservation 清单](python-graph-preservation.json)：原 **58 个 tracked 文件和 53 个真实数据/缓存/备份文件**逐文件 SHA-256 均未变；三业务仓库的 HEAD/branch/origin/status 均与开始相同。原 index pointer 和 API ledger 哈希保留；未调用付费 API。
- 只提交 experiments/python_graph 与本报告/三个配套审阅文件；排除真实数据库、索引、缓存、虚拟环境、压缩包、配置、key 和个人 Codex 文件。不创建 Release，不合并分支，不改变其它 remote。
