# Neo4j 小图投影（Batch 1）

这是已发布 SQLite catalog 与 manifest 的只读投影。SQLite 仍是源码、检索和索引版本的权威；Neo4j 不参与现有 Query、stdio MCP、解析或向量检索。导入只接受明确的 `namespace`、`version` 和数据库名，绝不重解析源码、不调用 Embedding API，也不提供任意 Cypher 入口。

安装 Python 3.12 与可选驱动：`uv sync --locked --group neo4j`。准备原有 LCT 配置及**已完成且程序兼容**的索引版本，并通过环境变量设置 `LCT_NEO4J_URI`、`LCT_NEO4J_USER`、`LCT_NEO4J_PASSWORD`；密码不作为 CLI 参数。示例：

```sh
python -m lct.neo4j_graph --config config.json --namespace review-a --version 20261028T000000-abcdef1234 --database neo4j import
python -m lct.neo4j_graph --config config.json --namespace review-a --version 20261028T000000-abcdef1234 --database neo4j info
python -m lct.neo4j_graph --config config.json --namespace review-a --version 20261028T000000-abcdef1234 --database neo4j nodes --kind function --limit 100
python -m lct.neo4j_graph --config config.json --namespace review-a --version 20261028T000000-abcdef1234 --database neo4j relations 'repo:path:function:name#0' --types CALLS --direction out
```

Python API：`load_snapshot(c, version)` 执行 manifest 兼容性校验、全量 artifact 哈希与 SQLite integrity 校验，再从只读 catalog 读取原始节点/边 JSON、完整 `graph`（含 sites）及 manifest 的 repositories/Git HEAD、source_fingerprint 和 files。`with Neo4jGraph(uri, user, password, database) as g:` 后使用 `g.import_snapshot(namespace, version, snapshot)`、`g.snapshot_info(namespace, version)`、`g.list_nodes(namespace, version, kind=None, repository=None, limit=100)`、`g.get_nodes(namespace, version, ids)`、`g.get_relations(namespace, version, ids, types=None, direction='both', limit=100)`。查询缺失版本会明确报错；`get_nodes` 按输入 ID 顺序返回存在的原始对象；`list_nodes`、`get_relations` 返回 `nodes`/`edges` 与 `has_more`，达到上限仍有后续结果时标记截断。其他列表按 ID 排序。

唯一约束覆盖 `(namespace,version)` 的 `LCTSnapshot`、`(namespace,version,node_id)` 的 `LCTNode`、`(namespace,version,edge_id)` 的 `LCTEdge` 和 `(namespace,version,kind,ordinal)` 的 `LCTChunk`。源码节点另带 `Repository`、`Module`、`Class`、`Function`、`DocumentSection` 固定标签；`LCTEdge` 保存每条逻辑边的原始 JSON、端点身份及常用过滤字段。两个端点都属于目录节点时建立 `CONTAINS`、`IMPORTS`、`CALLS`、`INHERITS`、`REFERENCES`、`WRAPS` 或 `CONTEXT_ENTERS` 固定类型的真实关系，查询内部端点走此真实邻接再关联边原文；boundary、external、null 端点从 `LCTEdge` 查询，不伪造源码节点。`LCTChunk` 分片保存完整 sites、原因和源版本元数据；`unknown_origin`、`complete`、`site_id`、`version_id` 与两个端点版本 ID 保持原值，不把不确定调用改写为 resolved。固定验收夹具包含 **17 个目录节点、30 条逻辑边**，另有 1 个辅助快照节点和 30 个辅助边记录节点；真实关系是内部端点的额外投影，不能与逻辑边重复计数。

节点、边、真实关系和元数据按受限大小分批提交；失败留下不可查询的不完整候选，同输入重试先清理候选再从头导入。最终校验后原子发布；不同指纹拒绝覆盖，其他 namespace/version 保持隔离。现行容量、事务、租约和分片细节见 [全图投影](NEO4J_FULL_GRAPH.md)。

真实服务定向验收：设置 `LCT_TEST_NEO4J_URI`，可设置 `LCT_TEST_NEO4J_USER`、`LCT_TEST_NEO4J_PASSWORD`、`LCT_TEST_NEO4J_DATABASE`，运行 `pytest -q tests/test_neo4j_small_graph.py`；没有 URI 时真实服务用例明确跳过。
