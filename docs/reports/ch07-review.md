# Chapter 7 backend review

Scope: 6046d94..0addf1f, frontend excluded by approved Vibe scope. Independent read-only reviewer ch07_backend_review.

Initial verdict: With fixes; no Critical; five Important findings.

1. Atomic summary/anchor snapshot: added MemoryRepository.context_snapshot with one consistent-read transaction; race regression.
2. Failed/cancelled checkpoint turns: filter by authoritative completed IDs before completeness check; mixed-turn regression.
3. Exhausted expired leases: mark failed during claim so new ranges are not blocked; real MySQL regression.
4. Ticket confirmation projection: MySQL marker-only write, stable message IDs, all statuses finalized; independent official checkpoint thread preserves paused cursor and merges on next ordinary turn. Legacy completed runs supply authoritative completion and worker repairs protocol ordering. Real MySQL + graph regression.
5. Complete rounds above 4000: batch preference no longer rejects a single round; actual summary prompt/background/output/safety are measured against configured model window. Retained raw_result metadata is not reintroduced as if it had been shown to the model. Large-round regression.

Minor: tool markers can include tool name and outcome more explicitly; follow-up tracked.

Additional real acceptance failure: decision node emitted prose. Added Workflow-only JSON response_format and protocol regression. Two interrupted first attempts are not acceptance passes.

Re-review pending; real default/demo 24-round acceptance pending.
