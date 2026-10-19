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

