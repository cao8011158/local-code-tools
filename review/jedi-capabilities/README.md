# Jedi 能力实验与接入边界

2026-11-02，Asia/Shanghai。当前只进行独立实验和文档更新；生产解析、来源接线、增量调度修改保持暂停。本报告不宣称本轮重构完成。

## 这份记录解决什么问题

目的：开发时直接使用 Jedi 已有能力，不凭想象添加限制、再推断或覆盖规则。每个限制判断必须落到具体源码、API、位置、配置和原始结果，并与官方说明对照。

**发现缺口不等于自动批准自研补全。** 目标结果仍由 Jedi 提供；来源记录、更新依赖、图保存属于我们的接入职责。一个调用查询为空，不能抹掉 Jedi 在赋值、实参或返回表达式处已经识别出的函数。

有限实验不能穷尽 Python 所有程序。这是可扩展的证据清单，**不是语法白名单**：未列入的写法默认正常调用 Jedi；不能因为尚未测试就禁用、标为不支持或添加兜底解析器。

## 输入、方法和结果

- Python 3.12.14、Jedi **0.20.1**、Parso **0.8.7**；完整环境在原始 JSON。
- **96 个不同源码场景**：90 个调用/来源场景，加 6 个导入、基类、lambda、外部调用和partial公共出口场景。每个在全新进程中运行两次，共 **192 次基线运行**。
- 另有 **17 次查询顺序/配置对照**。合计209次主实验运行，记录969次公共API查询。读取签名参数的懒属性不伪装成额外目标API查询。
- 主实验默认场景两次的完整结果一致；比较只忽略耗时和外层返回顺序，保留重复、所有位置/类型/参数内容及参数内部顺序。原始返回顺序仍保存在JSON。
- 默认基线99个调用签名查询位置中，71个有非空结果、28个为空。**这不是71项成功、28项失败或准确率**：非空也可能是抽象instance；空也可能是没有传入值、非可调用对象或接入负对照。
- 默认基线没有主API异常。关闭fast_parser的7项控制累计出现41次API KeyError，单独计错，不计为空目标。
- 递归转发的两个最小场景，在基线及顺序控制共5次出现Signature.params的RecursionError；已返回的签名目标仍保留。
- 另做14次有界诊断（6次原案例/cache假设对照、8次code/path构造对照），原始调用栈与输入保存在followups.json。它们没有修改生产依赖或设置。

实验只导入Jedi/Parso与标准库，不导入LCT，不执行样例模块。所有合成文件均挂载到独立临时目录，显式提供Project/sys_path；关闭unsafe extensions。查询标记被删除后计算Jedi的一基行号、零基字符列；同时记录行文本、源码SHA256、API原始Name类型和位置。infer、goto、get_signatures及params分别记录。

逐例索引：[CASE_MATRIX.md](CASE_MATRIX.md)。原始输入/结果：[observations.json](observations.json)、[edge_paths.json](edge_paths.json)、[followups.json](followups.json)。官方来源与版本限定：[OFFICIAL_DOCUMENTS.json](OFFICIAL_DOCUMENTS.json)。

## 已确认的能力与接入义务

| ID | 独立观察 | 对开发的约束 |
| --- | --- | --- |
| JEDI-CAP-01 | 直接/默认/关键字/star/kwargs回调、跨模块回调、两层转交、getter结果作为回调实参均有识别first的案例。 | 不能预设这些需要自研参数/返回值求解。 |
| JEDI-CAP-02 | 字典字面量、直接下标赋值、同文件覆盖、导入字面量、普通getter再调用、返回容器后写入、列表append/extend均有具体目标结果。 | “容器有修改”“跨文件”“中间函数”本身不是拒绝Jedi结果的理由。 |
| JEDI-CAP-03 | classmethod的表达式infer给出外部描述符__get__，调用上下文get_signatures给出捕获的C.build。 | 先核对API语义与坐标，不以描述符输出为由自行推导目标。不能反推为任一API在所有场景都更优。 |
| JEDI-CAP-04 | dict_register的写入参数fn与实参first能被infer识别，但最后registry['go']的infer/get_signatures均为空。两个注册键的fn还会返回first和second两项。 | 保存可用来源信息；它不等于末端调用目标已识别，不能按自研键/写入规则补出CALLS。 |
| JEDI-CAP-05 | 缺少provider.py时调用为空，补齐后找到first；右括号后查询签名为空，左括号内可找到first。 | 这些是输入/位置对照，不能记成上游能力缺口。 |
| JEDI-CAP-06 | Callable注解、异步返回、contextmanager绑定值、dict.get、可调用实例可给出抽象类型/instance；partial外部调用能找到execute，内部cb仍有空结果。 | 非空不自动等于具体源码函数；不得把instance改称构造类或__call__。也不能笼统说partial/async不支持。 |
| JEDI-CAP-07 | 直接与导入基类能定位Base，导入别名能定位原函数，lambda有function类型及位置但full_name为空，外部math.sqrt也可识别。 | full_name空不等于结果无效；外部边界和我们捕获/映射范围与Jedi能力分开。 |

## 具体缺口与官方说明如何对应

下列“空”均指该版本在精确样例和查询位置的原始结果。不能推广成整个Python特性不支持。

