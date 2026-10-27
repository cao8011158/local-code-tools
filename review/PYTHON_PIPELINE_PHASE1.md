# 第七轮：隐式执行认证收敛修复

分支 refactor/cgr-pipeline-integration；启动 HEAD 与审阅基线均为
10542de7c53bd3a825f0c016fe3d20d5db7d6fb9，未前进。无已跟踪修改，只有未跟踪 code_graph/。
已读适用指引检查（目标及父目录无额外 AGENTS.md）、当前契约及最新记录。
源码/测试提交：**e21cb68ecf273039f4b00993b454e48e03d349e9**。
最终报告提交 SHA 由交付消息及 `git log -1 --format=%H -- review/PYTHON_PIPELINE_PHASE1.md` 给出。

本批按用户确认的收敛方案结束，没有重新设计普通调用。python_access.py、Graph、storage、
extract、query 及依赖/锁文件未修改；未新建分支/reset/merge，未读取/清理 code_graph/ 或真实
graph/数据库/索引/向量/BM25/缓存/备份，未改其他仓库、安装依赖、启动服务或调用付费 API。
所有实际测试串行使用现有环境与合成源码/临时数据。

## 最终规则

- field_event 的可达 implicit-call 直接 UNKNOWN_EFFECT：
  implicit-decorator-effects-not-modeled；region 直接 unsupported-protocol-region。
  不做装饰器闭包或上下文协议效果推导，不用名称未命中证明无影响。
- scope-execution 仅接受有限无害类：无 bases/keywords/装饰器/type parameters；类体只含 Pass、
  常量表达式、普通/异步函数定义；函数无装饰器/type parameters，头部节点仅 arguments、arg、
  Constant。其他为 unsupported-class-definition-effects。没有赋值/继承/元类/复杂头部规则。
  方法体不参与安全判定；NO_EFFECT 只针对既有实例字段，不表示类定义没有运行行为。
- valid_coverage 对可能执行的隐式事件按类型分派。无规则的 implicit-call/region 不接受
  NO_EFFECT；scope-execution 重检实际源码语法结构、事件类型、原行列及 syntax_digest。
  缺证据、标志/原因标签、更换事件元数据均不能认证。不可达事件保留原规则。
  普通 call 继续原 valid_call_no_effect，没有把其参数模型套用到隐式事件。
- field_scope 的三个 UNKNOWN 原因在 value=None 时复用 absent-field，合入原类成员候选，
  未知原因保留。没有重写 attribute；second.work 的 R.work 候选及原未知断言继续通过。

## 实际验证

修改前固定两个 Graph.build 反例、两个未应用定义对照及三种无依据证据检查，
closed_world=False：**5 failed、2 passed**，原始 before.* 保留。两个程序反例都曾错误完整；
三个标签认证也都错误通过。修复后两个程序均保留 a 为不完整候选，禁止精确推导 b，
unknown_origin=true/complete=false，原因明确，无完整排除 Jedi 候选。删除应用/with 的对照
仍精确为 a。最终新增 **41 项通过**，包含原七项、类规则、行列/语法篡改、元数据伪造、
不可达、最终 CALLS 传播及匹配 Jedi 的负控制，没有 xfail。

| 本地实际命令范围 | 结果 |
| --- | --- |
| 原七项，修改前 | 5 failed、2 passed，exit 1 |
| 收敛后新增＋旧覆盖＋原复杂 contextlib 回归 | **109 passed**，exit 0 |
| 收敛后一次完整 tests | **397 passed、1 skipped**，69.72 s，exit 0 |
| Ruff check / format --check / git diff --check | 通过 |

最终完整分组为原 356 passed/1 skipped，加新增 41 passed。唯一 skip 仍为 opt-in 真实缓存，
未访问真实缓存；缺依赖跳过 0。旧普通调用、闭包、嵌套容器、方法效果等全部由全套覆盖。
用户提供的独立基线 363/1 与历史 26 passed 属外部审阅证据，未当作本批本地执行计数。
未重跑外部历史 26、旧选型 harness、冻结导出器、真实业务验证、MCP/E2E 或远端 CI。

仅两处旧断言调整：
1. test_unrelated_nested_body_in_region_does_not_resume：空 for 没有安全证明，完整降为未知；
   仍保留 a/禁止 b、位置/作用域检查，原因 unsupported-protocol-region，无 deferred 原因；
   obj.change 归属 caller.nested，不能归 caller。未新增空循环分析。
2. test_executed_class_body_is_an_explicit_scope_dependency：只改原因字符串为
   unsupported-class-definition-effects，原候选和未知状态不变。

test_contextlib_alias_and_complex_generator 未改。为解决其候选丢失，使用既有 absent-field
回退，没有放宽目标或删除断言。中间三项新测试一度因缺 Analyzer 导入失败，已修复并通过；
没有把测试构造错误计为语义通过。收敛前较宽规则曾运行 394/1；用户澄清后收紧规则并更换
原因，故该旧结果不作为最终验收。最终源码验证后仅整理契约文字与证据，没有再运行解析实验。

精简证据在 phase1-round7/：before.*、targeted.*、tests.*、summary.json。只复制已有输出，
没有为报告重跑测试。复现时选新的临时目录：

~~~powershell
.venv/Scripts/python.exe -m pytest -q tests/test_python_implicit_effects.py tests/test_python_effect_coverage.py tests/test_python_review_regressions.py::test_contextlib_alias_and_complex_generator --basetemp=.tmp/repro-round7-targeted
.venv/Scripts/python.exe -m pytest -q tests --basetemp=.tmp/repro-round7-all
.venv/Scripts/ruff.exe check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
.venv/Scripts/ruff.exe format --check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
~~~

范围边界：没有精确支持装饰器/with 协议的新字段效果。既有目录在区域结束记录 region，
区域内部读取的进入阶段时序覆盖问题已静态记录，未在本批扩展目录或协议分析，需独立复核；
不声称该范围已验证。合成通过不等于全库准确率或通用 Python 健全性。
完成本批 commit/push 后停止，等待独立审阅，不进入“小图＋MCP”。

---

以下为历史记录。

# 第六轮：调用三态关联与 NO_EFFECT 依据（2026-10-28）

分支：refactor/cgr-pipeline-integration。启动/已审阅 HEAD：
36b0ede83eb278f2af6079f2d2403493385d5a6b，与用户指定一致，未前进。
启动仅未跟踪 code_graph/，无已跟踪修改。目标及父目录未发现额外 AGENTS.md；
已阅读当前契约和第五轮报告。沿原分支继续，未新建分支、reset、merge、覆盖用户内容。
最终源码、测试及契约提交：**966ea960883ff9e050273fc16ba4b2b18ca9ad88**。
最终完整 tests：**356 passed、1 skipped、0 failed**。后续报告提交的完整 SHA 见交付消息，
或 `git log -1 --format=%H -- review/PYTHON_PIPELINE_PHASE1.md`。

code_graph/ 未读取/采用/暂存。未修改 CGR 或三个业务仓库，未访问/清理真实索引、数据库、
向量、BM25 或缓存。未启动 Neo4j/Docker/JVM/MCP，没有 Embedding/LLM 请求。
复用原 Python 3.12.14/Jedi 0.20.1/pytest 9.1.1 环境，未安装依赖，串行合成测试。

## 根因及修复边界

旧事件收集正确地发现了 consume([obj]) 和 mutate()，但 field_event 只检查直接实参、
bound receiver 与表面接收者；没命中便返回 call-without-queried-receiver-dependency。
缺失的容器路径/词法依赖因此被错误认证为 NO_EFFECT，覆盖清单完整也不能纠正错误结论。

本批保留 EffectCatalog、EffectOutcome、EffectCoverage、Result.requirements 和方法效果机制；
目录仅新增不被 detail.kind 覆盖的 event_kind 导出字段，没有重写事件收集器。
新增 python_access.ReceiverAccess 是有限来源/依赖检查，不执行赋值、不应用任意函数效果、
不维护运行对象堆或类型固定点；未接 CGR、Flow 或另一套节点解析器。

- Access 明确 REACHABLE、NOT_REACHABLE、UNKNOWN，附证据路径与 gaps。
  已知可达路径不表示必然修改；不可达必须覆盖相关来源，未知/递归/预算不当作 False。
- 参数共用现有值解析与当前 container_slots。普通 dict 检查键和值；*dict 只运输键，
  **dict 运输值并验证有限键语义。多层容器、别名及直接/条件修改、逃逸均参与关联。
  创建字面量不能覆盖后续状态。容器与实例的先前调用共用 history，继续检查传递依赖；
  可能存在未建模关联更新时 UNKNOWN，而不是只因当前槽/字段没有命中就判独立。
- 依赖摘要按本次定义身份/version_id 缓存，源引用和调用只在对应执行作用域内检查。
  调用绑定上下文区分局部/参数、closure/global/nonlocal、默认值、绑定方法及类接收者。
  捕获按已知调用时点读取，不能拿之后的覆盖证明当前不可达；缺少时点且有重绑定则未知。
  未调用的内部主体不作为当前执行；传出函数值时检查其捕获/有限传递路径。
