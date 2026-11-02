# Jedi 0.20.1：逐例原始结果索引

本表由 observations.json 生成，不是生产目标规则、白名单或准确率测试。
每个默认场景在独立进程中重复两次；源码、配置、坐标及所有原始结果见对应 JSON。
空结果、API 异常、元数据异常和 instance 类型分开显示；不将它们都归为“不支持”。

| 场景 ID | 类别 | 调用位置 get_signatures | 同位置表达式 infer |
| --- | --- | --- | --- |
| alias | binding | call: demo.first:function | value: demo.first:function |
| async_return | async | call: types.FunctionType:instance | value: types.FunctionType:instance |
| bound_method | object | call: demo.C.method:function | value: demo.C.method:function |
| callable_annotation | typing | call: 空 | value: typing.Callable:instance |
| callable_instance | object | call: demo.C:instance | value: demo.C:instance |
| callback_container_parameter | callback | call: demo.first:function | value: demo.first:function |
| callback_cross_module | callback | call: provider.first:function | value: provider.first:function |
| callback_default | callback | call: demo.first:function | value: demo.first:function |
| callback_getter_argument | callback | call: demo.first:function | value: demo.first:function |
| callback_keyword | callback | call: demo.first:function | value: demo.first:function |
| callback_kwargs | callback | call: demo.first:function | value: demo.first:function |
| callback_lambda | callback | call: demo.first:function | value: demo.first:function |
| callback_multiple_inputs | callback | call: demo.second:function, demo.first:function | value: demo.first:function, demo.second:function |
| callback_partial | callback | call: 空 | value: 空 |
| callback_positional | callback | call: demo.first:function | value: demo.first:function |
| callback_star | callback | call: demo.first:function | value: demo.first:function |
| callback_two_hops | callback | call: demo.first:function | value: demo.first:function |
| classmethod | object | call: demo.C.build:function | value: builtins.classmethod.__get__:function |
| closure | return | call: demo.first:function | value: demo.first:function |
| conditional | binding | call: demo.second:function, demo.first:function | value: demo.first:function, demo.second:function |
| contextmanager_factory | decorator | call: demo.manager:function, demo.manager:function; call_callback: types.FunctionType:instance, types.FunctionType:instance | value: typing.Callable:instance; callback_value: types.FunctionType:instance |
| custom_descriptor | object | call: demo.first:function | value: demo.first:function |
| custom_getattr | dynamic | call: demo.first:function | value: demo.first:function |
| custom_metaclass | dynamic | call: 空 | value: 空 |
| dataclass | typing | call: 空 | value: typing.Callable:instance |
| decorator | decorator | call: demo.first:function | value: demo.first:function |
| decorator_factory | decorator | call: demo.first:function | value: demo.first:function |
| dict_alias_write | dictionary | call: 空 | value: 空 |
| dict_assign | dictionary | call: demo.first:function | value: demo.first:function |
| dict_clear | dictionary | call: demo.first:function | value: demo.first:function |
| dict_cross_module_imported_literal | dictionary | call: provider.first:function | value: provider.first:function |
| dict_cross_module_write | dictionary | call: 空 | value: 空 |
| dict_delete | dictionary | call: 空 | value: 空 |
| dict_dynamic_key | dictionary | call: demo.first:function, demo.second:function | value: demo.first:function, demo.second:function |
| dict_equal_keys | dictionary | call: demo.first:function | value: demo.first:function |
| dict_get | dictionary | call: builtins.NoneType:instance, types.FunctionType:instance | value: builtins.NoneType:instance, types.FunctionType:instance |
| dict_getter | dictionary | call: provider.first:function | value: provider.first:function |
| dict_getter_cross_writer | dictionary | call: 空 | value: 空 |
| dict_literal | dictionary | call: demo.first:function | value: demo.first:function |
| dict_overwrite | dictionary | call: demo.second:function | value: demo.second:function |
| dict_parameter_writer | dictionary | call: 空 | value: 空 |
| dict_register | dictionary | call: 空 | value: 空 |
| dict_register_two_keys | dictionary | call: 空 | value: 空 |
| dict_returned_allocation | dictionary | call: demo.first:function | value: demo.first:function |
| dict_setdefault | dictionary | call: 空 | value: 空 |
| dict_unpack | dictionary | call: 空 | value: 空 |
| dict_update | dictionary | call: 空 | value: 空 |
| direct | binding | call: demo.first:function | value: demo.first:function |
| dynamic_import | dynamic | call: 空 | value: 空 |
| external_call | graph-exit | call: math.sqrt:function | value: math.sqrt:function |
| generator_yield | sequence | call: demo.first:function | value: demo.first:function |
| generator_yield_from | sequence | call: demo.first:function | value: demo.first:function |
| getattr_literal | dynamic | call: demo.C.method:function | value: demo.C.method:function |
| global_rebind | return | call: demo.second:function, demo.first:function | value: demo.first:function, demo.second:function |
| globals_write | dynamic | call: 空 | value: 空 |
| import_binding | graph-exit | call: provider.first:function | binding: provider.first:function; value: provider.first:function |
| inheritance_direct | graph-exit | call: demo.Child:class | base: demo.Base:class; value: demo.Child:class |
| inheritance_imported | graph-exit | call: client.Child:class | base: provider.Base:class; value: client.Child:class |
| instance_dict | object | call: demo.first:function | value: demo.first:function |
| instance_field | object | call: demo.first:function | value: demo.first:function |
| lambda_target | graph-exit | call: <lambda>:function | value: <lambda>:function |
| list_append | sequence | call: demo.first:function | value: demo.first:function |
| list_comprehension | sequence | call: demo.first:function | value: demo.first:function |
| list_cross_module_append | sequence | call: 空 | value: 空 |
| list_extend | sequence | call: demo.first:function | value: demo.first:function |
| list_literal | sequence | call: demo.first:function | value: demo.first:function |
| missing_context | integration | call: 空 | value: 空 |
| mutual_recursive_parameters | metadata | call: demo.first:function; params ERROR RecursionError | value: demo.first:function |
| namespace_package | import | call: pkg.provider.first:function | value: pkg.provider.first:function |
| noncallable_instance | object | call: 空 | value: demo.C:instance |
| nonlocal | return | call: demo.first:function | value: demo.first:function |
| object_dict_write | dynamic | call: 空 | value: 空 |
| outside_instance_write | object | call: 空 | value: 空 |
| partial_call | graph-exit | call_callback: 空; call: demo.execute:function | callback_value: 空; value: functools.partial:instance, functools.partial:instance |
| property_callable | object | call: demo.first:function | value: demo.first:function |
| recursive_parameters | metadata | call: demo.forward:function; params ERROR RecursionError | value: demo.forward:function |
| reexport | import | call: provider.first:function | value: provider.first:function |
| references_inventory | source | call: 空 | value: 空 |
| registered_callback_composition | dictionary | call_callback: 空; call: 空 | callback_value: 空; value: 空 |
| relative_import | import | call: pkg.provider.first:function | value: pkg.provider.first:function |
| restored_context | integration | call: provider.first:function | value: provider.first:function |
| returned_callback | return | call: demo.first:function | value: demo.first:function |
| returned_function | return | call: demo.first:function | value: demo.first:function |
| setattr | dynamic | call: 空 | value: 空 |
| staticmethod | object | call: demo.C.work:function | value: demo.C.work:function |
| stub | typing | call: provider.first:function | value: provider.first:function |
| super_method | object | call: demo.Base.work:function | value: demo.Base.work:function |
| syntax_recovery | syntax | call: demo.first:function | value: demo.first:function |
| try_except | flow | call: demo.first:function, demo.second:function | value: demo.first:function, demo.second:function |
| tuple_index | sequence | call: demo.second:function | value: demo.second:function |
| tuple_unpack | binding | call: demo.first:function | value: demo.first:function |
| type_comment | typing | call: 空 | value: builtins.object:instance |
| unbound | binding | call: 空 | value: 空 |
| utf8_split_call | position | call: demo.café:function | value: demo.café:function |
| walrus_header | binding | call: demo.first:function | value: demo.first:function |
| wrong_cursor_end | position | call: demo.first:function; end: 空 | value: demo.first:function |

## 重复及控制

- 默认场景重复差异：无（完整记录 multiset；保留重复和参数内部顺序）。
- API 异常：41 次；分布及原始错误见 summary.json。API 异常不能计为空结果。
- 签名参数元数据异常：5 次；已返回的签名目标仍保留。

所有结论只适用于案例中的具体源码、版本、API、坐标和配置。
