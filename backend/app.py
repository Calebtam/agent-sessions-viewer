from flask import Flask, Response, jsonify, send_from_directory, request
from parser import load_session, load_session_meta, load_session_preview
from providers.vscode_chat import VSCodeChatProvider
from providers.codex import CodexProvider
from providers.copilot_cli import CopilotCLIProvider
from registry import SessionRegistry
from pathlib import Path
import argparse
import json
import secrets
import time

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["JSON_AS_ASCII"] = False

parser = argparse.ArgumentParser()
parser.add_argument(
    "--session_dir",
    default="~/.codex/sessions",
    help="Codex session directory"
)
parser.add_argument(
    "--vscode_user_dir",
    default="~/.config/Code/User",
    help="VS Code user data directory (read-only diagnostics)",
)
parser.add_argument(
    "--copilot_session_dir",
    default="~/.copilot/session-state",
    help="Copilot CLI session-state directory (read-only)",
)
parser.add_argument("--host", default="127.0.0.1", help="HTTP listen address")
parser.add_argument("--port", default=9001, type=int, help="HTTP listen port")

args = parser.parse_args()

BASE = Path(args.session_dir).expanduser()
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
METADATA_FILE = Path(__file__).resolve().parents[1] / "session_metadata.json"
SESSION_CACHE = {}
VSCODE_PROVIDER = VSCodeChatProvider(Path(args.vscode_user_dir))
CODEX_PROVIDER = CodexProvider(BASE)
COPILOT_PROVIDER = CopilotCLIProvider(Path(args.copilot_session_dir))
REGISTRY = SessionRegistry([CODEX_PROVIDER, COPILOT_PROVIDER, VSCODE_PROVIDER])


def load_metadata():
    if not METADATA_FILE.exists():
        return {}
    try:
        with METADATA_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_metadata(metadata):
    with METADATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2, sort_keys=True)


def session_entry(metadata, rel):
    entry = metadata.get(rel, {})
    if not isinstance(entry, dict):
        entry = {}
    return entry


def metadata_categories(metadata):
    categories = metadata.get("_categories", [])
    if not isinstance(categories, list):
        categories = []
    return [str(item).strip() for item in categories if str(item).strip()]


def access_config(metadata):
    config = metadata.get("_access", {})
    if not isinstance(config, dict):
        config = {}
    public_sessions = config.get("publicSessions", [])
    if not isinstance(public_sessions, list):
        public_sessions = []
    tokens = config.get("tokens", [])
    if not isinstance(tokens, list):
        tokens = []
    legacy_token = str(config.get("remoteToken", "")).strip()
    if legacy_token and not any(item.get("token") == legacy_token for item in tokens if isinstance(item, dict)):
        tokens.append({
            "name": "Legacy admin",
            "token": legacy_token,
            "role": "admin",
            "publicSessions": public_sessions,
        })
    return {
        "remoteEnabled": bool(config.get("remoteEnabled", False)),
        "remoteToken": str(config.get("remoteToken", "")).strip(),
        "publicSessions": [str(item) for item in public_sessions if str(item).strip()],
        "tokens": [
            {
                "name": str(item.get("name", "Token")).strip() or "Token",
                "token": str(item.get("token", "")).strip(),
                "role": (
                    str(item.get("role", "viewer")).strip()
                    if str(item.get("role", "viewer")).strip() in ("admin", "viewer")
                    else "viewer"
                ),
                "publicSessions": [
                    str(path) for path in item.get("publicSessions", [])
                    if str(path).strip()
                ] if isinstance(item.get("publicSessions", []), list) else [],
            }
            for item in tokens
            if isinstance(item, dict) and str(item.get("token", "")).strip()
        ],
    }


def is_local_request():
    remote = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    remote = remote.split(",", 1)[0].strip()
    return remote in ("127.0.0.1", "::1", "localhost")


def request_token():
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.args.get("token", "").strip()


def current_token_entry(metadata):
    token = request_token()
    if not token:
        return None
    for item in access_config(metadata).get("tokens", []):
        if item.get("token") == token:
            return item
    return None