- 真正的目标、入口与依赖检查完毕后，已覆盖的 method_field_effect 或无输入使用摘要可继续
  提供确定效果。对象可达但效果未支持为 UNKNOWN_EFFECT；未解析目标/来源、传递递归、
  不支持的返回来源及预算也明确未知。没有为了闭包样例硬算 b。
- valid_call_no_effect/valid_coverage 对字段调用核对 call_access 的定义版本、入口状态/
  evidence/gaps，以及 no_effect_basis。无证据标签、UNKNOWN 关联、UNKNOWN 目标或无效摘要
  不能完整，Jedi 一致也不能绕过。原始 Jedi、未裁决候选和排除依据继续保留。

本批没有用布尔 container_reachable 的 False 为字段无影响认证背书；该旧接口仍供已有
槽传输适配使用。范围是字段调用认证及所需来源分析，未重建原槽位解析器、真实检索索引或图。

## 正常精度与有限无影响证明

仅创建协程/生成器不执行主体，实参求值仍由既有目录单独处理。恢复与调度保持未知。
普通同步方法、构造器、保存的 bound alias、继承 classmethod、确定 noop、常量 lambda、
原 contextmanager/gap/快照保留行为均有原断言或新增对照守护。

“输入回调未知”不自动变成“该调用一定能访问任何新对象”。为了保留既有
consume(obj.change()) 等精确场景，另有严格的私有分配证明，而非默认 NO_EFFECT：
callee 必须是未重绑的既有输入，目标是本作用域直接新建的局部实例；构造器须有无发布的
有限源码证明，全部当前参数不可达，先前调用/写入已处理且无逃逸；潜在闭包单元格的
后续绑定也必须排除。缺任一项，UNKNOWN。该证明不解析未知回调实现，也不把回调 CALLS
的未知目标升级为完整；仅证明支持边界内它不能影响该实例的字段。

同样，已验证函数完全不使用的参数/接收者可以通过有效无影响摘要排除；保存 ignored_inputs
原状态，实际会使用的依赖仍须全部检查。不能把一个 UNKNOWN 输入简单改标签称无影响。
尚不支持 frame/GC 反射、任意隐式协议、外部并发、完整别名/堆/CFG 或恢复调度。
这些边界不被合成通过结果掩盖，也不声称对任意 Python 全程序健全。

## 反例、负控制和最终结果

先固定两个 closed_world=False 反例及未调用闭包对照，再修改实现。
修改前实际 **2 failed、1 passed**，exit 1，原始 before.txt/before.xml 已保留。

| 样例 | 修复后 |
| --- | --- |
| mutate 捕获 obj 后修改字段 | 识别 closure-binding；旧 a 只保留为未确认候选，unknown=true/complete=false；不猜 b，不完整排除 Jedi |
| consume([obj]) | 识别 container-element/direct-argument 可达路径，UNKNOWN_EFFECT；未知传播到最终 CALLS |
| 只定义而未调用 mutate | obj.run 精确 a，complete=true，无 b |
| 已验证 noop(obj) | 有效无输入使用摘要，精确 a；没有统一降级 |
| 私有新实例＋既有输入回调 | 只有逐项所有权/时序证明有效时字段精确；回调本身仍未知 |
| 已逃逸或潜在延迟捕获 | 私有证明失效，保留 UNKNOWN |

86 项新增正式测试均使用开放输入或独立三态/收据检查，覆盖：
参数包装/多层别名、dict 键值与解包、传参前状态、捕获独立对象/同名局部/global/nonlocal、
未调用主体、使用/不使用的默认值、传递调用/构造/容器及对象关联、递归/预算、无效证据/
匹配信号、lambda 返回值、方法/实例隔离。直接测试三态函数、事件分类和最终 CALLS；
核对位置/执行作用域、目标/禁止目标、unknown/complete/reasons 与裁决依据。
未删旧断言、改旧目标或加 xfail。

两项补充组件负控制（传递闭包修改容器、闭包新增实例关联）在开发中也先复现了错误
NOT_REACHABLE，各 1 failed，保存 transitive-before.txt/object-before.txt；统一历史检查修复后
均通过，避免“最终字段碰巧未知”遮住组件错误。新增 lambda 返回值守卫也有独立回归。

| 实际验证 | 结果 | exit |
| --- | --- | --- |
| 修改前原始 3 项 | 2 failed、1 passed | 1 |
| 最终相关解析定向 | **321 passed** | 0 |
| 最终完整 tests/ | **356 passed、1 skipped**，34.36 s | 0 |
| 冻结输入与独立合成导出 | **39/39 标注、44 节点**，analysis_limited=false | 0 |
| Ruff check / format --check / diff --check | 通过 | 0 |

JUnit 互斥分组为原有 **270 passed/1 skipped**、新增 **86 passed/0 skipped**。
既有最终退化 0、最终新增失败 0、缺依赖跳过 0；唯一 skip 仍是 opt-in 真实缓存测试，
按范围未访问。原冻结 fixtures/truth、storage.py、extract.py、query.py 和依赖/锁文件无差异。

实际完整 tests 共运行 3 次，并非只运行一次：348/1 和 354/1 之后，代码审查/组件反例发现了
lambda 守卫与历史关联缺口，发生程序修改，故做必要定向及最终完整复验。前两次均不能替代
最终 356/1。各次约 33–34 秒，均串行；没有无目的重跑或安装/服务重试。
最终完整运行后程序和正式 tests/ 未再修改，仅整理契约文字、报告和证据。
一条辅助诊断曾因沙箱临时目录权限失败，使用指定仓库测试权限后成功，不计为解析失败。

summary.json 记录环境/命令/分组；tests.*、parser.* 是最终原始输出；cases.json 保存七个
开放样例的实际路径、双方证据、覆盖与 CALLS，并显示未知输入回调本身仍未知；frozen.json
保存精确源字节哈希和冻结校验。baseline_oracles.py 隔离原三个 oracle，可在只读导出的
36b0ede 源码中复现，预期 2 failed/1 passed，不依赖新模块。没有数据库/索引/向量/密钥。

在仓库根目录，选未使用的临时目录串行复现：

~~~powershell
.venv/Scripts/python.exe -m pytest -q tests/test_python_call_access.py --basetemp=.tmp/repro-round6-access
.venv/Scripts/python.exe -m pytest -q tests --basetemp=.tmp/repro-round6-all
.venv/Scripts/python.exe tools/review_python_pipeline.py --output .tmp/repro-round6-frozen.json
.venv/Scripts/ruff.exe check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
.venv/Scripts/ruff.exe format --check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
git diff --check 36b0ede83eb278f2af6079f2d2403493385d5a6b HEAD
~~~

基线独立复现可用 git archive 将该提交导出到新的 .tmp GUID 目录，将 baseline_oracles.py
复制为其中 tests/test_round6_baseline.py，创建 .tmp 父目录，再从导出目录用原虚拟环境运行
该文件。不切换/reset 当前分支，不需另建环境；本批没有再建这种副本，初始真实失败已保存。

## 限制与交付结论

不求解闭包写入的完整效果、任意属性/容器更新、所有传递分派或复杂控制流；无法覆盖时
明确 UNKNOWN。Source allocation 是有限关联标记，不是运行堆的唯一对象身份；重复工厂/
循环、动态来源、隐式协议和反射不因本批被宣称已解决。合成测试只支持所列源码模式及
不确定性契约，不推断三个业务仓库准确率。

未运行：旧选型实验 harness、真实业务 graph/向量/BM25/缓存验证、远程 MCP、
“小图＋MCP”及远端 CI。冻结导出不等同旧选型实验，也不代表任何未运行项目通过。
本批机制与回归具备独立审阅条件；不宣称全部 Python 语义或下一阶段已验收。
提交并仅 push 当前 LCT 分支后停止，等待独立审阅，不 merge。

---

以下为此前各轮历史证据。

# 第五轮：副作用事件目录与独立覆盖认证（2026-10-28）

分支：refactor/cgr-pipeline-integration。启动 HEAD/已审阅基线：
fdc56dde99e0e5d8d5214e8fad5d05a95930b701，未前进、没有已跟踪未提交修改；
唯一未跟踪项为 code_graph/，始终保留且未读取、采用或暂存。
最终程序、测试及契约提交：**f73289f362c150473cc4c013f84061fc4e069ee8**。
最终完整 tests：**270 passed、1 skipped、0 failed**。
交付还包含后续报告/证据提交；其完整 SHA 由交付消息及
`git log -1 --format=%H -- review/PYTHON_PIPELINE_PHASE1.md` 给出。

已核对适用 AGENTS.md（目标及父目录未发现额外文件）、当前契约和前轮报告。
沿当前分支提交，不新建分支、reset、merge、stash 或覆盖用户内容。
本批没有更改 CGR/三个业务仓库、真实索引/缓存/数据库、快照存储实现、依赖或锁文件。
没有启动服务、执行被分析源码或发出 Embedding/LLM 请求。使用既有 Python 3.12.14、
Jedi 0.20.1、pytest 9.1.1 环境串行处理小型合成源码和临时测试数据。

