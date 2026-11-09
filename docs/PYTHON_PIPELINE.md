# Python 节点与关系契约（第一阶段）

> 本文为早期阶段契约。当前解析重构的目标权威、来源边界和未知结果见 [Jedi authority plan](../review/parser-refactor/JEDI_AUTHORITY_PLAN.md) 与 [developer report](../review/parser-refactor/DEVELOPER_JEDI_AUTHORITY.md)。下文有关 LCT finite associations、目标裁决、字段/容器回推的历史描述不代表当前候选实现。

本契约只描述 LCT 当前源程序；未迁移或重建真实索引。入口仍为
lct.extract.extract(files) → (nodes, asts) 和 Graph(nodes, asts, repos).build() → (edges, info)。
调用方先捕获源码；Jedi 只读本次捕获的私有副本，源码不被 import/执行。
没有 CGR 包依赖、新 MCP 服务或业务仓库扫描入口。后续 Batch 1 已新增可选 Neo4j 小图投影驱动与独立管理入口，见 [NEO4J_SMALL_GRAPH.md](NEO4J_SMALL_GRAPH.md)；本解析阶段仍未接入 Neo4j。

## 唯一节点目录

| 字段 | 含义 |
| --- | --- |
| repository / repository_id | 由输入声明的仓库名称/身份；未提供 repository_id 时沿用名称，调用方负责唯一性 |
| path | 捕获的仓库相对路径 |
| node_type | module、class、function、method 或 lambda |
| kind | 兼容既有检索层的 module/class/function；method/lambda 仍属于 function 层 |
| name / qualname / parent / module | 名称、限定名、语法包含 owner 和模块节点 |
| resolution_parent | 名称解析的外层作用域；定义头中的 lambda 不闭包捕获被定义函数的局部变量 |
| node_id / logical_id | 同一逻辑身份，包含仓库、路径、检索 kind、限定名和逐层出现序号 |
| snapshot_id / snapshot_scope | extract 的仓库捕获内容根；单独 python_nodes 调用为单文件捕获 |
| version_id | 仓库身份、快照、逻辑身份、精确范围和源码指纹的 SHA-256 |
| definition_line / column / end / end_column | AST 声明范围，行从 1 开始，列为 UTF-8 字节偏移，末列为排他边界 |
| start | 为兼容源码展示保留的起始行，可能包含装饰器和相邻注释；不代替精确 AST 范围 |
| signature / docstring / fingerprint / source_sha256 | 源码签名、已有说明、节点内容哈希、整文件内容哈希 |

lambda 使用独立 ordinal，因此同一行、同一作用域多个 lambda 互不碰撞。
重定义节点的后代含 owner ordinal；插入更早的同名声明可能改变逻辑序号。
不承诺跨重命名或跨移动匹配，不向业务文件或 docstring 注入 ID。
extract/embedding_texts/storage 共用这些节点；没有第二套检索用 Python 提取器。
源码展示仍按现有行范围，精确切片应使用 AST 范围；同一行 lambda 的展示可能包含相邻源码。

Jedi full_name 只保留为证据。映射必须匹配私有捕获路径、声明名称 token 的行列及类型，
同时保留 version_id/source_sha256。full_name=None 可以有效；不唯一或未匹配必须保留原因。
没有捕获的定义属于 external-or-excluded，不能按相似名称连到内部节点。
跨仓库 RE pin 不匹配时保留原依赖版本边界。

## 调用位置与关系

info.sites 是调用位置的完整语法目录，而不是 CALLS 边数量的别名。每处包含：

- site_id：捕获快照、源路径、完整 callee 范围和位置类型的内容身份。
- lexical_owner、execution_owner、phase：定义头的词法节点可为被定义函数，执行 owner 为外层；
  函数/lambda body 属于各自节点。phase 为 module/class_body/body/definition/annotation。
- targets：已验证的内部候选；bound receiver 保存在关联证据，避免别名丢失 self/cls 偏移。
- boundaries：外部、排除源码或依赖版本边界，独立于内部目标。
- unknown_origin：是否仍有未知来源；complete：是否有有限语法/显式输入边界下的完整性依据。
- resolution_kind：proven-targets、partial-targets、proven-no-target 或 unsupported-or-unknown。
- resolution_decision：Jedi/LCT 原始候选、选中目标、已排除或未裁决候选及具体语义规则。
- completeness_basis、unresolved_reasons、evidence：AST、Jedi 原始映射和 LCT 逐位置关联路径。
  关联路径最多 100 步，截断单独标记；完整性不由证据输出长度推断。