def is_admin_request(metadata):
    entry = current_token_entry(metadata)
    return is_local_request() or bool(entry and entry.get("role") == "admin")


def visible_session_infos(infos, metadata):
    config = access_config(metadata)
    if not config["remoteEnabled"] or is_admin_request(metadata):
        return infos
    entry = current_token_entry(metadata)
    public = set(entry.get("publicSessions", [])) if entry else set(config["publicSessions"])
    return [item for item in infos if item.get("path") in public]


def require_admin(metadata):
    if is_admin_request(metadata):
        return None
    return jsonify({"error": "forbidden"}), 403


def public_session_info(item):
    """Remove local source details from normal API responses."""
    result = dict(item)
    result.pop("source_path", None)
    result.pop("sourceFingerprint", None)
    result.pop("source_id", None)
    return result


def cached_session(path):
    stat = path.stat()
    key = str(path)
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = SESSION_CACHE.get(key)
    if cached and cached["stamp"] == stamp:
        return cached["turns"]
    turns = load_session(path)
    SESSION_CACHE[key] = {"stamp": stamp, "turns": turns, "loaded_at": time.time()}
    return turns


def session_title(path):
    stem = path.stem
    if stem.startswith("rollout-"):
        stem = stem[len("rollout-") :]
    return stem


def session_short_title(path):
    stem = path.stem
    marker = "-019"
    idx = stem.find(marker)
    if idx >= 0:
        return stem[idx + 1 :]
    if stem.startswith("rollout-"):
        stem = stem[len("rollout-") :]
    return stem


def session_info(path, metadata=None):
    metadata = metadata or {}
    rel = str(path.relative_to(BASE))
    entry = session_entry(metadata, rel)
    references = entry.get("references", entry.get("relations", []))
    if not isinstance(references, list):
        references = []
    meta = load_session_meta(path)
    source = meta.get("source") or {}
    if not isinstance(source, dict):
        source = {}
    parent_thread_id = meta.get("parent_thread_id") or ""
    session_type = (
        "subagent"
        if parent_thread_id or source.get("subagent") or meta.get("thread_source") == "subagent"
        else "session"
    )
    file_id = session_short_title(path)
    return {
        "name": entry.get("name") or session_short_title(path),
        "fullName": session_title(path),
        "shortName": session_short_title(path),
        "fileId": file_id,
        "originalName": path.stem,
        "path": rel,
        "date": "/".join(path.relative_to(BASE).parts[:3]) if len(path.relative_to(BASE).parts) >= 4 else "",
        "previewQuestions": load_session_preview(path, limit=3),
        "sessionId": meta.get("session_id") or session_short_title(path),
        "parentThreadId": parent_thread_id,
        "cwd": meta.get("cwd") or "",
        "originator": meta.get("originator") or "",
        "threadSource": meta.get("thread_source") or "",
        "sessionType": session_type,
        "tags": entry.get("tags", []),
        "pinned": bool(entry.get("pinned", False)),
        "archived": bool(entry.get("archived", False)),
        "references": references,
        "relations": references,
        "category": entry.get("category", ""),
    }


def id_aliases(item):
    aliases = []
    for key in ("sessionId", "fileId", "shortName"):
        value = item.get(key)
        if value and value not in aliases:
            aliases.append(value)
    return aliases


def preferred_parent_map(infos):
    by_id = {}
    for item in infos:
        for alias in id_aliases(item):
            existing = by_id.get(alias)
            if not existing or (
                existing.get("sessionType") == "subagent"
                and item.get("sessionType") != "subagent"
            ):
                by_id[alias] = item
    return by_id