## 根因与本批机制

旧 method_field_effect 把 Name 写入无条件忽略，接收者已被替换后仍把后续字段写入归给原实例；
instance_field 只从少数外层语句的 .value 提取操作，遗漏表达式内部的 Call/Await。
这些漏检没有产生 unknown；attribute/subscript 再把 not result.unknown 当覆盖证明，
adjudicate 据此排除 Jedi 候选，形成错误的循环认证。增加 events/proof 标签无法补上漏检。

现在事件发现、效果结论和完整性认证分别承担职责：

- python_effects.EffectCatalog 复用既有 AST inventory 的执行 owner/phase，一次建立每作用域
  操作目录。赋值、带值/无值注解、增强赋值、Delete、NamedExpr、显式调用、Await、隐式绑定、
  装饰器应用、终止与未支持区域都独立于处理器收集。表达式递归，不再枚举外层语句补丁。
- EffectOutcome 明确 NO_EFFECT/KNOWN_EFFECT/UNKNOWN_EFFECT，带位置、原因和适用依据。
  field_scope/field_event 共用于构造器与普通方法；None 不再表示方法效果结论。
  处理器缺失、关联不明及不支持的相关语法均阻止认证，不因为没有匹配 allocation 而判无影响。
- EffectCoverage 在调用处理器前登记义务，保存 required_events/checks/sources/gaps。
  全部义务都有确定结论且来源有效才完整；UNKNOWN_EFFECT 不能被另一次依赖访问的 NO_EFFECT
  抹掉。valid_coverage 检查义务与结论集合、来源和缺口，裸 complete=true 不能冒充证明。
- Result.requirements 与 union、绑定及派生值一起传播。读取字段/槽位后存为变量不会丢掉覆盖
  义务；Graph CALLS、CONTEXT_ENTERS 和 adjudicate 使用同一门槛。certified 仅附规则标签。
  字段/槽位不再从最终候选是否带 unknown 反推事件覆盖。

AST 继续负责唯一目录、范围、作用域、执行位置；Jedi 继续提供原始定义/调用目标信号；
LCT 仅做有限关联、事件效果归责和证据裁决。没有另建检索节点解析器、Flow、通用执行器、
运行对象堆、完整 CFG 或异步调度器。新增文件约 12 KiB，依赖声明不变。
字段读取只消费相关作用域的已建事件前缀和摘要；槽位使用已建目录的槽依赖范围，保持原注册表
关联，不再每次遍历整个仓库 AST。目录和关联预算均限定在本次源码捕获，不跨快照复用。

## 接收者、执行阶段和顺序

有限摘要先确认调用位置的实际目标、绑定接收者及 ordinary-call 阶段，保留覆盖前后顺序及
保存的 bound method。实际接收者参数名来自签名，不硬编码 self。
重赋值、Delete、有值 AnnAssign、增强/解包或隐式语法替换接收者时，拒绝剩余摘要并记录
receiver-binding-changed。不支持的其他局部绑定记录 unsupported-summary-binding；不能
继续依赖该绑定解释后续写入。纯注解不写值。return 前的有效写入保留，后面事件不可达。

Call/Await 在参数、容器元素、条件、元组、短路和链式比较中均被发现。已支持的直线语法遵守
操作数先于操作、RHS 先于写入、callee/实参先于调用的顺序；分支、短路后项和后续 comparator
显式 conditional。未建模区域不被伪造成确定路径。类定义主体是执行作用域依赖，相关副作用
未特化时未知；类中未调用的方法、嵌套函数/lambda 主体不作为当前执行事件。
默认值、装饰器和 eager annotation 仍按原定义阶段 owner 处理。

创建协程/生成器不应用主体，创建调用中实参自身的副作用仍被独立处理。
Await（含保存 pending 后等待）关联到当前对象时返回 deferred-method-resumption-not-modeled，
不保留旧值的完整确认，也不猜测恢复后的目标。关联不足为 deferred-receiver-association-gap；
明确独立实例可无影响。条件恢复同样未知。本批没有执行/模拟恢复主体。

字典复制维持前轮候选、可能缺失、未知来源和左右覆盖行为。相关写入、展开来源和逃逸从
同一义务机制认证，sealed 或 literal-slot-state 不代替覆盖。确定后键可屏蔽前序展开的槽来源
依赖，表达式本身的调用事件仍须处理；副本不反向接受源字典之后的槽替换。

## Jedi/LCT 裁决与实际证据

原始 Jedi 映射与 LCT 候选分别保存，不无条件优先任一方，也不把并集称为完整。
只有有效覆盖、来源和具体语义规则全部满足，才用 tested-semantic-rule 排除冲突项。
覆盖不足时记录未裁决 Jedi 候选与原因，部分结果仍 unknown=true、complete=false。
双方恰好一致也不绕过覆盖。mechanism-cases.json 保存 13 个开放输入样例的实际位置、
双方原始证据、覆盖检查及最终 CALLS：

| 组 | 实际结果 |
| --- | --- |
| 重赋值、删除、有值注解、解包接收者 | 保留原 a 的部分候选，禁止错误 b；unknown=true、complete=false，原因明确；即使 matching-signals 也不认证 |
| 六种 await 位置及保存 pending | 不确认旧 a 或猜测 b，恢复原因及未知传播至 CALLS，Jedi 候选未被完整排除 |
| 普通同步方法 | run → b，禁止 a，完整；实际目标/接收者/摘要覆盖支持排除冲突 |
| 未等待的协程创建 | run → a，禁止 b，完整；创建阶段支持排除未执行主体带来的候选 |

## 测试与复现证据

修改前先加入 18 项 oracle 并实际运行：**11 failed、7 passed**，退出码 1。
失败为 4 项接收者绑定、2 项构造器/方法共同检查和 5 项此前漏掉的 await 位置。
before.txt/before.xml 保存当时实际失败；baseline_oracles.py 隔离这 18 个相同断言，方便在
只读导出的旧源码上复现，不依赖本轮 python_effects 模块。没有依据新输出改变正确答案。

本批最终新增 **67 项全部通过**：接收者/依赖绑定、六位置与 pending、事件收集器作用域、
函数头、未调用主体、同步求值顺序、实例隔离、缺失处理器、明确 UNKNOWN_EFFECT、只有标签、
伪 complete 标志、Jedi 一致、别名依赖、确定字典复制及覆盖未知不被抹去等。
最终图断言同时核对 targets/forbidden、执行/词法作用域、行列、unknown/complete/reasons、
CALLS 与排除理由，收集器另有直接断言。无删除 oracle、xfail 或新增跳过。

| 实际执行 | 结果 | exit |
| --- | --- | --- |
| 修改前新增 18 项 | 11 failed、7 passed | 1 |
| 旧基线只读源码导出＋隔离 oracle 复现 | 11 failed、7 passed | 1 |
| 中间覆盖接入回归 | 一度 5 failed、209 passed；注册表先提交临时 UNKNOWN 的时机被修复；新负控制明确同一义务不能被 NO_EFFECT 重置，独立义务另建收据。既有目标 oracle 未改，最终均恢复 | 1 |
| 接收者/顺序/旧解析相关定向 | 153 passed | 0 |
| 首次完整 tests | 266 passed、1 skipped | 0 |
| 最终完整 tests | **270 passed、1 skipped**，37.95 s | 0 |
| 冻结输入哈希与独立合成导出 | **39/39 标注、44 节点**，analysis_limited=false | 0 |
| Ruff check、format --check、git diff --check | 通过 | 0 |

首次全套之后，审查补齐链式比较条件位置、类主体依赖及 CONTEXT_ENTERS 的统一门槛，
因此执行了必要的定向和最终完整复验。最终完整运行后程序、正式 tests/ 和契约未再修改，
后续只生成审阅材料和隔离的基线复现 oracle。未为耗时目的重复全套。
Junit 互斥分组：原有 **203 passed/1 skipped**；本批 **67 passed/0 skipped**；合计 270/1。
最终既有退化 0、新增剩余失败 0、缺依赖跳过 0。唯一跳过仍是 opt-in 的真实缓存测试，
本批按要求不访问该缓存。前两项 gap、前轮实例字段/槽位/contextmanager、快照保留和生命周期
均由本次完整 tests 覆盖。storage.py 和冻结 fixtures/truth 均无差异。

summary.json 记录环境、命令和退出码，tests.txt/tests.xml 为最终原始输出；frozen.json 包含
精确源码 SHA-256、冻结输入校验与独立标注结果。全部是合成材料，没有数据库、向量、缓存、
虚拟环境或凭据。

在仓库根目录使用既有环境，选未使用的 basetemp 名称串行复现：

~~~powershell
.venv/Scripts/python.exe -m pytest -q tests/test_python_effect_coverage.py --basetemp=.tmp/repro-round5-mechanism
.venv/Scripts/python.exe -m pytest -q tests --basetemp=.tmp/repro-round5-all
.venv/Scripts/python.exe tools/review_python_pipeline.py --output .tmp/repro-round5-frozen.json
.venv/Scripts/ruff.exe check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
.venv/Scripts/ruff.exe format --check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
git diff --check fdc56dde99e0e5d8d5214e8fad5d05a95930b701 HEAD
~~~

