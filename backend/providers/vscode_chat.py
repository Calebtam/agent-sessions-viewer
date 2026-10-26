import base64
import json
import sqlite3
from pathlib import Path

from discovery import CHAT_INDEX_KEY, _workspace_location, discover_vscode_workspaces
from models import timestamp_fields, validate_session
from providers.base import SessionProvider


class VSCodeChatProvider(SessionProvider):
    """P1 provider: discovery only; index contents remain uninterpreted."""

    provider_id = "vscode-chat"

    def __init__(self, user_dir: Path):
        self.user_dir = Path(user_dir).expanduser()

    def discover(self):
        return discover_vscode_workspaces(self.user_dir)

    @staticmethod
    def _stable_id(workspace_id, source_id):
        encoded = base64.urlsafe_b64encode(source_id.encode("utf-8")).decode("ascii").rstrip("=")
        return f"vscode-chat:{workspace_id}:{encoded}"

    @staticmethod
    def _read_index(db_path):
        uri = db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1) as conn:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key=?", (CHAT_INDEX_KEY,)
            ).fetchone()
        if not row:
            return None
        parsed = json.loads(row[0])
        if not isinstance(parsed, dict) or parsed.get("version") != 1:
            raise ValueError("unsupported VS Code chat index version")
        entries = parsed.get("entries")
        if not isinstance(entries, dict):
            raise ValueError("VS Code chat index entries must be an object")
        return entries

    def discover_sessions(self):
        storage = self.user_dir / "workspaceStorage"
        sessions = []
        if not storage.is_dir():
            return sessions
        for db_path in sorted(storage.glob("*/state.vscdb")):
            try:
                entries = self._read_index(db_path)
            except (json.JSONDecodeError, sqlite3.Error, OSError, TypeError, ValueError):
                continue
            if entries is None:
                continue
            workspace_id = db_path.parent.name
            workspace = _workspace_location(db_path.parent / "workspace.json")
            for source_id, entry in entries.items():
                if not isinstance(source_id, str) or not isinstance(entry, dict):
                    continue
                date, updated_at = timestamp_fields(entry.get("lastMessageDate"))
                title = str(entry.get("title") or "Untitled VS Code Chat").strip()
                is_new_chat = title.casefold() == "new chat"
                stable_id = self._stable_id(workspace_id, source_id)
                sessions.append(validate_session({
                    "id": stable_id,
                    "path": stable_id,
                    "provider": self.provider_id,
                    "providerLabel": "VS Code Chat",
                    "title": title,
                    "name": title,
                    "fullName": title,
                    "shortName": title,
                    "originalName": title,
                    "sessionId": str(entry.get("sessionId") or source_id),
                    "workspace": workspace,
                    "workspaceId": workspace_id,
                    "cwd": workspace,
                    "date": date,
                    "updatedAt": updated_at,
                    "updated_at": updated_at,
                    "created_at": None,
                    "source_path": str(db_path),
                    "content_status": "index_only",
                    "has_transcript": False,
                    "turn_count": None,
                    "contentStatus": "index_only",
                    "hasTranscript": False,
                    "turnCount": None,
                    "sessionType": "session",
                    "previewQuestions": [],
                    "tags": [],
                    "category": "",
                    "pinned": False,
                    "archived": False,
                    "readOnlyMetadata": True,
                    "isNewChat": is_new_chat,
                    "canDelete": False,
                }))
        sessions.sort(key=lambda item: (item.get("updatedAt") or "", item["id"]), reverse=True)
        return sessions

    def load(self, session_id):
        for item in self.discover_sessions():
            if item["id"] == session_id:
                return {
                    "session": item,
                    "turns": [],
                    "offset": 0,
                    "limit": 0,
                    "total": 0,
                    "hasMore": False,
                    "outline": [],
                    "relations": {"masters": [], "subagents": [], "references": [], "manual": []},
                    "notice": "This VS Code Chat session was found in the index, but its message transcript has not been located.",
                }
        return None