def all_session_infos(metadata=None):
    metadata = metadata or load_metadata()
    infos = [session_info(p, metadata) for p in BASE.rglob("*.jsonl")]
    by_id = preferred_parent_map(infos)
    for item in infos:
        parent = by_id.get(item.get("parentThreadId"))
        item["parentPath"] = parent.get("path") if parent else ""
        item["parentName"] = parent.get("name") if parent else ""
        item["parentSessionId"] = parent.get("sessionId") if parent else ""
    for item in infos:
        ancestors = []
        seen = {item.get("path")}
        parent = by_id.get(item.get("parentThreadId"))
        while parent and parent.get("path") not in seen:
            ancestors.append({
                "path": parent.get("path", ""),
                "name": parent.get("name", ""),
                "sessionId": parent.get("sessionId", ""),
                "sessionType": parent.get("sessionType", "session"),
            })
            seen.add(parent.get("path"))
            parent = by_id.get(parent.get("parentThreadId"))
        root = ancestors[-1] if ancestors else None
        item["ancestorChain"] = list(reversed(ancestors))
        item["subagentDepth"] = len(ancestors) if item.get("sessionType") == "subagent" else 0
        item["mainAgentPath"] = root.get("path") if root else ""
        item["mainAgentName"] = root.get("name") if root else ""
        item["mainAgentSessionId"] = root.get("sessionId") if root else ""
    return infos


def unified_codex_info(item):
    result = dict(item)
    result.update({
        "id": f"codex:{item['path']}",
        "provider": "codex",
        "providerLabel": "Codex",
        "title": item.get("name", ""),
        "workspace": item.get("cwd", ""),
        "workspaceId": "",
        "created_at": None,
        "updated_at": None,
        "source_path": str(BASE / item["path"]),
        "content_status": "full",
        "has_transcript": True,
        "turn_count": None,
        "updatedAt": None,
        "contentStatus": "full",
        "hasTranscript": True,
        "turnCount": None,
        "readOnlyMetadata": False,
    })
    return result


def apply_viewer_metadata(item, metadata):
    result = dict(item)
    key = result.get("legacyPath") or result.get("path")
    entry = session_entry(metadata, key)
    if not entry and result.get("id"):
        entry = session_entry(metadata, result["id"])
    result["name"] = entry.get("name") or result.get("name") or result.get("title", "")
    result["title"] = result["name"]
    result["tags"] = entry.get("tags", result.get("tags", []))
    result["category"] = entry.get("category", result.get("category", ""))
    result["pinned"] = bool(entry.get("pinned", result.get("pinned", False)))
    result["archived"] = bool(entry.get("archived", result.get("archived", False)))
    return result


def subagent_tree(root_info, all_infos):
    children_by_parent = {}
    for item in all_infos:
        parent_path = item.get("parentPath")
        if item.get("sessionType") == "subagent" and parent_path:
            children_by_parent.setdefault(parent_path, []).append(item)
    for children in children_by_parent.values():
        children.sort(key=lambda item: (item.get("date", ""), item.get("name", "")))

    def build(parent_path, depth, seen):
        result = []
        for item in children_by_parent.get(parent_path, []):
            node_id = item.get("path") or item.get("fileId") or item.get("sessionId")
            if not node_id or node_id in seen or item.get("path") == root_info.get("path"):
                continue
            node = dict(item)
            node["subagentDepth"] = depth
            next_seen = seen | {node_id, item.get("path")}
            node["children"] = build(item.get("path"), depth + 1, next_seen)
            result.append(node)
        return result

    seen = {
        value
        for value in (
            root_info.get("path"),
            root_info.get("fileId"),
            root_info.get("sessionId"),
        )
        if value
    }
    return build(root_info.get("path"), 1, seen)


def descendant_subagent_paths(root_path, all_infos):
    children_by_parent = {}
    for item in all_infos:
        parent_path = item.get("parentPath")
        if item.get("sessionType") == "subagent" and parent_path:
            children_by_parent.setdefault(parent_path, []).append(item)

    result = []
    seen = {root_path}

    def visit(parent_path):
        for item in children_by_parent.get(parent_path, []):
            path = item.get("path")
            if not path or path in seen:
                continue
            seen.add(path)
            result.append(path)
            visit(path)

    visit(root_path)
    return result

# app=Flask(__name__)
# BASE=os.path.expanduser("~/.codex/sessions")

