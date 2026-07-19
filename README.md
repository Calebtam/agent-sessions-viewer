# Agent Sessions Viewer

English | [中文](README.zh-CN.md)

A lightweight web viewer for browsing, organizing, searching, and sharing Codex agent session logs stored as JSONL files.

## Version v0.0.3

v0.0.3 builds on v0.0.2 and focuses on session organization, multi-column reading, subagent relationship modeling, remote access control, and outline-aware reading.

### Highlights

- Category management
  - Home page supports grouping by date or category.
  - Categories can be created, renamed, and deleted.
  - Session cards and detail pages include category selectors.
  - Category metadata is stored in `session_metadata.json`; original `.jsonl` files are not modified.

- Relationship model
  - Related sessions are split into `Masters`, `Subagents`, and `References`.
  - Subagents are detected from `parent_thread_id`, `thread_source`, and source metadata.
  - Multi-level subagent trees are supported.
  - Duplicate `session_id` edge cases are handled using file-level IDs so a subagent is not mistaken for itself.
  - Manual related sessions are treated as removable references.

- Detail page navigation
  - The detail page uses a dedicated left navigation with Session, Relations, and Outline sections.
  - The outline highlights the currently visible turn while scrolling.
  - The active outline item automatically scrolls into view.
  - Clicking an outline item jumps to the corresponding turn.

- Layout controls
  - Detail pages support 1-column, 2-column, and 3-column modes.
  - The selected layout is persisted in `localStorage`.
  - The layout switch is placed according to the current column mode.

- Remote access control
  - `/admin` opens the access management page.
  - Local requests are treated as admin by default.
  - Remote admin access uses scoped admin tokens.
  - Guest access controls sessions visible without a token.
  - Viewer tokens can be generated or customized and can each expose a different session set.
  - Admin tokens can manage remote access and token configuration.
  - When remote restriction is enabled, list, search, details, and relation data are filtered by the active token.

- Search and reading improvements
  - Search covers titles, filenames, tags, previews, user prompts, assistant replies, and thinking content.
  - Search results can jump to the matched turn.
  - Each turn supports Copy turn.
  - Code blocks support Copy.
  - Thinking remains collapsible.
  - Long sessions use `content-visibility:auto` for lighter rendering.

- API and parser improvements
  - `/api/sessions` returns sessions and categories.
  - `/api/categories` supports create, rename, and delete.
  - `/api/access` supports remote policy, guest access, token generation, and token updates.
  - `/api/session/<path>?offset=0&limit=50` returns paginated turns, outline, relations, and session metadata.
  - Guardian approval sessions are summarized instead of rendering the full transcript as a normal user message.
  - Parser unit tests cover normal events, IDE context, guardian approval, and tool summaries.

## Features

- Browse all sessions from a configured session directory.
- View a session overview grouped by date or category.
- Organize sessions with display names, tags, categories, pinning, and archive state.
- Open detailed ChatGPT-style views for each session.
- Inspect master/subagent/reference relationships.
- Search across visible session content.
- Rename displayed session names without changing original session files.
- Toggle between dark and light themes.
- Configure remote visibility with guest access and scoped tokens.

## Project Structure

- `backend/app.py`: Flask API server, metadata handling, access control, session endpoints.
- `backend/parser.py`: parser for loading and formatting session JSONL data.
- `frontend/index.html`: single-page frontend UI.
- `session_metadata.json`: local metadata for display names, tags, categories, relations, and access settings.
- `tests/test_parser.py`: parser unit tests.

## Quick Start

1. Install dependencies

   ```bash
   pip install flask
   ```

2. Start the backend server

   ```bash
   cd agent-sessions-viewer/backend
   python3 app.py
   ```

   The server runs at:

   ```text
   http://127.0.0.1:9000/
   ```

3. Use a custom session directory

   ```bash
   cd agent-sessions-viewer/backend
   python3 app.py --session_dir /path/to/your/sessions
   ```

## Admin and Remote Access

Open the admin page locally:

```text
http://127.0.0.1:9000/admin
```

Remote admin access uses an admin token:

```text
http://<server-ip>:9000/admin?token=<admin-token>
```

Access model:

- `Guest`: controls what remote visitors can see without a token.
- `Viewer token`: allows remote read-only access to a configured session set.
- `Admin token`: allows remote access to `/admin` and access configuration.

When remote restriction is disabled, remote visitors can see all non-archived sessions. When enabled, remote visibility is limited by Guest or the active token.

## Metadata

The viewer writes local metadata to:

```text
agent-sessions-viewer/session_metadata.json
```

This file may contain:

- Display names
- Tags
- Categories
- Pins and archive flags
- Reference relations
- Access-control settings

The original Codex `.jsonl` session files are never modified.

## Testing

Run parser tests:

```bash
python3 -m unittest tests/test_parser.py
```

Compile backend files:

```bash
python3 -m py_compile agent-sessions-viewer/backend/app.py agent-sessions-viewer/backend/parser.py
```

## Notes

- Session files are expected to be JSONL files under the configured session directory.
- The Flask app is a lightweight local tool. If exposed to a network, enable remote restriction and use admin/viewer tokens deliberately.
