# 第四章验收记录

## 功能验收

- 真实Edge：QC-M100清洗问题选query_faq，答案支持洗碗机、建议上层篮架；引用弹层显示完整原文与章节路径，并提供受控原文链接。
- 同一会话问“邮费是多少”：普通配送8元、满99元包邮，来源配送政策/运费规则。型号和邮费分别22、39个SSE token帧。
- “火星配送费用是多少”：明确拒答；已核对low_confidence_questions中原话、会话、retrieval入口、low_score原因及时间。
- 反馈：点击👍后两个按钮锁定、选中一个，刷新保持；纯前端采集。页面脚本错误0。
- curl：HTTP200，真实SSE包含citations/token/done，无error；记录artifacts/ch04-curl.sse。
- 原有普通多轮：第二轮正确记起第一轮“小林”，ch04-multiturn.json。

证据：[真实三轮](ch04-live-acceptance.json)、[浏览器完整流](ch04-browser.json)。截图位于artifacts/ch04-real-source.png和ch04-real-chat.png。

## 四策略真实评估

42条人工标注问题，12条校准与30条测试隔离；63个不同商品章节，非同义问法复制。测试30×4=120组已跑完，包含6种query类型与3档难度。

|策略|Recall@10|MRR@10|Faithfulness|回答覆盖率|错误|
|---|---:|---:|---:|---:|---:|
|dense|0.955|0.970|0.984|0.533|0|
|BM25|1.000|0.955|0.986|0.600|0|
|hybrid|1.000|0.977|1.000|0.600|0|
|hybrid+rerank|1.000|1.000|0.980|0.667|2|

四策略Recall@50均1.000，无答案拒答率均1.000。2条失败为重排后的生成引用格式错误（ch04-12 missing_citations、ch04-24 invalid_citations），被校验拦截并保留，未作为成功回答。报告four_strategy_run_finished=true；complete_four_strategies=false明确表示并非120组全成功。拒答不计忠实度满分；忠实度是配置LLM对原子声明的评判，不是人工真实性保证。小语料与小样本不能推出普遍性能优势。

详见[ch04-comparison.md](ch04-comparison.md)、JSON和逐题JSONL。最终查询侧术语归一不改变本报告30个固定检索计划，逐项等价性验证见ch04-domain-normalization-validation.json；原执行manifest保持不变。诊断延迟约dense/BM25/hybrid 2–3秒、重排16秒；CPU且部分时间共享浏览器验收负载，不视为隔离性能基准。

## 模型与校准

官方bge-reranker-v2-m3 revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`，权重2271071852字节，SHA256 `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`与官方值一致。CPU启动一次。阈值0.5由独立12题选出，正例召回1.0、负例提前拦截1/3，之后仍由严格充分性gate拒绝不完整证据；分数不是校准概率。

## 工程验证与评审

交付前完整测试：108 passed in 16.07s；pip check：No broken requirements found。聊天、嵌入、重排三服务health均HTTP200，MySQL/Milvus/etcd/MinIO均healthy。真实MySQL/Milvus验证覆盖BM25型号、两路品类过滤、两个中断点重跑补齐、幂等与旧hash拒绝。后端独立多轮评审及最终增量复审均已通过，无剩余Critical/Important，页面遵照用户例外不参与review。

## 演示与过程

README第四章提供三服务、建库、校准和评估命令。聊天 http://127.0.0.1:18000/ ，嵌入18001、重排18002、MySQL3307、Milvus19531。

~~~powershell
curl.exe -N -H "Content-Type: application/json" --data-binary "@evals/ch04-chat-demo.json" http://127.0.0.1:18000/chat
.\.venv\Scripts\python -m scripts.evaluate_hybrid --output docs/reports/ch04-comparison-rerun
~~~

变更了品类、索引、预算、模型或实现时换输出路径，不能混合续跑。分阶段过程：[dev-notes/ch04.md](../../dev-notes/ch04.md)。旧失败/中断报告保留；本地分支按既有选择保留，不推送合并。
