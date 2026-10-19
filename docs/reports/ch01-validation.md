# 第 1 章验证记录

日期：2026-10-19（Asia/Shanghai）。上游：DeepSeek 官方直连，模型 deepseek-flash，非思考模式；密钥未记录。

## 自动化测试

执行：.venv/Scripts/python.exe -m pytest -q --basetemp artifacts/pytest

当前结果：49 passed（2.41s）。覆盖配置预算、密钥掩码、真实模型适配层请求与 schema 校验、内存会话与裁剪、SSE、两轮与隔离、错误回滚、TTL/容量、真实 socket 增量/断流、提取错误映射、验收脚本解析。

依赖检查：.venv/Scripts/python.exe -m pip check → No broken requirements found.

## 真实 DeepSeek 验收

执行：.venv/Scripts/python.exe -m scripts.acceptance --show-stream

- SSE：通过。首轮 96 个实时 token 事件，首片段约 0.470s，完整流约 1.215s。
- 多轮：通过。第二轮沿用相同会话 ID，正确回答首轮订单号 DS20261019001；10 个 token 事件。
- 结构化 JSON：通过。返回 order_id=DS20261019001、request_type=换货、expected_solution=换同款新的。
- curl.exe -N：实际调用成功，SSE 逐事件输出，原始事件保存于 ch01-curl-stream.txt。
- curl 提取：实际调用成功，返回上述三个固定字段。

完整验收结果见 ch01-acceptance.json。耗时与模型文本仅代表本次样例，不代表性能承诺。

## Prompt 标注评估

8 条提取样例：离散字段 8/8；期望方案按原意逐例核对 8/8。4 条客服行为样例：4/4，包含不虚构退款、政策、物流以及不索取凭证。

多诉求样例比标注多保留“没有优先顺序”，语义与原文一致。语义结论由当前会话按提供的 rubric 逐例审阅，不是脚本仅凭退出码推断，也未伪称用户人工签字。逐例输出与说明见 ch01-prompt-evaluation.json。

## 限制

预算是 UTF-8 字节保守估算；SSE token 是上游文本片段。只验收 DeepSeek，其他厂商需核实各自官方协议与模型能力。会话为单进程内存，重启清空。

## Code review 与最终复核

本记录为评审前验证证据，独立评审与最终复核结论将在实际完成时追加。

