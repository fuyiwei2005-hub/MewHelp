# 第七章：当前会话三层上下文设计

日期：2026-10-22。状态：用户于2026-10-22回复“批准”，完整设计获批。

## 1. 范围与已确认事项

本章先于第八章工具系统、第九章可观测飞轮实施，三章分别设计、计划、评审和验收。本章只当前conversation，不做跨会话记忆、画像、语义历史检索、主题重要度选取。延用FastAPI、LangChain、LangGraph、MySQL及现有官方AsyncPostgresSaver，不增加任务队列组件。

用户已确认：MySQL只保留工具调用与结果标识，完整工具结果保留LangGraph checkpoint；旧数据不删除。前几章的工单、选单、引用、满意度交互继续工作。

预算明细已经用户确认，见第5节；完整方案已获批准，进入实施计划与TDD。

## 2. 方案选择

推荐A：统一ContextManager负责模型视图、边界与token核算；MySQL持久化摘要工作项，FastAPI lifespan维护普通异步worker，执行追加式摘要。入口清晰，摘要模型调用可独立测试/评估，前台图仍处理客服业务。

可选B：同样的ContextManager、表和边界，worker内再运行一个独立LangGraph摘要图。适合未来摘要有多路校验/人工分支的场景，本章会多出一套图状态与checkpoint管理。

拟采用A。后台任务不放进当前请求必须await完成的图节点；不靠响应结束时的同步摘要才能推进前台。

## 3. 完整消息、MySQL投影与ID

WorkflowState新增messages，使用Annotated[list[AnyMessage], add_messages]。消息ID稳定；每个节点只返回新产生的消息，不再手动拼回全部history/turn_messages。完整messages由原有PostgreSQL checkpointer保存。裁剪和规则压缩只生成临时model_view，禁止把该视图、RemoveMessage或删除历史操作写回messages。

MySQL messages仍是用户/客服可回载的逐条原文流水：user、assistant正文完整；tool行只有工具名、tool_call_id、结果状态/定位标识，绝不复制完整工具payload。完整工具payload仅在checkpoint。新增message_key唯一键用于重跑幂等，原数值主键id作为两个边界的引用；LangGraph消息id与数值主键建立稳定映射。写入节点消息时先做幂等轻量投影得到id，再返回原文消息给reducer，工具投影与checkpoint消息共用ID但content按各自职责保存。

新消息按实际对话协议顺序写入。历史迁移从MySQL完整已完成回合补齐旧checkpoint中曾被裁掉的部分；旧tool原文保持原数据，迁移后新写入才使用轻量投影。遇到旧工单工具结果记录早于申请记录的回合，在模型视图按tool_call_id修复配对，原库记录不重排。旧checkpoint迁移幂等，保留原数据以便恢复。

失败/取消回合仍留审计原文，但不作为后续有效对话历史；State另记回合状态，过滤不会删除完整messages。选单恢复、工单确认和重复HTTP请求不得重复追加相同ID。

conversations增summary_upto_msg_id（摘要已覆盖的最后一条，初始0）、layer1_from_msg_id（最近原文层起点，初始为空）、context_version。按完整回合边界移动，两字段不允许倒退或跨越所属会话。

## 4. 三层划分

- 最远层：id <= summary_upto_msg_id，原文仍在原表/checkpoint，模型使用单独摘要表里一段段梗概。
- 中间层：summary_upto_msg_id < id < layer1_from_msg_id。用户原话完整；客服自然语言只留前60个Unicode字符；工具结果变为一行带工具名、调用ID和状态的标识。保留调用/结果配对，不能产生孤立ToolMessage。
- 最近层：id >= layer1_from_msg_id的已完成回合，逐条原文，正文和工具消息不做有损改写。

降级只前移layer1_from_msg_id，不移动、删除或覆写原始消息。层1超额时按最老完整回合降级到层2，按实际token占用触发，日志写明边界X→Y、前后用量。

层1/层2的70/30是正常配额；单个最近完整回合超过层1但仍能装入总历史预算时，可临时占用层2空余额保住原文，明确记录借用。单回合超过整个可用历史预算时不截半轮、不冒充完整，记录预算不足并返回可读提示。默认/演示验收语料均校验每个回合可容纳，不用计数阈值冒充token阈值。