若独立复现旧失败，导出只读基线到新的临时目录（不切换/reset 当前分支，也不采用其结果
修改答案），将 baseline_oracles.py 复制为导出目录下 tests/test_round5_baseline.py，再用同一
现有虚拟环境从该临时目录运行该文件；预期 11 failed/7 passed。不要把旧源码导出目录当成
具有 Git 元数据的旧选型实验环境。该隔离基线复现也已实际执行，结果相同；首次因导出目录缺少 basetemp 父目录出现 18 个 fixture
基础设施错误，创建该目录后用同一副本重跑成功复现，不计为解析失败。副本 zip 约 424 KiB，
未创建新环境/分支。基线失败原始日志已保存，不要求重复执行才能审阅。

完整基线复现命令如下，使用全新的 GUID 临时路径，保留当前工作区：

~~~powershell
$lctRoot = (Get-Location).Path
$lctPython = Join-Path $lctRoot '.venv/Scripts/python.exe'
$baselineDir = Join-Path $lctRoot ('.tmp/phase1-baseline-' + [guid]::NewGuid().ToString('N'))
$baselineZip = $baselineDir + '.zip'
git archive --format=zip --output=$baselineZip fdc56dde99e0e5d8d5214e8fad5d05a95930b701
Expand-Archive -LiteralPath $baselineZip -DestinationPath $baselineDir
Copy-Item -LiteralPath review/phase1-round5/baseline_oracles.py -Destination (Join-Path $baselineDir 'tests/test_round5_baseline.py')
New-Item -ItemType Directory -Path (Join-Path $baselineDir '.tmp') | Out-Null
Push-Location $baselineDir
try { & $lctPython -m pytest -q tests/test_round5_baseline.py --basetemp=.tmp/reproduce } finally { Pop-Location }
~~~

## 支持范围、限制与下一步边界

本批验收机制测试和既有回归均通过，具备提交独立审阅的条件；不表示任意 Python 程序的
健全性或三个业务仓库全库准确率。完整性只针对明确记录的有限源码/关联支持边界：
没有 self 重绑定后跨对象追踪、完整 CFG、任意别名/运行堆、动态反射、任意隐式协议或调度。
复杂方法/区域、不支持的依赖绑定、未知调用目标/接收者和延迟恢复明确保留未知；不承诺
通过当前合成样例证明这些能力已实现。保守未知不是新增跳过，也不伪装完整结果。

未运行：旧选型实验 harness、真实业务 graph/索引、远程 MCP、下一批“小图＋MCP”、远端 CI。
冻结导出只验证固定合成 oracle，不代表上述未运行项通过。未接 Neo4j、完整增量或发布协调。
后续消费者必须共同消费原节点目录和位置身份、覆盖依赖/未知状态；跨快照失效需重新认证。
未更改真实索引的 manifest 或触发 rebuild。完成本批提交和 push 后停止，等待独立审阅。

---

以下为前轮历史证据，其“当前/本批”仅适用于相应提交。

# 第四轮审阅修复：方法效果适用条件与字典复制的不确定性

审阅基线：3994134c51a9b5ab7f178a12ecb480e0df6e2905。
最终程序/测试提交：86e92a406e6bab148540cf8b04a3478067f8fa7b。
最终完整 tests/：**203 passed、1 skipped、0 failed**；本批五个反例和正常对照均通过。
没有运行旧选型实验 harness，不将历史的 7 passed 当成本批结果。

## 边界与工作区

启动时当前分支 refactor/cgr-pipeline-integration、HEAD 均符合用户指定，未前进到其他提交；
工作区仅有未跟踪 code_graph/。已读适用指引检查、docs/PYTHON_PIPELINE.md 及最新报告，
未发现额外 AGENTS.md。沿原分支修改，未新建分支、reset、merge 或覆盖用户工作。
code_graph/ 未读取、采用、移动、删除或暂存。未修改 CGR 或其他业务仓库，未访问/清理真实
索引，未生成真实 graph/向量/BM25，未启动 Neo4j/Docker/JVM/MCP 或长期后台服务。
付费 API 请求 0，根既有环境复用，无安装/下载依赖。解析保持 AST/Jedi 0.20.1/有限 LCT
关联，没有执行被分析源码，没有恢复通用执行器、Flow 或异步调度器。

本批只改方法效果和复制传播及相应 CALLS 阶段说明。原字段、槽位、contextmanager、
快照激活链等由既有测试守护；lct/storage.py、lct/query.py、lct/extract.py 均未修改。
之后的报告提交只保存本报告、日志空白规则及精简证据；交付 SHA 见最终消息，
或 git log -1 --format=%H -- review/PYTHON_PIPELINE_PHASE1.md。

## 先固定反例并复现

先加入五个 closed_world=False 的正确目标/禁止目标/完整性 oracle，再修改程序。
修复前实际 **5 failed，exit 1**，TXT/JUnit 在 phase1-round4/before.*。
测试复用严格 check：校验调用行列、caller 词法/执行作用域、目标集合、禁止目标、
complete/unknown_origin/unresolved_reasons、最终 CALLS 及冲突排除依据。
未修改现有 oracle 或冻结答案，未删断言、xfail、跳过新反例。

| 反例 | 修复前问题 | 修复后严格结果 |
| --- | --- | --- |
| A 未等待的异步 change | 错用主体赋值 b | obj.run → a，禁止 b，完整；change 为 coroutine-create，主体未执行 |
| B return 后赋值 | 继续读取不可达 b | obj.run → a，禁止 b，完整；摘要在 return 截断 |
| C 调用前覆盖方法 | 按 C.change 套用 b | 实际 callee 为 noop，obj.run → a，禁止 b，完整 |
| D 条件修改后复制 | 丢 b 及来源限制 | 保留 a、b，unknown=true、complete=false，条件来源不伪装穷尽证明 |
| E 逃逸来源后复制 | events 有逃逸但值重新封闭 | 保留 a，同时 unknown=true、complete=false，逃逸原因传播到最终槽及 CALLS |

D 的部分状态沿用有限条件写入的支持边界，不把已知 a/b 候选降成零目标；
A/B/C、普通同步 change、确定字典复制和明确覆盖等正常场景仍完整。

## 方法效果适用与执行阶段

method_field_effect 不再按类中方法名字直接采用声明。普通调用解析该位置的实际目标、
字段覆盖、绑定接收对象和创建位置；构造器内 self 调用按已知 receiver 特化，并只看调用前
可达的字段。直接覆盖在调用之前/之后分别处理；保存的 bound method 保留旧目标和 receiver，
表面对象不替换方法真实的 body receiver。跨对象绑定别名只更新真实接收对象。

仅同步、已识别的有限直线主体可提供字段效果。bare/简单 return 保留之前的有效 store，
截断之后的语句；构造器直线 return 同样不采用后续调用/赋值。条件终止、复杂控制流、
未特化参数或未知目标保留未知，没有引入通用 CFG 或跨过程执行状态。
构造器内来自字段覆盖/别名的调用仍可能保守未知，不假装执行原类方法。

统一 invocation_phase 识别 ordinary-call、coroutine-create、generator-create、
async-generator-create 及原有 context-manager-create。延迟对象创建的 CALLS 保留原函数目标，
executes_body=false，不能同时套用主体字段效果或未执行的 return 结果。
await、next 等实际恢复阶段本批不模拟；若影响该 receiver，字段明确返回
deferred-method-resumption-not-modeled，而不是保留旧字段的完整性。
延迟 initializer 协议同样不取得普通构造器主体证明。

write_source_coverage.events 记录实际 targets、body receiver allocation、创建阶段、
deferred-body-not-executed 或 return-terminated-summary/终止行等适用依据。
最终裁决仍分别保存 Jedi 原始候选、LCT 结果、选中/排除/未裁决候选；只有当前结果完整且有
具体覆盖证明才排除冲突项，不简单并集、不无条件优先一方。

## 字典复制规则

container_slots 现在把固定条件写入/删除的候选及 possible-missing-slot 直接放进每键 Result，
避免把 b 只留在复制层会遗失的限制列表中。展开把来源 limitations 的候选和原因一起加入
复制值/动态槽；sealed 只能在复制值本身无未知、且覆盖/存在性有依据时重新建立。
来源不完整不会因后面的具体槽遍历而变完整。

可能缺失的源键保留展开前的目标键候选；例如条件插入 b 时，左侧已存在 a 不会被错误删除。
源码顺序仍有效：未知展开后的明确 go=b 可确定覆盖 go；go=b 后的未知展开可再次影响它。
其他键的条件限制不无条件污染确定的 go。复制完成后的源槽替换不反向改变副本。
内部缺失标记不是伪造代码节点或 CALLS 目标。有限普通复制仍精确；动态来源、逃逸、
条件分支等在无法证明完整时保留部分结果/原因，不把零候选当成缺失键证明。

## 对照与最终验证

