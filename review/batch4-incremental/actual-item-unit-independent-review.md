# 真实校验模块限定扩展：独立审阅第1/3轮

固定生产提交：25d415f55b37a51992bb3fd8ae7550b702ba52df；分支feat/incremental-index-updates。GitHub远端引用已核对；88份生产、tests及配置文件与远端Git blob一致。其余可取得支持文件共377份；部分历史审阅制品不在本地，本轮未依赖它们。未包含旧file_incremental.py草稿。

结论：本次simple-python-v4限定扩展通过；整个Batch4未完成，不合并。旧跨库/缓存整改第2轮通过记录保留，本轮是新限定扩展的第1轮。

## 独立检查
- 最终固定生产运行tests加新独立反例：561 passed、25 skipped，23.79秒，exit0。跳过项为24项需Neo4j服务及1项可选缓存条件；未称服务验收通过。原始日志actual-item-unit-root-final.log。
- 新反例及历史普通函数、类、跨库、包上下文、实际源码恢复检查：31 passed、7.55秒，exit0，日志actual-item-unit-root-boundaries.log。与上项部分重叠，不相加计算覆盖量。
- 实际公开build入口计数：0/20无关文件时目标解析均1次、AST上下文均1个、Jedi均11次。0无关文件按no-unchanged-python-modules完整分析唯一文件；20无关文件走局部组件，复用20文件。已有导入调用者样例解析2/22。
- 六类记录nodes/edges/sites/query_observations/import_dependencies/import_requests逐项等于完整构建；旧版本记录不变。新增同名re.py安全回退。UNKNOWN和证据比较未删字段。
- 类型守卫倒序、嵌套否定、内置名覆盖、守卫后潜在修改调用、动态指数、未守卫正则输入、helper绑定逃逸均拒绝认证。

## 首次运行的两项失败如何处理
首次完整日志actual-item-unit-root-fixed.log为2 failed、559 passed、25 skipped，不隐藏。
1. 审阅副本未创建注册测试需要的.venv路径；补上指向现有已安装环境的链接，没有改注册程序，没有新安装依赖。
2. 主Agent新测在零无关文件时错误要求reused_python_files字段。实际公开结果为full-graph/no-unchanged-python-modules、总解析1次，是合理路径。测试改为明确断言该模式、原因和总解析量，保留完整记录对照。测试修正不是生产修复。
最终生产代码仍与固定提交一致；后续证据提交仅修正该独立测试并保存日志报告。

## 范围与下一步
全捕获认证仍保留，availability.py/errors.py等不支持文件与真实叶子一起出现时仍全量回退。没有实现任意未认证文件的安全隔离。库存扫描、已有目录/证据读取及完整输出写入仍有全局成本；这里只证明解析和分析工作局部。未执行真实整库、Neo4j、Embedding或Drive操作。
下一项必须解决真实业务语法和按分析单元复用的依赖证明，不能通过不断放宽白名单或删除完整性门槛宣布全库增量完成。
