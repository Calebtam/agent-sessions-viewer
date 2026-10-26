# P0/P1 baseline and diagnostics

English | [中文](p0-p1-baseline.zh-CN.md)

Recorded on 2026-10-23 before multi-provider session-list integration.

## P0 baseline

- Recoverable source baseline: Git commit `de9af4d`.
- `session_metadata.json` was not modified. Baseline SHA-256:
  `c2e899918863df561ca98b534f0078981807e1c5411909f15ef8fd7f743af0cb`.
- Codex JSONL files discovered by the default configuration: 3.
- Baseline API smoke test:
  - `GET /`: HTTP 200
  - `GET /api/sessions`: HTTP 200, 3 sessions
- Automated parser/discovery tests: 5 passed.
- Default server address is now consistently documented and configured as
  `127.0.0.1:9001`.

The Git baseline and metadata checksum are the rollback reference. No original
Codex, VS Code, or Copilot data was written or copied.

## P1 VS Code diagnostics

- VS Code workspace databases found: 22.
- Databases containing `chat.ChatSessionStore.index`: 8.
- Databases without that key: 14.
- Database read/format errors: 0.
- `GET /api/v2/diagnostics`: HTTP 200 for a local administrator.
- The same endpoint: HTTP 403 for a simulated unauthenticated remote request.

The earlier analysis documented two known indexed workspaces. The P1 scanner
found six additional indexed workspaces in the current machine state. This is
not a contradiction: the earlier two were confirmed examples, not an asserted
upper bound.

The diagnostic implementation opens SQLite databases with `mode=ro`. It reads
key names plus SQL-computed value type/byte length and never returns or parses
the stored values. Individual database errors are isolated so one bad database
does not prevent other workspaces from being reported.

This phase intentionally does not parse the index JSON or expose sessions from
it. That belongs to P2 after the real index shape is inspected and tested with
sanitized fixtures.