新增正式测试共 30 项：五个反例、同步/协程/生成器/异步生成器创建、return 前后有效写入、
覆盖时序、保存的 bound alias、真实 receiver 隔离、构造器 return、显式恢复未知、
条件插入/删除及缺失、逃逸、明确键覆盖、无关键隔离和复制后源替换等。
同一组 source-only 小样例串行执行，不运行源码来确认答案。

| 本批实际执行 | 结果 | exit |
| --- | --- | --- |
| 修改前五反例 | 5 failed | 1 |
| 两个复制反例定向 | 2 passed | 0 |
| 方法及相关旧回归定向 | 11 passed | 0 |
| 中间组合回归 | 89 passed / 112 passed | 0 |
| 最终新增定向 | 30 passed | 0 |
| 一次完整 tests/ | 203 passed、1 skipped | 0 |
| 冻结输入哈希和独立合成导出 | 39/39 标注、44/44 节点，analysis_limited=false | 0 |
| Ruff check / format --check / diff --check | 通过 | 0 |

此前完整基线 173 passed/1 skipped 来自已审阅批次；本批修改前实际重跑了新增五例，
不冒称重新执行过旧全套。完整 tests/ 包含所有原测试与冻结答案断言，无既有回归或本批剩余
失败。1 skip 仍为原有 opt-in 真实缓存测试，缺依赖跳过 0。没有修改 frozen fixture/truth。
最终完整运行后程序和测试断言未再修改；只整理报告/证据。没有无目的重复完整测试。

未运行：旧选型实验 harness（含 Jedi/Pyan 对比及 cross-version 子实验）、真实业务 graph/
索引验证、远程 MCP、“小图＋MCP”E2E、远端 CI；不推断它们本批通过。
冻结导出仅是 LCT 在冻结合成 oracle 上的校验，不等同旧候选选型实验通过，
也不构成三个业务仓库的全库准确率或任意 Python 动态语义健全性证明。

## 复现、限制与交付

在 LCT 根目录串行执行，输出路径选择未使用的名字；Python 3.12 与既有锁定环境。

~~~powershell
.venv/Scripts/python.exe -m pytest -q tests/test_python_review_round4.py --basetemp=.tmp/reproduce-round4
.venv/Scripts/python.exe -m pytest -q tests --basetemp=.tmp/reproduce-round4-all
.venv/Scripts/python.exe tools/review_python_pipeline.py --output .tmp/reproduce-round4-frozen.json
.venv/Scripts/ruff.exe check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
.venv/Scripts/ruff.exe format --check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
git diff --check 3994134c51a9b5ab7f178a12ecb480e0df6e2905..HEAD
~~~

仍有限制：未提供通用异步/生成器执行、完整跨过程/路径分析；复杂方法、构造器别名或覆盖、
动态属性/反射和复杂字典来源继续可能未知。条件复制只保证已识别候选与未知传播，
不将有界静态结果当作运行时无异常证明。

精简证据在 phase1-round4/：实际失败/定向/全套 TXT 与 JUnit、evidence.json 中的五例源码、
最终 CALLS 和裁决/覆盖信息、冻结哈希摘要与源码指纹。没有数据库、索引、向量、缓存、
虚拟环境、密钥或大型临时产物。只正常提交/push 当前分支，不 merge。
本批具备提交独立审阅的条件，交付后停止，等待审阅；通过前不进入“小图＋MCP”。

---

# 历史记录：3994134 第三轮审阅修复

以下保留旧报告，173 passed 和旧 harness 等数字只代表当时状态，不代表本批运行记录。

# 第三轮审阅修复：字段更新、字典来源、工厂阶段与快照顺序

本批审阅基线：0b35a984ec8335f3cfefc9dc198f8d337b93bd05。
最终程序/测试提交：999e0ca1b5187ce440a148873252bebf2864fd52。
最终仓库 tests/：**173 passed、1 skipped、0 failed**；冻结实验 harness：**7 passed**。
本批所列问题具备提交独立审阅的条件，尚未获得独立审阅通过结论。

## 范围与工作区

启动时分支为 refactor/cgr-pipeline-integration，HEAD 与审阅基线完全一致，没有其他新增提交
需要整合；工作区仅有未跟踪 code_graph/，未发现额外适用 AGENTS.md。
沿同分支工作，未创建新分支、reset、merge 或覆盖用户工作。code_graph/ 未读取、采用、
删除、移动或暂存。未修改 CGR 或三个业务仓库，未构建真实业务 graph/向量/BM25，
未启动 Neo4j、Docker、JVM、MCP 或其他常驻服务，付费 Embedding/LLM 请求为 0。
全部索引生命周期验证只使用测试夹具的合成源码和临时数据；未访问、迁移、清理用户真实索引。

AST、Jedi 0.20.1 与 LCT 的责任分工保持；根和实验环境均复用，没有安装或下载依赖。
没有 CGR 运行依赖、通用执行器或 Flow 引擎。小图＋MCP 端到端工作留待下一批。
随后的报告提交只更新本报告、契约边界说明、日志空白规则和精简证据；最终远端 SHA 见交付消息，
也可用 git log -1 --format=%H -- review/PYTHON_PIPELINE_PHASE1.md 定位。

## 修复前复现

先提交到工作区的测试覆盖五个字段/容器主要反例、sync/alias/async 工厂三条路径，以及
同秒逆序 UUID、恢复后发布/失败候选、旧指针保留三组快照场景。
在修改实现前实际得到 **11 failed、exit 1**，保存在 phase1-round3/before.txt、before.xml。
测试使用 closed_world=False，检查位置、caller 执行/词法作用域、应有/禁止目标、
unknown/complete/原因和最终 CALLS；工厂还检查包装/进入关系和无提前主体调用。
没有按解析输出修改答案，没有 xfail 或跳过难例，没有 sleep 或放宽旧游标断言。

## 四类问题的结果

| 类别 | 本批实现与验收 | 状态 |
| --- | --- | --- |
| 实例字段更新 | Assign、带值 AnnAssign、无值注解及 Delete 分开处理。注解-only 不覆盖值；删除后可回退类方法。简单同 receiver 直线方法的引用/常量 store/delete 可作有限效果关联；不支持的调用/参数/分支或被字段覆盖的方法使字段未知。其他 allocation 对象不受污染 | 通过 |
| 容器更新与来源 | 处理槽位 AnnAssign；有限字典展开读取展开时的源槽状态，按从左到右覆盖。后续源槽替换不反向改变副本；未知展开保留未知，后面的确定键可覆盖该键的不确定来源。无法覆盖的写入/逃逸不产生“缺失键”证明 | 通过 |
| contextmanager 工厂调用 | 工厂 Atom 纳入统一 callable 分类，acquire() 的 CALLS 指向原声明并标记创建阶段/不执行主体。WRAPS 记录标准库包装关系，CONTEXT_ENTERS 单独表示进入时恢复生成器；支持 async、装饰器别名及跨文件导入工厂别名 | 通过 |
| 快照保留顺序 | current.json 原子携带有界、去重的激活 history；build/recover 共用已有 update.lock。prune 按该链保留当前及策略要求的上一激活版本，不按随机版本名排序。恢复当前为 no-op；失败候选/完成 manifest 不算成功激活证据 | 通过 |

字段方法规则只检查有限的 AST 字段效果，不执行方法或建立通用跨过程状态。
构造器中的同类简单方法效果也覆盖；方法被实例字段覆盖时不假装执行原类方法。
条件/动态修改保持部分已知或未知。原实例隔离、普通字段、上轮六反例及原两项 gap 均在
最终完整测试中通过。本批新增正式测试共 38 项，没有修改任何既有 oracle 或冻结 fixture。

## complete 与冲突裁决

捕获范围内字段/槽位的完整性和排除候选都要求当前访问的 write_source_coverage，
记录源码行、事件种类和相关来源。继承的 literal-slot-state 或字段规则标签单独不足，
即使 Jedi 恰好给出同一候选也不能省略覆盖检查。
原始 Jedi 候选、LCT 轨迹、选中/排除/未裁决候选和具体规则仍分别保留；
缺覆盖时不简单合并双方，也不让 LCT 旧值排除 Jedi 正确信号。
两个注入控制分别证明“标签但无覆盖＋Jedi 冲突”和“标签但无覆盖＋Jedi 一致”均不完整。

简单确定场景仍完整，已知无有效目标须有缺失槽/越界/未绑定等证明；没有识别到目标、
内部 Atom 未被收集、只有一个候选或没有异常都不是证明。

## 工厂与执行阶段的最小契约调整

图输出 schema 从 2 到 3，仍使用一份 AST 声明目录，不另造检索解析器或业务源码 ID。

- acquire()：CALLS、target_role=decorated-factory、
  invocation_phase=context-manager-create、executes_body=false。
- WRAPS：标准库 contextlib boundary → 捕获原函数节点，保留 wrapper_origin。
- CONTEXT_ENTERS：with/async with 的执行 owner → 原函数节点，
  invocation_phase=generator-resume。生成器 body 中 C() 的词法/执行归属仍是 acquire。
- 普通 CALLS 的 executes_body=null，不新增“类声明主体在构造时执行”的错误保证。
- 查询核心只增加新关系的显式类型过滤，默认关系集合保持原样；没有运行 MCP E2E。