# @app.route("/api/sessions")
# def sessions():
#     return jsonify([{"name":p.stem,"path":str(p)} for p in Path(BASE).rglob("*.jsonl")])
@app.route("/")
@app.route("/admin")
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")
@app.route("/api/sessions")
def sessions():
    metadata = load_metadata()
    include_archived = request.args.get("archived") == "1"
    infos = visible_session_infos(all_session_infos(metadata), metadata)
    if not include_archived:
        infos = [item for item in infos if not item.get("archived")]
    infos.sort(key=lambda item: (not item.get("pinned"), item.get("date", ""), item.get("name", "")))
    return jsonify({
        "sessions": infos,
        "categories": metadata_categories(metadata),
    })


@app.route("/api/v2/diagnostics")
def diagnostics():
    metadata = load_metadata()
    denied = require_admin(metadata)
    if denied:
        return denied
    return jsonify({"providers": [VSCODE_PROVIDER.discover()]})


@app.route("/api/v2/sessions")
def v2_sessions():
    metadata = load_metadata()
    include_archived = request.args.get("archived") == "1"
    combined = [apply_viewer_metadata(item, metadata) for item in REGISTRY.discover()]
    combined = visible_session_infos(combined, metadata)
    if not include_archived:
        combined = [item for item in combined if not item.get("archived")]
    provider = request.args.get("provider", "").strip()
    workspace = request.args.get("workspace", "").strip()
    content_status = request.args.get("content_status", "").strip()
    category = request.args.get("category", "").strip()
    tag = request.args.get("tag", "").strip()
    if provider:
        combined = [item for item in combined if item.get("provider") == provider]
    if workspace:
        combined = [item for item in combined if item.get("workspace") == workspace]
    if content_status:
        combined = [item for item in combined if item.get("contentStatus") == content_status]
    if category:
        combined = [item for item in combined if item.get("category") == category]
    if tag:
        combined = [item for item in combined if tag in item.get("tags", [])]
    combined.sort(key=lambda item: item.get("name") or "")
    combined.sort(
        key=lambda item: item.get("updatedAt") or item.get("date") or "",
        reverse=True,
    )
    combined.sort(key=lambda item: bool(item.get("pinned")), reverse=True)
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = min(max(int(request.args.get("limit", 200)), 1), 200)
    except ValueError:
        offset, limit = 0, 200
    total = len(combined)
    workspaces = sorted({item.get("workspace") for item in combined if item.get("workspace")})
    page = combined[offset:offset + limit]
    return jsonify({
        "sessions": [public_session_info(item) for item in page],
        "categories": metadata_categories(metadata),
        "providers": REGISTRY.provider_infos(),
        "workspaces": workspaces,
        "contentStatuses": ["full", "partial", "index_only", "error"],
        "offset": offset,
        "limit": limit,
        "total": total,
        "hasMore": offset + limit < total,
    })


@app.route("/api/v2/sessions/<session_id>")
def v2_session(session_id):
    metadata = load_metadata()
    visible = visible_session_infos(REGISTRY.discover(), metadata)
    if session_id not in {item.get("id") for item in visible}:
        return jsonify({"error": "not found"}), 404
    try:
        detail = REGISTRY.load(session_id)
    except (OSError, UnicodeDecodeError, ValueError):
        return jsonify({"error": "session parse failed", "code": "provider_parse_error"}), 422
    if detail is None:
        return jsonify({"error": "not found"}), 404
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        offset, limit = 0, 50
    turns = detail.get("turns", [])
    detail["turns"] = turns[offset:offset + limit]
    detail["offset"] = offset
    detail["limit"] = limit
    detail["total"] = len(turns)
    detail["hasMore"] = offset + limit < len(turns)
    detail["session"] = public_session_info(
        apply_viewer_metadata(detail["session"], metadata)
    )
    return jsonify(detail)


