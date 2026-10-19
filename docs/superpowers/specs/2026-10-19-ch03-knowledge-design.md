# 第 3 章：Dense 知识库与第二章前置补齐设计

状态：用户于2026-10-19回复“批准”，设计定稿。用户已选择 A：先补齐第二章，再实施第三章；本次评审覆盖实际未落地的工具契约与第三章新增架构。

## 实施顺序与范围

1. 按 docs/superpowers/specs/2026-10-19-ch02-tools-design.md 补齐五个 @tool、单轮工具编排、四表 MySQL、状态帧和聊天徽章；真实验收并保存“邮费”关键词漏召回证据。
2. 冻结下述 query_faq 入参、出参和错误契约。
3. 增加文档建库、历史挖掘、MySQL/Milvus 双写恢复，将 query_faq 内部替换为 BGE-M3 dense 检索。
4. 在同一聊天页面重跑“邮费是多少”及建库中断恢复，保存前后对照。

第三章生产查询路径只用 dense 向量，不包含 SQL LIKE 召回、混合检索、稀疏向量、ColBERT 或 reranker。第二章关键词实现保留为独立基线测试，不在第三章查询失败时兜底调用。

沿用当前 DeepSeek 对话模型及 .env。聊天工具链仍最多一次业务工具执行后收敛，结构化售后提取接口继续可用。工具徽章的页面改动沿用用户明确的 Vibe Coding 例外；知识库后端走完整 Superpowers + TDD。

## 工具契约冻结

当前仓库尚无实际 query_faq，故本次把第二章接口明确后，两阶段共同遵守：

- 名称：query_faq。
- 入参：keyword: str，非空、最大 500 字符；保留参数名，语义检索时仍可以传用户原话中的词或问题，不增加 category、top_k 等必填参数。
- 成功：{"ok": true, "matches": [{"question": "...", "answer": "...", "category": "..."}]}，最多 5 条，按检索顺序排列。
- 未命中：{"ok": true, "matches": []}。
- 失败：{"ok": false, "error": {"code": "...", "message": "安全描述"}}。
- 不在工具公开返回中新增分数、向量 ID、元数据或知识库内部结构。原 FAQ 单问题与新 questions 数组通过适配器映射为 question 字符串；有多个真实问法时用首个问法展示。
- 运行配置决定检索实现，第三章默认 dense；故障明确返回错误，不悄悄退回 LIKE。
- 工具结果回灌模型，只能根据命中文本回答；未命中/失败不能编造运费或政策。

## 技术与进程边界

MySQL：沿用第二章 Docker 服务、SQLAlchemy 异步事务和非 root 业务账号。Milvus：Docker Standalone，加官方依赖 etcd / MinIO 与命名卷；服务和 PyMilvus 使用官方匹配版本并在实施时记录锁定值，不换其他向量库。

嵌入模型固定 BAAI/bge-m3，以 FlagEmbedding BGEM3FlagModel 加载，只启用 return_dense=True、return_sparse=False、return_colbert_vecs=False，输出维度 1024。文档和问题使用同一固定模型 revision 和同一编码规则。

推荐本地独立 embedding 服务，通过仅监听 127.0.0.1 的 /v1/embeddings 接口供在线服务与离线任务共用，模型只加载一次。GPU 优先、小批量（默认 2）、FP16；若显存不足，允许同一 BGE-M3 改用 CPU/FP32并明确报告性能，绝不换模型。编码在限并发工作线程运行，不阻塞 SSE 事件循环。

备选是每个进程直接加载 BGE-M3，少一个服务但重复占显存；本机 6GB 显存不选此方式。第三方远程 embedding 服务不默认采用，避免新增账号与数据外发边界。

模型下载和运行依赖需真实验证。当前 Docker 引擎未启动，实施先从已定位的 Docker Desktop 安装启动并确认；若固定技术栈无法运行、模型无法获取或依赖不可兼容，停止对应实施并问用户，不用假向量替代验收。

## 数据表

第二章四表保留。第三章新增：

### knowledge_chunks（原文权威源）

- id：稳定字符串主键。
- category：分类或上级标题路径。
- questions：非空字符串数组。
- answer：原始知识正文。
- section_path：完整章节路径。
- content_type：policy / faq / manual / table / conversation_qa。
- is_key_clause：布尔值。
- prev_chunk_id、next_chunk_id：同一来源文档内前后块指针，无相邻块时为空。
- source_id、source_version：来源标识和版本。
- content_hash：category/questions/answer 序列化文本的摘要。
- embedding_status：pending / embedded / failed。
- vector_id：Milvus 返回的主键，成功前为空。
- embedding_model、embedding_revision、embedding_dim。
- attempts、last_error_code、is_active、created_at、updated_at。

四类用户指定元数据（章节路径、内容类型、关键条款、前后指针）只保存，不拼进 embedding。来源与任务状态同样不拼进 embedding。