复杂 generator 协议、任意装饰器等仍有既有 unknown 边界，不能从创建调用完整推出进入/
yield 结果或运行时无异常。详见更新的 docs/PYTHON_PIPELINE.md。

## 发布顺序与旧格式策略

version 名仍为秒时间＋UUID，仅用作唯一身份。唯一发布/激活依据是原子 current.json：
version、previous、history_schema=1、最近不同激活的有界 history。默认至少保留 2 个。
recover 先完整校验，再把目标移到链首，旧 current 成为 previous；恢复后再 build 保留
恢复得到的 current。恢复当前不改链，不丢 previous。

未完成候选可清理；完成但未引用的候选/过期目录在历史充分时清理。
build-state 的时间或 failed 标记不证明年龄：标记可能在指针已发布后写入，
因此指针引用的有效版本始终保护。没有按候选名或 UUID 排序补足发布序列。
旧指针只有 version/previous 时沿用这两个有依据的顺序；若不足更大的保留数，
保守多保留其他完成目录，直到新链足够，不猜旧顺序。提高保留数不恢复已删除版本。
所有删除都限制在配置的 versions 直接目录，拒绝符号链接/越界目标；本批从未对真实数据运行。

同秒测试使 f/e/d/0 等 UUID 字典序与发布顺序相反，断言确切保留集合。
还覆盖旧游标到期、恢复后发布、失败候选清理、恢复当前、旧格式历史不足及发布后遗留
失败标记。既有 test_mutations_cursor_failure_recovery 原断言在最终全套中通过。
精简证据仅保存本批临时目录的 pointer/版本名，不上传 SQLite/索引内容。

## 验证时序、结果与限制

| 实际执行范围 | 结果 | exit |
| --- | --- | --- |
| 实现修改前新回归 | 11 failed | 1 |
| 稳定阶段本批定向测试 | 35 passed | 0 |
| 随后字段控制范围 | 12 passed | 0 |
| 覆盖标签两个负控制 | 2 passed | 0 |
| 第一次完整 tests/ | 172 passed、1 skipped | 0 |
| 最终完整 tests/ | 173 passed、1 skipped | 0 |
| 带 Git 元数据的冻结 harness | 7 passed | 0 |
| 冻结合成导出 | 39/39 标注、44/44 节点，未触限 | 0 |
| Ruff check / format --check / diff --check | 通过 | 0 |

第一次完整运行后增加了“Jedi 一致时也不能仅凭标签宣布完整”的门槛及一个负控制，
先复测两个覆盖控制，再运行最终完整 tests/。最终全套后程序没有修改，只给测试 import
组补了一处空行；随后 lint/format 通过，harness 串行运行。两次完整结果均保留，未掩盖时序。
修复过程中发现并修复了一个条件字段候选丢失的定向回归；最终既有回归失败 0，
本批强制验收剩余失败 0。跳过仍为可选真实缓存兼容测试，缺依赖跳过 0。
冻结答案/禁止目标未改，合成 TP/FP/FN 仍为 34/0/0，虚假确定 0。

这些是实际目标、禁止目标、作用域、阶段、关系和保留集合断言，不把框架通过当作
所有 Python 语义健全性证明。复杂方法效果、动态属性/描述符、任意装饰器、复杂复制/
别名/变参和反射仍有明确未知边界；旧格式缺失的历史只能保守保留。
未验证真实业务 graph、真实旧索引迁移、远程 MCP 或“小图＋MCP”闭环，不外推业务仓库准确率。

## 独立复现

在 LCT 根目录串行执行，输出路径选择尚未使用的名字。复用 Python 3.12 和已有锁定环境。

~~~powershell
.venv/Scripts/python.exe -m pytest -q tests/test_python_review_round3.py --basetemp=.tmp/reproduce-round3
.venv/Scripts/python.exe -m pytest -q tests --basetemp=.tmp/reproduce-round3-all
experiments/python_graph/.venv/Scripts/python.exe -m pytest -q experiments/python_graph/tests --basetemp=.tmp/reproduce-round3-harness
.venv/Scripts/python.exe tools/review_python_pipeline.py --output .tmp/reproduce-round3-frozen.json
.venv/Scripts/ruff.exe check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
.venv/Scripts/ruff.exe format --check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
git diff --check 0b35a984ec8335f3cfefc9dc198f8d337b93bd05..HEAD
~~~

旧选型实验运行前已确认本仓库 Git 元数据有效；实验自己建立的 cross-version 合成仓库也有
真实 Git 元数据，所有工具运行完成，未将缺环境算通过。
证据位于 phase1-round3/：原始 TXT/JUnit、简明 evidence.json（含源码指纹、解析裁决、
临时 pointer 状态及冻结摘要）、暂存审计。没有数据库、向量、索引、环境、密钥或大型临时产物。
只正常 push 当前分支，不 merge。完成后停止，等待独立审阅，通过后再进入下一批。

---

# 历史记录：上一轮 0b35a98 审阅修复批次

下文保留上一批报告，135 passed 等数字仅代表当时状态，不代表本批最终结果。

# Python 解析第一阶段：独立审阅修复批次

本批基线为 c1785038492a6955bbd140a31afc1a3867df3314。
六个审阅反例、原有两项 gap 以及本批新增控制均通过；最终仓库测试
**135 passed、1 skipped**，冻结实验 harness **7 passed**。
结论只适用于下列受测范围，不推断三个业务仓库的全库准确率或所有动态 Python 的健全性。

## 当前版本与范围

- 目录：D:\Projects\agentic-trpg\local-code-tools。
- 分支一直是 refactor/cgr-pipeline-integration；检查时 HEAD 与指定基线相同，
  工作区仅有未跟踪 code_graph/。未发现 LCT/祖先目录的额外适用 AGENTS.md。
- 最终程序与测试提交：521d6789f869eebaef21df727aa743e377012662。
  随后的报告提交仅保存报告/合成证据和日志空白规则；最终交付 SHA 见交付消息，
  或 git log -1 --format=%H -- review/PYTHON_PIPELINE_PHASE1.md。
- 没有新分支、回退、merge、reset/stash/rebase/force-push。只推送当前 LCT 分支。
  code_graph/ 未读取、采用、删除、移动或暂存；没有操作真实数据库、图、向量、缓存和备份。
  没有修改 CGR/三个业务仓库，也未扫描它们建索引。
- 复用既有根 .venv 和实验 experiments/python_graph/.venv；没有安装或下载依赖。
  Jedi 仍为 0.20.1，Python 3.12.14。测试串行，无 Docker/Neo4j/JVM/常驻服务或系统设置变更。
  没有付费 Embedding/LLM 请求，无新增 MCP、正式图、增量或发布协调实现。

## 六个反例与扩展控制

修改实现前，先加入六个 closed_world=False 正式测试，实际得到 6 failed、exit 1，
见 phase1-review/before-six.txt 和 XML；失败来自目标或完整性断言。
初始默认 lambda 的位置 helper 后来补正为显式调用行 2，避免误匹配声明行；
修复前其目标断言已经失败，没有改变目标、禁止目标、作用域或完整性答案。

