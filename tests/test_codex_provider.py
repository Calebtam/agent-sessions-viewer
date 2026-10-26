import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from providers.codex import CodexProvider


class CodexProviderTests(unittest.TestCase):
    def test_discovers_and_loads_without_exposing_absolute_path_as_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "2026" / "10" / "23" / "rollout-test.jsonl"
            path.parent.mkdir(parents=True)
            rows = [
                {"type": "session_meta", "payload": {"id": "codex-fixture", "cwd": "/tmp/example"}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": "Question"}},
                {"type": "event_msg", "payload": {"type": "agent_message", "phase": "final_answer", "message": "Answer"}},
            ]
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            provider = CodexProvider(root)
            sessions = provider.discover_sessions()
            self.assertEqual(len(sessions), 1)
            self.assertTrue(sessions[0]["id"].startswith("codex:"))
            self.assertNotIn(str(root), sessions[0]["id"])
            detail = provider.load(sessions[0]["id"])
            self.assertEqual(detail["turns"][0]["assistant"], "Answer")

    def test_delete_moves_source_to_recoverable_trash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "2026" / "10" / "23" / "rollout-delete.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"type": "session_meta", "payload": {"id": "delete-fixture"}}) + "\n",
                encoding="utf-8",
            )
            provider = CodexProvider(root)
            session = provider.discover_sessions()[0]
            result = provider.delete(session["id"])
            self.assertTrue(result["recoverable"])
            self.assertFalse(path.exists())
            trashed = list((root / provider.trash_dir_name).rglob("rollout-delete.jsonl"))
            self.assertEqual(len(trashed), 1)
            self.assertEqual(provider.discover_sessions(), [])


if __name__ == "__main__":
    unittest.main()