@app.route("/api/v2/sessions/<session_id>", methods=["DELETE"])
def v2_delete_session(session_id):
    metadata = load_metadata()
    denied = require_admin(metadata)
    if denied:
        return denied
    discovered = {item.get("id"): item for item in REGISTRY.discover()}
    session_item = discovered.get(session_id)
    if session_item is None:
        return jsonify({"error": "not found"}), 404
    if not session_item.get("canDelete"):
        return jsonify({
            "error": "provider does not support per-session deletion",
            "code": "delete_not_supported",
        }), 409
    try:
        result = REGISTRY.delete(session_id)
    except (OSError, ValueError) as exc:
        return jsonify({
            "error": "session could not be moved to trash",
            "code": type(exc).__name__,
        }), 409
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@app.route("/api/v2/sessions/<session_id>/metadata", methods=["PATCH"])
def v2_session_metadata(session_id):
    metadata = load_metadata()
    denied = require_admin(metadata)
    if denied:
        return denied
    discovered = {item.get("id"): item for item in REGISTRY.discover()}
    session_item = discovered.get(session_id)
    if session_item is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    allowed = {"name", "tags", "category", "pinned", "archived"}
    unknown = set(data) - allowed
    if unknown:
        return jsonify({"error": "unsupported fields", "fields": sorted(unknown)}), 400
    entry = metadata.setdefault(session_id, {})
    if "name" in data:
        value = str(data.get("name", "")).strip()
        if value:
            entry["name"] = value
        else:
            entry.pop("name", None)
    if "tags" in data:
        values = data.get("tags") if isinstance(data.get("tags"), list) else []
        entry["tags"] = list(dict.fromkeys(
            str(value).strip() for value in values if str(value).strip()
        ))
    if "category" in data:
        category = str(data.get("category", "")).strip()
        if category:
            entry["category"] = category
            categories = metadata_categories(metadata)
            if category not in categories:
                metadata["_categories"] = categories + [category]
        else:
            entry.pop("category", None)
    for field in ("pinned", "archived"):
        if field in data:
            entry[field] = bool(data[field])
    save_metadata(metadata)
    return jsonify(public_session_info(apply_viewer_metadata(session_item, metadata)))


@app.route("/api/v2/search")
def v2_search():
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify([])
    metadata = load_metadata()
    sessions = [apply_viewer_metadata(item, metadata) for item in REGISTRY.discover()]
    sessions = visible_session_infos(sessions, metadata)
    results = []
    for info in sessions:
        if info.get("archived") and request.args.get("archived") != "1":
            continue
        summary_fields = [
            ("title", info.get("name", "")),
            ("provider", info.get("providerLabel", info.get("provider", ""))),
            ("workspace", info.get("workspace", "")),
            ("tag", " ".join(info.get("tags", []))),
            ("category", info.get("category", "")),
        ]
        matched = None
        for label, value in summary_fields:
            text = str(value or "")
            if query in text.lower():
                matched = (label, text, None)
                break
        if matched is None and info.get("has_transcript"):
            try:
                detail = REGISTRY.load(info["id"])
            except (OSError, UnicodeDecodeError, ValueError):
                detail = None
            for turn in (detail or {}).get("turns", []):
                for label, value in (
                    ("user", turn.get("user", "")),
                    ("assistant", turn.get("assistant", "")),
                    ("reasoning", turn.get("reasoning", "")),
                ):
                    text = str(value or "")
                    if query in text.lower():
                        matched = (label, text, turn.get("index"))
                        break
                if matched:
                    break
        if not matched:
            continue
        label, text, turn_index = matched
        position = text.lower().find(query)
        start = max(0, position - 90)
        end = min(len(text), position + len(query) + 140)
        results.append({
            **public_session_info(info),
            "matchType": label,
            "snippet": " ".join(text[start:end].split()),
            "turnIndex": turn_index,
        })
        if len(results) >= 50:
            break
    return jsonify(results)