同一位置可以同时有 targets=[A] 和 unknown_origin=true、complete=false。
完整的 [A,B] 是两个有依据的可能目标；零目标、complete=true 必须有静态无效调用的显式证明，例如未绑定局部、缺失字面槽或越界下标。
空 Result、候选数、工具无异常均不构成完整性证明。
Jedi infer 单独输出不证明穷尽；项目输入默认开放。closed_world 只由本轮合成驱动显式设置，
生产 build 未设置它，也没有新增一个面向业务的闭合世界开关。

| 关系 | 精确含义 |
| --- | --- |
| CONTAINS | 目录中的词法包含，不表示执行 |
| REFERENCES | AST 的值引用；存入变量、容器或 return 本身不执行被引用函数 |
| CALLS | 显式调用或装饰器应用的候选投影，带 site_id；装饰后的上下文工厂也有创建调用 |
| WRAPS | 已验证 contextlib 装饰器对捕获生成器声明的包装关系，源为标准库 boundary，目标为原声明 |
| CONTEXT_ENTERS | with/async with 进入协议恢复原生成器，独立于工厂创建 CALLS |
| IMPORTS | import token 按精确捕获定义映射；可指向重导出后的实际定义 |
| INHERITS | 显式 AST 基类关联 |

旧 status 仅是兼容投影：唯一完整目标为 resolved，多候选或部分已知为 possible，
外部为 boundary，无 callable 目标保留 unresolved 位置。unresolved 并不总表示未知来源。
图输出 schema=3。每条边带 source_version_id/target_version_id，内部身份仍以节点目录为准。
工厂 CALLS 指向同一声明节点，target_role=decorated-factory、
invocation_phase=context-manager-create、executes_body=false；不声称立即执行 yield/body。
WRAPS 保留 wrapper_origin；CONTEXT_ENTERS 的 invocation_phase=generator-resume 表示进入时
恢复主体。普通 CALLS 的 executes_body=null 不对 class/函数执行协议作新增保证。
新增关系可由现有查询核心显式过滤；默认关系集合不变，本轮未运行 MCP 端到端验证。
外部没有伪造的内部节点或 version_id；捕获范围缺失和工具错误不能静默变成“没有调用”。

默认参数、装饰器表达式及应用发生在定义阶段。Python 3.12 eager annotations 记录为
annotation；future annotations 和函数局部变量注解不产生执行调用。
每个装饰器都有应用位置；工厂装饰器表达式的调用与返回装饰器的应用分别记录。

## 边界与后续消费者要求

有限关联只处理词法 reaching binding、if 候选、显式实参与默认值、绑定方法接收者、
字面容器槽、直接槽替换、项目注册调用的同次 key/value 对、直接返回表达式及普通上下文协议。
没有 Flow 环境/堆、通用执行器、全程序类型固定点或任意路径求值。
20,000 次关联和递归 40 是拒绝边界；不得把预算耗尽伪装为完整结果。

原两个 gap 保留为严格回归：单层直线 yield 的 contextlib 包装协议，以及模块顶层不同
构造位置的实例注册表。装饰器按 Jedi 实际定义来源核对，支持别名和 asynccontextmanager；
分支/多 yield、异常控制流或异步 await 等复杂协议仍保持 unknown。

实例字段查找先拒绝未建模的数据描述符、自定义动态属性/构造协议，再应用普通实例字段
优先于非数据类成员的规则。保存到实例的函数不会被误绑定 self。绑定方法和容器沿
allocation 源码创建位置关联，不建立运行对象堆；工厂复用/循环或非模块创建的实例容器
不能据此证明唯一身份，明确报告 nonunique-instance-container-allocation。

直接 walrus store 顺序生效；条件/短路 walrus 保留未知。字面槽直接删除会移除旧目标，
条件/动态删除保留未知；重写和无关槽分别处理。有符号字面整数按序列范围归一化，
不使用 eval。容器逃逸检查覆盖位置参数、关键字、星号、双星号及显式嵌套容器。

AnnAssign 有值才是写入，纯注解不覆盖字段或槽位；Delete 会移除字段/槽位。
字段删除可回退非数据类成员。有限效果先解析调用前的真实 callee 和绑定 receiver，
实例覆盖发生在调用前/后必须分开；保存的 bound method 保留原目标和接收对象，
不能按表面对象或类中同名声明套用摘要。普通同步方法只识别直线 self 字段
引用/常量 store/delete，bare/简单 return 终止摘要，后面的语句不能贡献效果。
构造器的直线 return 同样截断；条件终止及复杂控制流保持未知，不建立通用 CFG/执行器。

