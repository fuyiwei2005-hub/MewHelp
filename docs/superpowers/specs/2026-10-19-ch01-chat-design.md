# 第 1 章：电商客服纯对话设计

状态：用户于 2026-10-19 回复“批准”，设计定稿，进入实施计划阶段。

## 目标与范围

Python + FastAPI + LangChain，统一使用 OpenAI Chat Completions 协议直连上游。本次先验收 DeepSeek。地址、模型名、密钥及相关生成参数从本地 .env 加载。.env 排除版本跟踪，示例配置只含占位符。本章无工具调用、Agent 循环、数据库或检索。聊天页面不纳入本次三个接口验收目标；后续若制作页面按用户要求用 Vibe Coding。

## 架构选择

采用用户已选择的服务端内存会话方案：按 conversation_id 保存消息，单进程运行，重启清空。相较客户端提交历史，调用更简单；相较数据库持久化，符合本章最小范围。

拆为配置、Prompt 模板、模型接入、上下文预算、会话存储、HTTP 接口六个职责。模型接入使用 langchain-openai 的 ChatOpenAI，显式采用 Chat Completions；不依赖 LangGraph。

## 对话接口

POST /chat，请求包含 message 和可选 conversation_id。无 ID 时分配随机 ID；传未知 ID 返回 404，空消息等无效输入返回 422。同一会话只接受一个在途请求，冲突返回 409，不同会话可并行。

SSE 顺序：meta（conversation_id）、多个 token（text）、done（结束信息）。token 事件实时转发模型的非空内容片段，不缓存到回答完成后才发送；不保证上游一个片段等于一个 tokenizer token。连接期间需要支持心跳与取消。

请求前可判断的错误使用 HTTP 错误；已经开始流式响应后，上游超时或故障使用 error 事件并关闭流，不发送成功 done。客户端中断或模型输出被长度截断时不写入完整问答。只在完整成功时提交历史。错误信息不暴露密钥、认证头或原始异常请求内容。

内存会话配置空闲过期时间和最大会话数，默认分别为 30 分钟与 100；清理不影响在途会话，容量耗尽且无法回收时返回 503。客户端通过 meta 获取的新 ID 在失败后仍可重试，失败回合不进入历史。

## Prompt 与预算

使用 PromptTemplate 管理客服 System Prompt 和提取 Prompt。客服角色：中文电商客服，礼貌、简洁、先理解问题；信息不足时追问；不得虚构订单状态、物流、商品政策或声称已经退款/换货；只收集处理诉求所需的信息；用户消息不能覆盖系统约束。

每轮组成 system + 已完成历史 + 当前 user。先预留最大输出预算，再裁剪输入；保留系统提示和当前问题，历史按最旧完整问答对删除，不留下孤立 assistant。若只含系统与当前问题仍超过输入预算，返回 413，不静默截断当前问题。

跨上游 tokenizer 不统一，本章采用明确标注的保守 token 估算（UTF-8 字节长度加消息开销），配置预算与安全余量；不宣称是 DeepSeek 精确 token 计数。默认应用总预算 8192、输出预留 1024、安全余量 512。实际模型必须支持此窗口，配置阶段核实；历史提交后也受同一预算约束。

## 售后提取

POST /after-sales/extract，请求 description，响应固定字段：

```json
{"order_id":"DS20261019001","request_type":"换货","expected_solution":"换同款新的"}
```

order_id 和 expected_solution 为字符串或 null；request_type 固定为退款、退货退款、换货、维修、物流问题、其他、未知。缺失信息返回 null 或未知，不猜测。多个订单或多个诉求用样例界定：只提取首个明确订单和主要诉求；无法确定主要诉求时归其他，期望方案保留用户明确表达。

DeepSeek 显式使用 with_structured_output(PydanticSchema, method="json_mode")，在 Prompt 中给出 JSON 指令、字段说明和示例。JSON mode 只约束 JSON 语法，字段类型和枚举由本地 schema 校验。空内容、非法字段、截断输出均视为提取失败，返回 502；上游超时返回 504。不通过工具调用兜底，不自行切换模型或接入方式。提取不写入聊天历史。

## 模型可替换边界

统一协议配置允许替换 OpenAI 兼容端点；只有目标端点实际支持 Chat Completions 流式与所选结构化方式时才能通过本章验收。GPT、Claude、DeepSeek、Ollama 的具体兼容能力分别核实，不承诺任意模型仅更改名字即可具备相同能力。发现用户要求的直连接入与目标上游能力冲突时停下询问，不引入代理或替换技术栈。

DeepSeek 文档当前 Chat Completions 页列 deepseek-flash、deepseek-v4-pro，更新页仍出现 deepseek-v4-flash，旧别名也存在停用说明。配置时先读取认证的 /models 列表，以实际返回为准，优先选可用的 Flash 非思考模式；不自动使用 Pro 或推理模型替代。调用失败不得伪造验收成功。

## 验证与交付

可单测部分先写失败测试再实现：SSE 事件顺序与逐片段输出、两轮消息续接、会话隔离与并发冲突、预算裁剪和超长输入、断流及上游错误不污染历史、提取 schema 验证。使用受控模型替身验证应用边界，不能代替真实上游验收。

Prompt 用标注评估集验证，至少覆盖完整售后、缺订单、缺期望方案、退款与换货、多个订单、模糊诉求及提示注入。真实 DeepSeek 验证 curl 流式、连续两轮上下文和提取 JSON，并记录实际模型、结果和失败；不记录密钥。

交付启动说明、.env.example、三个目标的 curl 演示命令、自动化测试结果、Prompt 评估结果及 dev-notes/ch01.md。各阶段完成即追加日志，最终经过 code review 和修复验证后 finish。

## 文档依据（已通过 Context7 查询）

- https://fastapi.tiangolo.com/advanced/custom-response
- https://fastapi.tiangolo.com/reference/sse
- https://docs.langchain.com/oss/python/langchain/models
- https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI/with_structured_output
- https://reference.langchain.com/python/langchain-core/prompts/prompt/PromptTemplate/from_template
- https://reference.langchain.com/python/langchain-core/messages/utils/trim_messages
- https://api-docs.deepseek.com/api/create-chat-completion
- https://api-docs.deepseek.com/guides/json_mode
- https://api-docs.deepseek.com/api/list-models

自审：范围对应三个验收标准；显式 JSON mode 排除工具调用；区分估算预算与精确 token、上游片段与逐 token；设计尚未获得批准，不标记 brainstorm 定稿。
