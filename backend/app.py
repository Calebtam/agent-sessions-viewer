from flask import Flask, jsonify, send_from_directory, request
from parser import load_session, load_session_preview
from pathlib import Path
import argparse
import json

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
    return {
        "name": metadata.get(rel, {}).get("name") or session_short_title(path),
        "fullName": session_title(path),
        "shortName": session_short_title(path),
        "originalName": path.stem,
        "path": rel,
        "date": "/".join(path.relative_to(BASE).parts[:3]) if len(path.relative_to(BASE).parts) >= 4 else "",
        "previewQuestions": load_session_preview(path, limit=3),
    }

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
    return jsonify([session_info(p, metadata) for p in BASE.rglob("*.jsonl")])


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify([])
    metadata = load_metadata()
    results = []
    for path in BASE.rglob("*.jsonl"):
        info = session_info(path, metadata)
        haystacks = [
            ("title", info["name"]),
            ("file", info["originalName"]),
            ("date", info["date"]),
            ("preview", " ".join(info["previewQuestions"])),
        ]
        turns = []
        try:
            turns = load_session(path)
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
            })
            break
        if len(results) >= 50:
            break
    return jsonify(results)


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
        metadata.pop(key, None)
    save_metadata(metadata)
    return jsonify({
        "path": key,
        "name": name or session_short_title(file),
    })
@app.route("/api/session/<path:sp>")
def session(sp):
	
    file = BASE / sp
    # print(BASE.resolve())
    
    if not file.exists():
        return jsonify({
            "error":"not found",
            "path":str(file)
        }),404

    return jsonify(load_session(file))
if __name__=="__main__":
    # app.run(port=8080)  # 等价于 app.run(host="127.0.0.1", port=8080)
    app.run(host="0.0.0.0", port=9000)
