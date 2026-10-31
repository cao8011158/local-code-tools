# 第三次独立实验审阅：返回对象状态传播

- 检查提交：4560aee34db12ad01192bdeb0986d414c37ba846；分支feat/incremental-index-updates。
- v3.py远端与本地Git blob均为f877907491d5fe26fff1333f8ee57a524abdffbf。根Agent未修改实验实现或生产代码。
- 轮次：承接阶段21、23，本定向传播实验第3次独立审阅。整个Batch4还没有最终功能审阅；这不能用来重置本修复循环的三轮上限。
- 结论：原返回对象状态停止条件反例已关闭；新确认起点遗漏使通用接入仍不通过，暂停自动修复，需人工决定。

## 独立验证

运行环境为现有项目Python虚拟环境；没有服务启动、API、真实数据或完整仓库回归。生产代码未改变，仅实验脚本定向验证。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 固定提交v3.py复跑开发样例 | 20/20语义匹配，exit0 | root-v3-rerun.log、v3-results.json |
| 对象的cb字段先由中间函数提取，再转交调用 | 匹配，选择3/3相关文件 | independent-v3-results.json |
| 中间函数丢弃对象并返回常量7 | 匹配，只选a、b，未继续到c | 同上 |
| 只改Box.__init__字段，factory不变 | 不匹配，仅选a；b留下first，全量得到second | 同上 |

独立脚本命令：`PYTHONPATH=. <venv>/bin/python review/batch4-incremental/directional-experiment/independent_v3.py`。脚本exit0仅表示采集完成，3组结果为2匹配/1不匹配，不伪装为全通过。另有断言核对20组全部匹配和独立结果序列[true,true,false]。

## 已修复

B4-DIR-STATE：修改factory中的Box(first)为Box(second)，同类对象摘要不再阻止沿调用者传播。直接返回、局部变量返回、经中间函数转交、先读取字段再转交均对照一致。未知状态和候选保留；没有把全部结果改成UNKNOWN。返回固定值的正常停止对照通过。

## 仍开放：B4-DIR-SEED（P2，实验原有覆盖遗漏）

```python
class Box:
    def __init__(self):
        self.cb = first  # 修改为second

def factory():
    value = Box()
    return value

# 另一个文件
factory().cb()
```

实际候选保留first，全量候选为second。两者都complete=false/UNKNOWN；这不是虚假完整性的新退化，但旧候选不能被当作新结果复用。正式发布路径未启用此实验，因此不是已发布图受到破坏。

具体位置：v3.schedule()调用v1.direct_functions()，后者只枚举模块tree.body的FunctionDef/AsyncFunctionDef。类中的Box.__init__没有进入变更函数集合。factory自身AST和返回摘要均相同，function_body_changed为false；其返回值虽然不能证明字段等价，也不会被加入return_queue。之后错误复用b.py调用关系。

根Agent直接核对旧图，已存在：

- CONTAINS a -> Box
- CONTAINS Box -> Box.__init__
- CALLS factory -> Box
- CALLS run -> factory

因此这个反例并非解析器不能识别，也不是数据库不能反查；实验没有把已知方法变动映射到已有的类构造依赖。

## 明确修复方案（尚未执行）

1. 变更入口按(path,完整qualname,kind)对齐新旧定义，包含类方法；禁止继续只取顶层函数或qualname最后一段，避免同名方法碰撞。
2. 本反例的__init__字段写入变化，先沿所属关系定位Box；把Box作为构造结果可能改变的传播起点，不因__init__隐式返回None停止。
3. 按已有CALLS反向定位构造Box的factory，重算其受影响结果；返回实例摘要无法证明字段相同，则使用本次v3保守规则继续到run。
4. 新增/删除以新旧定义和关系合并定位；未覆盖的其他方法/副作用要明确无法认证，不能把这个单例补丁宣称通用方法支持。
5. 只先复跑上述反例、同名方法隔离、工厂无关常量修改及本轮20组；之后另行评估生产接入，不开启无边界反例追加。

这是待批准的第四轮实验修复方向，不是已验证修复。用户批准前，不继续修改或合并。

## 性能与范围

共享helper未变化返回值的样例仍为0/20外层调用点、20/40选择性阶段Jedi查询；旧新AST摘要上下文各21文件，全局非CALLS分析仍执行。未证明完整增量性能、跨版本身份/完整证据复用或真实图发布。现有实验比较是限定语义字段比较，不是所有原始字节完全相同。原有v1/v2失败证据保留。
