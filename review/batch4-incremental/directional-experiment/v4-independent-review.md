# 用户批准后的追加独立复核：构造器变动传播

检查提交：dc8fa9b35bd3b398a7071ac676abf132a1f94d06；分支feat/incremental-index-updates。承接前三次实验审阅，本次由用户“好的 请继续”明确批准，不重置历史轮次。主Agent未修改v4实现或生产代码。

## 结论

B4-DIR-SEED（构造函数变动未成为传播起点）在本次限定范围内已修复。B4-DIR-STATE既有修复保持。本次修复可关闭；完整增量实现及生产接入仍不通过、未合并。

新增证据确认B4-DIR-PROVENANCE：未重算的旧分析记录包含旧version_id。此前已声明跨版本身份复用未验证；本次把该边界落实为明确失败，不扩展修改，不将严格26/27写成27/27。

## 固定输入与验证

v4.py Git blob：a2c2fde991c7c2f64558335dc73e84375738a26e，本地与远端一致。检查22个相关Python文件（含冻结graph_under_test与v4），与固定远端一致或仅CRLF/LF字节差异。已知本地graph.py缺失模块草稿和file_incremental.py草稿不等于远端；实验明确使用已提交graph_under_test.py替代Graph，未接入file_incremental。

命令（项目根目录，现有venv）：

```
PYTHONPATH=. <venv>/bin/python review/batch4-incremental/directional-experiment/v4.py
PYTHONPATH=. <venv>/bin/python review/batch4-incremental/directional-experiment/independent_v4.py
```

| 独立检查 | 结果 | 证据 |
| --- | --- | --- |
| 复跑开发27组 | 严格26/27一致，exit0仅指采集完成 | root-v4-rerun.log、v4-results.json |
| 构造器字段变化经Bridge.forward方法返回转交 | 一致，3个相关文件，5个外层调用点 | independent-v4-results.json |
| 同一变动增加30个无关文件 | 一致，仅a/b进入调用点重审，3个调用点、4次选择性阶段Jedi | 同上 |
| 同文件双类隔离失败的逐字段核对 | 恰好12处version_id不同，其余字段相同 | v4-proof-version-differences.json |

independent_v4.py包含结果一致和无关文件未被选中的断言，exit0。没有运行无关的完整仓库回归；本次仅研究脚本变化，不是生产发布测试。未启动Neo4j、未调用Voyage或付费API、未更改真实图/Drive包。

## 代码审阅与范围

- definition_index按(path,完整qualname,kind)对齐定义，不再用方法尾名查调用者摘要。
- 变化__init__映射到所属类，反向遍历旧CALLS找到构造者；不使用__init__的None返回值截断实例状态影响。
- 已有类新加__init__通过完整类身份映射到旧类调用者。旧构造器删除路径存在分支，但本次没有单独的删除行为验收，不将新增测试当作删除验证。
- 同名方法选择隔离有效；方法转交结果独立验证通过。任意其他方法副作用、动态分发、缺失旧边、复杂新增删除的通用正确性仍未证明；不能把这次局部修复说成完整方法支持。

## 已知版本证据问题与后续方案

同一文件修改Alpha.__init__时，不受影响的Beta调用者仍应复用其分析结论。但当前定义版本规则使该文件中其他定义的version_id也变化，旧证据里的引用没有重新绑定。

需要单独实现：对已确认语义可复用的记录，按明确、类型化的定义引用映射到当前捕获版本；无法确认映射则标记需重新验证。不要全局字符串替换，不要删除version_id比较，不要为了刷版本强制重算所有无关消费者。应保留旧快照不变、校验新引用确实指向当前定义，并验证新增、删除、重命名及失败恢复。这是待实施方案，不是本次已经完成。

## 局部性边界

30无关文件样例的外层调用点范围保持a/b，但摘要阶段仍准备32个旧AST及32个新AST，候选阶段仍有32文件全上下文和全局非CALLS分析。以上证据只支持定向选择机制，不证明端到端工作量局部化。首次基线及全量oracle用于实验比较，不能当作候选自身必需成本。正式Batch4仍需完善版本复用、真实局部执行、存储发布及功能验收。
