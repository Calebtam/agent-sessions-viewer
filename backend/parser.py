import json
import re
from pathlib import Path


HIDDEN_USER_PREFIXES = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<turn_aborted>",
)

HIDDEN_EXACT_TAGS = {
    "<turn_aborted>",
    "</turn_aborted>",
    "<environment_context>",
    "</environment_context>",
}


def _is_hidden_user_message(text):
    stripped = text.strip()
    if not stripped:
        return True
    if any(stripped.startswith(prefix) for prefix in HIDDEN_USER_PREFIXES):
        return True
    if stripped in HIDDEN_EXACT_TAGS:
        return True
    return False


def _append_assistant(cur, text, kind="answer"):
    if not text:
        return cur
    if cur is None:
        cur = {"user": "", "assistant": [], "reasoning": []}
    if kind == "reasoning":
        cur["reasoning"].append(text)
    else:
        cur["assistant"].append(text)
    return cur


def _item_timestamp(obj, payload):
    return payload.get("timestamp") or obj.get("timestamp") or ""


def _compact_turns(turns):
    compacted = []
    for idx, turn in enumerate(turns):
        user = turn.get("user", "")
        assistant = "\n".join(x for x in turn.get("assistant", []) if x)
        reasoning = "\n".join(x for x in turn.get("reasoning", []) if x)
        if not assistant and not reasoning:
            continue
        title = " ".join(user.split())[:120] or "Assistant response"
        compacted.append(
            {
                "id": f"turn-{len(compacted)}",
                "index": len(compacted),
                "outlineTitle": title,
                "time": turn.get("time", ""),
                "user": user,
                "user_context": turn.get("user_context", ""),
                "assistant": assistant,
                "reasoning": reasoning,
            }
        )
    return compacted


def _tool_summary(payload):
    payload_type = payload.get("type")
    if payload_type in ("function_call", "custom_tool_call"):
        name = payload.get("name") or payload.get("tool_name") or "tool"
        arguments = payload.get("arguments") or payload.get("input") or ""
        if len(arguments) > 500:
            arguments = arguments[:500] + "\n..."
        return f"Tool call: `{name}`\n\n```json\n{arguments}\n```"
    if payload_type in ("function_call_output", "custom_tool_call_output"):
        output = payload.get("output") or payload.get("result") or ""
        if not output:
            return ""
        if len(output) > 700:
            output = output[:700] + "\n..."
        return f"Tool output:\n\n```text\n{output}\n```"
    return ""


def _message_text(payload):
    return "\n".join(
        x.get("text", "")
        for x in payload.get("content", [])
        if x.get("type") in ("input_text", "output_text")
    )


def _extract_guardian_review(text):
    if not text.startswith("The following is the Codex agent history whose request action you are assessing."):
        return None

    session_match = re.search(r"Reviewed Codex session id:\s*([^\s]+)", text)
    action_match = re.search(
        r"Planned action JSON:\s*(.*?)\s*>>> APPROVAL REQUEST END",
        text,
        flags=re.S,
    )
    action_text = action_match.group(1).strip() if action_match else ""
    action_summary = ""
    if action_text:
        try:
            action = json.loads(action_text)
            if "command" in action:
                command = action["command"]
                action_summary = " ".join(command) if isinstance(command, list) else str(command)
            elif "files" in action:
                action_summary = "Patch files: " + ", ".join(action.get("files", [])[:3])
            elif "tool" in action:
                action_summary = f"Tool: {action.get('tool')}"
        except json.JSONDecodeError:
            action_summary = " ".join(action_text.split())[:240]

    user_lines = re.findall(r"\[\d+\]\s+user:\s*(.*?)(?=\n\n\[\d+\]|\n\n>>>|$)", text, flags=re.S)
    user_summary = []
    for raw in user_lines[:4]:
        cleaned = raw
        marker = "My request for Codex:"
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[1]
        cleaned = " ".join(cleaned.split())
        if cleaned:
            user_summary.append(cleaned[:260])

    reviewed = session_match.group(1) if session_match else "unknown"
    title = f"Guardian approval review for `{reviewed}`"
    if action_summary:
        title += f"\n\nPlanned action: {action_summary}"
    if action_text:
        title += f"\n\n```json\n{action_text[:1600]}\n```"

    context = ""
    if user_summary:
        context = "Transcript user requests:\n" + "\n".join(f"- {item}" for item in user_summary)
    return title, context


