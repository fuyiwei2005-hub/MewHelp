# 第七章 Context Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. 用户沿用当前会话内执行与本地分支偏好。后端独立review再使用reviewer，前端按Vibe例外。

**Goal:** 当前会话完整历史经checkpoint保留，模型使用双锚点三层视图，异步追加摘要，页面能切换并回载所有会话。
**Architecture:** app/memory分别承载计数预算、分层/拼装、MySQL投影与摘要工作项、后台worker及只读API；Workflow节点仅输出新messages，ContextManager在prepare冻结本轮视图。后台使用固定checkpoint快照，模型调用在事务外，摘要与覆盖边界原子提交。
**Tech Stack:** 既有FastAPI、LangChain trim_messages、LangGraph add_messages/checkpointer、SQLAlchemy/MySQL、原生HTML/CSS/JS。
**Spec:** docs/superpowers/specs/2026-10-22-ch07-context-management-design.md（已批准）。

## Global Constraints

- 不增加外部组件，不做跨会话画像/语义检索/重要度选择；第八九章待后续独立设计。
- messages完整checkpoint；MySQL工具结果仅标识；用户/客服原话不覆盖；只用稳定ID和幂等键。
- summary_upto_msg_id包含末条、layer1_from_msg_id包含首条，均按完整回合单调推进；摘要仅追加。
- 用户同意演示固定预留：1050前缀、5×250证据、1000摘要、2000输出、1000余量、2000当前输入、3×(1200+150)ReAct。5650历史，3954层1，1695层2，1token保护。
- Prompt/数据用标注评估，后端先红后绿；每个任务完成即时四字段记dev-notes/ch07.md。
- 具体库API先Context7，已核对add_messages、trim_messages、自定义counter、AsyncSession每任务独享和lifespan。
- 继续feat/ch01-chat，不合并/推送；保留旧ch04笔记与knowledge-incoming资料，不读出.env密钥。

## Task 1：计数、窗口预算、整轮分层

Files: create app/memory/__init__.py、tokens.py、layers.py；modify app/config.py；tests/test_memory_budget.py、test_memory_layers.py。
Interfaces: TokenCounter.text(value)->int、messages(values)->int；ContextBudget.calculate(cfg,prefix_tokens,summary_tokens=0)->BudgetPlan(history,layer1,layer2)；partition(messages,summary_upto,layer1_from,plan,counter)->LayerView(window,layer1_from,layer2_tokens,events)。

- [x] 写失败测试：中文与ASCII不同计数、metadata/tool_calls计入；5650/3954/1695；小窗口报警；摘要增加导致历史余量减少；整轮移动不改原文、中层用户不动、客服60字、工具一行配对、超大最新整轮借用/拒绝。
```python
plan=ContextBudget.calculate(demo_cfg,prefix_tokens=900)
assert (plan.history,plan.layer1,plan.layer2)==(5650,3954,1695)
assert original_messages==before
assert all(m.content==raw.content for m,raw in recent_pairs)
```
- [x] 运行对应pytest确认缺实现失败；新增可配置窗口/固定项/系数和旧步骤别名。
```python
available=cfg.model_context_window-max(cfg.system_prefix_tokens,prefix_tokens)-cfg.rerank_top_k*cfg.evidence_chunk_tokens-max(cfg.summary_reserve_tokens,summary_tokens)-cfg.max_output_tokens-cfg.context_safety_tokens-cfg.max_user_input_tokens-cfg.agent_max_steps*(cfg.tool_result_max_tokens+cfg.tool_call_max_tokens)
history=min(cfg.history_target_turns*cfg.steady_round_tokens,available)
layer2=history*3//10
layer1=history-layer2-1
```
- [x] LangChain trim_messages仅用于临时窗口，按turn_id恢复完整轮边界；配对校验拒绝孤立tool。
- [x] 跑预算/层单测，记录任务并提交。

## Task 2：MySQL迁移、稳定消息ID与摘要仓储

Files: app/memory/models.py、migration.py、repository.py；app/models.py、db.py；scripts/init_memory.py；tests/test_memory_storage.py。
Interfaces: MemoryRepository.append(cid,tid,key,message)->AnyMessage（id=messages.id）；load_messages(cid)->list[AnyMessage]；boundaries(cid)->dict；advance_layer1(cid,id)；summaries(cid)->list[dict]；enqueue(cid,from_id,upto_id,checkpoint_config)->job；claim/complete/fail/recover job。

- [x] 真实隔离MySQL失败测试：迁移两遍不丢旧消息；同message_key重复追加只一条；tool数据库标识不含payload且返回消息原文；两个会话隔离；边界不能回退；唯一范围摘要与CAS/租约。
```python
one=await repo.append(cid,tid,'user',HumanMessage(content='订单1001'))
two=await repo.append(cid,tid,'user',HumanMessage(content='订单1001'))
assert one.id==two.id
assert (await repo.boundaries(cid))['summary_upto_msg_id']==0
```
- [x] 失败确认后实现显式inspect/ALTER幂等新增字段和表；旧message_key回填legacy:id。旧Repository/WorkflowRepository审计适配已有投影，不重复写；各异步任务独享Session。
- [x] 摘要工作项只存checkpoint定位和边界，不存完整tool；complete在短事务插新摘要+检查范围+推进summary_upto，layer1不得后退。
- [x] 跑真实MySQL测试与旧数据库回归，记任务并提交。

## Task 3：完整messages reducer与固定模型拼装

