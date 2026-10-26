# P0–P2 implementation and investigation playbook

English | [中文](p0-p2-playbook.zh-CN.md)

This document preserves the commands, scripts, reasoning, findings, safety
rules, and verification process used to implement P0, P1, and P2. It is the
starting point for later VS Code transcript research and P3–P5 work.

## 1. Scope and current outcome

P0 established a recoverable Codex baseline. P1 added read-only VS Code
workspace discovery and diagnostics. P2 parsed the verified VS Code Chat index
format and displayed its entries alongside Codex sessions.

Current verified result on 2026-10-23:

| Item | Result |
|---|---:|
| VS Code `state.vscdb` databases | 22 |
| Databases with `chat.ChatSessionStore.index` | 8 |
| Databases without the index | 14 |
| Parsed VS Code index entries | 40 |
| Codex sessions in the default directory | 3 |
| Unified sessions | 43 |
| VS Code transcript sessions | 0 confirmed |

The 40 VS Code records are indexes, not recovered transcripts. They must remain
`index_only` until a real transcript source and reliable association rule are
proven.

## 2. Safety and privacy rules

1. Open original SQLite databases with `mode=ro`.
2. Never execute `INSERT`, `UPDATE`, `DELETE`, schema changes, or SQLite repair
   commands against VS Code databases.
3. Structure diagnostics may print field names, types, counts, and byte sizes.
   They must not print titles, session IDs, input state, message content, token
   values, or complete database values.
4. Do not treat a key name as proof of content semantics.
5. Unknown counts are `null`, not zero.
6. A detected index is `index_only`; it is not `partial` or `full`.
7. New APIs must use the existing authorization checks.
8. The server binds to `127.0.0.1` by default. Network binding must be explicit.
9. `session_metadata.json` may contain access tokens. Never paste it into issue
   reports or diagnostic output.

For a consistent copy of a database that VS Code may be writing, use SQLite's
backup mechanism rather than a plain file copy:

```bash
mkdir -p "$HOME/vscode_chat_backup"
sqlite3 "$HOME/.config/Code/User/workspaceStorage/<workspace-id>/state.vscdb" \
  ".backup '$HOME/vscode_chat_backup/workspace-state.vscdb'"
```

The implemented P1/P2 readers normally do not need a copy because they open the
database read-only and tolerate individual database errors.

## 3. Reusable scripts

### 3.1 Safe inventory and index-shape inspection

Run the repository script:

```bash
python3 scripts/vscode_index_inventory.py
```

Include workspace IDs, decoded paths, relevant key names, and index sizes:

```bash
python3 scripts/vscode_index_inventory.py --include-workspaces
```

Inspect a non-default VS Code profile:

```bash
python3 scripts/vscode_index_inventory.py \
  --user-dir /path/to/Code/User \
  --include-workspaces
```

This script parses index JSON only to report its schema. It intentionally omits
all entry keys and values.

### 3.2 Complete P0–P2 verification

```bash
python3 scripts/verify_p0_p2.py
```

For a different VS Code profile:

```bash
python3 scripts/verify_p0_p2.py --user-dir /path/to/Code/User
```

The verifier runs unit tests, compiles backend modules, calls the Flask test
client, summarizes provider/status counts, and checks that an unauthenticated
remote request cannot access diagnostics. It does not start a listening server.

## 4. P0 process: establish the baseline

### 4.1 Inspect repository state

```bash
git status --short
git log -1 --oneline
rg --files -g '!node_modules/**' -g '!.git/**' -g '!dist/**' -g '!build/**'
```

The recoverable source baseline was Git commit `de9af4d`. The original metadata
file was preserved without modification.

Verify the working metadata still matches the Git baseline:

```bash
git show HEAD:session_metadata.json | sha256sum
sha256sum session_metadata.json
```

Baseline SHA-256 observed during P0:

```text
c2e899918863df561ca98b534f0078981807e1c5411909f15ef8fd7f743af0cb
```

### 4.2 Count default Codex sessions

```bash
find "$HOME/.codex/sessions" -type f -name '*.jsonl' -printf '.' \
  2>/dev/null | wc -c
```

