# 第五章验收记录 · 2026-10-21

真实上游为.env配置的deepseek-flash，复用BGE-M3、Milvus原生BM25/RRF与bge-reranker-v2-m3；业务MySQL，独立PostgreSQL16+官方AsyncPostgresSaver。无模型/检索/数据库替身的完整检查7/7通过，见[ch05-ch06-real.json](ch05-ch06-real.json)。

- 框架外裸循环：先query_order后query_logistics，再收敛，原始记录artifacts/ch05-bare.json。
- 确定性父图：normalize→intent→分流。白名单你好仅normalize/fixed_response/log，usage模型调用0；投诉固定安抚并提供两个独立选项，没有Agent。
- 政策：retrieve→confidence_gate先于agent_decide；有引用并能打开当轮快照。
- 物流：Agent自己选query_logistics，不走预检索。
- 复杂问题：query_order→模型再次决定→query_logistics→模型收敛，两个业务工具实际执行。
- 真实浏览器：转人工纯前端；确认工单调用原create_ticket，投诉会话只写tickets1条，refunds0条，详见[ch06-browser-real.json](ch06-browser-real.json)。
- 官方Saver关闭连接重开仍能取状态，同会话PG会话锁跨连接互斥；真实应用进程停止后恢复见[ch06-restart.json](ch06-restart.json)。

后端独立只读review共6项Important整改通过，末轮首帧取消补充已验证；未对前端做code review。首轮真实验收错误、修复实验与每阶段记录保留在dev-notes/ch05.md。

边界：当前演示用户/订单/物流，不含生产认证、实际电商接口、真实坐席和支付退款；本章交付编排与恢复架构。检查点与MySQL不是分布式事务，以稳定ID、幂等记录、恢复时投影协调处理。Windows专用启动器使用Selector事件循环。PG默认官方镜像，本机验收使用缓存的pgvector/pgvector:pg16创建独立实例，只使用PostgreSQL、不启用扩展。

演示命令与启动顺序见README第五、六章；自动化结果见最终测试记录，阶段留痕dev-notes/ch05.md。


最终自动化：137 passed in 17.52s；pip check无损坏依赖。结果汇总见[ch05-ch06-tests.json](ch05-ch06-tests.json)。最终18000服务健康检查与完整问候SSE验证通过。
