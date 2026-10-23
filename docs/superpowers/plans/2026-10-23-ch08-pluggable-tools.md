# Chapter 8 Pluggable Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Inline execution/current branch is already chosen.

**Goal:** Unified, hot discoverable built-in/MCP tools with enforced write confirmation and durable audit.
**Architecture:** ToolRuntime maintains trusted registrations and per-turn frozen catalogs. ToolEngine validates JSON Schema, applies local policy and executes with bounded retries; Workflow owns durable ticket previews and interrupt/resume.
**Tech Stack:** FastAPI/SQLAlchemy/MySQL, LangGraph/official PG saver, mcp1.28.0, langchain-mcp-adapters0.3.2, jsonschema4.26.0.
**Spec:** docs/superpowers/specs/2026-10-23-ch08-pluggable-tools-design.md (approved 2026-10-23).

## Global Constraints

- Only builtin:create_ticket may write; no write retries, no confirmation manufactured by LLM.
- MCP transport Streamable HTTP via official SDK/adapters; mocked independent servers, no business database.
- External descriptions/annotations never grant permission. Unknown local permissions deny.
- query_faq contract unchanged; full tool results stay checkpoint, MySQL markers only.
- Existing complaint button keeps its one-confirmation interaction; new Agent path uses preview interrupt.
- State stores serializable descriptions/versions only; actual tool prefix recalculated on catalog change.
- Current branch retained, no push/merge; ch04 notes/original CSV/knowledge-incoming excluded.
- Backend TDD; prompt fixtures evaluated; frontend Vibe, browser checked without UI TDD/review.

## Task 1: Registration, schema and local policy

Files: app/tooling/catalog.py, policy.py, runtime.py, __init__.py; config/tool-policy.json, tool-plugins.json; tests/test_tool_catalog.py.
Interfaces: ToolSpec(name,description,parameters,source,invoke,project=None); Catalog.register(spec), replace_source(source,specs), snapshot()->dict[str,ToolSpec]; LocalPolicy.load()->mapping; permits(spec)->read/write/None. Runtime.refresh() loads trusted local modules and MCP discovery, freezes versioned descriptions; bind(context,version)->Registry-compatible tools.

- [ ] Write tests for name collision, invalid Schema, missing metadata, parameter schema retained, forged readOnlyHint denied, local permissions hot reload and builtin module registration. Example:
~~~python
catalog.register(spec_a)
with pytest.raises(ValueError): catalog.register(spec_same_name_other_source)
assert policy.access('mcp:unknown','create_ticket') is None
~~~
- [ ] Run .venv/Scripts/python -m pytest tests/test_tool_catalog.py -q; missing-module failure must precede implementation.
- [ ] Install preflight-compatible pinned dependencies, add pyproject requirements, implement catalog/policy; no Agent edits yet. Update lock from installed metadata without secrets.
- [ ] Re-run targeted tests, log Task1 and commit.

## Task 2: Unified engine and SQL audit

Files: app/tooling/engine.py, models.py, audit.py, builtin.py; app/db.py; tests/test_tool_engine.py, test_tool_audit.py.
Interfaces: ToolEngine(catalog,policy,audit,timeout,attempts).execute(call,context,grant=None)->dict; ExecutionGrant immutable/call+args+cid scoped, created only by confirmed server flow; audit.upsert(record) best effort.
- [ ] Red tests: invalid type/required/bounds prevents handler, unknown tool audited, missing grant rejects write, transient read retries twice, business empty once, write timeout retry_count0, audit failure does not change successful result.
~~~python
result=await engine.execute({'name':'create_ticket','args':args,'id':'c'},ctx)
assert result['error']['code']=='permission_denied'
assert await ticket_count()==0
~~~
- [ ] Run targeted tests to observe missing implementation, implement real JSON Schema errors with paths, timeout/retry taxonomy, Chinese JSON projection, builtin adapters, no FK audit table.
- [ ] Real MySQL tests verify success/validation/permission/timeout rows, same call retry one row and duration/count; run old tool tests for legacy characterization. Log Task2/commit.

## Task 3: Two MCP servers and per-server discovery

