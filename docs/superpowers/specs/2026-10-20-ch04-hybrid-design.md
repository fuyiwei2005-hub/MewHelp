# 第四章：混合检索、重排与评估设计（待批准）

日期：2026-10-20。状态：设计草案，未开始实现。

## 目标和边界

保留现有FastAPI、SQLAlchemy/MySQL、LangChain、DeepSeek兼容接入、SSE与单轮Function Calling。知识问答升级为本轮Query理解、dense/BM25混合召回、重排、证据充分性判断、带引用回答。只理解当前问题，不做指代消解、多轮改写或Agent循环。前端按用户要求直接Vibe Coding，不进入后端brainstorm/TDD/code review。

## 已确认

用户选择A：聊天页显式选择品类，后端过滤；不选则查全部。现有category仍表示知识分类/章节父路径，新增product_category表示商品品类。选定品类时召回该品类和明确标为通用的知识，两路使用相同过滤条件；不能召回其他具体品类。只接受服务端允许的品类值，禁止拼接用户过滤表达式。

## 方案与迁移

推荐新建knowledge_hybrid_v4集合并从MySQL权威原文完整回填，验收后以配置切换；保留knowledge集合便于第三章对照与回退。原地重建会中断现有检索并丢失回退基线，不采用。没有BM25函数的旧集合不能因has_collection成功而被当成新schema使用；启动核验字段、维度、分析器与函数，不兼容明确报错。

Milvus继续用现有3.0.0及匹配SDK，满足2.5起的原生BM25能力，不降级、不引入外部全文引擎。字段包括稳定chunk_id、embedding(1024)、text、bm25_sparse、content_hash、product_category、active/索引版本。text严格沿用category/questions/answer的规范拼接，不把章节路径等元数据加入向量。text启用内置chinese analyzer，BM25函数生成稀疏列；dense COSINE与sparse BM25分别建索引。关键词召回不走MySQL LIKE。

MySQL权威源与幂等双写机制保留。新集合有独立索引同步版本/检查点，不能只凭第三章embedded状态跳过回填。更新、删除、品类变化都要同步；在线仍回MySQL检查active/hash/版本/品类，失效向量不能成为证据。保留两个故障点恢复验收。

## Query理解与检索

模型结构化输出normalized_query、有限synonyms和识别到的型号；只看本轮问题，原话单独保留，不补造条件。型号、数字、否定条件原样保留；无效改写回退当前原话，不转用多轮历史。同义词只拼入检索查询，不另存知识副本。废除旧FAQ工具对检索侧同义改写的限制，原始调用仍可审计。

Dense原标准问法向量检索Top-50；BM25以标准问法及有限扩展文本检索Top-50。使用Milvus hybrid_search和RRFRanker(k=60)融合，保留足够候选供重排，候选按chunk_id去重。不能在应用层用自制RRF替代原生接口。过滤在两路检索之前生效。

用本地BAAI/bge-reranker-v2-m3对候选的query/passage对计算分数，取Top-10。锁定模型revision、校验文件并与BGE-M3共享受控CPU/GPU资源预算；现有CPU构建可先运行，评估报告记录实际设备与耗时，不冒称GPU。候选不足时返回实际数量，不补无关块。分数sigmoid仅为归一化相关性分数，不称为校准概率；拒答阈值从独立校准集决定，不套用第三章COSINE阈值。

## Prompt、引用与拒答

先按相关性确定证据集，再做首尾排布，例如名次1/3/5/.../.../6/4/2，让最相关的两块分居首尾；编号与chunk映射在本轮固定，重排布不能改变引用所指原文。预算不足按整块去掉低相关证据并重新执行充分性检查，不截断正文凑预算。

生成前模型结构化自评：sufficient、supported_facts、evidence_ids、reason；只使用本轮问题及检索证据。空召回、低分、模型判不足、无效证据ID均明确拒答，并幂等写low_confidence_questions。模型/检索服务不可用记录独立原因，不能伪装成知识确实不存在。知识类回答只有通过证据检查才能流式生成；原有物流/订单工具保持演示标识，不能当成政策证据。