coroutine-create、generator-create、async-generator-create 只创建延迟对象，
executes_body=false；不应用未执行的主体或 return 值。context-manager-create 仍沿用
既有独立创建/进入协议。显式 await、next 等恢复阶段本批未建模为效果摘要，
字段返回 deferred-method-resumption-not-modeled，而不是套用“调用即执行”。
复杂方法、未知目标/参数、构造器内被覆盖的复杂调用等继续保留未知。没有执行被分析源码，
没有通用异步调度或跨过程堆模拟。其他 allocation 不因表面调用对象的别名而错用字段效果。

字典展开按源码顺序复制有限源槽状态，支持此前 store 和 AnnAssign 更新。
后续显式键覆盖前面的展开；后续未知展开使已有值部分未知。每次展开同时传递
槽位候选、条件写入/删除造成的可能缺失，以及源逃逸等未知原因，不只复制 events。
条件候选以每键 Result 保存，possible-missing-slot 是内部来源标记，不是伪造 CALLS 目标。
可能缺失的源键须保留展开前的目标键候选；源自身尚有未知时，sealed 不能重新证明该值确定。
来源限制中的候选和未知也进入动态槽，不能在复制具体键时抹掉。已明确覆盖的目标键可过滤
前序动态不确定性，其他键不被无条件污染。纯字典复制不继续引用源的后续槽替换。
复杂来源、逃逸或无法覆盖的写入保留原因，不把缺少候选变成缺失键证明。

副作用事件目录在同一 AST inventory 的 execution owner/phase 基础上每个快照构造一次。
python_effects.EffectCatalog 按作用域保存 Call、Await、普通/标注/增强赋值、NamedExpr、
Delete、隐式名称绑定、装饰器应用、终止及不支持的语法区域。发现事件不依赖效果处理器是否
支持它；字段查询使用相关构造器/方法及读取前的作用域目录，槽查询使用目录中的槽依赖范围，
不再逐查询遍历全仓库 AST。类定义主体以独立执行作用域依赖表示，相关效果未特化时保持未知，
但类中尚未调用的方法主体不当成已执行。名称/值解析仍由既有 AST reaching 与 Jedi 提供，没有新执行器。

目录递归访问表达式，Call/Await 在条件、参数、元组、容器、短路表达式中仍独立存在。
支持的直线顺序为操作数先于操作、赋值 RHS 先于写入、字典键/值交错、调用 callee/实参先于
调用；事件序号只在同一 scope 内有效。分支、短路后项和链式比较的后续 comparator 标 conditional，循环、异常和未建模
协议标 ordered=false/region；这些标记不是运行路径或通用 CFG。定义头沿用既有 definition/
annotation owner，嵌套函数/lambda 主体在独立目录内，不能当成外层正在执行的操作。

每个必需事件在处理前进入覆盖义务；结论是 NO_EFFECT、KNOWN_EFFECT 或 UNKNOWN_EFFECT，
带源码位置、原因及调用目标/接收者/阶段依据。缺失处理器或无法确认相关性默认为未知；
UNKNOWN_EFFECT 不能因其他依赖再次得到 NO_EFFECT 而消失。无法处理的次序、关联、区域和预算
缺口阻止认证。普通同步方法与构造器共用 field_scope/field_event，而不是两套扫描规则。
有限摘要以实际调用目标、稳定绑定 receiver、普通执行阶段为前提；对实际接收者参数名的
重绑定/删除、有值注解、解包或隐式绑定拒绝剩余摘要，记录 receiver-binding-changed。
其他不支持的局部绑定也会拒绝摘要；纯注解无写入。直线 return 后事件不可达，不能贡献效果。

Await 和延迟对象传递从同一目录处理，包括先保存 pending 后等待。这里只保留恢复事件和
接收者关联，不模拟恢复主体：可能涉及当前对象时产生 deferred-method-resumption-not-modeled；
关联不明记录 deferred-receiver-association-gap，不能因没有 allocation 匹配而判定无影响。
有明确独立创建位置的另一对象不污染当前对象。仅创建协程/生成器不执行主体，实参中自身的
调用仍先独立求值。复杂控制流、隐式动态协议和无法特化的摘要仍可能未知。