文档块 id 来自规范化 source_id + section_path + 块序号的确定性摘要。重复导入同一来源更新同一主键；内容改变则更新 content_hash、清空旧 vector_id 并置 pending。来源新版本不再包含的旧块标记 inactive，不参与在线回答，不直接删除原文审计。

### knowledge_staging（对话挖掘暂存）

保存 run_id、source_conversation_id、source_turn_ids、来源消息范围、category、questions、answer、evidence、normalized_hash、状态（staged / published / duplicate / conflict / rejected）、原因与时间。来源记录和候选内容组合唯一，重跑抽取不会重复灌暂存。

### knowledge_jobs（任务批次与游标）

保存任务类型、run_id、固定输入截止消息 id、当前已完成批次游标、抽取/去重/入库阶段和统计。只在对应批次暂存结果成功提交后推进游标，崩溃后从上次提交点继续。

这些是本章知识流水线所需表，不把第二章仅四张业务表的阶段约束误解为第三章不能新增表。

## 文档处理

输入为本地 Markdown 目录，包含退货政策、商品 FAQ、售后手册及大表格。用户尚未提供真实公司材料，先提供明确标为演示的知识文档，运费内容与第二章测试政策一致，不能冒充真实企业政策。

1. 按 # 至 ###### 标题层级识别章节，忽略代码围栏中的伪标题；保存完整路径。
2. FAQ 原文若有明确问答，questions 填真实问题，answer 填答案；不为验收特意把“邮费”塞进运费材料。
3. 政策/手册没有天然问题时，questions=[当前章节标题]，category=上级标题路径；无标题文档使用文件名，category=未分类。
4. 在章节内部按段落、完整句递归切长内容。软目标每块 600 字符，重叠目标 80 字符；重叠只复制尾部完整句，裁到最近句号，不跨章节混入另一条政策。
5. 句末识别中文句号和中英文问叹号；列表和表格以完整条目/行作为结构单元，不把 Markdown 行强行当半句话裁断。
6. 大表格识别表头和分隔行，按完整数据行组块，每块复制表头和分隔行。允许一条表格数据行超过软目标，但不能拆开行内单元格。
7. 单句或单行超过软目标时保持完整；序列化后的真实 BGE tokenizer 长度超过模型上限时标记输入错误并保留原文，要求整理来源，不静默截断、不留下半截话。
8. 关键条款优先读显式标记，辅以“必须/不得/例外”等可解释规则打标；仅作为元数据，本章不因该标记额外召回或调权。
9. 全部块确定后再统一计算前后指针并事务写 MySQL。

标题切分器和递归切分器作为底层能力使用，句边界、表格表头与指针规则由本项目明确实现和测试，不能假设普通递归 splitter 自动满足全部要求。

## Embedding 文本与 Milvus

唯一 embedding 文本格式：

分类：{category}
问题：{questions 按固定顺序换行拼接}
答案：{answer}

模型 revision 和格式版本锁定并记录；编码前使用模型 tokenizer 检查长度，禁止默认截断。相似度采用 COSINE；只建一个 FLOAT_VECTOR 字段，不建稀疏向量或全文索引。

Milvus collection 固定名 knowledge，auto_id=False，主键使用 knowledge_chunks.id；字段为 chunk_id、embedding、content_hash。原文仍从 MySQL 获取，不以 Milvus 中复制的文本为权威源。

## 双写与断点恢复

1. 文档处理或暂存发布先提交 MySQL，embedding_status=pending。
2. 单 worker 扫描 pending 以及可重试 failed，用 BGE-M3 批量编码。
3. 用稳定 chunk_id 执行 Milvus upsert，不使用每次重跑都会生成新 ID 的自动主键。
4. 检查 upsert 响应 ids 与预期主键一致，将返回 ID 回填 MySQL，并在短事务中置 embedded。
5. 回填时校验 content_hash 未改变；若编码期间原文更新，旧结果不能把新版本误标为成功。
6. 任务以数据库锁防止同类任务并发重入；进程崩溃后锁随连接释放，不留下永远 running 的不可恢复状态。
7. Milvus 已写成功但 MySQL 尚未回填时，该块仍为 pending；重跑对同一主键 upsert 并补回填，逻辑行数不增加。
8. 在线只接受 MySQL 中 active + embedded + hash/model 匹配的命中；旧向量、未回填向量和失效来源不能作为答案。
9. 查询暂时不可用、空结果和未向量化分开记录；不得把数据库失败伪装成无知识。

不宣称 MySQL/Milvus 有跨库原子事务，采用可重放状态机实现最终一致。提供可控 failpoint：after_mysql_commit、after_milvus_upsert；中断命令返回失败，恢复运行不必手工改库或清空卷。

## 定时从历史对话挖知识

提供独立应用任务进程，不嵌入 FastAPI reload 生命周期，默认每天 02:00（Asia/Shanghai）运行，也可命令行立即执行。使用 APScheduler 3.x 固定 job id、max_instances=1、coalesce=True；MySQL 保存业务游标与阶段，不依赖内存 job store 记住数据进度。

