# 实际生成的字典关系小例子

固定实现：`cf4b0fbac0e11f18d53f7dbff1be8b1e40cd6505`。使用临时合成源码、离线 lexical 构建，禁止 Embedding 请求。以下由实际 SQLite 内部图记录生成，**不是 Neo4j 投影或运行时调用次数图**。

A.py：

```python
def first(): pass
def second(): pass
registry={"go":first}
registry["go"]=second
```

B.py：

```python
from a import registry as handlers
def run(): handlers["go"]()
```

实际内部节点 7 个，关系 11 条；另引用已有函数节点 2 个。两次赋值都保留，但仅第4行的赋值通过 REACHES 连接到这次读取；调用目标为 second。

```mermaid
flowchart TD
    n0["A 的声明 registry"]
    n1["B.run 中的读取并调用"]
    n2["第4行赋值：second"]
    n3["该字典的 go 条目"]
    n4["第3行赋值：first"]
    n5["A 的 registry 字典"]
    n6["B 的导入别名 handlers"]
    n7["first 函数"]
    n8["second 函数"]
    n0 -->|"绑定同一字典"| n5
    n1 -->|"可能调用"| n8
    n1 -->|"读取条目"| n3
    n1 -->|"使用该绑定"| n6
    n2 -->|"保存的函数"| n8
    n2 -->|"此次生效的赋值"| n1
    n2 -->|"写入"| n3
    n4 -->|"保存的函数"| n7
    n4 -->|"写入"| n3
    n5 -->|"条目地址"| n3
    n6 -->|"绑定同一字典"| n5
```

字典声明和导入别名通过 BINDS 指向同一个字典。go 条目属于该字典；它不是全项目共享的 go 字符串节点。原始身份、字段和关系见 [dictionary-flow-example.json](dictionary-flow-example.json)。此例仅展示已支持的固定字符串 key、直线写入和直接导入，不能推出任意动态字典都支持局部更新。
