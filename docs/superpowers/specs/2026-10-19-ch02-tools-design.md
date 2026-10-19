# 第 2 章：聊天内单轮工具调用与 MySQL 持久化

状态：架构设计草案，等待用户评审；尚未开始实现。

## 目标与范围

用户在现有聊天页提问，由模型决定是否使用及选择业务工具；工具执行结果回灌，最终回答保持真实 SSE 流式。数据库只有 faq、conversations、messages、tickets 四张业务表。工具只有 query_order、query_product、query_logistics、query_faq、create_ticket。

固定技术栈：FastAPI + SQLAlchemy + Docker MySQL + LangChain @tool。沿用当前 DeepSeek 官方 OpenAI Chat Completions 接入和本地 .env。不引入 Agent Loop、LangGraph、向量检索、RAG、订单/商品/物流数据表或真实企业 API。

## 实现方式选择

推荐 SQLAlchemy AsyncSession + asyncmy：与现有异步 SSE 保持一致，每个短事务单独使用 session，不跨并发任务共享 session，也不在等待模型期间持有数据库事务。

另一个可行方案是同步 SQLAlchemy + 线程池，连接简单但需要额外明确线程边界；本章采用异步方案。不会改用 SQLite、其他数据库或 Agent 框架。

目录按职责分层：api（路由与 SSE）、services（单轮编排）、repositories（SQL 查询和事务）、models（四表 ORM）、tools（定义、注册、执行器）、数据库生命周期与配置。现有页面、结构化售后提取接口继续可用。

## “单轮调用”的具体解释

每条用户消息最多发生一次工具选择模型调用、最多执行一个业务工具、再进行一次禁用工具的流式回答；不自动再次选工具。

- 工具选择使用 bind_tools + auto，让模型选择；不使用后端关键词路由冒充 Function Calling。
- 模型可不调用工具：随后进入禁用工具的流式回答。
- 选择了工具：验证并执行一次，将原始 AIMessage.tool_calls 和匹配 tool_call_id 的 ToolMessage 交给第二次模型调用。
- 第二次显式 tool_choice=none，绝不再执行工具，即使模型违规输出新的调用也按错误处理。
- 模型一次给出多个调用时，本轮不执行任何业务工具，为全部调用返回“单工具限制”结果并收敛，提示用户拆分问题；不任意挑一个执行。
- 工具执行中的瞬时错误重试不算新一轮模型决策，参数不重写。

工具选择阶段不伪造流式文本；真正对用户显示的最终回答由第二次模型调用逐片段传输。现有页面继续把片段平滑逐字排版。

## 四张表

### faq

id 主键；question、answer、category 非空；问题使用唯一约束使种子脚本可重复执行。演示数据明确标注为测试政策，不代表真实商家承诺。

### conversations

id 使用现有字符串会话 ID；user_id（本地演示默认 demo-user，暂不引入登录）；status 为 open / escalated / closed；created_at 为 UTC。

MySQL 成为历史的事实来源，服务重启后已保存会话仍可查询并续聊。进程内只保留同会话请求互斥和容量控制，不再把会话内容仅存在内存。仍按单进程运行，本章不扩展分布式锁。

### messages

自增 id；conversation_id 外键；role 只允许 user / assistant / tool；content；tool_calls（JSON，可空）；tool_call_id（可空）；created_at。

额外记录 turn_id 与 turn_status（pending / completed / failed / cancelled），用于完整调用链裁剪和审计。assistant 工具申请保留 name、args、id；tool 消息的 tool_call_id 必须对应申请，普通消息为空。顺序按 id，不仅依赖同秒时间戳。

用户、工具申请、工具结果和最终回答都落库；失败和断流的真实过程也保留，但未完成轮次不作为正常上下文。工具重试细节存入结果元数据，不增加第五张表。

### tickets

ticket_no 为主键；conversation_id 外键；description；ticket_type；status（pending / processing / resolved）；created_at。增加 originating_tool_call_id 的唯一约束，保障同一次创建工具调用发生超时重试时不重复建工单。

创建成功时将 conversations.status 更新为 escalated。工单与对应 tool 结果的保存使用一致的事务边界，结果报告成功以数据库提交为准。

