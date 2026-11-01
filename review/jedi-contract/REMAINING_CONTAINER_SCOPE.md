# 完整源码的剩余检查成本：只读诊断与后续范围建议

## 已验证事实

JD-1固定提交 `e625662dc68a825382fb88865cff3ee066a80244`，tree `1c6f05941b5ce90b2ebef6993b6d608c67796a03`，runtime hash `c2cffb2bb8bb639a4ee74c6bf32ef657594dd7981bb6006d04cd8cf41297368b`。未知调用的按函数扫描已删除；独立同名方法/未知调用N0/20/100实测实际候选返回恒1，未知返回0，未知site全部保留。固定远端独立快速774 passed/27 skipped/1 deselected/107.05s/exit0；warm小规模N0/20/100仍10owner/6Jedi/8关联/3site，reverse65/61VM恒定。

完整83 SM源码首次新逻辑build的240秒预检exit124；随后在同一固定源上用不同数据目录作180秒有被动计数的诊断，同样exit124。165.78秒时：前端已准备9226个调用，query入口12451、真实Jedi10050；candidate_calls880、candidate_visits1180、未知桶0；关联budget14993未用完，memo4940、source supports1158、订阅269。与旧600秒14,797,200入口不是同耗时同阶段对比，不能报告比例加速；但新实际路径未再枚举未知调用桶。原始记录见root-full83-cold-preflight.log、review1-full83-observed.log。两次均未发布首次图，完整83 warm/query验收尚未开展。

采样在 `container_slots -> container_reachable -> call_field_effect -> field_event` 等字段/容器效果路径，也包含真实Jedi类型推断；没有剖析百分比，不能把所有剩余耗时归因于某一个函数。准备阶段47次回入包括descriptor来源补充，本身不证明缓存错误。

## 独立的小反例

目标代码只有一个全局容器：

```python
def first(): pass
registry={'go':first}
def run(): registry['go']()
```

新增的每个噪声函数仅操作自己的新字典，不返回、传出或调用其他逻辑：

```python
def idle_i():
    local = {}
    local['x'] = first
```

N0/20/100时，目标与完整性均保持 first/complete=True；实际写入作用域检查2/22/102，事件检查3/63/303，Jedi均只执行1次，函数caller candidate访问均0。原始JSON `container-scope-diagnostic.json`。这证明存在与未知caller扫描独立的、针对容器写入范围的额外检查；本反例未直接证明整个83文件的耗时占比。

原因：`_index_local_slot_scopes` 的局部容器分类要求写入值为AST Constant，值为函数名 first 的这些私有容器scope进入 fallback；`container_slots` 每次读取将全fallback scope加入候选。它和 `container_reachable`、`call_field_effect`、`field_event` 在aa95基线到JD-1的AST完全相同，见container-scope-source-parity.json；这不是JD-1新增回归。原有限制用来覆盖逃逸、参数、导入和未知写入来源，不能在没有替代定位和订阅的情况下直接删除。

## 建议的后续范围（尚未实施）

1. 将接收容器身份的定位与写入值是否为字面常量分开。对可证明是新建、私有、无逃逸且仅有简单赋值的容器，按具体origin索引写入scope；函数名作为被存储值不应自动把该scope扩成全局候选。先以上述反例验证，不承诺此单点解决全部83性能。
2. 核对成熟前端已有的声明/来源定位能力和现有容器origin/read/write索引，优先复用；对真正的参数、导入、返回、别名写入，按实际来源关系记录并消费。无法定位的写入保留明确未知和未来变化订阅，不能为了缩范围假装无影响。具体处理要由真实反例、文档与固定输入验证决定，不重写整套解析器或新增无依据兜底。
3. 分开计数一次writer索引准备、每次容器读的candidate/event枚举、实际工具调用与命中、来源记录和输出。固定origin及相关输入，加入无关局部writer时读取检查应不随N增长；相关writer修改必须仍触发正确函数的更新。
4. 保留既有可复现语义：字典别名/条件写入/删除/参数writer/导入writer/不同实例隔离、source supports和订阅、UNKNOWN/完整性、当前和旧快照以及失败发布。完成后再跑完整83首次图与连续warm验收，不再盲目延长相同长测时限。

此建议涉及本次“未知调用候选”之外的原有容器来源/字段效果逻辑。当前只做诊断与方案，未修改这部分代码，也不以超时断言Jedi有缺陷或更换依赖。按batch-dev-review的范围规则，需用户决定是否将具体后续范围纳入工作；当前JD-1成果和历史审阅记录保留。