Jedi 与 LCT 不简单合并。write_source_coverage 包含 required_events、逐事件 checks/outcome、
sources 和 gaps；complete 是独立覆盖检查的结果，不从最终 Result 没有 unknown 反推。
认证要求所有必需事件都有确定结论、来源属于支持范围且没有未解决缺口；已处理但结论未知
仍不完整。valid_coverage 再核对义务与结论及来源，裸 complete=true、proof 字符串或 signals
一致不能替代它。certified 仅附规则标签。Result.requirements 保留字段/槽位来源义务，union、
绑定、字典复制和变量别名读取不能抹去；Graph 的完整性和 adjudicate 排除候选共用这一门槛。

字典复制仍保留候选、未知来源、可能缺失及从左至右覆盖。为固定键做相关性覆盖时，后续
明确键值可以屏蔽前序展开的槽来源依赖，但不能跳过其表达式自身的调用事件；源复制完成后的
替换不回流副本。不能仅凭 sealed/literal-slot-state 认证；来源和相关操作也须覆盖。
原始 Jedi 记录、LCT 轨迹及排除/未裁决理由分别保留。只有完整且有效的覆盖和具体语义规则
才能排除冲突候选；否则保留部分关联及未裁决 Jedi 候选，明确 unknown/complete=false。
没有把双方候选简单并集后标完整，也没有把正常直线方法或确定字典复制统一降级。

## 调用访问与 NO_EFFECT 证明

字段事件不再以“没有直接找到当前实例”为无影响依据。python_access.ReceiverAccess
复用已有值解析和 container_slots，返回 REACHABLE、NOT_REACHABLE 或 UNKNOWN（Access）。
REACHABLE 表示发现有依据的可达路径，不表示一定修改；NOT_REACHABLE 必须覆盖全部相关来源；
UNKNOWN 记录来源、动态结构、调用、递归或预算缺口。一个已知路径足以阻止默认无影响；
存在未知来源时不能因为其余来源不相关就判不可达。旧布尔 container_reachable 仍服务原槽位
传输兼容检查，不能直接为新的字段调用无影响认证提供证明。

支持显式 list/tuple/dict、多层内容、变量别名、位置/关键字及星号/双星号来源。
普通 dict 的键和值都检查；*dict 运输键，**dict 运输值且要求键语义有依据。
读取当前有限槽状态及来源限制，不只看创建字面量；未知修改、逃逸、捕获后容器修改或递归
结构阻止不可达证明。不能完成的对象/属性关联保留 UNKNOWN，不建立一般对象堆。

被调目标的有限依赖摘要按本次定义身份和 version_id 缓存；使用实际调用位置和参数绑定检查
词法捕获、外部绑定、被使用的默认参数、绑定接收者及传递调用。参数/局部变量不因同名就
当成捕获，global/nonlocal 按词法声明处理。外层捕获在已知调用时点读取，不能拿其后的覆盖
证明当前不可达；缺少时点且存在重绑定则未知。默认值按定义阶段的值处理。未调用的嵌套
函数主体不作为当前执行依赖；把带捕获的函数当参数传出时则须检查其可达路径。
类绑定、有限类存储/构造输入和可见字段关联用于区分明确独立对象；先前调用可能改变对象
关联时，也须检查缓存的传递依赖，不能以创建初态证明独立。未支持的动态路径未知。
预算耗尽同时标记 analysis_limited。传递分析只有源定义与既有预算内的有限依赖检查，没有任意调用效果执行或类型固定点。

实际目标/入口有未知，或对象可达而没有适用的效果摘要，产生 UNKNOWN_EFFECT，例如
captured-receiver-effects-not-modeled、instance-argument-escape、unresolved-call-access。
普通同步方法继续用原 method_field_effect；有限事件摘要也用于 lambda 主体，常量 lambda 和
已验证完全不使用输入的函数可保持精确。调用返回值来源无法证明时保留未知，不将工具推测的
一个非目标返回值升级成不可达证明。
协程/生成器创建仍不执行主体，操作数求值独立记事件，恢复/调度继续未知。
调用内创建该查询对象且有未建模后续效果时，不能仅从输入不可达认证无影响。

