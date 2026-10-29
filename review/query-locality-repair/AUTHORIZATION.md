# 查询局部性专项整改

用户明确授权：“好的 那么先更新skill 然后修正我们上面的问题”。

基线：aeed8fd7cc381e9884d9602559e54acc207a5f28。工作分支：feat/full-business-graph-indexes。

保留 Batch3 已完成三轮审阅记录。本次重新打开 B3-005 及其共同读取路径，不把历史轮次清零。允许修复 Query.snapshot/manifest、LCT index_status、Neo4j graph_status 和 Neo4j 查询字节边界，补做受影响真实 MCP 与恢复验收。没有新增付费请求，不重建解析图或向量。

开发由 GPT-6 SOL（medium）子 Agent 完成，主 Agent 独立审阅。此前合并授权继续有效，但所有门槛完成之前不合并。