def _split_user_context(text):
    guardian = _extract_guardian_review(text)
    if guardian:
        return guardian

    marker = "My request for Codex:"
    if marker not in text:
        return text, ""
    context, request = text.split(marker, 1)
    request = request.strip()
    context = context.strip()
    if context.startswith("# Context from my IDE setup:"):
        context = context[len("# Context from my IDE setup:"):].strip()
    elif context.startswith("Context from my IDE setup:"):
        context = context[len("Context from my IDE setup:"):].strip()
    return request, context


def load_session_preview(path, limit=3):
    path = Path(path)
    questions = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = obj.get("payload", {})
            text = ""
            if obj.get("type") == "event_msg" and payload.get("type") == "user_message":
                text = payload.get("message", "")
            elif obj.get("type") == "response_item" and payload.get("type") == "message":
                if payload.get("role") == "user":
                    text = _message_text(payload)
            if not text or _is_hidden_user_message(text):
                continue
            guardian = _extract_guardian_review(text)
            if guardian:
                title, _ = guardian
                questions.append(" ".join(title.split())[:280])
                break
            marker = "My request for Codex:"
            if marker in text:
                text = text.split(marker, 1)[1]
            text = " ".join(text.split())
            if text and text not in questions:
                questions.append(text)
            if len(questions) >= limit:
                break
    return questions


def load_session_meta(path):
    path = Path(path)
    meta = {
        "session_id": "",
        "parent_thread_id": "",
        "cwd": "",
        "originator": "",
        "thread_source": "",
        "model_provider": "",
        "source": {},
    }
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "session_meta":
                continue
            payload = obj.get("payload") or {}
            meta.update(
                {
                    "session_id": payload.get("session_id") or payload.get("id") or "",
                    "parent_thread_id": payload.get("parent_thread_id") or "",
                    "cwd": payload.get("cwd") or "",
                    "originator": payload.get("originator") or "",
                    "thread_source": payload.get("thread_source") or "",
                    "model_provider": payload.get("model_provider") or "",
                    "source": payload.get("source") or {},
                }
            )
            break
    return meta


def load_session(path):
    path = Path(path)

    print("loading:", path)

    turns = []
    cur = None
    saw_event_messages = False
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = obj.get("payload", {})

            if obj.get("type") == "event_msg":
                payload_type = payload.get("type")
                if payload_type == "user_message":
                    text = payload.get("message", "")
                    if _is_hidden_user_message(text):
                        continue
                    text, context = _split_user_context(text)
                    if cur:
                        turns.append(cur)
                    cur = {"user": text, "user_context": context, "time": _item_timestamp(obj, payload), "assistant": [], "reasoning": []}
                    saw_event_messages = True
                elif payload_type == "agent_message":
                    phase = payload.get("phase")
                    kind = "answer" if phase == "final_answer" else "reasoning"
                    cur = _append_assistant(cur, payload.get("message", ""), kind)
                    saw_event_messages = True
                elif payload_type == "agent_reasoning":
                    cur = _append_assistant(cur, payload.get("text", ""), "reasoning")
                    saw_event_messages = True
                continue

            if obj.get("type") != "response_item":
                continue
            if payload.get("type") in (
                "function_call",
                "function_call_output",
                "custom_tool_call",
                "custom_tool_call_output",
            ):
                cur = _append_assistant(cur, _tool_summary(payload), "reasoning")
                continue
            if saw_event_messages:
                continue
            if payload.get("type") == "reasoning":
                summary = payload.get("summary") or []
                text = "\n".join(
                    item if isinstance(item, str) else item.get("text", "")
                    for item in summary
                )
                cur = _append_assistant(cur, text, "reasoning")
                continue
            if payload.get("type") != "message":
                continue
            role = payload.get("role", "unknown")
            text = _message_text(payload)
            if role == "user":
                if _is_hidden_user_message(text):
                    continue
                text, context = _split_user_context(text)
                if cur:
                    turns.append(cur)
                cur = {"user": text, "user_context": context, "time": _item_timestamp(obj, payload), "assistant": [], "reasoning": []}
            elif role == "assistant":
                cur = _append_assistant(cur, text)
    if cur:
        turns.append(cur)
    return _compact_turns(turns)