NO_EFFECT 保存 call_access 的定义版本、逐入口状态/路径/缺口及 no_effect_basis。
valid_call_no_effect/valid_coverage 对字段调用拒绝缺证明、未知目标/关联、未覆盖摘要的标签，
即使 Jedi/LCT 一致也不例外。构造本身的效果由字段构造摘要另行覆盖；对象创建前的调用可用
明确时序证明无访问。另有严格的有限私有分配证明：未重新绑定的既有输入回调、已验证新建的
局部实例、当前实参全部不可达、构造器无发布、此前调用/写入已检查且无逃逸，并排除潜在
闭包单元格的后续对象绑定，才可证明该输入不能访问实例。此证明不声称识别输入函数实现；
它依赖创建时序与所有权事实，不把回调本身的未知调用目标升级为完整；只为后续字段状态
提供独立不可访问证明。不适用于未知来源参数、已逃逸对象、捕获的局部绑定、复杂
构造器或缺失历史。证据逐项输出，缺一则 UNKNOWN；不假设任意反射/frame/GC 路径安全。

## 隐式执行的认证边界

普通 ast.Call 继续使用原 ReceiverAccess/方法效果摘要。装饰器应用属于 implicit-call，
不能用普通函数没有 bound receiver 或没有直接对象名证明无影响；本轮没有装饰器效果证明，
所有可达应用都返回 implicit-decorator-effects-not-modeled，阻止字段/槽位完整性认证。
仅定义未应用的普通函数不产生该事件。不可达事件继续使用目录的不可达事实。

With/AsyncWith、循环、异常、生成器/推导式等尚未建模 region 返回
unsupported-protocol-region。子调用成功不代表进入/退出或其他隐式协议
已覆盖。scope-execution 只有一个有限安全规则：无 bases/keywords/装饰器/type parameters，
类体仅 Pass、常量表达式及普通/异步函数定义；函数无装饰器/类型参数，定义头 AST 仅允许
arguments、arg、Constant，不检查方法主体。赋值、名称、属性、调用等其他结构不通过。
不满足时为 unsupported-class-definition-effects，不按名称未命中判断无影响。
该 NO_EFFECT 只指不会修改当前查询的既有实例字段，不代表类定义完全没有运行行为。
本轮不精算任何隐式执行写入的新字段值，不新建控制流/协议求解器。

valid_coverage 对 implicit-call、region、scope-execution 按事件类型检查证据，不套用 ast.Call
参数模型。无已支持规则就拒绝 NO_EFFECT，KNOWN_EFFECT 标签也不能冒充新支持。
局部无害类规则的 execution_evidence 包含实际语法源码、事件身份及原行列；验证核对事件类型、
行列，重新检查有限语法条件并匹配
捕获 AST 的 syntax_digest。proof=true、supported=true、原因标签或其他类的源码不能替代。
事件类型、可达性、位置及语法摘要由目录保持权威，不允许效果 detail 覆盖它们。
隐式未知保留“字段可能仍不存在”的原状态，使已有类成员可作为不完整候选；既不伪装唯一
确定目标，也不凭空推导新目标。覆盖失败沿 Result.requirements 传到最终 CALLS，Jedi 一致
也不能绕过。无害类定义中的未调用方法仍不算当前副作用。

保护范围是已进入当前读取覆盖义务的执行事件。现有目录按区域结束记录 region；区域内部读取
对进入阶段的时序覆盖属于另外的目录审阅问题，本轮按指定范围未调整，也不宣称已完整支持
任意 with 内部读取/进入阶段或上下文协议。后续应独立复核此已记录边界。

以上完整性受有限显式源语义约束，不证明任意 Python 隐式协议、反射、原生扩展或外部并发
修改的健全性。没有执行被分析源码来求值，不将同一创建位置等同于通用运行堆身份。

这些规则覆盖测试中的有限模式；复杂多继承、反射、任意装饰器替换、复杂控制流写入和
变参运输仍可能未知，不声称全库健全性。

后续 Neo4j 必须以 version_id 和 site_id 建立源码版本与位置，不按 qualname 或 legacy status
合并版本；必须消费 unknown/complete/边界及来源。关系查询当前仍是旧 edges facade，
尚未提供独立 sites 查询 API。检索继续消费同一目录；原程序指纹保护会拒绝旧真实索引，
本轮未修改旧 manifest，也没有执行真实 rebuild。后续增量工作须处理删除/重定义、
引用/调用依赖失效、快照一致性和完整性重新计算，不能复用另一个快照的 Jedi 名称对象。
这些是本解析阶段的后续接口要求；Batch 1 的小图投影已单独实现，仍不包含正式增量协议、MCP 集成或全量规模方案。
