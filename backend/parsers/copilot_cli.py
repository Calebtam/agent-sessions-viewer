"""Parse the verified Copilot CLI workspace.yaml + events.jsonl format."""

from __future__ import annotations

import ast
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ParseLimits:
    max_events_file_bytes: int = 256 * 1024 * 1024
    max_line_bytes: int = 2 * 1024 * 1024
    max_message_chars: int = 2_000_000
    max_tool_chars: int = 20_000
    max_attachment_chars: int = 100_000
    max_events: int = 2_000_000


@dataclass
class Tool:
    id: str
    name: str = "tool"
    arguments: object = None
    turn_id: str = ""
    interaction_id: str = ""
    success: bool | None = None
    result: object = None
    error: object = None
    started: bool = False
    completed: bool = False


@dataclass
class Interaction:
    id: str
    order: int
    user_id: str = ""
    user: str = ""
    transformed: str = ""
    timestamp: str = ""
    attachments: list = field(default_factory=list)
    assistant: list = field(default_factory=list)
    reasoning: list = field(default_factory=list)
    tool_ids: list = field(default_factory=list)
    aborted: bool = False
    errors: list = field(default_factory=list)


def _scalar(raw):
    value = raw.strip()
    if not value:
        return ""
    if value in ("null", "Null", "NULL", "~"):
        return None
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value[:1] in ("'", '"') and value[-1:] == value[:1]:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def load_workspace_yaml(path, max_bytes=1024 * 1024):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("workspace.yaml exceeds size limit")
    result = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        number, line = index + 1, lines[index]
        index += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace() or ":" not in stripped:
            raise ValueError(f"unsupported workspace.yaml at line {number}")
        key, value = stripped.split(":", 1)
        value = value.strip()
        if value in ("|", "|-", "|+", ">", ">-", ">+"):
            block = []
            while index < len(lines):
                candidate = lines[index]
                if candidate and not candidate[:1].isspace():
                    break
                index += 1
                block.append(candidate[2:] if candidate.startswith("  ") else candidate.lstrip())
            if value.startswith(">"):
                result[key.strip()] = " ".join(part.strip() for part in block).strip()
            else:
                result[key.strip()] = "\n".join(block).rstrip("\n")
        else:
            result[key.strip()] = _scalar(value)
    return result


def _text(value, limit):
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            value = str(value)
    return value if len(value) <= limit else value[:limit] + "\n…[truncated]"


def _append(parts, value, limit):
    value = _text(value, limit)
    if value and (not parts or parts[-1] != value):
        parts.append(value)


def _attachment(value, limit):
    if not isinstance(value, dict):
        return {"type": type(value).__name__}
    keep = ("type", "displayName", "filePath", "path", "selection")
    result = {key: value[key] for key in keep if key in value}
    if "text" in value:
        result["text"] = _text(value["text"], limit)
    return result


def _tool_summary(tool, limit):
    status = (
        "success" if tool.completed and tool.success is True
        else "error" if tool.completed and tool.success is False
        else "interrupted"
    )
    blocks = [f"Tool: {tool.name} ({status})"]
    for label, value in (
        ("Arguments", tool.arguments), ("Result", tool.result), ("Error", tool.error)
    ):
        text = _text(value, limit)
        if text:
            blocks.append(f"{label}:\n{text}")
    return "\n\n".join(blocks)