@app.route("/api/v2/export/<session_id>")
def v2_export(session_id):
    export_format = request.args.get("format", "markdown").strip().lower()
    if export_format not in ("markdown", "json"):
        return jsonify({"error": "unsupported format"}), 400
    metadata = load_metadata()
    visible = visible_session_infos(REGISTRY.discover(), metadata)
    if session_id not in {item.get("id") for item in visible}:
        return jsonify({"error": "not found"}), 404
    try:
        detail = REGISTRY.load(session_id)
    except (OSError, UnicodeDecodeError, ValueError):
        detail = None
    if detail is None:
        return jsonify({"error": "not found"}), 404
    detail = dict(detail)
    session_data = public_session_info(
        apply_viewer_metadata(detail.get("session", {}), metadata)
    )
    detail["session"] = session_data
    if export_format == "json":
        response = jsonify(detail)
        response.headers["Content-Disposition"] = "attachment; filename=session.json"
        return response
    lines = [
        f"# {session_data.get('name') or session_data.get('title') or 'Session'}",
        "",
        f"- Provider: {session_data.get('providerLabel') or session_data.get('provider')}",
        f"- Workspace: {session_data.get('workspace') or ''}",
        f"- Status: {session_data.get('content_status') or session_data.get('contentStatus')}",
        "",
    ]
    turns = detail.get("turns", [])
    if not turns:
        lines.extend(["_Transcript not available._", ""])
    for index, turn in enumerate(turns, start=1):
        lines.extend([f"## Interaction {index}", ""])
        if turn.get("user"):
            lines.extend(["### User", "", str(turn["user"]), ""])
        if turn.get("assistant"):
            lines.extend(["### Assistant", "", str(turn["assistant"]), ""])
        if turn.get("reasoning"):
            lines.extend([
                "<details><summary>Reasoning and tools</summary>", "",
                str(turn["reasoning"]), "", "</details>", "",
            ])
    return Response(
        "\n".join(lines),
        content_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=session.md"},
    )


@app.route("/api/categories", methods=["POST", "PATCH", "DELETE"])
def categories():
    data = request.get_json(silent=True) or {}
    metadata = load_metadata()
    denied = require_admin(metadata)
    if denied:
        return denied
    categories = metadata_categories(metadata)

    if request.method == "POST":
        name = str(data.get("name", "")).strip()
        if not name:
            return jsonify({"error": "empty category"}), 400
        if name not in categories:
            categories.append(name)

    elif request.method == "PATCH":
        old_name = str(data.get("oldName", "")).strip()
        new_name = str(data.get("name", "")).strip()
        if not old_name or not new_name:
            return jsonify({"error": "empty category"}), 400
        if old_name not in categories:
            return jsonify({"error": "category not found"}), 404
        categories = [new_name if item == old_name else item for item in categories]
        deduped = []
        for item in categories:
            if item not in deduped:
                deduped.append(item)
        categories = deduped
        for key, entry in metadata.items():
            if key.startswith("_") or not isinstance(entry, dict):
                continue
            if entry.get("category") == old_name:
                entry["category"] = new_name

    else:
        name = str(data.get("name", "")).strip()
        if not name:
            return jsonify({"error": "empty category"}), 400
        categories = [item for item in categories if item != name]
        for key, entry in metadata.items():
            if key.startswith("_") or not isinstance(entry, dict):
                continue
            if entry.get("category") == name:
                entry.pop("category", None)

    metadata["_categories"] = categories
    save_metadata(metadata)
    return jsonify({"categories": categories})


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify([])
    metadata = load_metadata()
    results = []
    for info in visible_session_infos(all_session_infos(metadata), metadata):
        if info.get("archived") and request.args.get("archived") != "1":
            continue
        path = BASE / info["path"]
        haystacks = [
            ("title", info["name"]),
            ("file", info["originalName"]),
            ("date", info["date"]),
            ("tag", " ".join(info.get("tags", []))),
            ("preview", " ".join(info["previewQuestions"])),
        ]
        turns = []
        try:
            turns = cached_session(path)
        except OSError:
            turns = []
        for idx, turn in enumerate(turns):
            haystacks.extend(
                [
                    (f"user #{idx + 1}", turn.get("user", "")),
                    (f"assistant #{idx + 1}", turn.get("assistant", "")),
                    (f"thinking #{idx + 1}", turn.get("reasoning", "")),
                ]
            )
        for label, text in haystacks:
            lower = text.lower()
            pos = lower.find(query)
            if pos < 0:
                continue
            start = max(0, pos - 90)
            end = min(len(text), pos + len(query) + 140)
            snippet = " ".join(text[start:end].split())
            results.append({
                **info,
                "matchType": label,
                "snippet": snippet,
                "turnIndex": int(label.rsplit("#", 1)[1].strip()) - 1 if "#" in label else None,
            })
            break
        if len(results) >= 50:
            break
    return jsonify(results)


