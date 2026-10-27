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
