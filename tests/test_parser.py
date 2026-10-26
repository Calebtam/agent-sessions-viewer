import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from parser import load_session, load_session_meta, load_session_preview


class ParserTests(unittest.TestCase):
    def write_jsonl(self, rows):
        temp = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".jsonl", delete=False
        )
        with temp:
            for row in rows:
                temp.write(json.dumps(row) + "\n")
        self.addCleanup(Path(temp.name).unlink, missing_ok=True)
        return Path(temp.name)

    def test_event_messages_meta_preview_and_tools(self):
        path = self.write_jsonl([
            {"type": "session_meta", "payload": {"id": "s1", "cwd": "/work"}},
            {"type": "event_msg", "timestamp": "2026-01-01", "payload": {"type": "user_message", "message": "Question"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}},
            {"type": "event_msg", "payload": {"type": "agent_message", "phase": "final_answer", "message": "Answer"}},
        ])
        self.assertEqual(load_session_meta(path)["session_id"], "s1")
        self.assertEqual(load_session_preview(path), ["Question"])
        turns = load_session(path)
        self.assertEqual(turns[0]["user"], "Question")
        self.assertEqual(turns[0]["assistant"], "Answer")
        self.assertIn("Tool call", turns[0]["reasoning"])

    def test_hidden_context_is_not_a_user_turn(self):
        path = self.write_jsonl([
            {"type": "event_msg", "payload": {"type": "user_message", "message": "<environment_context>private</environment_context>"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Visible"}},
            {"type": "event_msg", "payload": {"type": "agent_message", "phase": "final_answer", "message": "Done"}},
        ])
        self.assertEqual(load_session_preview(path), ["Visible"])
        self.assertEqual(len(load_session(path)), 1)


if __name__ == "__main__":
    unittest.main()
