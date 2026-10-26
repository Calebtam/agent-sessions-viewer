#!/usr/bin/env python3
"""Safe VS Code Chat index inventory and schema inspection.

Only structure, types, counts, workspace paths, and byte sizes are printed.
Entry keys, titles, session IDs, input state, and message content are omitted.
SQLite databases are opened with mode=ro.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from discovery import CHAT_INDEX_KEY, discover_vscode_workspaces


def index_shape(user_dir: Path) -> dict:
    storage = user_dir / "workspaceStorage"
    versions = Counter()
    field_types = defaultdict(Counter)
    top_level_keys = set()
    entry_count = 0
    parse_errors = 0

    for db_path in sorted(storage.glob("*/state.vscdb")):
        try:
            uri = db_path.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1) as conn:
                row = conn.execute(
                    "SELECT value FROM ItemTable WHERE key=?", (CHAT_INDEX_KEY,)
                ).fetchone()
            if not row:
                continue
            obj = json.loads(row[0])
            if not isinstance(obj, dict):
                parse_errors += 1
                continue
            top_level_keys.update(obj.keys())
            versions[f"{type(obj.get('version')).__name__}:{obj.get('version')}"] += 1
            entries = obj.get("entries", {})
            if not isinstance(entries, dict):
                parse_errors += 1
                continue
            for entry in entries.values():
                if not isinstance(entry, dict):
                    parse_errors += 1
                    continue
                entry_count += 1
                for field, value in entry.items():
                    field_types[field][type(value).__name__] += 1
        except (json.JSONDecodeError, sqlite3.Error, OSError, TypeError):
            parse_errors += 1

    return {
        "top_level_keys": sorted(top_level_keys),
        "versions": dict(sorted(versions.items())),
        "entry_count": entry_count,
        "entry_field_types": {
            field: dict(sorted(types.items()))
            for field, types in sorted(field_types.items())
        },
        "parse_errors": parse_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-dir",
        type=Path,
        default=Path("~/.config/Code/User").expanduser(),
        help="VS Code User directory (default: ~/.config/Code/User)",
    )
    parser.add_argument(
        "--include-workspaces",
        action="store_true",
        help="Include workspace IDs/paths and index sizes; never includes index values",
    )
    args = parser.parse_args()
    user_dir = args.user_dir.expanduser()
    inventory = discover_vscode_workspaces(user_dir)
    result = {
        "source": inventory["source"],
        "mode": inventory["mode"],
        "user_dir": inventory["user_dir"],
        "workspace_storage_exists": inventory["workspace_storage_exists"],
        "database_count": inventory["database_count"],
        "chat_index_count": inventory["chat_index_count"],
        "status_counts": inventory["status_counts"],
        "shape": index_shape(user_dir),
    }
    if args.include_workspaces:
        result["workspaces"] = [
            {
                "workspace_id": item["workspace_id"],
                "workspace": item["workspace"],
                "status": item["status"],
                "chat_index": item["chat_index"],
                "relevant_keys": item["relevant_keys"],
            }
            for item in inventory["workspaces"]
        ]
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if inventory["workspace_storage_exists"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
