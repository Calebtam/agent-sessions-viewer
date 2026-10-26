"""Read-only discovery for VS Code workspace state databases.

Stored values are never returned: diagnostics expose only keys, types and sizes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse


CHAT_INDEX_KEY = "chat.ChatSessionStore.index"
RELEVANT_KEY_PATTERNS = ("chat", "copilot", "agentSessions")


def _workspace_location(workspace_file: Path) -> str:
    if not workspace_file.is_file():
        return ""
    try:
        data = json.loads(workspace_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    raw = data.get("folder") or data.get("workspace") or ""
    if not isinstance(raw, str):
        return ""
    parsed = urlparse(raw)
    return unquote(parsed.path) if parsed.scheme == "file" else raw


def inspect_workspace_database(db_path: Path) -> dict:
    """Return non-content diagnostics for one state.vscdb database."""
    result = {
        "database": str(db_path),
        "database_bytes": 0,
        "item_table": False,
        "chat_index": None,
        "relevant_keys": [],
        "status": "ok",
        "error": None,
    }
    try:
        result["database_bytes"] = db_path.stat().st_size
        uri = db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1) as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ItemTable'"
            ).fetchone()
            if not table:
                result["status"] = "no_item_table"
                return result
            result["item_table"] = True
            rows = conn.execute(
                "SELECT key, typeof(value), length(CAST(value AS BLOB)) FROM ItemTable"
            ).fetchall()
        for key, value_type, value_bytes in rows:
            key = str(key)
            if any(pattern.lower() in key.lower() for pattern in RELEVANT_KEY_PATTERNS):
                result["relevant_keys"].append(key)
            if key == CHAT_INDEX_KEY:
                result["chat_index"] = {
                    "key": CHAT_INDEX_KEY,
                    "value_type": str(value_type),
                    "value_bytes": int(value_bytes or 0),
                }
        result["relevant_keys"].sort()
        if result["chat_index"] is None:
            result["status"] = "no_chat_index"
    except FileNotFoundError:
        result["status"] = "missing"
        result["error"] = "database not found"
    except (sqlite3.Error, OSError) as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def discover_vscode_workspaces(user_dir: Path) -> dict:
    """Scan workspaceStorage and return a content-free diagnostic report."""
    user_dir = Path(user_dir).expanduser()
    storage = user_dir / "workspaceStorage"
    workspaces = []
    if storage.is_dir():
        for db_path in sorted(storage.glob("*/state.vscdb")):
            item = inspect_workspace_database(db_path)
            item["workspace_id"] = db_path.parent.name
            item["workspace"] = _workspace_location(db_path.parent / "workspace.json")
            workspaces.append(item)
    status_counts = {}
    for item in workspaces:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    return {
        "source": "vscode-chat",
        "mode": "read_only_diagnostics",
        "user_dir": str(user_dir),
        "workspace_storage_exists": storage.is_dir(),
        "database_count": len(workspaces),
        "chat_index_count": sum(item["chat_index"] is not None for item in workspaces),
        "status_counts": status_counts,
        "workspaces": workspaces,
    }