| 审阅项 | 修复与严格断言 | 状态 |
| --- | --- | --- |
| 实例字段覆盖方法 | 普通实例字段优先于非数据类成员，实例保存的函数不绑定 self；目标 target，禁止 C.run。数据描述符/动态访问/构造协议不能用该规则证明 | 通过 |
| 默认参数 lambda | 语法 parent/qualname 不改为“修复”手段；新增 resolution_parent。定义头按外层解析，lambda body 仍独立执行；目标模块 target，禁止 f.target | 通过 |
| NamedExpr | 明确顺序 store 生效，cb→a；短路/条件 store 有候选且 unknown；真正未绑定局部仍无全局回退 | 通过 |
| 删除槽位 | 直接删除移除旧值，缺失槽有无有效目标证明；条件/动态删除 unknown，重写及无关槽分别处理 | 通过 |
| 关键字容器逃逸 | 覆盖位置/关键字/*/** 及显式嵌套容器；a 保留但 complete=false。无关容器传递不污染完整性 | 通过 |
| 负字面下标 | Constant 与 UnaryOp 正负整数按有限序列归一化，无 eval；-1 只选 b，禁止 a；正/负边界、越界、动态下标均检查 | 通过 |

新增控制包括不同实例、未知构造参数、普通方法未覆盖、实例直接写入、property/数据描述符、
非数据描述符、动态 __getattribute__/__setattr__、嵌套/装饰器参数/类中默认 lambda、
条件 walrus、删除后重写、关键字及解包对照。正式 review 测试共 44 例，
其中开放输入反例/控制没有被统一降级为 unknown；简单确定场景仍 complete=true。

额外发现并先复现了“实例通过关键字传给未知函数后字段仍完整”的问题，exit 1，
见 escape-before.txt；用有限实参逃逸守卫修复，字段原候选仍在，完整性降为 unknown。
该修复发生在最终全套之前。

## 原两项 gap

| 原 gap | 当前行为及边界 | 状态 |
| --- | --- | --- |
| generator contextmanager | 按 Jedi 外部定义核对 contextlib.contextmanager/asynccontextmanager，捕获内同名函数不算标准包装；单层直线 yield 建立协议证明。支持别名和 async with；多 yield/分支/异常控制流/await 等复杂协议保留未知 | 原 oracle 通过 |
| separate instance registries | 保存 AST 创建位置、构造参数和绑定接收者 origin，注册 key/value 只与同一 receiver 关联；first.dispatch 保留 a，禁止 second 的 b。闭合 fixture 完整；开放输入保留 a+未知 | 原 oracle 通过 |

tests/test_python_pipeline_gaps.py 只更新了过时说明，未改任何正确答案、fixture 或断言，
未 xfail/skip。review-cases.json 导出两项在 closed_world=True/False 的实际结果。
实例关联是有限源码位置连接，没有通用对象堆；工厂复用、循环或函数内多次创建不能据此证明
实例容器唯一性，明确 unknown/nonunique-instance-container-allocation，避免合并成确定目标。

## 完整性及 Jedi/LCT 冲突规则

Result 现在携带语义证明。complete 同时要求无未知原因且有具体证明；
空 Result、唯一候选、工具无异常都不构成证明。新增 resolution_kind 区分：

- proven-targets：有依据的完整目标集合。
- partial-targets：有候选，也有未知来源。
- proven-no-target：未绑定局部、删除后缺失字面槽、越界等明确无有效目标。
- unsupported-or-unknown：缺证明、工具失败或尚未支持。

每处保留原始 Jedi 映射、LCT 关联轨迹、双方候选及 resolution_decision。
本批六个修复后双方候选一致；曾被 LCT 错误覆盖的正确信号不再被错误规则替代。
如果双方不同：仅完整的已测试有限语义规则可排除候选，并列出 semantic_rules/
excluded_jedi_targets；部分关联冲突保留未知及 unresolved_jedi_targets。
没有决定性依据时保持冲突，不按一方优先，也不简单并集。模拟空适配结果的负控制检查
Jedi 仍有候选时不能输出“空且完整”。来源目录、关系和检索仍共用同一节点提取器。

## 最终验证与回归

| 范围 | 结果 | exit |
| --- | --- | --- |
| 新增六反例，修改实现前 | 6 failed | 1 |
| 额外实例逃逸反例，修复前 | 1 failed | 1 |
| 新增 review 定向用例 | 44 passed | 0 |
| 最终完整 tests/ | 135 passed、1 skipped、0 failed | 0 |
| 冻结解析实验 harness | 7 passed | 0 |
| 冻结合成导出 | 39/39 标注、44/44 节点，analysis_limited=false | 0 |
| Ruff check / format --check | 通过 / 通过 | 0 / 0 |
| diff whitespace/文档链接及围栏/暂存文件审计 | 通过 | 0 |

135 个通过项包括既有回归、原两 gap 和新 review 控制。
跳过仍是已有 opt-in 真实缓存兼容测试，缺依赖跳过 0。
本轮修改前的完整基线 89 pass/2 fail/1 skip 来自独立审阅及首轮留存证据；
本轮修改实现前实际重跑的是新增六反例，不能冒称重新跑过旧全套。
最终新增失败 0，剩余强制验收失败 0。修复过程中曾出现单实例、未观察 dispatch 调用的
旧注册表回归，已恢复有限构造来源，最终原测试通过。

首次全套为 134 pass/1 skip；之后加入上面的实例逃逸修复，再最终运行 135 pass/1 skip。
**最终完整 tests/ 与 harness 之后没有程序修改**，只生成证据和编辑本报告。
两个进程按 JUnit 时间戳不重叠。原 truth/truth-freeze/real_truth 和冻结 fixtures 字节未改，
harness 继续检查冻结哈希及禁止目标；合成调用指标仍 TP/FP/FN=34/0/0、虚假确定 0。
这些不是业务仓库的 precision/recall，也不是独立审阅通过或远端 CI 通过。

## 复现与剩余限制

以下在 LCT 根目录串行执行；复用已有环境，输出目录选择尚未使用的名字。

~~~powershell
.venv/Scripts/python.exe -m pytest -q tests/test_python_review_regressions.py tests/test_python_pipeline_gaps.py --basetemp=.tmp/reproduce-review-focused
.venv/Scripts/python.exe -m pytest -q tests --basetemp=.tmp/reproduce-review-all
experiments/python_graph/.venv/Scripts/python.exe -m pytest -q experiments/python_graph/tests --basetemp=.tmp/reproduce-review-harness
.venv/Scripts/python.exe tools/review_python_pipeline.py --output .tmp/reproduce-review-frozen.json
.venv/Scripts/ruff.exe check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
.venv/Scripts/ruff.exe format --check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
git diff --check c1785038492a6955bbd140a31afc1a3867df3314..HEAD
~~~

无既有环境的独立审阅可按根/实验各自 uv.lock 安装；本轮没有执行安装。
所有受测模式已通过，但复杂动态描述符/属性、任意装饰器、复杂 MRO、控制流写入、
重用创建位置的实例容器、一般变参/逃逸关联仍有限。支持的有限规则与未解析原因见
[节点与关系契约](../docs/PYTHON_PIPELINE.md)。没有恢复 CGR Flow、通用执行器或堆模拟器。
后续 Neo4j/增量/检索迁移仍须使用同一 version_id/site_id、作用域、证明及未知信息，
本轮没有提前实施或重建真实索引。

---

# 历史记录：首轮第一阶段交付

以下保留 c1785038492a6955bbd140a31afc1a3867df3314 的首轮报告原文。
其中“本轮失败两项”等措辞仅代表当时历史状态，不代表上面的独立审阅修复批次。

# Python 节点与调用关系第一阶段审阅报告

本轮交付程序、测试及可复现证据，**完整语义验收仍失败 2 项**。
本报告不是独立审阅、远端 CI 或三个业务仓库的准确率结论。

## 1. 版本与边界

- 目录：D:\Projects\agentic-trpg\local-code-tools。
- 分支始终为 refactor/cgr-pipeline-integration；起始 HEAD：
  9d5a54f9f8ecdd6f5ce6349a916c03522a1453a7。
- 最终程序/测试提交：542100e1f9b6150aa34b95f480469c30464d5b66。
  随后的报告提交只保存本报告与证据（含原始日志空白规则）；最终交付 tip 的完整 SHA 见交付消息，
  也可执行 git log -1 --format=%H -- review/PYTHON_PIPELINE_PHASE1.md。
  不把报告自身的 SHA 写进自身制造循环身份。
- origin：https://github.com/agentic-trpg/local-code-tools.git。
  没有 main；未创建、切换、拉取 main，未 reset/stash/rebase/merge/force-push。
- 起始已经是预期基线，无需重新定位；feat/cgr-neo4j-integration 仍保留
  d7211fa50a99d3bc3bebdca0a9f5b70c48a6963d。
- 起始仅有未跟踪 code_graph/，没有读取或采用其中实现，未删除、移动或暂存。
  未操作已有真实数据库、图、向量、缓存或备份。
- LCT/祖先目录未发现额外适用 AGENTS.md；入口给出的 SM 指引不改变 LCT 为唯一工具主体。
- CGR 只读参考分支 refactor/reuse-upstream-graph-pipeline，HEAD：
  4686c82b53b6745acd3a760599cb94d709a9ba79；交付前分支/HEAD 相同且工作区干净。
  参考 class-body aliases、scope-bound names、context managers、callback flow 测试语义。
  没有复制 CGR 代码或测试、安装其依赖、修改或推送 CGR。参考许可证为 MIT，
  本轮无复制代码的归属条目。

## 2. 保留、修改与移除

保留 Voyage 客户端、向量缓存、BM25、HNSW、RRF、过滤、分页、分层和源码定位。
storage 仅同步一行说明，继续消费 extract 的同一目录和 Graph facade；
query/embedding/lexical/MCP/管理实现没有改变，本轮不重建真实索引。

extract 增加 lambda、精确 node_type、源码范围及逻辑/版本身份；
legacy kind/node_id 保持兼容，method/lambda 仍进入 function 检索层。
Graph 保留依赖版本守卫和 build/imported 入口，增加独立 sites 与兼容 edges。
新增 python_analysis，负责私有捕获副本、Jedi 映射和有限关联。
Jedi 从 0.19.2 固定到 0.20.1，同步 uv.lock/requirements.lock.txt；
其余正式依赖不变，没有 CGR/Neo4j/Docker 运行依赖。

移除旧 Graph 的全局单调 bindings/members/maps/returns fixed-point、字符串当表达式解析、
只增不删的赋值及“收敛且唯一即 resolved”的判定。
旧 truth/truth-freeze/real_truth/fixture/评估报告未改；
worker 明确 synthetic 闭合驱动，harness 改为要求已知错误修复，
没有修改预期目标或冻结答案。

## 3. AST、Jedi、LCT 与上一轮 Flow 的区别

| 层 | 本轮职责 |
| --- | --- |
| AST | 唯一节点、层级、范围、调用/引用/装饰器位置及执行阶段 |
| Jedi 0.20.1 | 名称、导入、接收者/调用结果的定义信号；infer 本身不证明完整性 |
| LCT | 按捕获路径/行列/类型验证定义，有限关联实参/绑定接收者/容器，保留未知和完整性依据 |

有限规则包括顺序赋值杀死旧值、if 候选、callback 实参与默认值、self/cls 绑定偏移、
同次注册调用 key/value 关联、字面容器及直接槽覆盖、直接 return、
单继承/零参 super、普通 __enter__/__aenter__ 协议。
没有上一轮 integration/Flow 环境、堆、通用 Python 执行器或大规模类型固定点，
没有把代码放进 CGR 当成能力复用，也没有采用未跟踪 code_graph/。

总关联 20,000、递归 40，触限明确 unknown；递归截断答案不污染 memo。
Jedi 原始映射与 LCT 关联轨迹分开保留。冻结捕获没有触限。
普通生产输入默认开放；closed_world 只由合成驱动显式设置。

## 4. 逐项验收

| 要求 | 结果与边界 |
| --- | --- |
| 唯一节点、重定义、嵌套同名、同行 lambda | 通过，44/44 冻结节点；逻辑/版本身份分开 |
| 普通调用、别名、跨文件/相对导入、重导出、src | 小型合成及已有用例通过；排除文件不泄漏 |
| self/cls/static/classmethod/继承/super | 通过，含继承 classmethod 返回具体子类 |
| bound method 保存后调用 | 通过，target 不被错当 self，证据保留 receiver |
| 无条件赋值、类 run=target | 通过，旧目标禁止；含同行绑定与容器直接覆盖 |
| 条件候选 | 通过，候选数与未知来源分开 |
| dict/list 固定/动态槽、注册表 | 单容器、跨文件、单实例通过，不同键不混入；多实例身份仍失败 |
| callback、已知+未知、转发/default/keyword-only | 通过，开放输入与混合源保持 incomplete |
| 返回函数/对象/链式调用 | 通过，含返回 lambda |
| with/async with | 普通对象协议通过；生成器 wrapper 的完整性仍失败 |
| 嵌套/lambda owner | 通过，body 不归给创建函数 |
| defaults/decorators/annotations | 定义阶段及 eager/future/local annotation 通过；任意装饰器替换明确 unknown |
| 裸名称/未绑定局部 | 通过，不误连同类方法或同名全局 |
| 外部/排除/无法映射/工具失败 | 正反例通过，缺 full_name 仍可映射，歧义拒绝，失败有原因 |

接口详见 [节点与关系契约](../docs/PYTHON_PIPELINE.md)。
CALLS、REFERENCES、CONTAINS、IMPORTS、INHERITS 分开，存引用不产生执行边。
每个位置有 targets、unknown_origin、complete、依据、证据、词法 owner、执行 owner 和 phase。
legacy status 只是兼容投影，不能代替这些字段。

## 5. 保留失败与候选方案

1. generator contextmanager：Jedi 找到 Resource.work，但 yield/wrapper 的完整性依据未建立，
   测试要求完整结果，实际 incomplete。候选：核对 contextlib 装饰器实际来源后，用 Jedi
   generator/yield 信息补足协议证据，并覆盖异常、多 yield 和 asynccontextmanager；
   不泛化为任意装饰器执行器。
2. separate instance registries：两个 Registry 实例分别注册 a、b，仅 first.dispatch()。
   当前缺实例容器身份，检测多构造位置后返回 separate-instance-containers-not-modeled，
   拒绝把 b 混成确定候选；正确 a 仍缺失，因此严格失败。候选：研究 Jedi
   definition/value 是否能保留分配位置，再做有限 owner 关联；不能退回大 Flow/堆模拟器。

两项测试在 tests/test_python_pipeline_gaps.py，正常收集、真实失败，无 xfail/skip。
复杂多继承、反射、任意装饰器替换、复杂控制流写入和变参运输还可能 unknown；
不能从通过的合成范围推断全库健全性。

## 6. 修改前后证据

| 范围 | 修改前 | 修改后 |
| --- | --- | --- |
| 原有 tests/ 同 36 个测试身份 | 35 pass、1 skip，exit 0 | 35 pass、1 skip，无既有回归 |
| 首批新契约，修改源码前运行 | 9 fail，exit 1 | 后续拆为逐 oracle 用例 |
| 最终同一解析范围 81 例 | 24 pass、56 fail、1 skip，exit 1 | 78 pass、2 fail、1 skip |
| 完整当前 tests/ 92 例 | 见下述基线说明 | 89 pass、2 fail、1 skip，exit 1 |
| 冻结实验 harness | 7 pass，exit 0 | 7 pass，exit 0 |
| ruff check / format --check | 未重算旧版静态基线 | exit 0 / exit 0 |
| git diff --check | 干净起点 | exit 0 |
| 最后 IMPORTS 投影局部修复 | 未单独打分 | 受影响 4 pass，exit 0 |
| 无路径且无 full_name 的定义映射修复 | 未单独打分 | 受影响 2 pass，exit 0 |

tools/run_python_pipeline_baseline.py 将固定 SHA 的只读 Git blobs 物化到新的 .tmp，
强制先导入基线 lct，防止 pytest 路径注入误用新代码，不切换分支。
完整临时基线回放有 57 fail/34 pass/1 skip：56 是新契约失败，
另 1 是临时副本缺 .venv 入口导致的 registration 基础设施失败；
原地修改前此测试已通过。另存 parser-only 81 例排除此差异。
不能把基础设施差异算产品修复；新 API 在旧版不存在，部分失败为缺字段/接口，
也不能把 54 个转为通过直接解释为 54 个独立旧语义 bug。

冻结目标指标 TP/FP/FN：28/3/6 → 34/0/0；原 callback_mixed 虚假确定 → 无。
39/39 标注（36 调用、3 引用）符合未改答案；所需节点 44/44。
这些不覆盖两项新失败，不是三个业务仓库准确率。
没有修改前已失败的原有产品测试；新增未满足验收 2 项。
缺依赖跳过 0；1 skip 是既有、显式 opt-in 的真实缓存兼容测试。

TXT/JUnit、逐位置证据、冻结/程序指纹和暂存审计在 review/phase1/。
全套最后运行后修复 IMPORTS 边界投影（4 测试通过），以及同时缺 path/full_name 的
不可定位结果保持 unknown（2 测试通过），并恢复 Graph 原有换行格式；冻结导出通过；
没有为此局部修复重复无关全套。

## 7. 完整复现

在 LCT 根目录、Python 3.12，以下命令串行执行；测试输出路径使用新目录。
根环境复用，仅升级 Jedi；实验由 uv 从缓存生成小环境，未下载依赖，
未安装 CGR 全套依赖或启动服务。

~~~powershell
uv sync --offline --locked
uv run --offline --locked ruff check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
uv run --offline --locked ruff format --check lct tests tools experiments/python_graph/worker.py experiments/python_graph/tests/test_experiment.py
uv run --offline --locked pytest -q tests --basetemp=.tmp/reproduce-phase1-all --junitxml=.tmp/reproduce-phase1-all.xml
# 上条预期 exit 1，两项 gap 真实失败；下面仅验证已实现范围：
uv run --offline --locked pytest -q tests --ignore=tests/test_python_pipeline_gaps.py --basetemp=.tmp/reproduce-phase1-supported
uv run --offline --locked --project experiments/python_graph python -m pytest -q experiments/python_graph/tests --basetemp=.tmp/reproduce-phase1-harness
uv run --offline --locked python tools/review_python_pipeline.py --output .tmp/reproduce-phase1-frozen.json
# output 必须尚不存在，此命令预期 exit 1，旧版缺新契约：
uv run --offline --locked python tools/run_python_pipeline_baseline.py --parser-only --output .tmp/reproduce-phase1-baseline
git diff --check
~~~

原始完整/初始基线命令和计数见 phase1/summary.json。
无离线依赖缓存的新机器先用 uv sync --locked；缺依赖须报告，不能当作通过。
无 Embedding/LLM 请求；无真实 build/update、三库索引扫描、Neo4j/Docker/JVM、
安全软件或系统设置变更。JUnit 时间戳确认全套与 harness 无重叠运行。

## 8. 后续接口与交付

Neo4j 必须消费同一目录和 sites，使用 version_id/site_id，保留 unknown/complete/边界/证据，
不能按 qualname 合并版本或从 legacy status 反推完整性。
检索按原 kind/node_id 兼容，method/lambda 另有 node_type；
旧真实索引由 program_hash 拒绝误用，本轮没有重建或改写 manifest。
增量阶段需定义快照、删除/重定义、调用依赖失效及旧引用/证据隔离。
正式 Neo4j、完整增量、发布协调、sites 查询 API 和新 MCP 均未实施。

提交只含程序、测试、小 fixture、依赖锁、文档和无真实数据证据。
报告提交后仅正常推送 origin/refactor/cgr-pipeline-integration，不 merge。
最终 SHA/远端核对见交付消息，随后停止实现，等待独立审阅。