Files: mcp_servers/logistics.py, aftersales.py; app/tooling/mcp.py; runtime.py; tests/test_tool_mcp.py; scripts/serve_mcp.py; app/config.py.
Interfaces: MCPDiscovery.refresh()->dict[source,list[ToolSpec]], bounded per-server; transport errors preserved; each ToolSpec wrapper adapts structured/text content without inferring permissions.
- [ ] Red integration starts two subprocesses on test ports and verifies query_logistics source, warranty/return tools, no duplicate builtin logistics, one failed server isolated. Stop/restart only logistics with additional registered test tool; next discovery sees it.
- [ ] Run red; implement SDK FastMCP instances and adapters get_tools(server_name=...), health-independent discovery errors, mock data/demo flag, no MySQL import in servers.
- [ ] Verify actual HTTP discovery/calls and source/Schema/policy; pinned API signatures inspected after Context7. Log Task3/commit.

## Task 4: Chat integration, dynamic prefix and audit coverage

Files: app/workflow/common.py, agent.py, graph.py, service.py, state.py, rules.py; app/main.py, memory/manager.py, assembly.py; tests/test_tool_workflow.py.
Interfaces: WorkflowService.tool_runtime; State.tool_catalog/version serializable; tools_for binds frozen catalog to per-turn ToolContext; execute_call used by Agent, query_order and complaint action.
- [ ] Red tests: newly registered read tool is visible and callable without Agent changes, MCP logistics executes, all calls audited, extra/forbidden calls rejected and audited; catalog Schema changes trigger prefix recomputation and budget failure if too large.
- [ ] Run red, wire runtime only after real lifecycle DB initialization; remove active hardcoded names/LABELS lookups, keep source and route policy. Refund eligibility still prohibits opportunistic tools after mandatory policy.
- [ ] Add status-query routing test (warranty/return progress, selector if no order); generic policies retain RAG and intent JSON two-field contract.
- [ ] Run chapter5/6/7 targeted regression; log Task4/commit.

## Task 5: Explicit ticket intent and durable preview

Files: app/tooling/tickets.py; app/workflow/ticket_flow.py, service.py, graph.py, api.py, state.py, repository.py; tests/test_ticket_preview.py; evals/ch08-ticket-intent.jsonl; scripts/evaluate_ticket_intent.py.
Interfaces: explicit_ticket_request(text)->bool, pending user request tracked in State; PreviewStore.prepare/confirm/cancel/supersede with frozen args/hash/version/call; service.prepare_ticket_resume(cid,tid,preview_id,confirmed)->Turn; POST /workflow/ticket-preview.
- [ ] Red real graph/DB tests: bare request asks description with no ticket; supplied facts create preview only; true confirm creates once/receipt, false confirm no write+permission audit; replay/foreign/stale previews rejected or idempotently replayed; new message supersedes preview and resumes ordinary chat without orphan tool messages.
- [ ] Run red; implement separate interrupt node with idempotent preparation and engine grant only after server validates click. Model arguments cannot manufacture grant; missing description cannot be guessed.
- [ ] Evaluate labeled explicit/negated/quoted/hypothetical/bare/continuation cases; inspect true model supplement/preview behavior. Old complaint button passes its existing confirmation through engine without second preview.
- [ ] Verify pending checkpoint survives reopening official PG saver, memory histories remain separate; log Task5/commit.

## Task 6: Preview card UI (Vibe)

Files: app/web/index.html; scripts/acceptance_tools_browser.cjs.
- [ ] Render ticket preview from SSE/state, confirm/cancel each locked after click; refresh restores pending preview.
- [ ] Confirm resumes SSE and displays ticket number; cancel shows cancelled without ticket; plain new message behaves normally. Existing complaint buttons/order cards remain.
- [ ] Real installed Edge checks both flows, source tool badges, duplicate clicks and refresh. No frontend TDD/review; log Task6/commit.

## Task 7: Full acceptance, independent review and finish

Files: scripts/acceptance_tools.py; docs/reports/ch08-*; README/.env.example/dev-notes/ch08.md.
- [ ] Independent read-only backend review through requesting-code-review; Important red/green fix and re-review, no frontend review.
- [ ] All pytest, pip check, live upstream query logistics/aftersales, new builtin registration and MCP Server-only restart (prove customer PID unchanged), ticket supplement/confirm/cancel SQL counts.
- [ ] Fault-injection readonly timeout audited with retry_count1; write timeout audited retry_count0. Production mock defaults unchanged.
- [ ] Document complete demo commands, results/limits, write incremental finish, retain current branch.

## Plan self-review

Spec1-3 covered Task1/3/4, spec4-5 Task2/4, spec6 Task3/4, spec7 Task5/6, spec8 Task7. Interfaces/version fields consistent. No change to chosen architecture or models; no unresolved dependency conflict in pip dry-run. Plan review passed; proceed inline through executing-plans, no repeated execution-choice question.
