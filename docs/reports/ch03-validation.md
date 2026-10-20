# 第三章验收记录

验收模型：BAAI/bge-m3，revision 5617a9f61b028005a4858fdac845db406aefb181；1024维 dense，CPU运行。MySQL 8.4.11，Milvus 3.0.0，PyMilvus 3.0.2。MySQL为原文权威源，Milvus只做单路COSINE检索。

## 已实测

- 标题层级、整句重叠、列表项、表格表头复制、元数据不进入向量、稳定主键均有回归验证。
- after_milvus_upsert真实中断：9 pending，重跑processed=9/embedded=9。
- after_mysql_commit真实中断：9 embedded + 1 pending，重跑processed=1/embedded=1；最终active pending=0。
- 独立6条标注校准样例，阈值0.65为6/6；另“邮费是多少 / 买满多少免运费 / 退货期限是多久”3条验收均通过。小演示集不代表生产准确率。
- Edge浏览器两轮：邮费8元、满99元包邮；相同conversation_id、气泡工具徽章、增量字数变化、SSE done、无页面异常全部通过。截图已查看。
- 合成种子真实DeepSeek挖掘：发布1条，重跑0条；暂存证据、发布知识与job完成状态已查MySQL确认。全量历史外发未运行。
- 最终独立后端复审通过，未发现剩余问题；页面按Vibe Coding直接改造。

- 完整回归78 passed；pip check无依赖冲突。实际curl SSE返回40个token事件。
- MySQL标注暂存评估：发布1、重复1、冲突2；docs/reports/ch03-mining-dedup.json。

## 证据

- ch03-browser.json / ch03-chat.png：浏览器与流式轨迹。
- ch03-dense-acceptance.json：真实模型三条召回及最终pending数。
- ch03-retrieval-calibration.json：6条标注、最高分原文及阈值比较。
- ch03-mining-demo.json：真实DeepSeek合成来源及MySQL记录。
- ch03-schedule.json：真实启动paused调度器后的下一次02:00注册时间，随后关闭验证实例。

## 复现

完整命令见仓库README第二、三章。默认dense；MySQL本机3307，Milvus19531，嵌入8001，聊天8000。采用这些端口避免本机其他项目冲突。

~~~powershell
.\.venv\Scripts\python -m pytest -q --basetemp artifacts/pytest-check
.\.venv\Scripts\python -m scripts.acceptance_knowledge
.\.venv\Scripts\python -m scripts.mine_knowledge --demo-only --no-sync --batch-size 1
.\.venv\Scripts\python -m scripts.mine_knowledge --demo-only --no-sync --show-schedule
~~~

API流式演示（PowerShell，UTF-8无BOM）：

~~~powershell
[IO.File]::WriteAllText("$PWD\artifacts\demo-chat.json", '{"message":"邮费是多少"}', [Text.UTF8Encoding]::new($false))
curl.exe -N http://127.0.0.1:8000/chat -H "Content-Type: application/json" --data-binary "@artifacts/demo-chat.json"
~~~

SSE meta返回conversation_id；后续请求带上同一conversation_id可继续多轮。
