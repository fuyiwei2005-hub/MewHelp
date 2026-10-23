# 第八章：可插拔工具系统设计（待批准）

日期：2026-10-23。基于第七章完整State/上下文管理，沿用FastAPI、LangGraph与现有MySQL/独立PostgreSQL。本文件是设计，不表示功能已经实现；第九、十章不混入本章。

## 1. 目标、范围与方案选择

统一内置工具与两个自建MCP Server的发现、Schema、权限、执行、审计；物流迁至MCP；增加显式请求建工单后的interrupt预览确认。旧投诉按钮路径保留。MCP描述及annotations都是外部数据，不能授予执行权限。

方案A（推荐）：进程内注册表+可信本地注册/权限配置热刷新，每轮按Server动态发现，全部调用经过同一执行引擎。复用现有Agent图与checkpoint；新增依赖限官方MCP SDK、官方adapters及JSON Schema校验。
方案B：独立工具网关服务，客服通过网关调用。未来多应用共享便利，但增加进程与协议，本章没有必要。
方案C：只在启动时拉MCP并拼列表。改动少，但不满足客服不重启即可使用Server新增工具，排除。

拟采用A。注册表为统一的内存目录，并非额外业务工具数据库。业务数据仍在原MySQL；两个MCP Server只返回演示数据，不建表、不接真实系统。

## 2. 统一描述、来源与热注册

ToolSpec包含：name、description、JSON Schema parameters、source（builtin或mcp:<server>）、本地权限标识、调用适配器及本地结果投影器。名称/用途/Schema缺失或Schema本身非法则拒绝登记，记录发现错误。来源由客户端连接配置赋予，不能取Server自报字段。

内置query_order/query_product/query_faq/create_ticket服务启动登记。内置query_logistics退出活动目录，同名仅由物流MCP提供。旧实现可留作历史兼容参考，但不向Agent暴露第二个版本。执行前拒绝任何名称冲突，不允许外部工具覆盖内置工单。Agent移除固定工具名允许集与LABELS强索引，改从目录和本地路由策略取得工具/显示名；更新固定Prompt以允许申请工单预览，仍禁止自动写入。新增工具不再要求修改Agent分支。

新增内置工具走受信任开发者的本地插件模块：模块提供register(registry)，本地注册清单增加该模块；每轮检查清单版本，新模块首次导入并登记，无须修改Agent/执行引擎或重启客服。此入口不提供HTTP上传或任意模块执行。只对新模块热注册，本章不实现运行中卸载正在执行的Python代码。

MCP连接配置固定本机两个Server。每轮取工具前分别调用MultiServerMCPClient.get_tools(server_name=...)；某Server发现超时不影响其他Server，下一轮继续发现。失败Server本轮不提供新执行能力，不能把陈旧清单当连接健康。发现成功后按Server原子替换该来源目录；Server删除的工具随之退出。每轮冻结排序稳定的目录版本；State/checkpoint只存可序列化的工具描述/版本，不存网络连接或Python函数。恢复预览不重新绑定同名不同Schema工具。

同一目录版本的system和工具Schema保持稳定。目录更新后重新核算第七章实际工具前缀及历史预算，记录版本/预算；工具增多导致连一轮装不下时明确报预算不足，不继续沿用1050预留。

## 3. 本地权限

可信本地权限文件按(source, tool_name)登记read/write与是否可执行，支持下一轮热读取。内置注册是本地可信来源；MCP未列入本地许可的工具即使已发现也不提供给Agent执行。模型伪造名称或直接发起禁用工具调用仍由引擎拒绝并审计。

本章唯一允许的write是builtin:create_ticket；所有MCP write拒绝。工具描述、readOnlyHint或模型说“这是只读”均不能变更规则。预置物流query_logistics、售后query_warranty/query_return_progress的read许可。

热发现验收时，预先在本地权限配置授权一个尚未发布的只读演示名query_delivery_eta；随后只在物流Server新增该工具并重启该Server。客服PID、代码和权限文件保持不变，下一轮即可调用。一般外部新工具仍需我们侧显式授权，不能以动态发现为由自动放行未知写操作。

## 4. 统一执行与结果

所有入口（Agent、退款确定性子流程查订单、旧投诉建单按钮、新预览确认）统一经过ToolEngine。依次执行来源/版本检查、JSON Schema参数校验、权限检查、调用与结果投影。参数错误回传字段路径、缺失/类型/取值说明，作为tool消息回灌；不抛异常终止整轮，不自动修正参数或补编必填项。

只读工具仅对连接抖动、可识别临时网络故障和超时按配置有限重试，默认最多2次尝试、短退避；业务未找到/空结果不重试，普通逻辑异常不重试。写工具总尝试次数为1，超时标记超时且retry_count=0，不暗中重发。MCP传输异常要穿透适配器交给统一引擎，MCP业务isError按失败处理，不把任意业务错误当网络重试。

统一结果含ok、data或error（kind=invalid_arguments/not_found/failure、code、中文message、必要字段说明）。兼容已有query_faq入参keyword及matches/citations/refused等返回契约；其他工具只保留回答所需业务字段，内部枚举转换中文，JSON ensure_ascii=False。MCP原始内容不得作为新system指令。完整实际tool结果继续只在checkpoint；MySQL messages保持第七章调用/结果标识投影。

第七章单次tool结果上限继续生效；真实工具调用状态与结果摘要在审计保留，不把“上游执行成功但给模型的结果超预算”误记为从未执行。

## 5. tool_audit_logs