@app.route("/api/session-meta/<path:sp>", methods=["PATCH"])
def update_session_meta(sp):
    file = BASE / sp
    if not file.exists():
        return jsonify({"error": "not found", "path": str(file)}), 404
    data = request.get_json(silent=True) or {}
    metadata = load_metadata()
    denied = require_admin(metadata)
    if denied:
        return denied
    key = str(file.relative_to(BASE))
    entry = metadata.setdefault(key, {})
    for field in ("name",):
        if field in data:
            value = str(data.get(field, "")).strip()
            if value:
                entry[field] = value
            else:
                entry.pop(field, None)
    for field in ("pinned", "archived"):
        if field in data:
            entry[field] = bool(data[field])
    if "tags" in data:
        tags = data.get("tags") or []
        clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        entry["tags"] = clean_tags
    if "category" in data:
        category = str(data.get("category", "")).strip()
        if category:
            categories = metadata_categories(metadata)
            if category not in categories:
                categories.append(category)
                metadata["_categories"] = categories
            entry["category"] = category
        else:
            entry.pop("category", None)
    if "tags" in data or "category" in data:
        descendant_paths = descendant_subagent_paths(key, all_session_infos(metadata))
        for child_key in descendant_paths:
            child_entry = metadata.setdefault(child_key, {})
            if "tags" in data:
                child_entry["tags"] = list(clean_tags)
            if "category" in data:
                if category:
                    child_entry["category"] = category
                else:
                    child_entry.pop("category", None)
    save_metadata(metadata)
    return jsonify(session_info(file, metadata))


@app.route("/api/session-relations/<path:sp>", methods=["POST", "DELETE"])
def session_relations(sp):
    file = BASE / sp
    if not file.exists():
        return jsonify({"error": "not found", "path": str(file)}), 404
    data = request.get_json(silent=True) or {}
    metadata = load_metadata()
    denied = require_admin(metadata)
    if denied:
        return denied
    target = str(data.get("path", "")).strip()
    target_file = BASE / target
    if not target or not target_file.exists():
        return jsonify({"error": "target not found", "path": target}), 404
    key = str(file.relative_to(BASE))
    target_key = str(target_file.relative_to(BASE))
    entry = metadata.setdefault(key, {})
    references = entry.get("references", entry.get("relations", []))
    if not isinstance(references, list):
        references = []
    if request.method == "POST":
        if target_key not in references and target_key != key:
            references.append(target_key)
    else:
        references = [item for item in references if item != target_key]
    entry["references"] = references
    save_metadata(metadata)
    return jsonify(session_info(file, metadata))


@app.route("/api/session-title/<path:sp>", methods=["PUT"])
def rename_session(sp):
    file = BASE / sp
    if not file.exists():
        return jsonify({
            "error": "not found",
            "path": str(file)
        }), 404

    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    metadata = load_metadata()
    denied = require_admin(metadata)
    if denied:
        return denied
    key = str(file.relative_to(BASE))
    if name:
        metadata.setdefault(key, {})["name"] = name
    else:
        metadata.setdefault(key, {}).pop("name", None)
    save_metadata(metadata)
    return jsonify({
        "path": key,
        "name": name or session_short_title(file),
    })


