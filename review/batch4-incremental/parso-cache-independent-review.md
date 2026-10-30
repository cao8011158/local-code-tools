# Cache compatibility and package-context independent review — round 2/3

2026-10-31（北京时间）。分支 `feat/incremental-index-updates`；固定审阅提交 `ee6bbb9a72dbd8dd08129ede23e9d4a271dcdaa6`，远端引用核对一致。第1轮的包上下文问题及后续授权的核心依赖缓存问题保持同一整改链。本轮限定结论通过，整个Batch4未完成，不合并。

## 源码与交付

审阅完整跨库切片的既有接入规则及本次修复差异。按远端Git blob哈希复制357个可用源码、测试、配置及相关证据文件到独立目录。必要生产/测试/实验支持文件齐全；部分早期历史报告不在本环境，未伪称完整克隆。

首次上传eb2404ceba919bd806bc7a2f1fd2d91736524eba的python_analysis.py受到工具输出截断。逐文件哈希核对发现后，追加ee6bbb9修复传输，完整源文件blob为368cd39caa1ecb9104c971aa006d75e2a3d065c0。未用截断代码验收，未重写历史。其他上传文件已按远端哈希核对。

## 已关闭问题

- B4-JEDI-PARSO-CACHE：在Analyzer初始化、Jedi脚本构建前安装exact Parso0.8.7的插入时间兼容层。新建和磁盘加载均经过_set_cache_item，在原函数执行前只更新当前条目的last_used。change_time不改，原清理函数照常执行。版本不符明确报错；重复安装幂等，安装锁防止重复包裹。不修改site-packages、不吞KeyError、不提高阈值、不禁止清理。额外工作每次插入O(1)，原Parso阈值清理O(N)保留。
- B4-CROSSREPO-PACKAGE-CONTEXT：局部闭包从现有模块目录按实际点分名称前缀加入请求方和提供方的包/模块祖先，包括未修改的__init__.py和普通模块遮蔽。保留严格语法准入及未知情况完整回退。此前两项独立反例通过。
- 既有B4-CROSSREPO-PROJECT/SHADOW：每仓库环境和精确绑定策略、requester索引、同名模块和增删遮蔽检查继续通过。实际requester SQL扩容独立测试通过，未用全表搜索替代索引。

## 独立测试

Python3.12、Jedi0.20.1、Parso0.8.7。固定目录 `lct-cache-review`。

1. `PYTHONPATH=. .venv/bin/python -m pytest -q -rs tests` 加入11份独立测试文件：changed_python、source_prepare、evidence_reuse、dependency_store、class_component、effect_markers、crossrepo、jedi_environment、requester_access、existing_package_context、parso_cache。结果 **570 passed、25 skipped，30.53秒，exit0**；完整日志parso-cache-root-fixed.log。25跳过为24项owned Neo4j/相关服务及1项可选真实缓存验证，不属于已执行成功项目。
2. 独立反例使用真实grammar.parse解析旧mtime源文件，分别冷解析和真实pickle恢复，再解析620个其他源文件触发实际清理；确认目标仍可用，修改源内容/mtime后正确返回新树。以上2项已计入570，不能重复相加。
3. 在独立新进程中只停用兼容层，复跑同两项测试：**2 failed，0.73秒，exit1**，均在预期目标缓存读取处KeyError。未修改生产文件；日志parso-cache-root-unpatched.log。这是原始行为反例，不是修复版本失败。
4. 开发的过期条目清理、幂等、版本拒绝测试经独立全回归复跑。原contextlib断言未放宽。

## 限制与后续

没有安装新依赖版本；pyproject显式pin与现有uv.lock/requirements的0.8.7一致。开发离线锁解析因Jedi不在本地uv下载缓存失败，元数据采用最小同步；未验证全新电脑下载安装。未启动Neo4j、未重建正式图、未调用付费API、未操作Drive。

不保证超过10分钟仍被Jedi持有但未访问的缓存生命周期；不声称600是内存容量上限。当前修复只关闭刚加载却带旧使用时间的误删。整个Batch4仍需要真实业务支持范围、统一增量发布/恢复与规模验收；本轮通过不意味着Batch4完成或可合并。
