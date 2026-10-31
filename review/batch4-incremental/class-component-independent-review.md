# 类与方法局部更新独立审阅

固定实现提交 `1ca7ca32cf5e0b816eee95a01956417308f38407`，本切片第1/3轮，结论：限定范围通过，整个Batch4未完成、未合并。主Agent未实施生产修改。

## 代码与验证

- 核对simple_python.py准入范围和python_effects.py的6行标记修复；读取完整python_incremental.prepare，确认沿原有依赖索引计算闭包并保留证据校验和完整回退。
- 独立目录中使用远端Git blob SHA核对实际源码、测试和必要支持文件。没有把未推送草稿纳入测试。
- 命令：`PYTHONPATH=. .venv/bin/python -m pytest -q tests review/batch4-incremental/test_changed_python_independent.py review/batch4-incremental/test_source_prepare_independent.py review/batch4-incremental/test_evidence_reuse_independent.py review/batch4-incremental/test_dependency_store_independent.py review/batch4-incremental/test_class_component_independent.py review/batch4-incremental/test_effect_markers_independent.py`。
- 结果：**545 passed、25 skipped，26.45秒，exit 0**；日志class-component-root-fixed.log。跳过项仍为环境/显式真实服务验收门槛，不能宣称执行了真实Neo4j/付费API验收。

## 独立反例与结论

- B4-CLASS-MARKER关闭：旧版独立验证1 failed/1 passed；新版两个顺序对照通过，新增无关模块不会改变目标scope事件ID，before仍包含前面的写入且排除当前调用。未删除或归一化证据字段来绕过比较。
- 构造器self.cb从first改second，而factory返回类型不变：有0/20无关同名类文件时，都只解析a/b两个文件。节点、边、调用位置、私有观察和导入记录全字段等于全量构建，旧版本不变。
- 保存绑定方法后更改callback参数、直接factory().cb调用均与完整构建一致。
- 准入扩展明确排除任意参数属性、继承/装饰器/动态属性和外部未解析导入；旧普通类回退测试改为不支持的继承，另补普通类正向测试，未删除正确性断言。

## 局部性与限制

公开build→python_incremental.prepare→FileDependencies索引→所选python_nodes/Graph.build路径未添加SQL扫描。无关类扩容不增加AST解析文件数；已有同一路径索引执行证据见changed-python-independent-review.md。本轮未重新声称数据库实际PROFILE已执行。

完整捕获校验、哈希和新产物装配仍为全量成本；类支持仍在严格闭合的单Python仓库子集内，不代表实际业务仓库已经全部可局部更新。跨仓库、统一图发布、真实规模与恢复验收尚待完成。

无本轮确认的P0/P1或剩余阻塞缺陷；保留已有阶段历史及审阅次数。本结论只关闭类支持切片，不能自动合并整个Batch4。

按远端blob核对的实际文件数：135。未下载无关历史服务验收脚本；本次所有执行路径依赖均已存在并核对。