四表均采用 InnoDB、utf8mb4；数据库凭证只放 .env，业务连接不用 root。时间存 UTC，界面按本地时间显示。

## Docker 与数据初始化

Docker Compose 启动独立 MySQL 服务，固定使用官方 mysql:8.4.11，命名卷持久化，端口默认只绑定 127.0.0.1:3307；健康检查通过后再初始化四表和测试种子。

镜像版本与环境变量首先通过 Context7 查询；其 MySQL 检索没有返回完整镜像说明，补查 Docker Official Image 页面确认支持该标签及初始化参数：https://hub.docker.com/_/mysql 。

本章提供明确的初始化命令，幂等灌入 FAQ、示例会话、关联消息和工单；重复执行不清空用户聊天或重复灌种子。仅四张业务表，不为本章引入额外版本追踪表；已有数据不会使用 drop_all 重建。后续 schema 演进需单独设计迁移。

当前 Docker 客户端可用但 Linux 引擎未启动。实施先启动并验证 Docker；若无法运行 MySQL 或驱动与 Python 不兼容，报告具体原因并问用户，不以 SQLite 或仅内存结果替代验收。

## 五个工具

全部用 langchain_core.tools.tool 的 @tool 装饰器和明确 Pydantic args_schema。模型可见参数不包含数据库连接、用户身份或 conversation_id；会话关联由服务端在当前请求作用域绑定，避免模型把工单写到其他会话。不依赖需要 Agent/图运行时的 ToolRuntime 自动注入。

- query_order(order_id)：内部随机生成演示订单状态、金额、商品概要，返回订单号和 demo 数据来源。
- query_product(product_id)：内部随机生成演示名称、价格和库存等，不建表、不调用外部 API。
- query_logistics(order_id)：直接按订单号随机生成演示物流状态和轨迹，不需要先调用 query_order，因此“订单 1001 的物流到哪了”可以只调用一次工具。
- query_faq(keyword)：SQL LIKE 查 faq.question，返回至多 5 条 question / answer / category；参数化查询，字面 % / _ 转义，不拼接原始 SQL。
- create_ticket(description, ticket_type)：写当前会话的人工工单，返回真实入库工单号与状态。缺少可用描述先追问；不能把工单创建说成实际退款、换货成功。

模拟数据在回答/徽章中明确标为演示，不造成真实订单已查询的误解。随机结果在一次工具调用的重试中保持同一逻辑结果，避免前后矛盾；不会随机注入故障来影响演示。

## FAQ 预期漏召回

种子包括：
- question：“退货政策”；answer：测试商家未使用商品可在签收后 7 天内申请，质量问题与非质量问题处理规则以测试数据为准；category：“售后”。
- question：“运费规则”；answer：测试普通配送运费 8 元、满 99 元包邮；category：“配送”。
- 其他常见商品/发票等测试条目，question 不包含“邮费”。

模型从用户原话提取字面关键词，只删问句虚词，不做同义词扩展；执行器拒绝不在当前原话中出现的关键词。FAQ 只匹配 question，不顺便扩大到 answer 或 category。

因此：
- “退货政策是什么” → keyword=“退货政策” → SQL 命中。
- “邮费是多少” → keyword=“邮费” → SQL 0 行；不得改写为“运费”再查。
- 工具返回空结果后，最终模型明确说未找到对应政策，不用常识编造金额，不调用第二个工具。

这是指定的关键词检索能力边界，不是人为在后端识别“邮费”后直接返回失败。验收保留原始关键词、SQL 命中条数和模型最终回答，为下一章升级提供基线。

## 注册、校验、错误和重试

工具注册表只允许上述五个唯一名字，统一生成给模型的 schema；未知名字、非法 JSON、缺参数、额外参数和类型错误返回结构化工具错误，不调用任意函数。

默认每次工具执行超时 5 秒，最多 2 次尝试，第二次前等待 0.2 秒。仅超时、连接中断、可判定的瞬时数据库错误重试；参数错误、未知工具、业务未找到不重试。模型请求沿用现有整体时限，并配置包含工具执行和最终回答的整轮时限，避免无限等候。