@app.route("/api/access", methods=["GET", "PATCH"])
def access():
    metadata = load_metadata()
    config = access_config(metadata)
    if request.method == "GET":
        public = set(config["publicSessions"])
        sessions_public = [
            public_session_info(apply_viewer_metadata(item, metadata))
            for item in REGISTRY.discover()
            if item.get("path") in public
        ]
        return jsonify({
            "remoteEnabled": config["remoteEnabled"],
            "isAdmin": is_admin_request(metadata),
            "publicSessions": sessions_public if is_admin_request(metadata) else [],
            "publicPaths": config["publicSessions"] if is_admin_request(metadata) else [],
            "guestPublicPaths": config["publicSessions"] if is_admin_request(metadata) else [],
            "tokens": config["tokens"] if is_admin_request(metadata) else [],
        })

    denied = require_admin(metadata)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    next_config = dict(config)
    if "remoteEnabled" in data:
        next_config["remoteEnabled"] = bool(data["remoteEnabled"])
    if "remoteToken" in data:
        next_config["remoteToken"] = str(data.get("remoteToken", "")).strip()
    if data.get("generateToken"):
        return jsonify({"token": secrets.token_urlsafe(24)})
    if "publicSessions" in data:
        paths = data.get("publicSessions") or []
        discovered = REGISTRY.discover()
        existing = {
            value for item in discovered for value in (item.get("path"), item.get("id"))
            if value
        }
        next_config["publicSessions"] = [
            str(path) for path in paths
            if str(path) in existing
        ]
    if "tokens" in data:
        discovered = REGISTRY.discover()
        existing = {
            value for item in discovered for value in (item.get("path"), item.get("id"))
            if value
        }
        tokens = []
        for item in data.get("tokens") or []:
            if not isinstance(item, dict):
                continue
            token = str(item.get("token", "")).strip()
            if not token:
                continue
            role = str(item.get("role", "viewer")).strip()
            if role not in ("admin", "viewer"):
                role = "viewer"
            sessions = [
                str(path) for path in item.get("publicSessions", [])
                if str(path) in existing
            ] if isinstance(item.get("publicSessions", []), list) else []
            tokens.append({
                "name": str(item.get("name", "Token")).strip() or "Token",
                "token": token,
                "role": role,
                "publicSessions": sessions,
            })
        next_config["tokens"] = tokens
    metadata["_access"] = next_config
    save_metadata(metadata)
    return jsonify(access_config(metadata))


@app.route("/api/session/<path:sp>")
def session(sp):
    file = BASE / sp
    if not file.exists():
        return jsonify({
            "error":"not found",
            "path":str(file)
        }),404
    metadata = load_metadata()
    all_infos = all_session_infos(metadata)
    visible_infos = visible_session_infos(all_infos, metadata)
    visible_paths = {item.get("path") for item in visible_infos}
    if str(file.relative_to(BASE)) not in visible_paths:
        return jsonify({"error": "forbidden"}), 403
    turns = cached_session(file)
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = int(request.args.get("limit", 80))
    except ValueError:
        offset = 0
        limit = 80
    limit = min(max(limit, 1), 200)
    page = turns[offset:offset + limit]
    outline = [
        {
            "id": turn.get("id"),
            "index": turn.get("index"),
            "title": turn.get("outlineTitle") or f"Turn {idx + 1}",
            "hasThinking": bool(turn.get("reasoning")),
        }
        for idx, turn in enumerate(turns)
    ]
    info = next((item for item in all_infos if item.get("path") == str(file.relative_to(BASE))), session_info(file, metadata))
    visible_path_set = {item.get("path") for item in visible_infos}
    masters = [
        item for item in reversed(info.get("ancestorChain", []))
        if item.get("path") in visible_path_set
    ]
    subagents = subagent_tree(info, visible_infos)
    reference_paths = set(info.get("references", info.get("relations", [])))
    references = [
        item for item in visible_infos
        if item.get("path") in reference_paths
    ]
    return jsonify({
        "session": info,
        "turns": page,
        "offset": offset,
        "limit": limit,
        "total": len(turns),
        "hasMore": offset + limit < len(turns),
        "outline": outline,
        "relations": {
            "masters": masters,
            "subagents": subagents,
            "references": references,
            "manual": references,
        },
    })
if __name__=="__main__":
    app.run(host=args.host, port=args.port)
