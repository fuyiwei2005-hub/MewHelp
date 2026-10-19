# 第三章 Dense 知识库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 用真实 BGE-M3/Milvus 替换 FAQ 内部检索，演示语义召回和可恢复双写。
**Architecture:** Markdown/对话候选先进入 MySQL，统一 pending worker 编码 upsert Milvus；在线向量搜索后回 MySQL 取原文。独立 embedding 服务共享单份模型。
**Tech Stack:** BGE-M3 FlagEmbedding、Milvus/PyMilvus、SQLAlchemy/MySQL、APScheduler 3.x。
**Spec:** docs/superpowers/specs/2026-10-19-ch03-knowledge-design.md。

## Global Constraints
- 只用 dense；query_faq 入参出参冻结不变；无 LIKE 兜底/混合/重排。
- 向量文本严格只有 category/questions/answer，四类结构元数据不参与。
- MySQL 权威原文，稳定主键 upsert；禁止自动主键重复向量。
- 切分不截断整句/表格行；超出模型长度明确报错。
- Prompt/数据用标注集验证，后端TDD，每阶段立即写 dev-notes/ch03.md。

## Task 1：文档结构切分

Files: app/knowledge/chunking.py、tests/test_chunking.py、knowledge/*.md。
接口：Chunk 数据类、split_markdown(source_id,text,max_chars=600,overlap=80)->list[Chunk]；embedding_text(chunk)->str。
- [ ] 先写标题路径、围栏、长段递归、完整句重叠、大表格、指针、元数据排除测试。
~~~python
chunks = split_markdown("policy", "# 售后\n## 退货\n第一句。第二句。", max_chars=8, overlap=4)
assert all(c.answer.endswith("。") for c in chunks)
assert chunks[0].next_chunk_id == chunks[1].id
~~~
- [ ] 按标题/段落/整句及表格结构递归，软目标600/重叠80。保留表头，单句/行可超软目标，embedding时验证硬上限。稳定source/path/ordinal id，统一生成指针。
- [ ] 真实FAQ提取原问法，手册用章节标题和父路径。演示运费原文不含“邮费”。
- [ ] 测试和标注切分样例通过，记录提交。

## Task 2：知识表、双写与恢复

Files: app/knowledge/models.py、repository.py、pipeline.py、tests/test_knowledge_pipeline.py、scripts/ingest_knowledge.py；修改 compose.yaml。
接口：KnowledgeRepository.upsert_chunks、pending、mark_embedded(id,hash,vector_id)、active(ids/hashes)；VectorStore.upsert/search；KnowledgePipeline.ingest/sync_pending。
- [ ] 测试先失败：重复主键、更新重置pending、过期hash拒绝、两个failpoint恢复、原文权威过滤。
~~~python
await pipeline.sync_pending(failpoint="after_milvus_upsert")
assert (await repo.get(chunk_id)).embedding_status == "pending"
await pipeline.sync_pending()
assert (await repo.get(chunk_id)).vector_id == chunk_id
~~~
- [ ] 建 knowledge_chunks/staging/jobs。事务先存pending，Milvus upsert成功校验IDs后带hash条件回填；失败保留待处理。任务MySQL锁防重入。
- [ ] Docker部署真实Milvus Standalone官方配套组件，SDK与服务匹配；不用Milvus Lite替代验收。原文变更/失效处理明确。
- [ ] 真实数据库两处中断重跑，保存MySQL状态与Milvus主键查询证据，记录提交。

## Task 3：BGE-M3服务与在线检索

Files: app/embedding_server.py、app/knowledge/embedding.py、vector.py、retrieval.py、tests/test_retrieval.py；修改 config.py、tools.py、requirements。
接口：Embedder.encode(texts)->list[list[float]]；DenseRetriever.query(keyword)->冻结FAQ返回；embedding HTTP服务POST /v1/embeddings。
- [ ] 先测试HTTP载荷、字段映射、阈值、原文hash过滤、无命中与故障区别、两阶段工具契约一致。
~~~python
assert set(result) == {"ok","matches"}
assert set(result["matches"][0]) == {"question","answer","category"}
~~~
- [ ] 安装FlagEmbedding兼容依赖并下载锁定BGE-M3 revision；模型仅加载一次，GPU FP16 batch2，编码前真实tokenizer检查8192上限，无稀疏/ColBERT。
- [ ] embedding请求只包含规定三字段；Milvus集合knowledge，VARCHAR主键和1024维COSINE，TopK3/上限5，回MySQL校验active/status/hash并保持顺序。
- [ ] 用独立标注集评估阈值，锁定实际选择；线上默认为dense，错误不走LIKE。
- [ ] 真实“邮费”检索和回答通过，保存模型、分数、块ID与原文。记录提交。

## Task 4：对话挖掘、暂存整体去重与定时任务

Files: app/knowledge/mining.py、scheduler.py、tests/test_mining.py、scripts/mine_knowledge.py、evals/mining.jsonl。
接口：MiningService.run(resume=True)->统计；publish(run_id)->统计；独立--watch任务进程。
- [ ] 测试先失败：固定快照/批次游标、暂存幂等、抽完再整体发布、同答案并问法、冲突隔离、重跑不重复。
~~~python
assert await mining.publish(run_id) == {"published":1,"duplicates":1,"conflicts":0}
~~~
- [ ] LLM结构化提取QA及来源证据；过滤失败轮次、一次性个人信息和无证据候选；staging事务成功才推进游标。
- [ ] 全快照完成后和已有知识按category/规范化answer整体去重，相同问题不同答案保留conflict；发布pending与更新stage同事务。
- [ ] APScheduler独立进程每天02:00 Asia/Shanghai、job id固定/max_instances1/coalesce；MySQL保存业务游标。提供手动执行和恢复。
- [ ] 用真实历史表跑LLM标注样例与完整挖掘，启动任务调度并验证注册时间；记录提交。

## Task 5：最终验收、评审与交付

Files: scripts/acceptance_knowledge.py、evals/retrieval.jsonl、docs/reports/ch03-*.json/md、README.md。
- [ ] 浏览器真实“邮费是多少”显示query_faq徽章并依据没有“邮费”字样的运费原文回答。
- [ ] 两个failpoint真实中断，恢复并比对唯一主键数量、pending清零、vector_id回填。
- [ ] 手动挖掘与定时任务注册验证；整体去重、重跑幂等和冲突样例真实落库。
- [ ] 全量测试/pip check/现有聊天回归、真实BGE召回标注评估；报告实测不伪造结果。
- [ ] 后端独立code review并修复，verification-before-completion复核，finish保留本地分支、服务与命名卷；交付命令与两章日志。

## 计划自审
标题/整句/表格、三字段embedding、元数据、权威表、两个崩溃窗口、原文更新、denseTopK、挖掘快照/暂存/整体去重、定时、模型资源和真实验收都有任务。接口一致，无混合检索或模型替换。用户已批准设计和当前会话执行，自审通过后直接实施。