每次重试都重新创建短生命周期数据库 session。create_ticket 用工具调用 ID 幂等键解决“写成功但确认超时”的重复问题，重试先查询原结果；不能把随机生成新工单号作为重试幂等。

工具错误回灌模型，要求说明查询未完成、不要把失败当成功。输出错误码和安全描述，不暴露连接串、SQL 参数、密钥或内部堆栈。

## SSE 和聊天页面

仍使用 POST /chat，保留 meta / token / done / error 与心跳，增加：
- status：例如“正在判断如何为您查询”。
- tool_start：name、tool_call_id、中文名称、演示标识。
- tool_retry：name、attempt。
- tool_end：name、成功/未命中/失败、耗时及安全摘要。

状态在工具执行前到达浏览器。气泡顶部显示中文小徽章，如“查询物流 · 演示数据”“查询常见问题 · 未命中”“创建工单 · 已完成”。不把原始数据库报错或全量工具 JSON 塞进普通用户流程。

本次页面改造完全按用户指定用 Vibe Coding，直接在现有样式上做徽章与状态，不走页面 brainstorm / TDD / code review。

## 事务、断流与上下文

数据库事务不跨越模型生成或 SSE 等待，避免占用长事务。短事务分别保存用户消息、工具申请、工具结果及最终回答。

数据库成功保存后才发送成功 done。断流保留已发生的审计过程，标记未完成，不把残缺调用链用于后续正常上下文；已提交工单是已发生的业务副作用，断流不会删除它，重试通过调用 ID 避免重复创建。

上下文按完整用户回合裁剪：user → assistant(tool_calls) → tool → assistant(final) 是一个整体；普通无工具回合是 user → assistant。不得沿用第一章“每两条删一对”算法。预算包含工具定义与结果，限制 FAQ 条数与工具结果体积；保留当前问题和系统约束，仍不足时报明确预算错误。

同一会话的占用由一个响应所有者释放，覆盖模型决策、工具执行、最终发送和清理，保留第一章已修复的竞态保护。

## 验证与交付

后端按 TDD：四表约束/持久化、FAQ LIKE 命中/不命中、工单创建与幂等、工具 schema/未知工具/超时重试、最多一次工具执行、第二次禁用工具、工具消息关联、完整调用链裁剪、SSE 状态先于执行、断流与并发、原售后提取回归。

使用真实 Docker MySQL 集成验证数据库行为；测试数据库与演示数据库隔离，清理只限测试数据，不删除命名卷。模拟依赖只用于可控异常边界，不能替代 MySQL 验收。

Prompt 与种子数据用标注样例评估工具选择、参数、FAQ 预期漏召回和禁止编造；实际 DeepSeek 验证选择行为，不在后端硬编码验收句路由。

真实浏览器验收三个指定问题，保存工具徽章、状态、最终回答和 DB 消息/结果证据；额外验证创建工单入库与重试不重复。页面按 Vibe Coding 做浏览器效果验证，不套独立代码评审。

最终交付 Docker/建表/种子/启动命令、浏览器入口和 curl 示例、测试报告、标注评估结果、预期漏召回记录，以及 dev-notes/ch02.md。后端按技能做 code review、修复和 finish。

## 自审与待批准项

草案覆盖五工具、四表、真实聊天链路与三个验收问题。明确了工具调用轮次、持久化与上下文的区别、写入幂等、FAQ 不做同义词扩展、演示数据边界及数据库环境阻塞处理。

请用户评审本草案，尤其确认“每条用户消息最多执行一个工具”的单轮解释。批准后按此前选择继续在当前会话编写计划、自审并实施，不再次询问已经选定的执行方式。

## 已查官方资料

- https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- https://docs.sqlalchemy.org/en/20/dialects/mysql.html
- https://docs.sqlalchemy.org/en/20/core/metadata.html
- https://reference.langchain.com/python/langchain-core/tools/convert/tool
- https://reference.langchain.com/python/langchain-openai/ChatOpenAI
- https://api-docs.deepseek.com/guides/tool_calls
- https://api-docs.deepseek.com/api/create-chat-completion
- https://github.com/docker/compose
- https://hub.docker.com/_/mysql

