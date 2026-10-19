# 第 1 章 Code review

## 初审

评审方式：按 Superpowers requesting-code-review，独立只读 reviewer；实现仍在主会话完成。
评审范围：0901dc2..b9b9706。

优点：真实增量 SSE 有 socket 验证；错误信息脱敏；完整问答裁剪；结构化结果对原始完整 JSON 和 schema 双重检查；密钥未纳入跟踪。

Critical：无。Important：两项。

1. done 发送失败时，历史已提前提交。通过 ASGI send 在 done 时抛 OSError 确定性复现。修复为生成器在 done 成功发送并恢复执行后才提交。
2. 生成器与响应层重复释放会话。最终 HTTP body 发送等待期间，新请求可获得会话，旧响应 finally 再清除新请求 busy。评审者独立确定性复现。修复为 SessionResponse 唯一释放，忙碌状态覆盖最终发送与清理。

初审结论：有修复前不可交付，问题已即时追记 dev-notes。

## 修复后定点复核

修复提交：535e463。

同一独立 reviewer 核查两项修复与新增回归测试，独立运行对话测试：18 passed（2.08s）。结论：两项 Important 已解决；此次定点复核无遗留 Critical / Important / Minor，批准范围内可交付。

最终完整回归由主会话运行：51 passed；真实 DeepSeek 三项验收重新通过。最终数据见 ch01-validation.md。

