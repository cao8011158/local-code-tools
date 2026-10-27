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