def parse_copilot_session(workspace_file, events_file, *, limits=None):
    limits = limits or ParseLimits()
    workspace_file, events_file = Path(workspace_file), Path(events_file)
    if events_file.stat().st_size > limits.max_events_file_bytes:
        raise ValueError("events.jsonl exceeds size limit")
    workspace = load_workspace_yaml(workspace_file) if workspace_file.is_file() else {}
    interactions = OrderedDict()
    turn_to_interaction = {}
    tools = {}
    warnings = []
    session_start = {}
    last_interaction = ""
    bad_lines = event_count = 0

    def get_interaction(interaction_id):
        if interaction_id not in interactions:
            interactions[interaction_id] = Interaction(interaction_id, len(interactions))
        return interactions[interaction_id]

    with events_file.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            event_count += 1
            if event_count > limits.max_events:
                raise ValueError("events.jsonl exceeds event limit")
            if len(raw) > limits.max_line_bytes:
                warnings.append(f"line_too_large:{line_number}")
                bad_lines += 1
                continue
            try:
                obj = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                warnings.append(f"invalid_json:{line_number}")
                bad_lines += 1
                continue
            if not isinstance(obj, dict) or not isinstance(obj.get("data"), dict):
                warnings.append(f"invalid_event:{line_number}")
                bad_lines += 1
                continue
            event_type, data = str(obj.get("type", "")), obj["data"]
            timestamp = str(obj.get("timestamp") or "")
            if event_type == "session.start" and not session_start:
                session_start = dict(data)
            elif event_type == "user.message":
                iid = str(data.get("interactionId") or obj.get("id") or "")
                if not iid:
                    warnings.append(f"user_without_interaction:{line_number}")
                    continue
                item = get_interaction(iid)
                if item.user:
                    warnings.append(f"duplicate_user:{iid}")
                item.user_id = str(data.get("messageId") or obj.get("id") or "")
                item.user = _text(data.get("content"), limits.max_message_chars)
                item.transformed = _text(data.get("transformedContent"), limits.max_message_chars)
                item.timestamp = timestamp
                item.attachments.extend(
                    _attachment(x, limits.max_attachment_chars)
                    for x in (data.get("attachments") or [])
                )
                last_interaction = iid
            elif event_type == "assistant.message":
                iid = str(data.get("interactionId") or last_interaction)
                if not iid:
                    iid = f"orphan:{obj.get('id', line_number)}"
                    warnings.append(f"assistant_without_interaction:{line_number}")
                item = get_interaction(iid)
                _append(item.assistant, data.get("content"), limits.max_message_chars)
                _append(item.reasoning, data.get("reasoningText"), limits.max_message_chars)
                turn_id = str(data.get("turnId") or "")
                if turn_id:
                    turn_to_interaction[turn_id] = iid
                for request in data.get("toolRequests") or []:
                    if not isinstance(request, dict):
                        continue
                    tool_id = str(request.get("toolCallId") or "")
                    if not tool_id:
                        continue
                    tool = tools.setdefault(tool_id, Tool(tool_id))
                    tool.name = str(request.get("name") or tool.name)
                    tool.arguments = request.get("arguments")
                    tool.turn_id = turn_id or tool.turn_id
                    tool.interaction_id = iid
                    if tool_id not in item.tool_ids:
                        item.tool_ids.append(tool_id)
                last_interaction = iid
            elif event_type == "tool.execution_start":
                tool_id = str(data.get("toolCallId") or "")
                if tool_id:
                    tool = tools.setdefault(tool_id, Tool(tool_id))
                    tool.started = True
                    tool.name = str(data.get("toolName") or tool.name)
                    tool.arguments = data.get("arguments", tool.arguments)
                    tool.turn_id = str(data.get("turnId") or tool.turn_id)
            elif event_type == "tool.execution_complete":
                tool_id = str(data.get("toolCallId") or "")
                if tool_id:
                    tool = tools.setdefault(tool_id, Tool(tool_id))
                    tool.completed = True
                    tool.success = data.get("success") if isinstance(data.get("success"), bool) else None
                    tool.result = data.get("result")
                    tool.error = data.get("error")
                    tool.turn_id = str(data.get("turnId") or tool.turn_id)
                    tool.interaction_id = str(data.get("interactionId") or tool.interaction_id)
            elif event_type == "abort" and last_interaction in interactions:
                interactions[last_interaction].aborted = True
            elif event_type == "session.error" and last_interaction in interactions:
                interactions[last_interaction].errors.append(
                    str(data.get("errorType") or "session_error")
                )

    for tool_id, tool in tools.items():
        iid = tool.interaction_id or turn_to_interaction.get(tool.turn_id, "")
        if not iid:
            warnings.append(f"orphan_tool:{tool_id}")
            continue
        item = get_interaction(iid)
        if tool_id not in item.tool_ids:
            item.tool_ids.append(tool_id)

    turns = []
    for item in sorted(interactions.values(), key=lambda value: value.order):
        reasoning = list(item.reasoning)
        reasoning.extend(
            _tool_summary(tools[tool_id], limits.max_tool_chars)
            for tool_id in item.tool_ids if tool_id in tools
        )
        context = item.transformed if item.transformed != item.user else ""
        if item.attachments:
            context = (context + "\n\nAttachments:\n" + json.dumps(
                item.attachments, ensure_ascii=False, indent=2
            )).strip()
        status = (
            "error" if item.errors else
            "interrupted" if item.aborted or not item.assistant else "complete"
        )
        turns.append({
            "id": item.user_id or f"interaction-{len(turns)}",
            "index": len(turns),
            "outlineTitle": " ".join(item.user.split())[:120] or "Assistant activity",
            "time": item.timestamp,
            "user": item.user,
            "user_context": context,
            "assistant": "\n\n".join(item.assistant),
            "reasoning": "\n\n".join(reasoning),
            "status": status,
            "toolCallCount": len(item.tool_ids),
        })

    directory_id = events_file.parent.name
    start_id = str(session_start.get("sessionId") or "")
    workspace_id = str(workspace.get("id") or "")
    identity_ok = bool(
        start_id and start_id == directory_id
        and (not workspace_id or workspace_id == directory_id)
    )
    if not identity_ok:
        warnings.append("session_identity_mismatch")
    return {
        "workspace": workspace,
        "session_start": session_start,
        "turns": turns,
        "event_count": event_count,
        "bad_lines": bad_lines,
        "warnings": warnings,
        "identity_ok": identity_ok,
        "tool_count": len(tools),
    }
