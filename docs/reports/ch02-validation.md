# 第二章真实验证

日期：2026-10-19；固定模型 deepseek-flash，Docker MySQL 8.4.11。

- Edge 真实聊天页“订单1001的物流到哪了”：模型选择 query_logistics，徽章显示演示数据/已完成，回答依据返回位置。
- “退货政策是什么”：模型选择 query_faq，最终说明演示政策7天及退货运费责任。
- “邮费是多少”：模型选择 query_faq，字面 LIKE 未命中，未编造8元；保留为第三章升级前基线。
- 创建人工售后工单：模型选择 create_ticket，数据库真实产生工单，消息中保存原始 tool_calls 与对应 tool_call_id。
- 每轮 user / assistant(tool request) / tool / assistant(final) 均为 completed，按消息id保留顺序；真实数据库验证工单调用ID幂等。
- 当前完整回归 66 passed（3.77s），pip check 无冲突。数据库测试使用独立 support_test。
- 浏览器截图已查看，工具徽章位于回复气泡顶部；pageerror为空。页面按Vibe Coding例外，没有套TDD/code review。

初次退货验收未命中，原因是模型传入完整问句；补失败测试后仅移除问句虚词，保留字面检索限制，重新浏览器验证通过。第二章后端独立评审结论随后记录。

