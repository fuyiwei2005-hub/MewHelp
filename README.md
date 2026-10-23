# 电商智能客服 · 第 1 章

Python + FastAPI + LangChain，直连 OpenAI Chat Completions 兼容上游。支持多轮对话、SSE 实时文本片段、PromptTemplate 和 with_structured_output 售后提取。无工具调用、Agent 循环或数据库。

## 安装与启动（PowerShell）

在项目根目录运行：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
# 仅首次配置时复制；已有 .env 不要覆盖
Copy-Item .env.example .env
# 在本地编辑 .env，填写地址、实际模型 ID、密钥
.\.venv\Scripts\python.exe -m scripts.check_models
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
~~~

当前工作区已经配置了本地 .env。密钥不会出现在示例、测试或提交中。默认只监听本机；接口文档：[Swagger UI](http://127.0.0.1:8000/docs)。

## 聊天页面

服务启动后打开 [在线客服](http://127.0.0.1:8000/)。

左右消息气泡，SSE 到达后逐字显示；直接追问会延续当前会话。Enter 发送，Shift + Enter 换行；支持停止回复和开启新对话。刷新页面会开始新的本地聊天视图，服务重启后原会话清空。

页面与 API 同源，不需要单独启动前端，也不需要在浏览器配置模型密钥。支持手机布局，普通用户文本不作为 HTML 执行。

页面按用户指定走 Vibe Coding，浏览器实际验证见 [页面验收](docs/reports/ch01-web-validation.md)。

## curl 演示

另开 PowerShell，切换到项目根目录。用 UTF-8 文件传 JSON，避免 Windows 引号转义差异；使用 curl.exe 避免 PowerShell 同名别名。示例请求已在 examples/。

~~~powershell
curl.exe -N -H "Content-Type: application/json" --data-binary "@examples/chat-first.json" http://127.0.0.1:8000/chat
~~~

首个 meta 事件包含 conversation_id，把它填入 examples/chat-second.json 后执行：

~~~powershell
curl.exe -N -H "Content-Type: application/json" --data-binary "@examples/chat-second.json" http://127.0.0.1:8000/chat
curl.exe -H "Content-Type: application/json" --data-binary "@examples/after-sales.json" http://127.0.0.1:8000/after-sales/extract
~~~

售后示例返回：

~~~json
{"order_id":"DS20261019001","request_type":"换货","expected_solution":"换同款新的"}
~~~

一条命令自动完成流式、连续两轮与提取三项验收：

~~~powershell
.\.venv\Scripts\python.exe -m scripts.acceptance --show-stream
~~~

## 接口行为

POST /chat 请求：

~~~json
{"message":"你好","conversation_id":null}
~~~

无 ID 创建会话，续聊带上相同 ID。SSE 顺序为 meta、多个 token、done；失败为 error，等待期间有心跳。示例：

~~~text
event: meta
data: {"conversation_id":"..."}

event: token
data: {"text":"您好"}

event: done
data: {"finish_reason":"stop","conversation_id":"...","input_tokens_estimate":100,"token_count_method":"utf8_bytes_conservative"}
~~~

token 事件即时转发上游文本片段，一个片段可能包含多个 tokenizer token；不在回答完成后切字模拟流式。客户端按 SSE 空行划分事件，不能假设一次网络读取等于一个事件。

POST /after-sales/extract 请求：

~~~json
{"description":"想退款"}
~~~

固定返回 order_id、request_type、expected_solution。缺失信息用 null / 未知；诉求限定为退款、退货退款、换货、维修、物流问题、其他、未知。多订单取首个明确订单，无主次多诉求归其他。JSON mode 约束 JSON 语法，Pydantic 再校验字段；语义正确性通过标注集评估。

输入无效 422，会话未知/过期 404，同会话忙碌 409，超预算 413，会话满且无可回收项 503。提取上游错误为 502、超时为 504。流开始后的错误使用 SSE error，HTTP 可能仍为 200。失败、中断、截断、空回答不进入历史。

## 配置和边界

| 环境变量 | 用途 / 默认 |
| --- | --- |
| LLM_BASE_URL | 上游兼容 API 根地址 |
| LLM_MODEL | 上游实际模型 ID |
| LLM_API_KEY | 本地密钥 |
| LLM_STRUCTURED_METHOD | json_mode；可选 json_schema，需上游支持 |
| LLM_REASONING_EFFORT | 可选；DeepSeek 本次用 none，不支持则留空 |
| LLM_TIMEOUT_SECONDS | 60；整轮时限及上游请求超时 |
| TOKEN_BUDGET | 8192 |
| MAX_OUTPUT_TOKENS | 1024；从总预算预留 |
| TOKEN_MARGIN | 512 |
| MAX_SESSIONS | 100 |
| SESSION_TTL_SECONDS | 1800 |
| HEARTBEAT_SECONDS | 15 |

内存保存会话，必须单进程，重启清空。满额回收最旧空闲会话，不回收正在生成的会话。TTL 按新请求触发清理，空间另受会话数和历史预算限制。

历史优先删最旧完整问答，保留 system 和当前问题。使用 UTF-8 字节加消息开销的保守估算，**不是 DeepSeek 精确 tokenizer**；当前问题过长则拒绝，不静默截断。

接入固定 use_responses_api=False。替换 GPT、Claude、DeepSeek 或 Ollama 时，需要目标官方直连端点支持 OpenAI Chat Completions、流式和选定 JSON 模式。当前只真实验收 DeepSeek，不能承诺所有厂商仅换模型名就兼容，也未引入转发代理。能力冲突需先确认接入方案。

## 测试与过程

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp artifacts/pytest
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m scripts.evaluate
~~~

测试包含真实本地 socket 的增量到达与断流关闭检查；受控 HTTP 响应用于验证实际模型适配层载荷。评估会调用真实模型；生成的 artifacts/prompt-evaluation.json 需要按标注逐例核对语义，脚本不会自动宣称语义通过。

- 设计：[design](docs/superpowers/specs/2026-10-19-ch01-chat-design.md)
- 计划：[plan](docs/superpowers/plans/2026-10-19-ch01-chat.md)
- 实际验证：[validation](docs/reports/ch01-validation.md)
- Prompt 逐例结果：[evaluation](docs/reports/ch01-prompt-evaluation.json)
- 开发过程：[dev-notes](dev-notes/ch01.md)

本章为本地功能验收原型，部署、多进程持久化、用户鉴权和真实订单操作不在本章范围。


## 第二、三章：数据库、工具和知识库

第二章浏览器入口仍为 http://127.0.0.1:8000/ ，工具状态和工具徽章随 SSE 更新。数据库路径保存完整 user/assistant/tool 消息；仅已完成回合进入上下文，工具结果与申请通过 tool_call_id 对齐。请保持单 worker。

~~~powershell
docker compose up -d
.\.venv\Scripts\python -m scripts.init_db
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

.env 的 DATABASE_URL 使用 mysql+asyncmy；MySQL 在本机 3307。FAQ_BACKEND=keyword 可重现第二章基线：退货政策命中，邮费未命中。订单/商品/物流为随机演示数据，人工工单真实写 MySQL。

第三章使用相同聊天接口及 query_faq 契约，仅替换工具内部检索实现。先下载 BAAI/bge-m3 官方权重（脚本完成后把模型提交号写入本地 .env），启动 Milvus 和本地嵌入服务，再建库：

~~~powershell
docker compose -f compose.milvus.yaml up -d
.\.venv\Scripts\python -m scripts.download_model
.\.venv\Scripts\python -m uvicorn app.embedding_server:app --host 127.0.0.1 --port 8001
# 另一个终端：
.\.venv\Scripts\python -m scripts.ingest_knowledge
.\.venv\Scripts\python -m scripts.acceptance_knowledge
~~~

在 .env 设置 FAQ_BACKEND=dense 后重启聊天服务；浏览器问“邮费是多少”。Milvus 仅 dense COSINE Top-K；MySQL 回查原文及 hash/状态，服务故障不退回 LIKE。embedding_text 只包含 category、questions、answer。原文、元数据、向量同步状态存 knowledge_chunks。

恢复演示：先修改knowledge目录中的一份Markdown内容，产生新的待向量化块，再故意在Milvus写成功、MySQL回填之前中断，随后原命令重跑；按chunk主键覆盖向量并补齐回填。没有待处理块时不会触发该中断点。

~~~powershell
.\.venv\Scripts\python -m scripts.ingest_knowledge --failpoint after_milvus_upsert
.\.venv\Scripts\python -m scripts.ingest_knowledge
.\.venv\Scripts\python -m scripts.acceptance_knowledge
~~~

合成客服对话挖掘示例（只发送固定白名单种子给配置的模型，--no-sync 先留待向量化）：

~~~powershell
.\.venv\Scripts\python -m scripts.mine_knowledge --demo-only --no-sync --batch-size 1
.\.venv\Scripts\python -m scripts.mine_knowledge --demo-only --no-sync --show-schedule
# 持续运行，每天上海时间02:00，单实例与数据库锁：
.\.venv\Scripts\python -m scripts.mine_knowledge --demo-only --watch
~~~

省略 --demo-only 会处理全量已完成历史，并发送给 .env 的模型供应商；本次尚未执行该模式。定时进程需保持运行。暂存表 knowledge_staging 保存证据和去重状态，knowledge_jobs 保存快照及游标。冲突问答隔离处理，不覆盖既有答案。

过程记录：dev-notes/ch02.md、dev-notes/ch03.md。第三章真实依赖验收状态以 docs/reports/ch03-validation.md 为准。


第三章实际验收：78项测试通过、依赖检查通过；两个故障点恢复成功，最终pending为0；真实浏览器两轮及curl流式通过。BGE-M3当前使用CPU，检索阈值0.65由6条独立标注小样本校准。Milvus本机端口19531，健康检查19091。

~~~powershell
.\.venv\Scripts\python -m scripts.acceptance_tools --backend dense
.\.venv\Scripts\python -m scripts.evaluate_knowledge
.\.venv\Scripts\python -m scripts.evaluate_mining
~~~

完整交付与故障恢复证据见 docs/reports/ch03-validation.md。

## 第四章：混合检索、重排和评估

本机端口已改为聊天18000、嵌入18001、重排18002（Windows保留了旧端口段）。MySQL3307、Milvus19531不变。启动三个服务时分别保持终端运行：

~~~powershell
docker compose up -d
docker compose -f compose.milvus.yaml up -d
.\.venv\Scripts\python -m scripts.download_reranker
.\.venv\Scripts\python -m uvicorn app.embedding_server:app --host 127.0.0.1 --port 18001
# 第二个终端，官方权重下载完成后：
.\.venv\Scripts\python -m uvicorn app.reranker_server:app --host 127.0.0.1 --port 18002
# 第三个终端：
.\.venv\Scripts\python -m scripts.prepare_ch04
.\.venv\Scripts\python -m scripts.calibrate_hybrid --apply
# 在.env设FAQ_BACKEND=hybrid，然后启动聊天服务
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
~~~

下载脚本固定官方revision并生成哈希manifest；嵌入模型仍用第三章已下载的BGE-M3。重排使用bge-reranker-v2-m3，CPU也可运行，但首次加载与每轮处理较慢。四章集合knowledge_hybrid_v4独立于旧dense集合；新增同步台账保证旧embedded记录也能迁移。品类白名单过滤在Milvus两路检索前执行，选择品类同时包含通用知识。

浏览器打开 http://127.0.0.1:18000/ ，选择陶瓷杯，问“QC-M100支持洗碗机清洗吗？”；再问“邮费是多少？”；问“火星配送费用是多少？”验证证据不足拒答。点击[1]查看当轮原文快照和章节路径；👍/👎仅在浏览器本地保存并锁定，没有后端反馈写入。

~~~powershell
curl.exe -N -H "Content-Type: application/json" --data-binary "@evals/ch04-chat-demo.json" http://127.0.0.1:18000/chat
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pip check
.\.venv\Scripts\python -m scripts.evaluate_hybrid --output docs/reports/ch04-comparison
~~~

四策略各在相同30条测试题上运行，另12条校准题独立（含6条通用政策题）；固定语料63个商品章节。报告包含Recall@10/50、MRR@10、原子声明Faithfulness、回答覆盖率、拒答率、错误与逐桶结果。拒答不计Faithfulness满分，判定失败保留。断点续跑要求相同语料、品类、索引状态、预算、模型和实现版本；变化时另给--output。保留早期失败报告作为返工证据，不当作最终报告。

知识回答按引用单元验证后输出原始模型片段；不合法或无引用事实不发送，因此首段会等待一个完整引用单元。先进行证据充分性自评，最终实际payload超预算则整块裁掉低排名证据并重新自评；不足时拒答并写low_confidence_questions，原文/会话/入口/原因/时间可追查。真实验收数字与限制见docs/reports/ch04-validation.md，阶段记录dev-notes/ch04.md。


## 第五、六章：持久化Workflow与正式分流

先运行第二至四章的MySQL、Milvus、BGE-M3（18001）、bge-reranker-v2-m3（18002）并完成既有索引，`.env`使用`FAQ_BACKEND=hybrid`。新增检查点配置见`.env.example`，密码与连接串必须一致。业务记录仍在MySQL，独立PostgreSQL仅保存LangGraph检查点及同会话锁。

```powershell
docker compose -f compose.checkpoint.yaml up -d
.\.venv\Scripts\python -m scripts.init_workflow
.\.venv\Scripts\python -m scripts.serve_workflow --port 18000
```

Windows使用上述专用启动器，确保psycopg异步使用Selector事件循环。Compose默认官方`postgres:16-alpine`；本机下载缓慢，实际验收用已缓存的`CHECKPOINT_IMAGE=pgvector/pgvector:pg16`创建全新独立实例与卷，只使用PostgreSQL16，不启用扩展或连接其他项目实例。旧的一轮Function Calling模式仍可通过原`app.main:app`入口回归，专用Workflow启动器会显式开启新流程。

```powershell
# 祛魅：不使用LangGraph的Python裸循环
.\.venv\Scripts\python -m scripts.bare_agent
# 实际SSE：物流、强制政策检索、多步ReAct、投诉选择、退款选单
curl.exe -N -H "Content-Type: application/json" --data-binary "@evals/ch05-logistics.json" http://127.0.0.1:18000/chat
curl.exe -N -H "Content-Type: application/json" --data-binary "@evals/ch05-policy.json" http://127.0.0.1:18000/chat
curl.exe -N -H "Content-Type: application/json" --data-binary "@evals/ch05-complex.json" http://127.0.0.1:18000/chat
curl.exe -N -H "Content-Type: application/json" --data-binary "@evals/ch05-complaint.json" http://127.0.0.1:18000/chat
curl.exe -N -H "Content-Type: application/json" --data-binary "@evals/ch06-refund.json" http://127.0.0.1:18000/chat
# 真实整体验收与正式意图/指代标注评估
.\.venv\Scripts\python -m scripts.acceptance_workflow --base-url http://127.0.0.1:18000
.\.venv\Scripts\python -m scripts.evaluate_router
.\.venv\Scripts\python -m pytest -q --basetemp artifacts/pytest-delivery
.\.venv\Scripts\python -m pip check
```

浏览器打开`http://127.0.0.1:18000`。问“我要投诉”，两个按钮分别操作；“转人工”仅前端模拟客服小猫，“建工单”确认后才调用原工具。问“这个能退吗”，点击演示订单卡片继续流程，退款原因从下拉选；退款申请只写本地演示记录，不执行真实退款。不点击按钮可继续聊天，新消息使旧订单选择过期；刷新页面会从检查点恢复当前待选卡片。

当前只支持演示用户`demo-user`和1001/1002/1003三张演示订单，尚不包含真实身份认证/订单API/付款退款/真人坐席。新喵喵优选知识资料仍暂存，未混入当前演示知识；用户待补章节不影响本章流程验收。证据缺失仍会拒答；小样本闸评估保留“已使用15天”保守拒答误差。阶段记录见`dev-notes/ch05.md`、`dev-notes/ch06.md`，真实验收与限制见`docs/reports/ch05-validation.md`、`docs/reports/ch06-validation.md`。


## 第七章：会话内三层上下文与多会话页面

沿用第五六章Workflow启动器、现有MySQL与独立PostgreSQL。启动时会幂等补充双锚点字段、会话摘要和持久化任务表；也可单独迁移。完整State.messages保存在官方checkpointer，用户/客服原文和工具结果标识投影到MySQL；模型只拿独立的三层视图。投诉按钮确认动作另存同一checkpointer的actions线程，避免更改正在等待订单选择的主图游标，下一普通轮合入主State。

```powershell
.\.venv\Scripts\python -m scripts.init_memory
.\.venv\Scripts\python -m scripts.serve_workflow --port 18000
# 浏览器打开 http://127.0.0.1:18000 ，开启两次新对话，再从左侧切回续聊
curl.exe http://127.0.0.1:18000/api/conversations
curl.exe "http://127.0.0.1:18000/api/conversations/替换为会话ID/messages?limit=100"
# 真实标注摘要评估 / 默认24轮
.\.venv\Scripts\python -m scripts.evaluate_summary
.\.venv\Scripts\python -m scripts.acceptance_memory --profile default --output docs/reports/ch07-default-24.json
```

演示配置在单独终端启动，不改默认服务的环境；本机端口18004：

```powershell
$env:MODEL_CONTEXT_WINDOW='18000'
$env:MAX_OUTPUT_TOKENS='2000'
$env:MAX_USER_INPUT_TOKENS='2000'
$env:MAX_AGENT_STEPS='3'
$env:TOOL_RESULT_MAX_TOKENS='1200'
$env:RERANK_TOP_K='5'
$env:CONTEXT_LOG_PATH='log/ch07-demo.log'
.\.venv\Scripts\python -m scripts.serve_workflow --port 18004
# 另一终端
.\.venv\Scripts\python -m scripts.acceptance_memory --profile demo --base-url http://127.0.0.1:18004 --log log/ch07-demo.log --output docs/reports/ch07-demo-24.json
```

上述基线按1050固定前缀、5×250证据、1000摘要、2000输出、1000安全余量、2000当前输入、3×(1200工具结果+150参数)倒推：历史5650、层1为3954、层2为1695，保留1token保护。实际前缀或追加摘要超预留会重新扣减。默认128000窗口下历史目标上限64000，装得下不压缩。CJK按1字约1token、ASCII约4字1token统一核算；日志token_calibration记录上游真实用量，改计数系数时须连同稳态/预留重新校准。声明窗口应由部署者对照实际模型能力配置。

```powershell
Select-String -Path log/app.log -Pattern 'model_ctx|history_ctx|summary|layer1_degrade'
.\.venv\Scripts\python -m pytest -q --basetemp artifacts/pytest-ch07-final
.\.venv\Scripts\python -m pip check
```

摘要只追加新段，旧段作为背景不再压缩；任务读冻结checkpoint、LLM在事务外执行，失效租约不能提交。失败/取消轮保留原文但不参与后续模型历史；合法大回合按实际摘要模型窗口处理，不设4000token硬拒绝。超预算工具原文留checkpoint元数据，模型只收到结构化超限结果，摘要不会把未展示的原文当成已确认事实。

侧栏列出当前demo-user全部会话，新对话不删旧会话；切换/刷新从只读接口分页回载完整原文并恢复待选订单。列表失败静默降级。仍无跨会话记忆、画像、真实认证或真实客服系统接入。第八章接入见下节，第九章待独立设计。阶段过程见dev-notes/ch07.md，完整实测结果见docs/reports/ch07-validation.md。


## 第八章：统一工具与MCP

安装依赖后在三个终端分别启动；沿用现有MySQL/PostgreSQL和知识库服务：

~~~powershell
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m scripts.serve_mcp --server logistics --plugin-file mcp_servers/delivery_eta_plugin.py
.\.venv\Scripts\python -m scripts.serve_mcp --server aftersales
.\.venv\Scripts\python -m scripts.serve_workflow --port 18000
~~~

打开 http://127.0.0.1:18000 ，问“演示订单1001的物流到哪了”“演示订单1001还在保吗”，气泡工具徽章分别显示物流、售后MCP来源。工具返回随机演示数据，不连接真实业务系统。

问“帮我建工单”会先追问描述；补充“演示饮水机不出水”后出现预览。确认才写tickets并返回工单号；取消不写tickets，审计为权限拒绝。也可以不点卡片继续聊天，旧卡片失效。原投诉流程的转人工、建工单两个按钮独立保留。

本地可信扩展示例为app/tool_plugins/order_note.py，只在config/tool-plugins.json登记模块并在config/tool-policy.json授权builtin:query_order_note为read；下一轮即发现，不改Agent代码、不重启客服。当前演示已登记，可问“演示订单1001的订单备注是什么”。不要把不可信Python代码放进此目录。

MCP热发现演示：先不带--plugin-file启动物流，随后仅停掉该物流进程，再带上述--plugin-file重启；客服进程保持不动。下一轮问“演示订单1001预计还要几天送到”，会调用新发现的query_delivery_eta。该工具已在本地权限表预授权；外部Server声明不会自动获得授权。未知工具默认拒绝，外部MCP写工具禁用。

~~~powershell
.\.venv\Scripts\python -m scripts.acceptance_ticket --base-url http://127.0.0.1:18000 --output docs/reports/ch08-ticket-live.json
.\.venv\Scripts\python -m scripts.acceptance_workflow --base-url http://127.0.0.1:18000 --output docs/reports/ch08-workflow-regression.json
.\.venv\Scripts\python -m scripts.evaluate_ticket_intent
.\.venv\Scripts\python -m pytest -q --basetemp artifacts/pytest-ch08-delivery
.\.venv\Scripts\python -m pytest tests/test_tool_mcp.py tests/test_tool_audit.py tests/test_tool_engine.py -q --basetemp artifacts/pytest-ch08-faults
.\.venv\Scripts\python -m pip check
~~~

工具审计写入tool_audit_logs，无外键；参数错误、权限拒绝、网络重试和超时均记录。读工具只重试暂时故障，空结果不重试；写工具默认一次，不因超时重复执行。工单预览冻结参数、会话、轮次、调用ID，服务端确认后才签发执行许可；断线后的不确定结果先查已有工单，不能盲重试。审计失败只记录告警。

每轮发现有4秒每Server上限，故障Server本轮移除、其他Server继续；JSON Schema和权限表均以服务端可信配置为准。新增工具会重新核算模型固定前缀，工具清单无限扩大仍可能触发上下文预算不足。当前仍是demo-user演示，不含身份认证或真实物流、坐席。

结果及限制见docs/reports/ch08-validation.md，阶段留痕见dev-notes/ch08.md。