摘要尚未完成导致层2暂时超额时，前台不等待LLM；从本次模型视图按整轮做最后安全裁剪，记录暂时未注入范围，原文和摘要边界不变。后台成功后下一轮重新载入新摘要。旧摘要生成失败不能推进summary_upto。

## 5. 统一预算与中文计数

新配置MODEL_CONTEXT_WINDOW描述当前部署已核准的模型窗口；不根据模型名猜测。默认应用profile拟为128000，启用前用当前上游配置核对，超出上游能力需显式调整，不能把应用声明当成供应商能力。

历史预算：

H = min(HISTORY_TARGET_TURNS × STEADY_ROUND_TOKENS,
        MODEL_CONTEXT_WINDOW − Prefix − Evidence − Summary − Output − Safety − CurrentUser − ReActPeak)

Prefix=max(固定前缀预留, 实际固定system及工具Schema估算)。Evidence按RERANK_TOP_K与每块上限计算并在构造证据时落实。Summary=max(摘要预留, 本轮实际注入全部历史摘要估算)，摘要增长后重新核算；不为了维持旧预算回头合并老摘要。ReActPeak=MAX_AGENT_STEPS×(TOOL_RESULT_MAX_TOKENS+TOOL_CALL_MAX_TOKENS)，当前用户和最终输出分别预留，不在峰值重复扣除。每次调用还必须按实际序列化payload再检查窗口。

拟默认HISTORY_TARGET_TURNS=32、STEADY_ROUND_TOKENS=2000作为可配置稳态规划值，接受实际会话统计和标注样例校准；它不是按条数决定压缩。默认profile的目标历史预算64000，不足部分由真实窗口决定。MAX_AGENT_STEPS替代/兼容旧AGENT_MAX_STEPS；MODEL_CONTEXT_WINDOW与旧TOKEN_BUDGET在Workflow和旧模式的边界明确，禁止静默叠加两套限制。RERANK_TOP_K是最终证据数量上限，原生两路各Top50保持第四章约定。

### 用户已确认的演示profile

| 项 | token预留 |
|---|---:|
| MODEL_CONTEXT_WINDOW | 18000 |
| 固定system+工具前缀 | 1050 |
| 证据：RERANK_TOP_K=5，每块250 | 1250 |
| 摘要预留 | 1000 |
| MAX_OUTPUT_TOKENS | 2000 |
| 安全余量 | 1000 |
| MAX_USER_INPUT_TOKENS | 2000 |
| 峰值：MAX_AGENT_STEPS=3 × (TOOL_RESULT_MAX_TOKENS=1200 + TOOL_CALL_MAX_TOKENS=150) | 4050 |
| 剩余历史H | 5650 |

HISTORY_TARGET_TURNS×STEADY_ROUND_TOKENS在演示配置下大于5650，因此由窗口余量决定。正常分配保守留1 token拼装保护：层2=floor(H×0.3)=1695，层1=H−层2−1=3954。不依赖浮点0.7的偶然舍入。

以上是用户同意的规划上限，不是伪造的实际测量。启动核验实际前缀和规划的一轮稳态是否能装入；前缀超预留必须重算并报警，历史不够一轮则启动自检失败，不带病发上游。摘要实际增长或单轮实际超限也须调用前拒绝/安全裁剪，不靠上游报错兜底。

中文按可校准的CJK字符系数、ASCII字符系数和消息/工具协议开销统一估算，替换旧“UTF-8字节即token”口径。初始CJK按1 token/字、ASCII按约4字符/token作保守规划，使用真实上游prompt_tokens做校准并保留误差；系数变化后全部固定成本、稳态、分层用量和窗口自检同口径重算。演示预算数字依赖前缀实际不超过1050，Prompt精简须用标注评估验证，不能只调系数凑数。

工具单次回灌上限是执行契约：超过上限不截成非法JSON，返回明确结果超限错误；原始工具payload留checkpoint元数据。层1保留实际回灌消息原文。当前轮ReAct消息按真实协议追加并全部计入峰值，不参与历史摘要。

## 6. 模型输入固定顺序和前缀

