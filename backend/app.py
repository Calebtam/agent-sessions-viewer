from flask import Flask, jsonify, send_from_directory, request
from parser import load_session, load_session_meta, load_session_preview
from pathlib import Path
import argparse
import json
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
    meta = load_session_meta(path)
    source = meta.get("source") or {}
    if not isinstance(source, dict):
        source = {}
    session_type = "subagent" if source.get("subagent") or meta.get("thread_source") == "subagent" else "session"
    return {
        "name": entry.get("name") or session_short_title(path),
        "fullName": session_title(path),
        "shortName": session_short_title(path),
        "originalName": path.stem,
        "path": rel,
        "date": "/".join(path.relative_to(BASE).parts[:3]) if len(path.relative_to(BASE).parts) >= 4 else "",
        "previewQuestions": load_session_preview(path, limit=3),
        "sessionId": meta.get("session_id") or session_short_title(path),
        "parentThreadId": meta.get("parent_thread_id") or "",
        "cwd": meta.get("cwd") or "",
        "originator": meta.get("originator") or "",
        "threadSource": meta.get("thread_source") or "",
        "sessionType": session_type,
        "tags": entry.get("tags", []),
        "pinned": bool(entry.get("pinned", False)),
        "archived": bool(entry.get("archived", False)),
        "relations": entry.get("relations", []),
    }


def all_session_infos(metadata=None):
    metadata = metadata or load_metadata()
    return [session_info(p, metadata) for p in BASE.rglob("*.jsonl")]

# app=Flask(__name__)
# BASE=os.path.expanduser("~/.codex/sessions")

# @app.route("/api/sessions")
# def sessions():
#     return jsonify([{"name":p.stem,"path":str(p)} for p in Path(BASE).rglob("*.jsonl")])
@app.route("/")
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")
@app.route("/api/sessions")
def sessions():
    metadata = load_metadata()
    include_archived = request.args.get("archived") == "1"
    infos = all_session_infos(metadata)
    if not include_archived:
        infos = [item for item in infos if not item.get("archived")]
    infos.sort(key=lambda item: (not item.get("pinned"), item.get("date", ""), item.get("name", "")))
    return jsonify(infos)


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify([])
    metadata = load_metadata()
    results = []
    for info in all_session_infos(metadata):
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
    save_metadata(metadata)
    return jsonify(session_info(file, metadata))


@app.route("/api/session-relations/<path:sp>", methods=["POST", "DELETE"])
def session_relations(sp):
    file = BASE / sp
    if not file.exists():
        return jsonify({"error": "not found", "path": str(file)}), 404
    data = request.get_json(silent=True) or {}
    target = str(data.get("path", "")).strip()
    target_file = BASE / target
    if not target or not target_file.exists():
        return jsonify({"error": "target not found", "path": target}), 404
    key = str(file.relative_to(BASE))
    target_key = str(target_file.relative_to(BASE))
    metadata = load_metadata()
    entry = metadata.setdefault(key, {})
    relations = entry.setdefault("relations", [])
    if request.method == "POST":
        if target_key not in relations and target_key != key:
            relations.append(target_key)
    else:
        entry["relations"] = [item for item in relations if item != target_key]
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
@app.route("/api/session/<path:sp>")
def session(sp):
    file = BASE / sp
    if not file.exists():
        return jsonify({
            "error":"not found",
            "path":str(file)
        }),404
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
    metadata = load_metadata()
    info = session_info(file, metadata)
    all_infos = all_session_infos(metadata)
    subagents = [
        item for item in all_infos
        if item.get("parentThreadId") and item.get("parentThreadId") == info.get("sessionId")
    ]
    manual = [
        item for item in all_infos
        if item.get("path") in set(info.get("relations", []))
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
            "subagents": subagents,
            "manual": manual,
        },
    })
if __name__=="__main__":
    # app.run(port=8080)  # 等价于 app.run(host="127.0.0.1", port=8080)
    app.run(host="0.0.0.0", port=9000)
