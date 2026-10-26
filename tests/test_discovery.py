import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from discovery import CHAT_INDEX_KEY, discover_vscode_workspaces
from providers.vscode_chat import VSCodeChatProvider


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.user_dir = Path(self.temp.name) / "User"
        self.storage = self.user_dir / "workspaceStorage"
        self.storage.mkdir(parents=True)

    def make_db(self, workspace_id, rows, workspace="file:///tmp/example%20project"):
        root = self.storage / workspace_id
        root.mkdir()
        (root / "workspace.json").write_text(
            json.dumps({"folder": workspace}), encoding="utf-8"
        )
        with sqlite3.connect(root / "state.vscdb") as conn:
            conn.execute(
                "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
            )
            conn.executemany("INSERT INTO ItemTable(key, value) VALUES (?, ?)", rows)

    def test_discovers_index_without_returning_its_content(self):
        secret = '{"sessions":[{"title":"private text"}]}'
        self.make_db(
            "abc", [(CHAT_INDEX_KEY, secret), ("workbench.panel.chat", "secret")]
        )
        report = discover_vscode_workspaces(self.user_dir)
        self.assertEqual(report["database_count"], 1)
        self.assertEqual(report["chat_index_count"], 1)
        item = report["workspaces"][0]
        self.assertEqual(item["workspace"], "/tmp/example project")
        self.assertEqual(item["chat_index"]["value_bytes"], len(secret.encode()))
        serialized = json.dumps(report)
        self.assertNotIn("private text", serialized)
        self.assertNotIn('"secret"', serialized)

    def test_one_broken_database_does_not_hide_other_workspaces(self):
        self.make_db("good", [("agentSessions.state.cache", "x")])
        broken = self.storage / "broken"
        broken.mkdir()
        (broken / "state.vscdb").write_text("not sqlite", encoding="utf-8")
        report = discover_vscode_workspaces(self.user_dir)
        self.assertEqual(report["database_count"], 2)
        self.assertEqual(report["status_counts"]["error"], 1)
        self.assertEqual(report["status_counts"]["no_chat_index"], 1)

    def test_binary_index_is_reported_without_attempting_json_decode(self):
        self.make_db("binary", [(CHAT_INDEX_KEY, b"\x00\xff\x10")])
        report = discover_vscode_workspaces(self.user_dir)
        index = report["workspaces"][0]["chat_index"]
        self.assertEqual(index["value_type"], "blob")
        self.assertEqual(index["value_bytes"], 3)
        self.assertEqual(report["status_counts"], {"ok": 1})

    def test_provider_maps_real_v1_shape_to_index_only_session(self):
        source_id = "agent-host-copilotcli:/untitled-example"
        index = json.dumps({
            "version": 1,
            "entries": {
                source_id: {
                    "sessionId": "session-example",
                    "title": "Fixture title",
                    "lastMessageDate": 1792713600000,
                    "isEmpty": False,
                }
            },
        })
        self.make_db("workspace-id", [(CHAT_INDEX_KEY, index)])
        provider = VSCodeChatProvider(self.user_dir)
        sessions = provider.discover_sessions()
        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertTrue(session["id"].startswith("vscode-chat:workspace-id:"))
        self.assertEqual(session["provider"], "vscode-chat")
        self.assertEqual(session["content_status"], "index_only")
        self.assertFalse(session["has_transcript"])
        self.assertIsNone(session["turn_count"])
        self.assertEqual(session["contentStatus"], "index_only")
        self.assertFalse(session["hasTranscript"])
        self.assertIsNone(session["turnCount"])
        self.assertFalse(session["isNewChat"])
        detail = provider.load(session["id"])
        self.assertEqual(detail["turns"], [])
        self.assertIn("not been located", detail["notice"])

    def test_provider_marks_exact_new_chat_placeholder(self):
        index = json.dumps({
            "version": 1,
            "entries": {
                "new-chat-source": {
                    "sessionId": "new-chat-session",
                    "title": "New chat",
                    "lastMessageDate": 1792713600000,
                    "isEmpty": True,
                },
                "named-source": {
                    "sessionId": "named-session",
                    "title": "New chat investigation",
                    "lastMessageDate": 1792713600001,
                    "isEmpty": False,
                },
            },
        })
        self.make_db("workspace-id", [(CHAT_INDEX_KEY, index)])
        sessions = VSCodeChatProvider(self.user_dir).discover_sessions()
        by_title = {item["title"]: item for item in sessions}
        self.assertTrue(by_title["New chat"]["isNewChat"])
        self.assertFalse(by_title["New chat investigation"]["isNewChat"])


if __name__ == "__main__":
    unittest.main()
