# Agent Sessions Viewer

English | [中文](README.zh-CN.md)

A lightweight web viewer for browsing and searching Codex agent session logs exported as JSONL files.

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
