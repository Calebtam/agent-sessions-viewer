# Agent Sessions Viewer

English | [中文](README.zh-CN.md)

A lightweight web viewer for browsing and searching Codex agent session logs exported as JSONL files.

## Version v0.0.2

### Implemented changes

- Session directory enhancements: support Pin/Unpin, Archive/Unarchive, tag editing, and display tags and subagent identifiers on cards.
- Detail page left navigation: split into Session, Related sessions, and Outline sections.
- Related sessions: automatically show parent/subagent relationships and support Add relation to manually connect other sessions.
- Conversation outline: list user questions by turn and jump to the corresponding section.
- Search enhancements: search results include turnIndex so clicking jumps to the target turn.
- Reading experience improvements: each turn supports Copy turn, code blocks support Copy, and Thinking remains collapsible.
- API pagination: /api/session/<path>?offset=0&limit=50 returns paginated turns, outline, relations, and session metadata.
- Frontend rendering optimization: uses content-visibility:auto for native browser virtualization, making long sessions lighter to browse.
- Parser unit tests: added tests/test_parser.py covering normal events, IDE context, guardian approval, and tool summaries.

## Features

- Browse all sessions from a configured session directory
- View a session overview grouped by date
- Open detailed chat-style views for each session
- Search across session titles, filenames, preview questions, user prompts, assistant replies, and reasoning content
- Rename displayed session names without changing the original files
- Toggle between dark and light themes

## Project Structure

- backend/app.py: Flask API server and session endpoints
- backend/parser.py: parser for loading and formatting session data
- frontend/index.html: single-page frontend UI
- session_metadata.json: custom display names for sessions

## Quick Start

1. Install dependencies

   ```bash
   pip install flask
   ```

2. Start the backend server

   ```bash
   cd backend
   python3 app.py
   ```

   The server will run at http://127.0.0.1:9000.

3. Open the frontend

   ```bash
   xdg-open frontend/index.html
   ```

   If your browser blocks local file access, you can also open the generated page through the backend entry at http://127.0.0.1:9000/.

## Configuration

The backend reads session files from the default directory:

```bash
~/.codex/sessions
```

You can override it with:

```bash
cd backend
python3 app.py --session_dir /path/to/your/sessions
```

## Notes

- Session files are expected to be JSONL files under the configured session directory.
- The viewer uses metadata stored in session_metadata.json to give sessions custom display names.