每次快照固定截止消息 id，按会话/完整用户轮次组批，不在 user/assistant/tool 中间截断。仅处理已完成轮次，过滤工具失败、未完成流和一次性订单/物流个人数据。

LLM 用结构化输出抽取 category、真实 questions、answer、证据消息 id/原句，不得补充原文没有的政策；缺证据、含敏感凭据或无法解析的结果标 rejected。结果先全部进入 staging，批次之间不直接发布知识。

整个快照抽取完毕后，再把本次全部暂存与既有知识整体比较：
- 规范化空白、标点和大小写做确定性去重，不做语义相似合并或向量重排。
- 同 category、相同规范化 answer 的候选合并真实问法列表，稳定排序；更新 questions 会触发重新向量化。
- 相同规范化问题、同类别却有不同答案时标 conflict 并保留证据，不自动覆盖权威答案。
- 发布和 staging 状态更新在同一 MySQL 事务；知识一律先 pending，再由统一双写任务向量化。
- 只有全部发布阶段提交成功才推进本次完成水位；崩溃重跑靠来源唯一键和知识主键幂等。

这是“分批抽取、整体去重后入库”，不是每批各自去重后直接入向量库。定时任务是仓库应用功能，不创建个人 Codex 提醒或外部自动化。

## 在线检索

query_faq(keyword) → 同一 BGE-M3 问题向量 → Milvus COSINE Top-K → 按返回顺序读取 MySQL 有效原文 → 适配为冻结 matches 格式。

默认 Top-K=3，上限 5，阈值为可配置的评估参数；用标注集确定后锁定并记录，不为单句验收手工特判。无 SQL LIKE 兜底，无同义词字典，无 reranker。关键词参数名保留只是契约兼容，内部已经不做字面查表。

元数据只作为记录与一致性校验，不拼进向量，也不通过前后块指针扩展召回；本章保持单路 Top-K。问题过长明确返回校验错误。

## 验证与交付

第二章先真实验收五工具、四表、单轮收敛、错误/重试/工单幂等，以及“邮费”0 行基线；保存在 ch02 日志与报告。

第三章 TDD：
- 标题路径、围栏伪标题、递归长段、完整句重叠、复制表头、超限单句/行拒绝。
- embedding 严格只含三个内容字段，metadata 改变不污染向量文本。
- 稳定主键、重复导入、内容更新重置 pending、失效块过滤。
- 两个 failpoint 恢复、写 Milvus 后未回填恢复、并发源更新保护；真实 MySQL/Milvus 查验结果。
- 分批游标、全量去重、重复问法合并、冲突隔离和发布幂等。
- query_faq 两阶段契约一致、Top-K 排序、阈值/错误语义与聊天工具链回归。

Prompt、抽取数据和召回质量用标注样例评估，不为纯文本写镜像单测。记录真实 BGE 模型 revision、来源文本、预期块 id、实际 Top-K/分数/答案，不用随机或假向量替代实际验收。

必须真实完成：
1. 原文只有“运费”没有“邮费”的材料，经现有浏览器问“邮费是多少”，出现 query_faq 徽章并根据运费说明答对。
2. 分别中断于 MySQL 提交后、Milvus upsert 后，重跑补齐 pending，确认 vector_id 全部回填、无重复逻辑向量。
3. 真实历史表分批抽取到 staging，整体去重发布；定时任务实际启动并可手动触发，不只写一个未接线的函数。

交付启动/建库/挖掘/定时执行/中断恢复/浏览器演示命令、测试和评估结果、dev-notes/ch02.md 与 dev-notes/ch03.md。两章各阶段及时追加记录；后端独立 code review 与修复，页面仍按用户例外。

## 自审结论与审批边界

本草案明确补齐前置范围、冻结契约、表格与整句极端输入、三字段向量文本、最终一致状态机、挖掘整体去重、真实验收和环境限制。尚未实施、下载模型、安装依赖或启动数据库，不宣称任何测试已通过。

用户的 A 确认实施顺序；本草案为新知识库架构的具体评审物。批准后沿用用户此前选择，在当前会话编写计划、自审并执行，不重复询问执行方式。

## Context7 已核实资料

- https://reference.langchain.com/python/langchain-core/tools/convert/tool
- https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- https://github.com/flagopen/flagembedding/blob/master/research/BGE_M3/README.md
- https://github.com/flagopen/flagembedding/blob/master/Tutorials/1_Embedding/1.2.1_BGE_Series.ipynb
- https://github.com/milvus-io/pymilvus
- https://milvus.io/docs/install_standalone-docker-compose.md
- https://milvus.io/docs/install-pymilvus.md
- https://reference.langchain.com/python/langchain-text-splitters/markdown/MarkdownHeaderTextSplitter
- https://reference.langchain.com/python/langchain-text-splitters/character/RecursiveCharacterTextSplitter
- https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/base.html
- https://apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html

