# 第1轮整改：包上下文已修，核心依赖缓存阻塞

2026-10-31；远端生产提交d9ecf8538b0078b30edbf0e92dd2f78b2e85bbe4，第1/3轮review结论为需整改；证据提交211de5cd543793263a5f33e3ab39895117ef8493。当前整改候选在本地冻结，以patch保存；第2轮正式review尚未开始，未合并。

## 当前整改开发

python_incremental.prepare通过resolver.modules的(repository,module)索引，补入所选模块及导入请求的包名前缀上下文：既包括请求仓库已有包/模块边界，也包括目标仓库包祖先。沿现有闭包继续扩展，不扫描/解析所有无关AST。新增正确绑定的provider包上下文正常对照，证明只解析caller、provider包__init__、provider目标三个文件；旧无关文件仍不解析。

开发定向19 passed，5.52秒。原2项独立失败通过；改动仅python_incremental.py、新跨仓库测试及契约文档。candidate patch及SHA256清单保留。

## 快回归不能宣称通过

- 开发全tests/两次均6 failed、531 passed、25 skipped；首次24.40秒，日志crossrepo-review1-fast.log、crossrepo-review1-fast-rerun.log。
- 失败的contextlib 6项单独运行全部通过（1.08秒）；新crossrepo+contextlib组合12 passed；固定d9ec全tests/536 passed、25 skipped。
- 有限顺序诊断和原始query记录已保存；未改任何历史断言，没有继续反复重跑全套取绿灯。

## B4-JEDI-PARSO-CACHE：已确认核心依赖缓存交互，暂停自动修复

环境Jedi 0.20.1、Parso 0.8.7。主Agent没有修改生产或依赖，而是分别包裹Script.goto与parso.cache._set_cache_item记录异常/淘汰，异常原样重抛；pytest遇首个失败即停止。

1. 异常栈诊断：1 failed、442 passed、25 skipped，15.06秒。Jedi goto→gradual conversion→ParserTreeFilter→get_parso_cache_node；最后直接访问parser_cache[grammar._hashed][contextlib.py]抛KeyError。详见crossrepo-jedi-stack-diagnosis.log。
2. 淘汰观测：1 failed、442 passed、25 skipped，14.16秒。缓存600条时contextlib.py被淘汰，最近使用年龄约419741.6秒，而保留阈值600秒；604条时再次观察淘汰。详见crossrepo-parso-eviction-diagnosis.log。
3. 安装源码核对：Parso _NodeCacheItem把last_used初始化为change_time；磁盘加载后直接_set_cache_item，没有先刷新last_used；_set_cache_item在达到600条时按last_used清理。Jedi后续仍持有解析引用，并假定相应Parso条目存在，直接索引失败。项目lct/tests未直接操作parser_cache或清理它。

因此不能将这6项失败解释为包语义断言不应成立，也不能靠删断言、清缓存后只测一次或强行UNKNOWN通过。此次范围内的包上下文整改定向有效，但核心依赖缓存边界阻止稳定大范围验收。没有证据确认错误确定调用目标/P0P1；问题是丢失应有候选并返回jedi-error:KeyError。

## 人工决定事项

按batch-dev-review的核心外部依赖规则，需用户批准将Jedi/Parso缓存兼容性修复纳入本轮。建议保持解析器不变，围绕“新解析/磁盘加载的缓存条目应记录当前使用时间，活跃解析引用不能依赖已淘汰条目”建立独立最小复现，检查可用官方修复或制定有界兼容补丁；验证冷/热缓存、600条阈值、contextlib语义和内存生命周期。不擅自升级/替换依赖、关闭淘汰或永久保留全部缓存。

未调用Voyage、未更改真实图/Drive，未启动真实Neo4j。没有合并；旧失败及全部诊断证据保留，审阅次数不重置。