| 观察/案例ID | 实际结果 | 官方文档对照与分类 |
| --- | --- | --- |
| dict_alias_write、dict_register、dict_parameter_writer、dict_cross_module_write、dict_getter_cross_writer、list_cross_module_append | 写入处能找到函数，最终读取调用处为空；默认重复及所选call-first对照保持该现象。 | Features列出相关容器能力，Development对副作用给出背景限制。但Development自称部分内容过时，且没有对这些精确案例逐项解释。分类：**已复现的具体未解析场景，未确认是官方已知缺陷**。 |
| dict_update、dict_setdefault、dict_unpack | 精确样例的末端为空；直接dict_assign的正对照能找到first。 | Features的广义容器/解包能力声明不是逐个操作的精度保证，也没有给出此处空结果的专门解释。不能据此编写整类屏蔽规则。 |
| custom_metaclass、setattr、dynamic_import、globals_write、object_dict_write、outside_instance_write | 这些具体样例末端为空。 | 与Features明确列出的限制类别相符。文档限制也不意味着同类任意样例永远不能返回结果；真实返回仍须采纳。 |
| callable_annotation、dataclass、type_comment | 声明的Callable/object等类型可见，具体函数目标可能为空。 | Using Jedi介绍注解和stub的类型推断；并未保证任意Callable声明都能定位唯一实现。分类：**类型信息和具体函数身份需要区分**，不自动认定上游bug。 |
| nonlocal、global_rebind、dict_clear | 静态结果可保留first；global_rebind给first/second，dict_clear后仍观察到first。它们不是对运行顺序的精确模拟。 | 当前API是静态推断接口，Features/Development讨论副作用边界；未查到这些精确顺序案例的官方解释。记录具体精度差异，不能偷偷以自研latest-write改写结果。 |
| recursive_parameters、mutual_recursive_parameters | get_signatures正确给出forward/first；随后params抛RecursionError。 | API Result Classes说明params返回参数定义，未查到对此递归例子的专门官方说明。分类：**已复现的元数据异常/上游问题候选**；不抹掉正确目标，不宣称官方已确认。 |
| fast_parser=False且Script带源码path的最小对照 | 主API抛KeyError；同一源码code-only不带path可返回f。 | Settings与API允许配置并提示parser可变性，但没有解释此精确异常。调用栈到Jedi读取Parso缓存。Parso在线文档版本是0.8.4，不能把它当作0.8.7的确切解释。分类：**配置/依赖接入异常候选**，不是语言特性为空。 |

fast_parser异常的诊断还尝试了现有Parso usage-timestamp兼容处理；本例仍报KeyError。这个失败假设保存在followups.json中，**没有新增生产补丁或推荐临时兜底**。公开默认配置的90场景结果未受这组关闭配置的异常污染。

官方来源：

- [Features and Limitations](https://jedi.readthedocs.io/en/latest/docs/features.html)
- [API Overview](https://jedi.readthedocs.io/en/latest/docs/api.html)
- [API Return Classes](https://jedi.readthedocs.io/en/latest/docs/api-classes.html)
- [Settings](https://jedi.readthedocs.io/en/latest/docs/settings.html)
- [Using Jedi / Type Hinting](https://jedi.readthedocs.io/en/latest/docs/usage.html#type-hinting)
- [Jedi Development](https://jedi.readthedocs.io/en/latest/docs/development.html)（页面明确警告部分内容较旧）

检索到的Jedi页面显示0.20.1；latest会变化，不是固定tag。版本化features地址本次未能取回。没有查到的精确解释应保持“未找到”，不能用宽泛说明替官方确认某个bug。

## 明确尚未证明的内容

- 不是所有Python程序、所有语法组合、所有版本/平台的穷尽边界；复杂类型、框架插件、第三方注册机制和大规模压力未在本轮全部覆盖。
- 不是“每个非空结果都等于实际运行时唯一调用目标”的证明；样例业务代码没有执行。
- 没有验证或修复LCT最终消费者到原始写入点的完整直接来源依赖，也没有修复过宽增量传播。
- 不是新生产运行时的全仓库回归、九文件或83文件验收。此前暂停的fresh83仍未完成，不能借此实验标为通过。
- 缺口登记不是自研求解器、依赖升级或替换授权。若需要改变能力边界，应另列具体方案与证据。

## 重现

在仓库根目录、现有固定虚拟环境中运行（会写入指定实验输出，不调用provider）：

~~~sh
PYTHONPATH=. .venv/bin/python review/jedi-capabilities/probe.py --repeats 2 --controls --output review/jedi-capabilities/observations.json
PYTHONPATH=. .venv/bin/python review/jedi-capabilities/edge_paths.py --output review/jedi-capabilities/edge_paths.json
PYTHONPATH=. .venv/bin/python review/jedi-capabilities/followups.py --output review/jedi-capabilities/followups.json
PYTHONPATH=. .venv/bin/python review/jedi-capabilities/summarize.py
~~~

单例：probe.py增加--only dict_register --repeats 1，并使用另一个输出路径。每条观察保留源码和坐标，后续增加边界应添加最小样例及正常对照，不从我们自己的Graph输出生成预期。

开发约束已写入仓库根[AGENTS.md](../../AGENTS.md)。这个实验清单可以要求开发者核对证据；不能代替实现的独立审阅。
