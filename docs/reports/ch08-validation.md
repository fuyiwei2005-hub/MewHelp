# 第八章交付验收

日期：2026-10-23。保留feat/ch01-chat本地分支，不合并、不推送。

## 结果

- 全套：203 passed / 35.02s；pip check无依赖冲突；git diff --check通过。
- 两个独立MCP实际Streamable HTTP发现、调用、仅Server重启后热发现、故障隔离：tests/test_tool_mcp.py通过。
- 真实上游+MySQL+官方PostgreSQL checkpointer：ch08-ticket-live.json八项通过。
- 实际Edge：ch08-browser.json十五项通过，桌面和390px手机预览人工查看；旧多会话页面ch08-memory-browser-regression.json十项通过。
- 浏览器对应SQL：确认1单、取消0、忽略0、刷新后取消0、旧投诉按钮1；取消/忽略均审计权限拒绝。
- 热注册真实对话：ch08-hot-registration.json；query_order_note与query_delivery_eta分别调用成功，客服PID34524前后不变，仅物流Server从原PID23116重启。此后因引用Prompt修订重启客服，不属于热注册证明区间。
- 超时实际MySQL审计：ch08-timeouts.json；读工具超时95ms、重试1，写工具27ms、重试0。来自最新完整测试的睡眠故障注入handler，不执行真实工单写操作。
- 显式建单意图标注16/16；断线后已提交不重复、旧预览过期、官方PG重新打开后可恢复均有集成测试。
- 独立后端审查：两项Important红绿修复并复审Ready，见ch08-review.md。前端按用户要求不套独立代码审查。

- 最终真实Workflow结构回归7项通过，见ch08-workflow-regression.json；退款最终回答仍遇引用格式失败，现为明确兜底且入池，不能把结构回归通过解读为生成质量全绿。

## 演示

先启动现有MySQL/PostgreSQL、嵌入/重排与Milvus，再分别开三个终端：

~~~powershell
.\.venv\Scripts\python -m scripts.serve_mcp --server logistics --plugin-file mcp_servers/delivery_eta_plugin.py
.\.venv\Scripts\python -m scripts.serve_mcp --server aftersales
.\.venv\Scripts\python -m scripts.serve_workflow --port 18000
~~~

浏览器打开 http://127.0.0.1:18000 。依次问：
1. 演示订单1001的物流到哪了。
2. 演示订单1001还在保吗。
3. 演示订单1001的订单备注是什么（本地注册插件）。
4. 演示订单1001预计还要几天送到（MCP新增插件）。
5. 帮我建工单 → 演示饮水机不出水 → 点击确认。再开一轮同类对话点击取消。

不带plugin-file启动物流后，再仅重启物流并添加plugin-file，可重现新工具发现。config/tool-plugins.json和tool-policy.json是可信开发配置，新增本地工具只登记模块及权限，下一轮可用。无外部Server自授权限。

~~~powershell
.\.venv\Scripts\python -m scripts.acceptance_ticket --base-url http://127.0.0.1:18000 --output docs/reports/ch08-ticket-live.json
.\.venv\Scripts\python -m scripts.acceptance_workflow --base-url http://127.0.0.1:18000 --output docs/reports/ch08-workflow-regression.json
.\.venv\Scripts\python -m scripts.evaluate_ticket_intent
.\.venv\Scripts\python -m pytest -q --basetemp artifacts/pytest-ch08-delivery
.\.venv\Scripts\python -m pip check
~~~

## 限制与返工

- 当前是demo-user、随机物流/售后数据、无真实认证或业务API。
- 工具发现每Server有超时，服务不可用时该轮不暴露其工具；新增工具实际前缀计入预算。
- 工单确认绑定会话/轮次/调用与冻结参数；超时不代表未执行，不自动重试，先核查已有工单。
- 实际旧流程回归前两次出现CitationError，严格校验拦下；固定前缀补充合法数字引用格式和无引用结尾约束仍不能保证模型遵从；另加非法引用兜底与generation问题池记录，无效引用单元不释放，未放宽校验。第三次政策被原置信度闸保守拒答，暴露旧验收脚本假设必进Agent；脚本修正为检索必经闸、弱证据禁止进Agent，符合原设计。该闸依旧是第五章简版，正式校准属于第九章。
- 非阻断限制：引用失败兜底分支的最终生成用量尚未完整计入统计；正常调用用量不受影响，正式成本追踪属于第九章。
- 用户另行提供的喵喵资料、原始CSV、ch04笔记修改未摄入或纳入本章提交。

阶段留痕：dev-notes/ch08.md。