使用一份冻结的Agent system：客服角色、业务红线、来源为数据、决策/最终生成规则都写在常量中。工具定义按稳定顺序附加，每轮相同。当前意图、证据、订单、disposition、phase等全部移到可变尾部，不再字符串拼进system。路由约束由执行侧校验，不通过每轮删工具Schema破坏前缀。

模型实际输入顺序：

1. 固定system及固定工具定义。
2. 中间层规则压缩后的完整回合。
3. 最近层原文完整回合。
4. 当前用户原话。
5. 一条非system背景消息：全部早期摘要段、当轮RAG证据及来源、当前订单事实/执行阶段；明确内容是数据而非指令。
6. 当前轮已经产生的ReAct申请/工具结果等瞬时消息，保持合法配对。

早期摘要不能单独占system；背景消息严格挂在当前用户原话之后。决策和最终生成复用同一固定前缀，以尾部phase及tool_choice约束不同阶段，不将历史事实混入固定前缀。

历史层用LangChain trim_messages(strategy=last, allow_partial=False, 自定义统一token_counter)生成临时视图；按完整回合与工具调用配对再校验，禁止只留下半个工具协议。

HistoryContext供指代消解与意图识别共用：摘要段+同一滑窗视图；白名单闲聊也创建并记录该视图，但依旧不调用模型。指代守卫只允许当前会话真实原话、工具事实、经源消息校验的摘要实体，不把摘要推测的新订单号当可信事实。

## 7. 追加式异步摘要

conversation_summaries单独存成功段落：id、conversation_id、段序号、from_msg_id、upto_msg_id、摘要全文、来源checkpoint_id、创建时间，覆盖范围唯一。旧段不可更新/合并。摘要目标约50—200中文字；不为凑长度漏掉唯一订单/手机号/明确诉求。

conversation_summary_jobs存工作项：会话、覆盖范围、来源checkpoint_id、状态pending/running/completed/failed、lease截止、尝试次数、耗时/错误和时间。这里不存完整工具结果，worker按固定checkpoint读取原文。MySQL写摘要和推进边界在同一短事务提交。

触发判断层2规则视图的实际token > 层2预算；同会话只允许一个有效任务。前台只做入队和轻量落单，不await摘要模型。worker使用自己的AsyncSession，模型调用期间不持有数据库事务或前台会话锁。

任务冻结当时layer1起点；覆盖到该起点前最后一条完整回合消息，不覆盖正在回复或层1消息。原文批次过大时按摘要模型输入预算拆成若干不重叠批次，各自产生新段，最终追到冻结目标。旧摘要仅作为背景，不作为本次要被摘要的源材料。每次仅压缩一次原始批次。

摘要Prompt只提炼事实和诉求：问过的商品/型号、用户报过的订单/手机号、明确诉求、未解决问题及已发生的处理结果，忽略寒暄；不推断退货资格、履约承诺、未给出的数字。输出携带源消息ID和事实引用供校验，再保存自然语言段。数字/实体不在源消息中或格式不完整就失败、不推进边界，Prompt使用标注样例评估代替纯Prompt单测。

提交时锁会话行检查旧summary_upto/context_version：已有覆盖或过期任务跳过，前台已推进更远的layer1边界不能被worker回退；本次只推进自己覆盖到的summary_upto。后台不调用主图aupdate_state改写正在处理的State，下轮prepare读取新摘要/边界快照进入State。

应用重启恢复pending和租约过期running任务；相同覆盖范围不重复追加段。正常关机有限时优雅取消，未提交段保持可重试。失败任务有限次数重试，失败不会删除原文或阻塞前台。

## 8. 实际上下文日志

UTF-8追加JSON行写log/app.log。每条带事件、会话、turn、调用阶段、时间、边界、窗口消息数、各层tokens和总估算。

history_ctx：每轮必打，包含实际共用的完整摘要行、滑窗逐条消息和预算。指代/意图模型实际调用也记录各自完整request，能核对共用历史内容；固定白名单轮有history_ctx并标明模型未调用。

model_ctx：Agent每次决策和最终生成前，记录完整实际messages、固定工具Schema、摘要全文、各层来源/条数、tokens估算和窗口余量；不使用截断repr冒充完整payload，不记录密钥和Authorization配置。

