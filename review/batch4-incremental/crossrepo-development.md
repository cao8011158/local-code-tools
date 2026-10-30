# 跨仓库环境与局部更新开发报告

基线39b6d0ab3e18e9a5642078bde8c71a23999cd599；feat/incremental-index-updates；开发GPT-6 SOL medium，当前冻结未提交。用户已授权限定修复，不更换Jedi或重写解析器。

## 实现
- Analyzer.__init__按请求仓库复用Jedi Project，本库源码根优先，依赖根依据Graph.imported现有精确pin规则选择；保留query结果后置验证。
- simple-python-v3及python_incremental.prepare支持(repository,path)身份、现有绑定解析和索引闭包；新旧绑定变化仍完整回退。
- import_requests新增requester索引，FileDependencies.requesters按请求方与模块名找调用方；祖先名字范围检查使用同一索引。新增/删除同名本库模块会重新分析调用方，包初始化/祖先模块布局变动保守完整分析。
- RebindContext生产用tuple身份，旧实验字符串保持保守拒绝；旧sidecar缺新索引回退。
- 同步docs/INCREMENTAL_UPDATE.md，保留严格语法子集及全量产物成本限制。

## 开发验证（非独立review）
- 定向：tests/test_cross_repository_python_incremental.py + review/batch4-incremental/test_crossrepo_independent.py + review/batch4-incremental/test_jedi_environment_independent.py →16 passed，6.05秒；crossrepo-targeted.log。
- 快速全tests/：536 passed、25 skipped，20.29秒；crossrepo-fast.log。
- Ruff：通过；crossrepo-ruff.log。
- 包initializer与祖先pkg.py新增/删除的完整差分均验证回退；索引检查包含实际SQLite EXPLAIN。

## 限制
完整产物校验、目录/候选装配仍全量；仅严格闭合语法下的Python组件局部分析。没有真实业务全图、Neo4j、API或Drive操作。跨仓库完整功能尚需root固定提交独立审阅，整个Batch4仍不合并。此前暂停失败证据保留。
