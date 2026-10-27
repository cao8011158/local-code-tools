# Python 节点与关系契约（第一阶段）

本契约只描述 LCT 当前源程序；未迁移或重建真实索引。入口仍为
lct.extract.extract(files) → (nodes, asts) 和 Graph(nodes, asts, repos).build() → (edges, info)。
调用方先捕获源码；Jedi 只读本次捕获的私有副本，源码不被 import/执行。
没有 CGR 包依赖、Neo4j 驱动、新 MCP 服务或业务仓库扫描入口。

## 唯一节点目录

| 字段 | 含义 |
| --- | --- |
| repository / repository_id | 由输入声明的仓库名称/身份；未提供 repository_id 时沿用名称，调用方负责唯一性 |
| path | 捕获的仓库相对路径 |
| node_type | module、class、function、method 或 lambda |
| kind | 兼容既有检索层的 module/class/function；method/lambda 仍属于 function 层 |
| name / qualname / parent / module | 名称、限定名、直接词法 owner 和模块节点 |
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
- completeness_basis、unresolved_reasons、evidence：AST、Jedi 原始映射和 LCT 逐位置关联路径。
  关联路径最多 100 步，截断单独标记；完整性不由证据输出长度推断。

同一位置可以同时有 targets=[A] 和 unknown_origin=true、complete=false。
完整的 [A,B] 是两个有依据的可能目标；零目标、complete=true 可表示静态无效调用尝试。
Jedi infer 单独输出不证明穷尽；项目输入默认开放。closed_world 只由本轮合成驱动显式设置，
生产 build 未设置它，也没有新增一个面向业务的闭合世界开关。

| 关系 | 精确含义 |
| --- | --- |
| CONTAINS | 目录中的词法包含，不表示执行 |
| REFERENCES | AST 的值引用；存入变量、容器或 return 本身不执行被引用函数 |
| CALLS | 某个显式调用或装饰器隐式应用位置的候选投影，带 site_id |
| IMPORTS | import token 按精确捕获定义映射；可指向重导出后的实际定义 |
| INHERITS | 显式 AST 基类关联 |

旧 status 仅是兼容投影：唯一完整目标为 resolved，多候选或部分已知为 possible，
外部为 boundary，无 callable 目标保留 unresolved 位置。unresolved 并不总表示未知来源。
每条边另带 source_version_id/target_version_id，内部身份验证仍以节点目录为准。
外部没有伪造的内部节点或 version_id；捕获范围缺失和工具错误不能静默变成“没有调用”。

默认参数、装饰器表达式及应用发生在定义阶段。Python 3.12 eager annotations 记录为
annotation；future annotations 和函数局部变量注解不产生执行调用。
每个装饰器都有应用位置；工厂装饰器表达式的调用与返回装饰器的应用分别记录。

## 边界与后续消费者要求

有限关联只处理词法 reaching binding、if 候选、显式实参与默认值、绑定方法接收者、
字面容器槽、直接槽替换、项目注册调用的同次 key/value 对、直接返回表达式及普通上下文协议。
没有 Flow 环境/堆、通用执行器、全程序类型固定点或任意路径求值。
20,000 次关联和递归 40 是拒绝边界；不得把预算耗尽伪装为完整结果。

两个严格验收失败保存在 tests/test_python_pipeline_gaps.py：生成器 contextmanager 的完整性，
以及不同对象实例的容器身份。多继承 MRO、任意装饰器替换、复杂反射/动态属性、
循环/try/match 写绑定和变参运输等仍可能未知，不声称全库健全性。

后续 Neo4j 必须以 version_id 和 site_id 建立源码版本与位置，不按 qualname 或 legacy status
合并版本；必须消费 unknown/complete/边界及来源。关系查询当前仍是旧 edges facade，
尚未提供独立 sites 查询 API。检索继续消费同一目录；原程序指纹保护会拒绝旧真实索引，
本轮未修改旧 manifest，也没有执行真实 rebuild。后续增量工作须处理删除/重定义、
引用/调用依赖失效、快照一致性和完整性重新计算，不能复用另一个快照的 Jedi 名称对象。
这些都是后续接口要求，本轮未实施 Neo4j、正式增量协议或发布协调。