字段：id、conversation_id、tool_call_id、tool_name、source、arguments JSON、result_summary、status、error、retry_count、duration_ms、created_at。不挂外键；按会话+call_id+source定位同一次调用，重试合为一条。最终状态为成功/失败/超时/校验拦下/权限拒绝；等待人工确认时可记录中间态待确认，恢复后更新终态，不新建第二条调用。

未知工具、参数被拦、权限被拒、预览取消都记录。审计写入失败只记录服务日志，不逆向阻断读工具或已授权写工具。审计不是授权凭据；授权与预览幂等使用独立状态。耗时记录引擎执行时间，用户等待确认时间单列事件，不算网络调用超时。

## 6. 两个独立MCP进程

物流Server：127.0.0.1:18011/mcp，query_logistics(order_id)返回状态、位置、轨迹；随机mock，明确demo=true。
售后Server：127.0.0.1:18012/mcp，query_warranty(order_id)查在保、query_return_progress(order_id)查退货进度；随机mock，不连接MySQL。

使用MCP官方Python SDK FastMCP、Streamable HTTP、stateless_http=True/json_response=True；客服使用langchain-mcp-adapters.MultiServerMCPClient、transport=http。拟锁定已核查兼容组合adapters0.3.2 + SDK1.28.0（adapters约束SDK<2，不混用SDKv2 API）。安装时若当前项目依赖求解存在矛盾则停止说明，不自行换SDK、框架或传输。

售后“退货资格/能否退款/维修条件”保持第六章先订单再扩写检索政策；明确“在保状态/退货处理进度”属于业务状态查询，分流到相应MCP而不强塞政策闸。缺订单号仍复用订单选择器，选择后恢复状态查询分支；通用保修政策仍走RAG。意图输出仍仅intent/confidence，不额外扩字段。

## 7. 工单请求、补槽与确认

只有用户明确提出创建工单，或点击旧投诉建单按钮，才建立建单许可意图。服务端用本地明确请求规则及当前用户文本证据核验；否定、引用示例、假设句、仅抱怨均不算。模糊表述可建议按钮或澄清，不凭模型主张授予许可。用户已明确提出后，State保留本会话待建单意图，后续补充描述不会误入退款选单；取消/完成/新目标时清除。

主力Agent复用create_ticket的description/ticket_type Schema。缺问题描述先追问，description必须来自用户已提供事实，不能将“帮我建工单”本身当充分描述。模型发起调用后引擎只准备预览，不写tickets。

在独立、可恢复的图节点执行interrupt：载荷包含preview_id、turn_id、tool_call_id、类型、问题描述；预览绑定会话、冻结参数hash和注册版本。interrupt之前只做幂等准备，不执行写工具。前端显示预览卡片及确认提交/取消，两者互斥、一次性禁用。

新增resume接口只接受属于当前用户/会话的待确认preview，判断确认或取消，不能由请求体覆盖冻结参数。确认后后端签发只针对本次call/参数的内部许可，引擎校验后执行一次；复用既有工单幂等键，重复点击/网络重复resume返回已有结果，不创建第二单。写超时不自动重试；回执状态不明时如实提示，不能另开新call悄悄再建。

取消后不执行，工具结果为权限拒绝并落审计，图继续正常收敛。用户不点击而发送新消息时旧预览失效且按权限拒绝结束，正常新轮继续；旧预览不再能被确认。页面刷新可回载待预览卡，checkpoint完整保留工具协议。

第五章投诉仍展示两个独立按钮：转人工仅前端模拟，建工单按钮本身即明确确认，保持原有接口/回执交互，不额外弹第二次预览，但同样经过统一引擎。Agent不能伪造按钮确认凭据；不点击任何按钮不会创建工单。

## 8. 验证与交付

后端按TDD验证注册/冲突/非法Schema、参数类型/必填/边界、来源伪造、无许可写拒绝、只读暂时失败重试/业务空不重试、写超时0重试、审计失败不影响执行；真实两个MCP进程验证动态发现、来源、Server单独重启新增工具且客服PID不变。

工单用例覆盖缺描述追问、补齐预览、未确认无tickets、确认一条带单号、取消无tickets且权限拒绝审计、重复确认幂等、越权/过期预览拒绝、旧投诉按钮不变、用户继续聊天无动作。Prompt/明确请求识别用正负标注评估（含否定、引用、模糊请求）。前端卡片依用户要求Vibe，真实浏览器点选验证，不进行页面TDD/独立code review。

回归第七章预算/原文/侧栏、第五六章物流/退款选单/投诉/ReAct，真实网络超时使用隔离故障注入工具，生产默认mock不故意变慢。交付演示启动命令、真实测试/审计结果和dev-notes/ch08.md。开发按阶段即时追记用户原话、产出、纠偏与返工。

## 9. 文档依据与设计自审

Context7于2026-10-23复核：
- https://github.com/langchain-ai/langchain-mcp-adapters/blob/main/_autodocs/api-reference/client.md ：get_tools(server_name=...)、临时会话与http传输。
- https://github.com/modelcontextprotocol/python-sdk/blob/v1.28.0/docs/server.md ：FastMCP、Streamable HTTP与stateless设置。

自审：范围限第八章，未新增真实接口或MCP写权限；动态发现与本地授权分开，避免“新增自动可用”绕过权限约束；写前interrupt且写执行无自动重试；旧投诉明确确认与新Agent预览分别保留；工具目录变化与第七章前缀预算联动。无未决占位；本书面稿待用户批准后才进入计划和实现。
