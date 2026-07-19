from flask import Flask, jsonify, send_from_directory, request
from parser import load_session, load_session_meta, load_session_preview
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

args = parser.parse_args()

BASE = Path(args.session_dir).expanduser()
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
METADATA_FILE = Path(__file__).resolve().parents[1] / "session_metadata.json"
SESSION_CACHE = {}


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


def subagent_tree(root_info, all_infos):
    children_by_parent = {}
    for item in all_infos:
        parent_id = item.get("parentThreadId")
        if item.get("sessionType") == "subagent" and parent_id:
            children_by_parent.setdefault(parent_id, []).append(item)
    for children in children_by_parent.values():
        children.sort(key=lambda item: (item.get("date", ""), item.get("name", "")))

    def build(parent_id, depth, seen):
        result = []
        for item in children_by_parent.get(parent_id, []):
            node_id = item.get("path") or item.get("fileId") or item.get("sessionId")
            if not node_id or node_id in seen or item.get("path") == root_info.get("path"):
                continue
            node = dict(item)
            node["subagentDepth"] = depth
            child_parent_ids = [value for value in id_aliases(item) if value]
            children = []
            next_seen = seen | {node_id, item.get("path")}
            for child_parent_id in child_parent_ids:
                children.extend(build(child_parent_id, depth + 1, next_seen))
            deduped = []
            child_seen = set()
            for child in children:
                child_id = child.get("path") or child.get("fileId") or child.get("sessionId")
                if child_id in child_seen:
                    continue
                child_seen.add(child_id)
                deduped.append(child)
            node["children"] = deduped
            result.append(node)
        return result

    root_ids = [value for value in id_aliases(root_info) if value]
    subagents = []
    seen = {
        value
        for value in (
            root_info.get("path"),
            root_info.get("fileId"),
            root_info.get("sessionId"),
        )
        if value
    }
    for root_id in root_ids:
        subagents.extend(build(root_id, 1, seen))
    deduped = []
    child_seen = set()
    for item in subagents:
        node_id = item.get("path") or item.get("fileId") or item.get("sessionId")
        if node_id in child_seen:
            continue
        child_seen.add(node_id)
        deduped.append(item)
    return deduped

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
        entry["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
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
            item for item in all_session_infos(metadata)
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
        existing = {str(p.relative_to(BASE)) for p in BASE.rglob("*.jsonl")}
        next_config["publicSessions"] = [
            str(path) for path in paths
            if str(path) in existing
        ]
    if "tokens" in data:
        existing = {str(p.relative_to(BASE)) for p in BASE.rglob("*.jsonl")}
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
    # app.run(port=8080)  # 等价于 app.run(host="127.0.0.1", port=8080)
    app.run(host="0.0.0.0", port=9001)
