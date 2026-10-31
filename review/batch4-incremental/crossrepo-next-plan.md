# 跨仓库局部更新接入点：只读诊断

2026-10-31；基线 a052f88d25646ee515523053898fe77463dbc526，GPT-6 SOL medium 子 Agent 只读检查。没有修改实现、运行真实构建或调用 API。本报告是后续方案，不是已实现或已验收。

1. `simple_python.certify` 当前限制单 Python 仓库且自己按 `(repo,module)` 查找导入。后续应调用既有 `Graph.imported(requester_repo,module)`，保留本仓库优先、规则引擎依赖精确 pin 和工作区状态规则。要求唯一已捕获模块，且引用的定义可认证；不能另建一套跨仓库名称解析器。
2. `python_incremental.prepare` 的变更、选中集合本来已用 `(repository,path)`，但仍有固定 `repo` 变量、单仓库拒绝、`bymodule[module]` 和 AST ID 使用同一 repo。需统一改为每个键自己的仓库；用全捕获模块目录构造只读 Graph 解析导入，不解析全部未改 AST。当前选中源码导入的新目标也必须加入闭包。
3. `FileDependencies.adjacent` 已支持跨仓库关系；`importers` 按 lookup_repository/module 查询。已匹配 pin 的 lookup_repository 是提供方，未匹配边界可能仍是请求方。因此 pin、HEAD、Python cleanliness 等绑定状态变化时必须先整体回退；不能只沿旧提供方反查。
4. 保留 `dependency_bindings` 新旧比较，且要在复用前完成。提供方更新并相应更新精确 pin，通常会触发该回退；不能宣布这种变动已经局部化。
5. `RebindContext.selected_paths` 仍是路径字符串，跨库同路径会误判所属范围。后续改为 `(repository,path)`，同步所有调用者和独立实验 API，不能只删除仓库数量判断。
6. `Graph.__init__` 当前对规则引擎目标执行 git cleanliness 检查；从 source_snapshot 恢复的非 Git 目录不能自然满足。不得把 manifest 的 head 字符串直接当作干净工作区证明。先保留完整分析/现有边界规则；若要修改绑定契约，需另列证明和验收。

定向验收至少包括：两个库同路径/同模块名；本仓库导入优先；明确匹配与不匹配的 pin；依赖绑定转换回退；新增跨库导入；提供方变动反查消费者；同绑定下互不相关仓库复用；source_snapshot 环境不擅自放宽绑定；完整节点、边、sites、UNKNOWN 和版本引用与全量对照。

与当前类支持开发分开：本报告未声称支持任意跨仓库更新，先完成类/方法独立审阅，再按上述明确接点实施。
