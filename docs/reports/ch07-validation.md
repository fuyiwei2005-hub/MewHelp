# 第七章验收与交付

日期：2026-10-23。分支feat/ch01-chat保留本地，不推送/合并。只做当前会话记忆；第八、九、十章尚未实现。

## 验收结果

| 项目 | 实际结果 | 证据 |
| --- | --- | --- |
| 完整回归 | 168 passed in 22.95s | pytest，artifacts/pytest-ch07-ready-oct23 |
| 依赖一致性 | No broken requirements found | pip check |
| 后端独立复核 | Ready，无新增Critical/Important；定点9项通过 | ch07-review.md |
| 默认128000窗口 | 24/24，原文完整，零降级、零摘要 | ch07-default-24.json |
| 演示18000窗口 | 24/24后追加回忆轮；19次降级、6段摘要、原文完整 | ch07-demo-24.json |
| 多会话页面 | 真实Edge浏览器10/10，无脚本错误 | ch07-browser.json |
| 摘要标注评估 | 7/7，含否定、未解决事项、旧背景、重复事实 | ch07-summary.json |
| 无证据编号约束 | 3/3真实模型回放 | ch07-memory-citations.json |
| 时间指代与意图 | 3/3真实模型回放 | ch07-memory-resolution.json |
| 既有Workflow | 闲聊、物流、多步ReAct、政策闸、投诉、退款暂停/恢复7项通过 | ch07-workflow-regression.json |

默认会话30325b50c62e4b91b42eeb9bdca7de94；演示会话068de01fbee841ddae5e84a076b248e9。订单1001/1002为系统已有的虚构演示订单，不是真实个人数据。

## 真实级联与异步证据

演示首轮预算5650/3954/1695由可配置成本倒推，不硬编码结果。首轮layer1_degrade为703→707（消息ID）。首个summary trigger为层2=2104 token > 1695，冻结范围0..718；成功追加第1段并推进covered_upto=718，随后共追加6段，未改写旧段。

首任务第1次摘录的quote不在源原文中，被校验拦下并记录summary failed；第2次成功，未提交未经验证事实或提前推进边界。脚本foreground_during_summary=true：summary start/done之间存在前台history_model_ctx/model_ctx事件；慢摘要集成测试也验证前台写消息不等待模型。日志覆盖范围和耗时齐全。

回忆轮准确指出最初是“演示订单1001”，用户最初希望“查询物流延误情况”，并区分后来查的1002和历史记录/最新查询。完整回答见演示JSON。逐条对照两个profile的24条用户原话全部保留；只读API完整回载，tool仅标识，PG checkpoint保留完整消息。

## token校准和实际限制

ch07-calibration.json记录本次带会话ID的语言/Agent调用：默认119次，最大实际输入15280、最大总量15307；演示124次，最大实际输入6062、最大总量6225。估算/实际输入最小均0.9939，均值默认1.4138、演示1.4014。估算不是精确tokenizer，短调用有少量低估，本次误差由1000安全余量覆盖，不能宣称每次都保守。摘要模型另有日志，不混入这些统计。

CJK/ASCII系数、稳态规划和预留一起配置。每次实际组装再次检查窗口，追加摘要超过1000预留会继续扣历史，不为维持5650回头合并。摘要目标50—200字，保留唯一身份/诉求优先；多对象批次有段落超过目标，按实际注入量扣预算，不硬截事实。持续追加最终可能耗尽窗口，本章明确报警/拒绝超预算，不实现无限压缩。仍只有demo-user，无真实身份认证、跨会话记忆或画像。

## 演示

先按README启动现有MySQL、Milvus、独立PostgreSQL、BGE-M3和重排服务。第七章命令：

~~~powershell
.\.venv\Scripts\python -m scripts.init_memory
.\.venv\Scripts\python -m scripts.serve_workflow --port 18000
curl.exe http://127.0.0.1:18000/api/conversations
.\.venv\Scripts\python -m scripts.acceptance_memory --profile default --output docs/reports/ch07-default-24.json
# 按README演示变量另起18004后
.\.venv\Scripts\python -m scripts.acceptance_memory --profile demo --base-url http://127.0.0.1:18004 --log log/ch07-demo.log --output docs/reports/ch07-demo-24.json
Select-String -Path log/app.log,log/ch07-demo.log -Pattern 'model_ctx|history_ctx|summary|layer1_degrade'
.\.venv\Scripts\python -m pytest -q --basetemp artifacts/pytest-ch07-reproduce
.\.venv\Scripts\python -m pip check
~~~

浏览器http://127.0.0.1:18000，新建两个会话，切回旧会话、刷新后继续。截图artifacts/ch07-browser-desktop.png与ch07-browser-mobile.png；侧栏失败不影响聊天。

## 返工与记录

早先JSON控制、伪造引用与时间指代失败报告保留为before-prompt/before-temporal-fix/attempt3-failed精简JSON，完整轨迹归档artifacts同名文件，不冒充当前通过。电脑重启后首轮完整测试因Milvus尚未就绪1失败，健康检查200后完整重跑168通过，未为环境失败改测试。

批准设计docs/superpowers/specs/2026-10-22-ch07-context-management-design.md；完成计划docs/superpowers/plans/2026-10-22-ch07-context-management.md。过程实时记录dev-notes/ch07.md。前端按Vibe例外不做独立code review。