P0 observed 3 files. Counts are machine-state dependent and may increase.

### 4.3 Baseline fixes and tests

P0 added parser fixtures for normal events, metadata, previews, tool calls, and
hidden environment context. It also reconciled the documented and implemented
address as `127.0.0.1:9001`.

Commands:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile \
  backend/app.py \
  backend/parser.py \
  backend/discovery.py \
  backend/models.py \
  backend/registry.py \
  backend/providers/base.py \
  backend/providers/vscode_chat.py
```

## 5. P1 process: discover VS Code databases safely

### 5.1 Locate candidate files

```bash
find "$HOME/.config/Code/User/workspaceStorage" -maxdepth 2 -type f \
  \( -name state.vscdb -o -name workspace.json \) -print | sort
```

### 5.2 Read only structural information

`backend/discovery.py` performs these logical steps:

1. Enumerate `workspaceStorage/*/state.vscdb`.
2. Decode `folder` or `workspace` from the adjacent `workspace.json`.
3. Connect through a URI ending in `?mode=ro`.
4. Check for `ItemTable` through `sqlite_master`.
5. Query key name, SQLite value type, and SQL-computed byte length.
6. Record relevant `chat`, `copilot`, and `agentSessions` keys.
7. Isolate errors per database.

Equivalent core SQL:

```sql
SELECT 1
FROM sqlite_master
WHERE type = 'table' AND name = 'ItemTable';

SELECT key, typeof(value), length(CAST(value AS BLOB))
FROM ItemTable;
```

The discovery layer never selects a complete value. P1's admin-only API is:

```text
GET /api/v2/diagnostics
```

Authorization checks used during verification:

```bash
PYTHONPATH=backend python3 - <<'PY'
import app
client = app.app.test_client()
print(client.get('/api/v2/diagnostics').status_code)
print(client.get(
    '/api/v2/diagnostics',
    environ_base={'REMOTE_ADDR': '10.0.0.2'},
).status_code)
PY
```

Expected with the current access configuration: local `200`, unauthenticated
remote `403`.

### 5.3 P1 failure modes covered

- Missing `workspaceStorage`: empty report, not a crash.
- Missing `ItemTable`: `no_item_table`.
- Database without Chat index: `no_chat_index`.
- Corrupt or locked database: isolated `error`; other databases remain visible.
- Text or binary index values: type/size reported without JSON assumptions.
- Missing or malformed `workspace.json`: workspace path remains empty.

## 6. P2 process: verify and parse the index

### 6.1 Schema discovery

The original investigation used a read-only Python/SQLite loop to aggregate
only JSON structure. Its maintained equivalent is:

```bash
python3 scripts/vscode_index_inventory.py
```

Verified across all eight indexes:

```text
top-level keys: entries, version
version: integer 1
entries: object
entry count: 40
```

Every current entry contained these fields:

```text
hasPendingEdits: bool
initialLocation: str
inputState: dict
isEmpty: bool
isExternal: bool
lastMessageDate: int
lastResponseState: int
permissionLevel: str
sessionId: str
timing: dict
title: str
```

`lastMessageDate` is consistently a 13-digit integer and is therefore converted
as Unix epoch milliseconds. The implementation uses UTC ISO time plus a
`YYYY/MM/DD` display date.

### 6.2 Stable identity

VS Code entries do not map to Codex JSONL paths. P2 uses:

```text
vscode-chat:<workspace-id>:<base64url(source-entry-key)>
```

The provider prefix prevents cross-source collisions, the workspace ID prevents
collisions between workspaces, and Base64 URL encoding avoids arbitrary path
construction. The source entry key is not shown by the safe inventory script.

### 6.3 Unified fields

Provider responses include canonical snake-case fields:

```text
id, provider, title, workspace, created_at, updated_at, source_path,
content_status, has_transcript, turn_count
```

Temporary camel-case compatibility fields remain for the existing frontend.
Codex sessions are `full`; VS Code index records are `index_only`.

### 6.4 APIs

```text
GET /api/v2/sessions
GET /api/v2/sessions?provider=vscode-chat
GET /api/v2/sessions?workspace=<exact-workspace-path>
GET /api/v2/sessions?content_status=index_only
GET /api/v2/sessions/<stable-id>
```

Legacy Codex endpoints remain intact. The frontend uses the v2 list, continues
to use the legacy detail endpoint for Codex, and uses the v2 detail endpoint for
VS Code index-only records.

### 6.5 Frontend behavior

- Source filter: all, Codex, VS Code Chat.
- Workspace filter populated from the unified list.
- Content-state filter: full, partial, index only, error.
- `VSC` card badge for VS Code records.
- Explicit “Index found; transcript not located” message.
- No empty transcript is presented as a real conversation.
- Metadata/relation editing is disabled for VS Code records until migration to
  stable metadata IDs is implemented.

Cross-source content search is not part of P2; it remains P5 work. Existing
search continues to cover Codex content.

## 7. Verification commands used after P2

Run all unit tests:

```bash
python3 -m unittest discover -s tests -v
```

Check frontend JavaScript syntax without starting a browser:

```bash
node -e "const fs=require('fs'),vm=require('vm');\
const h=fs.readFileSync('frontend/index.html','utf8');\
const s=[...h.matchAll(/<script(?: [^>]*)?>([\\s\\S]*?)<\\/script>/g)]\
.map(x=>x[1]).filter(Boolean);\
s.forEach(x=>new vm.Script(x));console.log('frontend scripts ok')"
```

API count/filter smoke test:

```bash
PYTHONPATH=backend python3 - <<'PY'
import app
client = app.app.test_client()
for url in (
    '/api/v2/sessions',
    '/api/v2/sessions?provider=vscode-chat',
    '/api/v2/sessions?provider=codex',
    '/api/v2/sessions?content_status=index_only',
):
    response = client.get(url)
    print(url, response.status_code, len(response.get_json()['sessions']))
PY
```

Review modifications:

```bash
git diff --check
git diff --stat
git status --short
```

## 8. Test coverage accumulated

`tests/test_parser.py`:

- Codex session metadata.
- Preview extraction.
- User/assistant events.
- Tool-call summaries.
- Hidden environment context suppression.

`tests/test_discovery.py`:

- Content-free index discovery.
- Correct workspace URI decoding.
- Corrupt-database isolation.
- Non-index database handling.
- Binary/non-JSON index diagnostics.
- Mapping the verified version-1 index shape into an `index_only` session.
- Loading an index-only detail with no fabricated turns.

## 9. File map

| File | Purpose |
|---|---|
| `backend/discovery.py` | Content-free P1 database diagnostics |
| `backend/models.py` | Unified field validation and timestamp conversion |
| `backend/registry.py` | Provider lookup and aggregation |
| `backend/providers/base.py` | Provider contract |
| `backend/providers/vscode_chat.py` | P1 diagnostics and P2 index parsing |
| `backend/app.py` | Legacy APIs, v2 APIs, access control, startup options |
| `frontend/index.html` | Unified list, filters, badges, index-only details |
| `tests/test_parser.py` | Codex regression tests |
| `tests/test_discovery.py` | P1/P2 fixtures and provider tests |
| `scripts/vscode_index_inventory.py` | Reusable safe inventory/schema report |
| `scripts/verify_p0_p2.py` | Repeatable P0–P2 verification |
| `docs/p0-p1-baseline.md` | Recorded P0/P1 result |
| `docs/p2-index-integration.md` | Recorded P2 result |

## 10. Handoff for later phases

Before attempting VS Code transcript recovery, collect evidence rather than
extending the current index parser speculatively:

1. Search for a transcript store using session IDs only in a private local
   analysis; do not publish the IDs.
2. Check VS Code global storage and extension-private storage read-only.
3. Record file types, schemas, and association fields before recording values.
4. Prove at least one user message and one assistant message belong to the same
   indexed session.
5. Add sanitized fixtures and failure cases.
6. Only then promote that session from `index_only` to `partial` or `full`.

For P3, Copilot CLI data must receive its own format investigation and provider;
it must not reuse the Codex parser merely because both may use JSONL.