System Prompt禁止承诺退款到账时间、未验证的补偿/赔付、无依据的发货时效、库存或价格保证；创建工单不等于退款执行成功。证据文本为数据而非指令。最终回答中知识性结论带[1]等编号，SSE提供本轮citation映射，校验编号合法性；无有效来源的引用不能显示为可点击链接。

提供来源读取接口，按实际chunk_id及内容版本返回answer原文、section_path、source_id等；只允许知识目录内受控来源定位，不接受任意文件路径。引用映射保存到该轮记录，避免刷新/后续重排导致编号错位；源文更新时显示版本状态，不把新正文冒充旧证据。保留SSE状态、token、done/error，并增加稳定turn_id/citations信息。

low_confidence_questions保存id、原话、conversation_id、turn_id、入池入口(retrieval/generation/system_error)、reason_code、reason、created_at；同一轮同一入口幂等。不保存密钥或内部异常堆栈。

## 评估

补充含具体型号及易混型号的合成商品知识与品类标签，至少60块，使Top-50测试有实际区分意义。固定语料快照、chunk ID及版本，不用线上用户隐私数据做评估。

构建带难度、query类型、标准答案、相关chunk_ids、是否应拒答的标注集：型号精确、口语同义、约束组合、跨块证据、品类干扰、无答案六桶；至少36题，校准集和测试集隔离。人工编写ground truth，模型可以辅助评判但不自己生成并宣称真值。

四策略：dense-only、BM25-only、hybrid RRF、hybrid RRF+rerank。共用同一问题预处理、语料、过滤及生成模板；只有检索策略不同。报告Recall@10/50、MRR@10，最终生成使用每策略Top-10预算内证据。另报告候选覆盖、延迟、回答覆盖率、拒答准确率及分桶样本量。无答案题不计入正例Recall/MRR分母，单独统计误答/拒答。

Faithfulness按回答中可核查原子声明被所给证据支持的比例计算，保存评判理由、模型版本及原始样例，抽查关键案例；空答/拒答单独统计，不当成100%忠实回答。保留评判失败/超时数量，不能丢样本后报好数字。四策略必须跑真实Milvus/BGE/reranker及真实生成，不用替身分数冒充实测；不承诺复杂策略必然优于小样本基线。

## 前端（Vibe Coding）

在现有页面加品类选择，引用编号点击展开本轮来源正文和章节路径，提供受控原文定位。正文继续安全渲染，不把来源当HTML注入。每条完成的assistant回答左下角放点赞/点踩：点击点亮、显示已反馈、两个按钮一次锁定。用turn_id为键记录前端本地事件并在刷新后保持锁定，不增加反馈后端表或上传接口。本章不做反馈分析平台。

## 验证和阶段记录

后端先失败测试后实现；Prompt/数据以标注集评估；前端直接改造后真实浏览器验证，不套页面TDD或code review。每完成阶段立即追记dev-notes/ch04.md四项要求。后端独立code review并修复后，执行全量回归、真实四策略报告及浏览器四项验收，交付命令、测试结果、日志和本地分支。

## Context7核实

已查询/milvus-io/milvus-docs：BM25需创建集合时配置，text启用analyzer，FunctionType.BM25，SPARSE_INVERTED_INDEX/BM25，AnnSearchRequest+hybrid_search+RRFRanker；内置chinese使用jieba/cnalphanumonly。已查询/flagopen/flagembedding：FlagReranker支持bge-reranker-v2-m3、query/passage批量compute_score及normalize。具体过滤模板、SDK3返回结构与其余框架接口在动手前继续查Context7并核对已安装版本。

## 自审

固定技术未替换；A品类选择已落实；元数据与正文分离；旧索引状态不能冒充新索引完成；型号不被改写损坏；同义词仅在查询侧；首尾布局与引用映射分开；拒答不能刷Faithfulness；前端例外单独执行。本设计尚待用户批准。
