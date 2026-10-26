#!/usr/bin/env python3
"""Safely inventory Copilot CLI session-state format without printing content."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


CONTENT_FIELDS = {
    "content",
    "transformedContent",
    "reasoningText",
    "reasoningOpaque",
    "arguments",
    "result",
    "error",
    "message",
}


def inspect_events(path: Path) -> dict:
    event_counts = Counter()
    data_keys = defaultdict(Counter)
    data_types = defaultdict(lambda: defaultdict(Counter))
    bad_lines = 0
    line_count = 0
    min_line_bytes = None
    max_line_bytes = 0
    ids = {}
    parent_links = defaultdict(Counter)
    tool_requested = set()
    tool_started = set()
    tool_completed = set()
    interaction_types = defaultdict(Counter)
    session_id_matches_directory = False

    for raw in path.open("rb"):
        line_count += 1
        size = len(raw)
        min_line_bytes = size if min_line_bytes is None else min(min_line_bytes, size)
        max_line_bytes = max(max_line_bytes, size)
        try:
            obj = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            bad_lines += 1
            continue
        if not isinstance(obj, dict):
            bad_lines += 1
            continue
        event_type = str(obj.get("type", "<missing>"))
        event_counts[event_type] += 1
        event_id = obj.get("id")
        if isinstance(event_id, str):
            ids[event_id] = event_type
        data = obj.get("data")
        if not isinstance(data, dict):
            data_types[event_type]["<data>"][type(data).__name__] += 1
            continue
        if event_type == "session.start":
            session_id_matches_directory = data.get("sessionId") == path.parent.name
        for key, value in data.items():
            data_keys[event_type][key] += 1
            data_types[event_type][key][type(value).__name__] += 1
        interaction_id = data.get("interactionId")
        if isinstance(interaction_id, str) and interaction_id:
            interaction_types[interaction_id][event_type] += 1
        if event_type == "assistant.message":
            for request in data.get("toolRequests") or []:
                if isinstance(request, dict) and isinstance(request.get("toolCallId"), str):
                    tool_requested.add(request["toolCallId"])
        elif event_type == "tool.execution_start":
            if isinstance(data.get("toolCallId"), str):
                tool_started.add(data["toolCallId"])
        elif event_type == "tool.execution_complete":
            if isinstance(data.get("toolCallId"), str):
                tool_completed.add(data["toolCallId"])

    # Resolve parent types in a second streaming pass; values are never printed.
    for raw in path.open("rb"):
        try:
            obj = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        parent_links[str(obj.get("type", "<missing>"))][
            ids.get(obj.get("parentId"), "<none-or-external>")
        ] += 1

    return {
        "events_bytes": path.stat().st_size,
        "line_count": line_count,
        "bad_lines": bad_lines,
        "line_bytes": {"min": min_line_bytes or 0, "max": max_line_bytes},
        "session_id_matches_directory": session_id_matches_directory,
        "event_counts": dict(sorted(event_counts.items())),
        "data_schema": {
            event_type: {
                "keys": dict(sorted(data_keys[event_type].items())),
                "types": {
                    key: dict(sorted(types.items()))
                    for key, types in sorted(data_types[event_type].items())
                },
            }
            for event_type in sorted(event_counts)
        },
        "parent_event_types": {
            child: dict(sorted(parents.items()))
            for child, parents in sorted(parent_links.items())
        },
        "interaction_groups": {
            "count": len(interaction_types),
            "with_user": sum("user.message" in x for x in interaction_types.values()),
            "with_assistant": sum(
                "assistant.message" in x for x in interaction_types.values()
            ),
            "with_user_and_assistant": sum(
                "user.message" in x and "assistant.message" in x
                for x in interaction_types.values()
            ),
        },
        "tool_links": {
            "requested": len(tool_requested),
            "started": len(tool_started),
            "completed": len(tool_completed),
            "requested_without_start": len(tool_requested - tool_started),
            "start_without_complete": len(tool_started - tool_completed),
            "complete_without_start": len(tool_completed - tool_started),
        },
    }


def workspace_yaml_keys(path: Path) -> list[str]:
    keys = []
    if not path.is_file():
        return keys
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip().strip("\"'")
        if key and not key.startswith("-") and key not in keys:
            keys.append(key)
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session-root",
        type=Path,
        default=Path("~/.copilot/session-state").expanduser(),
    )
    parser.add_argument(
        "--full-schema",
        action="store_true",
        help="Include per-event field/type schema; values are still omitted",
    )
    args = parser.parse_args()
    root = args.session_root.expanduser()
    sessions = []
    for index, events_path in enumerate(sorted(root.glob("*/events.jsonl")), start=1):
        item = inspect_events(events_path)
        item["session_number"] = index
        item["workspace_yaml_keys"] = workspace_yaml_keys(
            events_path.parent / "workspace.yaml"
        )
        if not args.full_schema:
            item.pop("data_schema")
            item.pop("parent_event_types")
        sessions.append(item)
    result = {
        "mode": "structure_only_no_content",
        "session_root": str(root),
        "session_count": len(sessions),
        "total_event_lines": sum(x["line_count"] for x in sessions),
        "total_bad_lines": sum(x["bad_lines"] for x in sessions),
        "sessions": sessions,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if root.is_dir() else 1


if __name__ == "__main__":
    raise SystemExit(main())