summary trigger/start/done/skip/failed：包含覆盖from/upto、来源checkpoint、段序号、层2用量与预算、耗时及原因。层1降级记录X→Y；示例可直接rg或Select-String检索model_ctx/history_ctx/summary。

日志原样记录会话内容是本次明确授权的可观测要求。日志轮转、保留周期可配置，不写入Git；不会顺带把内容上传外部观测平台，第九章另做自部署Langfuse。

## 9. 多会话接口和页面

GET /api/conversations：按当前demo-user过滤，创建时间倒序；返回id、首问预览、创建时间、是否已有成功摘要、当前待办状态。分页拉取到全部，不用更改其他用户归属作为会话切换。

GET /api/conversations/{id}/messages：先检查归属；返回用户/客服原文、工具调用和轻量结果标识、turn_id、完成状态、引用和动作回执信息，按协议完整回合组织，分页完整回载。API只读，不触发摘要或业务操作。

侧栏新增会话列表和“已摘要”标记，新对话仅切换为空白会话，首次发送时沿用现有懒创建；旧会话保留在服务器和侧栏。切换回载原文，恢复conversation_id、引用、反馈锁定和当前待选订单。发送中禁切换，避免把流写到另一会话。侧栏加载失败静默降级，当前会话继续正常聊天；消息加载失败不清空已显示内容。

前端保持原生HTML/CSS/JavaScript，侧栏和切换按浏览器效果验证；不进行无关页面重做。后端接口和权限/分页按TDD验证。

## 10. 迁移、验证与交付

显式幂等迁移现有conversations/messages：create_all不会补已有表的列。新增摘要/任务表；给旧消息回填稳定message_key，旧消息不删除。开发/测试数据库与当前业务库隔离，checkpoint兼容迁移在读旧会话时触发并记录。

后端TDD：reducer只追加/更新同ID、不丢完整历史；合法工具协议；中文统一预算、演示5650/3954/1695；边界单调、整轮降级；并发摘要/重启/CAS/租约/重复段；超时不阻塞当前回复；每轮日志与实际payload一致；两只读API的归属和完整回载。

Prompt/数据评估：有源事实与禁编事实的摘要样例，覆盖订单/手机号/诉求/未解决、寒暄不留、旧摘要不再次压缩、数字/否定保留；固定前缀变更用Agent/引用/指代标注样例复验。

真实验收分别独立会话：默认profile连续至少24轮，不能出现降级或摘要；演示profile至少24轮，用token实际用量引发层1降级、层2超额、后台追加新段，记录该轮SSE与任务时间证明未await摘要。看到summary done后问最早订单后续情况，核对原始订单号与诉求；两种profile不得共用被污染的边界。测试只统计同会话日志。

真实浏览器多开会话、切换完整原文、继续对话、已摘要标记、引用/反馈/待选订单以及侧栏错误静默降级。完成独立后端review并修复Important，运行旧137项与新增回归，交付演示命令、完整结果/局限、dev-notes/ch07.md。按此前偏好保留本地分支，不合并/推送。

## 11. 官方文档依据与自审

- Context7 /websites/langchain_oss_python_langgraph：add_messages按ID追加/替换、AnyMessage序列化；模型前裁剪不等于删除checkpoint消息。
- Context7 /websites/reference_langchain：trim_messages自定义token_counter、allow_partial=False及合法起止/工具配对要求，已核对安装版本签名。
- Context7 /websites/sqlalchemy_en_20：AsyncSession每个并发任务独享，事务和锁不能跨摘要LLM等待。
- Context7 /websites/fastapi_tiangolo：lifespan管理启动/关闭，BackgroundTasks运行在响应后；本章使用lifespan worker和持久化工作项以支持后台并发与恢复。

自审：两个已确认选择落实；未把预留当测量；两个锚点区间无重叠；原文/轻量投影/模型视图分离；后台只提交自己的覆盖边界；前台不等摘要；没有新增外部组件、跨会话画像或语义记忆。超长单轮及后台滞后时的安全降级明确留痕，尚未实施代码，也未宣布验收通过。