Files: app/memory/manager.py、assembly.py、logging.py；app/workflow/state.py、common.py、graph.py、agent.py、service.py、language.py、budget.py；app/gateway.py；tests/test_memory_graph.py、test_memory_assembly.py；tests/workflow_fakes.py。
Interfaces: ContextManager.prepare(state/checkpoint,cid,tid,question)->frozen context；append_node_messages(state,new,key)->list[AnyMessage]；assemble(state,cfg,phase,tools)->list[BaseMessage]；log_event(event,**data)。

- [x] 红测试：State.messages通过add_messages只合并增量，同ID重跑不重复；两轮/恢复不丢历史；模型view压缩后checkpoint仍原文；固定system/tools逐轮相等，尾部附件在当前user后，当前ReAct调用配对；闲聊也history_ctx。
```python
assert next_state['messages'][:len(old)]==old
assert requests[0][0].content==requests[1][0].content
assert requests[1][user_index+1].type!='system'
```
- [x] 节点接入轻量投影取得稳定ID后返回messages增量；active-turn和completed-turn按State状态过滤，旧checkpoint一次性由MySQL迁移完整历史。旧接口模式继续可用。
- [x] 固定角色/红线/phase解释写一份静态system；工具定义稳定，不随路由/证据改变，执行许可仍由当前route约束。ContextManager构造L2+L1+当前原话+一条摘要/证据/事实附件+本轮ReAct。
- [x] 指代/意图共享HistoryContext，经过源校验的摘要实体加入指代守卫；实际request日志每次完整记录，白名单只记录不调模型。统一窗口检查与旧累积消费预算区分。
- [x] Gateway记录实际usage供计数校准；超限工具结果返回结构化错误，原文只存checkpoint元数据。
- [x] 跑新旧graph/API回归及真实固定前缀计数/上游窗口核对，记录并提交。

## Task 4：追加式异步摘要worker与样例评估

Files: app/memory/summary.py、worker.py；app/main.py生命周期；evals/ch07-summary.jsonl；scripts/evaluate_summary.py；tests/test_memory_worker.py。
Interfaces: Summarizer.summarize(source,background)->SummaryResult；SummaryWorker.start/close/wake；run_once()->bool，按job checkpoint读源；摘要结果包含文本、源ID与事实引用。

- [x] worker红测试用可控慢summarizer证明当前SSE不等模型；相同范围不重复、并发前移不回退、失败不推进、旧摘要只背景不进本次source、重启恢复、原文批次过大按整轮拆分。
```python
assert response_finished and not summary_gate.is_set()
assert (await repo.boundaries(cid))['summary_upto_msg_id']==before
```
- [x] Prompt先造标注源数据和禁止事实：订单/手机号/未解决诉求/寒暄/数字否定；评估源引用和凭空实体、召回最早订单；摘要格式/引用校验可以单测，纯Prompt用标注评估。
- [x] worker在lifespan启动，持久化job+lease，每任务独享Session，LLM事务外；日志trigger/start/done/skip/failed与边界耗时完整。退出有限等待，不提交半段。
- [x] 真实上游标注评估、真实PG snapshot+MySQL worker集成、非阻塞验证，记录并提交。

## Task 5：只读会话列表/原文回载

Files: app/memory/api.py、repository.py；app/main.py；tests/test_memory_api.py。
Interfaces: GET /api/conversations?cursor=&limit=；GET /api/conversations/{cid}/messages?after_id=&limit=。固定当前demo-user，跨归属返回404。

- [x] 红测试会话按创建倒序/首问预览/摘要标志/分页到全部；消息原文不变、tool只有标识、引用/动作/回合状态齐全；两接口不改变边界、不触发任务。
```python
assert response.json()['items'][0]['preview']=='第一问'
assert other_user_response.status_code==404
assert before_boundaries==after_boundaries
```
- [x] 使用短只读Session，cursor/limit校验；支持恢复待选订单和旧会话，不让页面GET创建会话。
- [x] API/数据库回归通过，记任务并提交。

## Task 6：原生多会话侧栏

Files: app/web/index.html；浏览器验收脚本/截图。
- [x] 直接Vibe实现服务端列表、首问预览、已摘要徽标、点击回载原文、新对话空白懒创建；保持引用、反馈和选单。
- [x] 发送中禁切换；列表失败静默降级；消息失败保留原有显示。
- [x] 真实浏览器多会话对照、切回/刷新/继续、列表断网错误回退；不对页面做TDD或独立code review。记任务并提交。

## Task 7：评审、双profile真实24轮与finish

Files: scripts/acceptance_memory.py、evals/ch07-conversations.jsonl；docs/reports/ch07-*.json、ch07-validation.md；README、.env.example、dev-notes/ch07.md。
- [ ] 后端requesting-code-review独立只读评审；Important先红绿修复并复审，前端/密钥排除。
- [ ] 全部旧137+新增回归、pip check；校准真实prompt_tokens与估算，不改一个系数却保留旧预算口径。
- [ ] 默认与演示独立会话各至少24轮：默认零降级/摘要；演示出现L1降级→L2超额→summary done，之后正确回忆最早订单号/诉求。记录SSE/摘要时间证明不阻塞。
- [ ] 完整日志对照真实发出messages，浏览器侧栏与原文回载；工具full只在PG，新MySQL仅标识。
- [ ] 更新演示配置、命令、评估结果和局限，实时finish留痕，沿用保留本地分支。

## 自审通过

Spec每节映射Task1—7：预算/层→1，存储/ID→2，State/前缀/日志→3，后台/Prompt评估→4，会话API→5，页面→6，迁移兼容/完整验收→2/7。方法签名一致，无未定义占位；旧资料与第八九章范围隔离。执行前已确认用户批准，无需重问执行方式。
