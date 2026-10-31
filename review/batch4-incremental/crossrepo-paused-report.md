# 跨仓库局部更新：开发暂停与明确修复方案

2026-10-31。远端已通过的生产实现仍是1ca7ca32cf5e0b816eee95a01956417308f38407；证据提交1c9a799d8b4fff0ff1c62d8e1c16974b37cb69c2。以下是未通过验收的本地候选；仅保存patch，不把它应用到远端生产目录。开发者GPT-6 SOL medium，主Agent独立诊断。尚未开始跨仓库固定提交正式review，不重置之前轮次。

## 已完成与测试

候选复用Graph.imported、用(repository,path)隔离文件身份、前置检查依赖绑定、拒绝同库重复模块名；支持部分精确绑定场景，但尚不完整。改动文件和原始内容见crossrepo-paused-candidate.patch及SHA256清单。

- 开发者定向报告34 passed、2 failed；该次完整日志未保存，不冒充主Agent证据。
- 固定旧实现扩容基线：3 failed、1 passed，1.43秒，exit1。失败体现未实现局部解析；crossrepo-root-baseline-expanded.log。
- 主Agent在冻结本地候选独立运行：`PYTHONPATH=. ../lct-round5-review/.venv/bin/python -m pytest -q tests/test_cross_repository_python_incremental.py::test_exact_pinned_cross_repository_import_and_local_precedence review/batch4-incremental/test_crossrepo_independent.py` → **3 failed、2 passed，2.11秒，exit1**。原始日志crossrepo-root-candidate-diagnosis.log。
- 两项通过包括精确绑定下consumer回调参数改变，以及provider变脏后回退；失败为0/20无关同名模块的局部范围，以及新增本库模块遮蔽依赖模块。没有执行全套回归，因为具体阻塞已确认。

## B4-CROSSREPO-PROJECT（P2，既有核心解析接入问题）

固定1ca代码独立复现，原始记录crossrepo-root-diagnosis.json：left/right都有src/a.py和src/b.py。right.b导入本库a.use，但Jedi原始候选的module_path是left/src/a.py。Analyzer.query检查发现仓库不匹配，将它转成dependency-version-unmatched边界；targets=[]、complete=false、unknown_origin=true。没有证据证明生成了错误的确定CALLS，不能定性为P1。

根因是lct/python_analysis.py Analyzer.__init__把所有仓库的source roots合并sorted后，构造一个jedi.Project，所有Script共用；Graph.imported的本库优先和精确pin规则只在推断后校验，不能纠正Jedi已经选错的模块。不是证明Jedi库本身有缺陷。

旧证据保留了错误仓库候选的版本引用；左库变化时，右库的原始证据也会变化。RebindContext拒绝这种未认证证据并退回全量，安全校验不能删掉或放宽。

建议修复：按请求仓库创建并复用Jedi Project；本库解析根优先，仅加入现有Graph.imported/精确绑定规则允许的依赖根，保留受控外部库路径和后置授权校验。同库内部根歧义继续拒绝局部复用。不要更换Jedi、不要重写调用分析。必须测试同名模块、仓库顺序变化、精确pin/不匹配pin、本库优先和原UNKNOWN边界，并与完整构建对照。该修改涉及此前核心解析环境的语义，不直接在当前候选里擅自实施，需用户确认范围。

## B4-CROSSREPO-SHADOW（P2，当前候选新增的失效范围缺口）

原consumer从已匹配provider导入dnd5e_engine.evaluation；新增consumer内同名模块后，Graph.imported应改选本库。旧import_requests按lookup_repository=provider存储；FileDependencies.importers(consumer,module)找不到这个旧请求，所以只重算新增模块，遗漏caller，保留旧import_requests。完整构建则选择consumer。

明确修复：在现有import_requests表补(source_repository,requested_module)索引和查询方法；当前模块新增/删除等可能改变名字解析时，合并按请求方模块名找到的caller，再沿现有闭包扩展。不要扫全部请求。新旧依赖均纳入，保持原lookup_repository反查provider用途。旧sidecar缺索引/证明时完整回退。验证新建/删除本库遮蔽、没有受影响导入时不扩大范围、EXPLAIN实际索引定位及全字段差分。保守替代是检测此遮蔽转换后完整回退，不能输出错误局部结果。

## 决策与状态

推荐先授权限定修复B4-CROSSREPO-PROJECT，再一并完成当前step内B4-CROSSREPO-SHADOW。若暂不改变核心解析配置，就需明确接受同名跨库场景完整回退，并修复遮蔽遗漏；不能宣称跨仓库局部更新全面完成。

遵守batch-dev-review的范围升级规则：旧核心接入语义变更先请求人工决定。子Agent最初怀疑P1，经主Agent复现确认UNKNOWN与完整回退后更正为P2；不以未证实的严重级别制造阻塞。未执行真实建图、Neo4j服务、Voyage请求或Drive操作；未合并。
