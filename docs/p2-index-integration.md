# P2 VS Code Chat index integration

English | [中文](p2-index-integration.zh-CN.md)

Completed on 2026-10-23.

## Verified source format

All eight current `chat.ChatSessionStore.index` values use JSON version 1 with
top-level `version` and `entries` fields. `entries` is an object keyed by a
source-specific session identifier. Across the eight workspaces, 40 entries
were found. Every entry exposes the same field set, including `sessionId`,
`title`, and a 13-digit `lastMessageDate`.

No transcript location was proven during P2. All 40 VS Code records are
therefore represented as `index_only`, with `has_transcript=false` and
`turn_count=null`.

## Implementation

- VS Code index parsing is isolated in `VSCodeChatProvider`.
- Stable IDs combine provider, workspace ID, and URL-safe encoding of the
  source-specific index key.
- The unified v2 list combines existing Codex sessions with VS Code index
  sessions while retaining the legacy Codex endpoints.
- `GET /api/v2/sessions` supports `provider`, `workspace`, and
  `content_status` query filters.
- `GET /api/v2/sessions/<id>` returns an explicit transcript-not-located notice
  for index-only sessions.
- The frontend provides source, workspace, and content-state filters, source
  badges, and index-only detail pages.
- Metadata editing and relation controls are disabled for VS Code records until
  stable-ID metadata migration is implemented. Original source data remains
  read-only.

## Verified result

- Unified sessions returned: 43
- Codex/full: 3
- VS Code Chat/index-only: 40
- Distinct non-empty workspaces: 8
- Automated tests: 6 passed
- Frontend JavaScript syntax check: passed
