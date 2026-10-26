import base64
import copy
import secrets
from datetime import datetime, timezone
from pathlib import Path

from parser import load_session, load_session_meta, load_session_preview
from providers.base import SessionProvider


def _encode(value):
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _short_title(path):
    stem = path.stem
    marker = "-019"
    if marker in stem:
        return stem[stem.find(marker) + 1 :]
    return stem.removeprefix("rollout-")


class CodexProvider(SessionProvider):
    provider_id = "codex"
    trash_dir_name = ".agent-sessions-viewer-trash"

    def __init__(self, session_root):
        self.session_root = Path(session_root).expanduser()
        self._paths = {}
        self._summary_cache = {}
        self._detail_cache = {}

    def discover(self):
        return {
            "source": self.provider_id,
            "session_root": str(self.session_root),
            "exists": self.session_root.is_dir(),
            "session_count": len(list(self.session_root.rglob("*.jsonl")))
            if self.session_root.is_dir() else 0,
        }

    def discover_sessions(self):
        sessions = []
        paths = {}
        if not self.session_root.is_dir():
            self._paths = {}
            return sessions
        for path in sorted(self.session_root.rglob("*.jsonl")):
            if self.trash_dir_name in path.parts:
                continue
            try:
                rel = str(path.relative_to(self.session_root))
                stat = path.stat()
            except (OSError, UnicodeDecodeError):
                continue
            stable_id = f"codex:{_encode(rel)}"
            paths[stable_id] = path
            stamp = (stat.st_mtime_ns, stat.st_size)
            cached = self._summary_cache.get(stable_id)
            if cached and cached["stamp"] == stamp:
                sessions.append(dict(cached["session"]))
                continue
            try:
                meta = load_session_meta(path)
                preview = load_session_preview(path, limit=3)
            except (OSError, UnicodeDecodeError):
                continue
            parts = path.relative_to(self.session_root).parts
            date = "/".join(parts[:3]) if len(parts) >= 4 else ""
            name = _short_title(path)
            parent_id = meta.get("parent_thread_id") or ""
            session = {
                "id": stable_id,
                "path": rel,
                "legacyPath": rel,
                "provider": self.provider_id,
                "providerLabel": "Codex",
                "title": name,
                "name": name,
                "fullName": path.stem.removeprefix("rollout-"),
                "shortName": name,
                "fileId": name,
                "originalName": path.stem,
                "sessionId": meta.get("session_id") or name,
                "parentThreadId": parent_id,
                "workspace": meta.get("cwd") or "",
                "workspaceId": "",
                "cwd": meta.get("cwd") or "",
                "date": date,
                "created_at": None,
                "updated_at": None,
                "updatedAt": None,
                "source_path": str(path),
                "sourceFingerprint": f"{stat.st_mtime_ns}:{stat.st_size}:codex-v1",
                "content_status": "full",
                "has_transcript": True,
                "turn_count": None,
                "contentStatus": "full",
                "hasTranscript": True,
                "turnCount": None,
                "sessionType": "subagent" if parent_id else "session",
                "previewQuestions": preview,
                "tags": [],
                "category": "",
                "pinned": False,
                "archived": False,
                "readOnlyMetadata": False,
                "canDelete": True,
                "capabilities": ["transcript", "metadata", "search_content", "export", "delete"],
            }
            self._summary_cache[stable_id] = {"stamp": stamp, "session": dict(session)}
            sessions.append(session)
        self._paths = paths
        return sessions

    def load(self, session_id):
        if session_id not in self._paths:
            self.discover_sessions()
        path = self._paths.get(session_id)
        if path is None or not path.is_file():
            return None
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._detail_cache.get(session_id)
        if cached and cached["stamp"] == stamp:
            return copy.deepcopy(cached["detail"])
        turns = load_session(path)
        session = next(
            (item for item in self.discover_sessions() if item["id"] == session_id),
            None,
        )
        detail = {
            "session": session,
            "turns": turns,
            "offset": 0,
            "limit": len(turns),
            "total": len(turns),
            "hasMore": False,
            "outline": [
                {
                    "id": turn.get("id"),
                    "index": turn.get("index"),
                    "title": turn.get("outlineTitle") or f"Turn {index + 1}",
                    "hasThinking": bool(turn.get("reasoning")),
                }
                for index, turn in enumerate(turns)
            ],
            "relations": {
                "masters": [],
                "subagents": [],
                "references": [],
                "manual": [],
            },
        }
        self._detail_cache[session_id] = {"stamp": stamp, "detail": copy.deepcopy(detail)}
        return detail

    def delete(self, session_id):
        if session_id not in self._paths:
            self.discover_sessions()
        path = self._paths.get(session_id)
        if path is None or not path.is_file():
            return None
        root = self.session_root.resolve()
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("session source is outside the configured root") from exc
        if self.trash_dir_name in relative.parts:
            raise ValueError("session source is already in trash")
        batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = root / self.trash_dir_name / f"{batch}-{secrets.token_hex(3)}" / relative
        target.parent.mkdir(parents=True, exist_ok=False)
        resolved.replace(target)
        self._paths.pop(session_id, None)
        self._summary_cache.pop(session_id, None)
        self._detail_cache.pop(session_id, None)
        return {"id": session_id, "provider": self.provider_id, "recoverable": True, "trashName": target.name}

