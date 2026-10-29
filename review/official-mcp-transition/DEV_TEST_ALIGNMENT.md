# B3-007 测试对齐开发记录

2026-10-30（北京时间），针对第5次正式审阅指出的两处旧断言/夹具，按用户授权作窄范围开发收尾。远端候选基线`1ec4a6c417b3bb702a45c32bf9a0766ca681bb1d`与合并目标`655b78a834c40542bf62c09bdd508c17d7f46450`经主Agent核验未变。本次尚未推送，亦非第6次独立审阅。

## 改动

- `tests/test_neo4j_bulk_import.py`：批次行数从旧投影期望调整为`1200 + 6000 + 6000 + 601 + 2`；原生CALLS计数调整为6000。原始逻辑记录`internal`分布4800/1200、JSON、分页及批次上限断言保持。
- `tests/test_neo4j_staged_import.py`：过期写入者重试夹具明确写入`projection_schema='native-boundary-v2'`；新增旧格式不完整标记对照，检查导入明确拒绝、前后标记属性相同且快照仍不可读取。没有修改生产代码。

## 定向验证

自有Neo4j 5.26.0启动器运行`tests/test_neo4j_bulk_import.py::test_bulk_roundtrip_and_query_bound`、`tests/test_neo4j_staged_import.py::test_expired_owner_is_fenced_on_retry`、`tests/test_neo4j_staged_import.py::test_incomplete_old_projection_marker_is_rejected_without_rewrite`：**3 passed in 16.27s**，退出码0。完整输出保存在`dev-test-alignment.log`。按用户限制未运行快速或全套回归。此前第5轮真实服务的2 failed与隔离副本2 passed记录均原样保留；本结果仅证明正式测试文件的三项定向通过。
