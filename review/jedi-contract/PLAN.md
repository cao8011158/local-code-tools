# JD-1：按 Jedi 输出与明确关系定位调用者

日期：2026-11-02（Asia/Shanghai）。用户已批准：“可以保留找不到或者当前解析不了函数来源的调用”，禁止分析每个函数时逐个遍历无来源调用集合，并在确认修改/验证步骤后回复“好的 开始工作”。按新建 prefer-proven-tools 的文档契约和证据原则执行。

## 身份、权限与历史

- 仓库 agentic-trpg/local-code-tools，工作分支 feat/local-only-updates，远端基线 aa95ca6968812fdd357d5fe5b91740dc0ba0d371，tree fca68a59395159841f357fe412fbc6b2ee2e205f。实际目标 feat/local-code-tools-import 仍为 e3db45fcf1362f0a26e0ab7760b12b4fd408ce64；已通过 GitHub API 核验。
- 当前 local-only-work 是物化树，本地Git基线141e不是远端祖先；不得据此push/reset。lo3-review1-fixed保留583个逐blob核对的基线文件。此前未推送的报告/观察脚本及日志保留。发布叠加远端树，不覆盖未物化653历史文件。
- 本次是用户明确改变未知候选规则和结果权威的新需求 JD-1，不伪装成旧LO2第4轮。保留LO2三轮及最终通过、原问题状态；同一旧问题如重新打开仍遵守原上限。LO3全83验收原先未完成，需在本次通过后补验，不能沿用旧完整通过结论。
- 开发 /root/jedi_contract_developer，实际 gpt-6-sol/medium；root负责架构、反例和独立审阅，不修改生产。新需求正式review尚0/3。已授权实施、必要测试与分支发布；未假定合并授权。

## 范围和实现约束

取消candidate_sites每函数合入_site_no_atoms/_site_unqueried，以及query-inflight/索引变化导致的默认全site扫描；未知调用保留原始结果、UNKNOWN及原因，不作为任意函数的caller。构造器、receiver、registry路径使用同一具体关系索引。首次新捕获允许一次必要site准备；普通warm仍按selected owner和真实依赖，不将开销搬到每次query/每个参数。

优先消费Jedi明确映射的目标。自研缺少证明或仅有部分结果，不能默认丢弃Jedi目标；保持未知/完整性、冲突证据与外部边界。已有确凿测试支持的局部语义扩展可保留，必须列依据，不能以不保证100%完整为由恢复全未知池。

保留callback实参来源、container writer/read订阅和新旧支持替换、命名空间变化、失败发布/旧视图、预算限制与普通更新不自动full回退。不更换Jedi/Parso、不提升20k预算、不运行捕获业务、不付费Embedding、不启动Neo4j。必要修改仅限我方解析/建图接入、相关缓存调度和版本/计数、契约及测试；外部核心组件真正缺陷先报告。

## 已确认根因与验收

python_analysis.py candidate_sites合并空/未查池，may_call对空atoms放行；parameter的self/构造器/普通参数及registry消费，造成未知调用重复被枚举。adjudicate对非decisive冲突清空已知Jedi目标。map_name已有原始路径/位置/type/mapping和外部boundary分类，须复用，不把映射失败都称为Jedi未知。

- 独立先失败反例：未知/未查调用不得进入无关函数候选；Jedi已知目标不得被自研无依据UNKNOWN抹掉；未知原始输出及原因仍存在。
- 回归：明确导入/别名、callback多参数、self/构造器、registry/key、字典getter返回后调用、连续修改/重启、namespace、新旧视图与失败重试；新增目标后索引及时维护，不用全域重算补漏。
- 计数：候选访问、未知桶枚举、准备site、query入口/唯一key/缓存/真实Jedi、raw空/映射失败/目标。固定相关输入，增加无关未知调用与无关函数，未知池每函数枚举必须0；初始一次全量site查询与必要捕获/哈希/序列化单列。
- 最终快速 tests + 5份原独立控制；昂贵九文件与完整83固定SM a7b0804d5635e185a79ff3c1d1fa6241c2b858fe（83文件1,207,159bytes）在定向计数通过后只运行有区分力版本。源文件齐全且有外部边界，不要求运行时Python全解析。
- 新语义明确取消旧“空Jedi必须入所有候选”断言；其它真实目标/来源断言不能仅为变绿而删除。对精度变化提供原始Jedi/源码依据及范围。

每次开发/修复/正式review均追加原累计STAGE_REPORT并立即给用户摘要与链接；保留所有原始失败，按固定远端提交独立审阅。
