import base64
import copy
import json
import secrets
from datetime import datetime
from pathlib import Path

from parsers.copilot_cli import ParseLimits, load_workspace_yaml, parse_copilot_session
from providers.base import SessionProvider


def _encode(value):
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _display_date(value):
    if not value:
        return ""
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y/%m/%d")
    except ValueError:
        return text[:10].replace("-", "/") if len(text) >= 10 else ""


class CopilotCLIProvider(SessionProvider):
    provider_id = "copilot-cli"
    trash_dir_name = ".agent-sessions-viewer-trash"

    def __init__(self, session_root, limits=None):
        self.session_root = Path(session_root).expanduser()
        self.limits = limits or ParseLimits()
        self._sources = {}
        self._summary_cache = {}
        self._detail_cache = {}

    def discover(self):
        return {
            "source": self.provider_id,
            "session_root": str(self.session_root),
            "exists": self.session_root.is_dir(),
            "session_count": len(list(self.session_root.glob("*/events.jsonl")))
            if self.session_root.is_dir() else 0,
        }

    @staticmethod
    def _event_summary(events_path):
        start = {}
        interactions = set()
        bad = 0
        with events_path.open("rb") as stream:
            for raw in stream:
                try:
                    obj = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    bad += 1
                    continue
                if not isinstance(obj, dict):
                    bad += 1
                    continue
                if obj.get("type") == "session.start" and not start:
                    start = obj.get("data") if isinstance(obj.get("data"), dict) else {}
                elif obj.get("type") in ("user.message", "assistant.message"):
                    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
                    interaction_id = data.get("interactionId")
                    if isinstance(interaction_id, str) and interaction_id:
                        interactions.add(interaction_id)
        return start, len(interactions), bad

    def discover_sessions(self):
        sessions, sources = [], {}
        if not self.session_root.is_dir():
            self._sources = {}
            return sessions
        for events_path in sorted(self.session_root.glob("*/events.jsonl")):
            workspace_path = events_path.parent / "workspace.yaml"
            try:
                events_stat = events_path.stat()
                workspace_stat = workspace_path.stat() if workspace_path.is_file() else None
                stamp = (
                    events_stat.st_mtime_ns,
                    events_stat.st_size,
                    workspace_stat.st_mtime_ns if workspace_stat else 0,
                    workspace_stat.st_size if workspace_stat else 0,
                )
                directory_id = events_path.parent.name
                stable_id = f"copilot-cli:{_encode(directory_id)}"
                sources[stable_id] = (workspace_path, events_path)
                cached = self._summary_cache.get(stable_id)
                if cached and cached["stamp"] == stamp:
                    sessions.append(dict(cached["session"]))
                    continue
                workspace = (
                    load_workspace_yaml(workspace_path)
                    if workspace_path.is_file() else {}
                )
                start, turn_count, bad_lines = self._event_summary(events_path)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            start_id = str(start.get("sessionId") or "")
            workspace_id = str(workspace.get("id") or "")
            identity_ok = bool(
                start_id and start_id == directory_id
                and (not workspace_id or workspace_id == directory_id)
            )
            title = str(workspace.get("name") or f"Copilot CLI {directory_id[:8]}")[:500]
            cwd = str(
                workspace.get("cwd")
                or (start.get("context") or {}).get("cwd")
                or ""
            )
            created = workspace.get("created_at") or start.get("startTime")
            updated = workspace.get("updated_at")
            status = "error" if not identity_ok else "partial" if bad_lines else "full"
            session = {
                "id": stable_id,
                "path": stable_id,
                "provider": self.provider_id,
                "providerLabel": "Copilot CLI",
                "title": title,
                "name": title,
                "fullName": title,
                "shortName": title,
                "fileId": directory_id,
                "originalName": directory_id,
                "sessionId": directory_id,
                "parentThreadId": "",
                "workspace": cwd,
                "workspaceId": "",
                "cwd": cwd,
                "date": _display_date(updated or created),
                "created_at": str(created) if created else None,
                "updated_at": str(updated) if updated else None,
                "updatedAt": str(updated) if updated else None,
                "source_path": str(events_path),
                "sourceFingerprint": f"{events_stat.st_mtime_ns}:{events_stat.st_size}:copilot-cli-v1",
                "content_status": status,
                "has_transcript": identity_ok,
                "turn_count": turn_count,
                "contentStatus": status,
                "hasTranscript": identity_ok,
                "turnCount": turn_count,
                "sessionType": "session",
                "previewQuestions": [],
                "tags": [],
                "category": "",
                "pinned": False,
                "archived": False,
                "readOnlyMetadata": False,
                "canDelete": True,
                "capabilities": ["transcript", "reasoning", "tools", "attachments", "metadata", "search_content", "export", "delete"],
                "diagnosticCode": None if identity_ok else "session_identity_mismatch",
            }
            self._summary_cache[stable_id] = {"stamp": stamp, "session": dict(session)}
            sessions.append(session)
        self._sources = sources
        return sessions

    def load(self, session_id):
        if session_id not in self._sources:
            self.discover_sessions()
        source = self._sources.get(session_id)
        if source is None:
            return None
        workspace_path, events_path = source
        events_stat = events_path.stat()
        workspace_stat = workspace_path.stat() if workspace_path.is_file() else None
        stamp = (
            events_stat.st_mtime_ns,
            events_stat.st_size,
            workspace_stat.st_mtime_ns if workspace_stat else 0,
            workspace_stat.st_size if workspace_stat else 0,
        )
        cached = self._detail_cache.get(session_id)
        if cached and cached["stamp"] == stamp:
            return copy.deepcopy(cached["detail"])
        parsed = parse_copilot_session(*source, limits=self.limits)
        session = next(
            (item for item in self.discover_sessions() if item["id"] == session_id),
            None,
        )
        if session is None:
            return None
        if parsed["bad_lines"]:
            session["content_status"] = session["contentStatus"] = "partial"
        if not parsed["identity_ok"]:
            session["content_status"] = session["contentStatus"] = "error"
            session["has_transcript"] = session["hasTranscript"] = False
        turns = parsed["turns"]
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
                    "title": turn.get("outlineTitle") or f"Interaction {index + 1}",
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
            "warnings": parsed["warnings"],
        }
        self._detail_cache[session_id] = {"stamp": stamp, "detail": copy.deepcopy(detail)}
        return detail

    def delete(self, session_id):
        if session_id not in self._sources:
            self.discover_sessions()
        source = self._sources.get(session_id)
        if source is None:
            return None
        workspace_path, events_path = source
        session_dir = events_path.parent.resolve()
        root = self.session_root.resolve()
        try:
            relative = session_dir.relative_to(root)
        except ValueError as exc:
            raise ValueError("session source is outside the configured root") from exc
        if len(relative.parts) != 1 or relative.name == self.trash_dir_name:
            raise ValueError("invalid Copilot CLI session directory")
        if not events_path.is_file():
            return None
        batch = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        target = root / self.trash_dir_name / f"{batch}-{secrets.token_hex(3)}" / relative.name
        target.parent.mkdir(parents=True, exist_ok=False)
        session_dir.replace(target)
        self._sources.pop(session_id, None)
        self._summary_cache.pop(session_id, None)
        self._detail_cache.pop(session_id, None)
        return {"id": session_id, "provider": self.provider_id, "recoverable": True, "trashName": target.name}
