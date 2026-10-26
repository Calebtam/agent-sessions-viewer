import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from parsers.copilot_cli import ParseLimits, load_workspace_yaml, parse_copilot_session
from providers.copilot_cli import CopilotCLIProvider


class CopilotCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "session-state"
        self.root.mkdir()

    def make_session(self, session_id="11111111-1111-1111-1111-111111111111"):
        root = self.root / session_id
        root.mkdir()
        workspace = root / "workspace.yaml"
        workspace.write_text(
            "\n".join([
                f'id: "{session_id}"',
                'cwd: "/tmp/example"',
                'name: "Fixture session"',
                'created_at: "2026-10-23T00:00:00Z"',
                'updated_at: "2026-10-23T01:00:00Z"',
                "user_named: false",
            ]) + "\n",
            encoding="utf-8",
        )
        rows = [
            {
                "type": "session.start",
                "data": {"sessionId": session_id, "startTime": "2026-10-23T00:00:00Z", "context": {"cwd": "/tmp/example"}},
                "id": "e0", "timestamp": "2026-10-23T00:00:00Z", "parentId": None,
            },
            {
                "type": "user.message",
                "data": {
                    "content": "Question",
                    "transformedContent": "Question with context",
                    "attachments": [{"type": "file", "displayName": "example.py", "text": "safe fixture"}],
                    "messageId": "m1", "interactionId": "i1", "turnId": "u1",
                },
                "id": "e1", "timestamp": "2026-10-23T00:01:00Z", "parentId": "e0",
            },
            {
                "type": "assistant.message",
                "data": {
                    "messageId": "m2", "content": "", "reasoningText": "Reasoning",
                    "toolRequests": [{"toolCallId": "tc1", "name": "shell", "arguments": {"command": "true"}}],
                    "interactionId": "i1", "turnId": "t1",
                },
                "id": "e2", "timestamp": "2026-10-23T00:01:01Z", "parentId": "e1",
            },
            {
                "type": "tool.execution_start",
                "data": {"toolCallId": "tc1", "toolName": "shell", "arguments": {"command": "true"}, "turnId": "t1"},
                "id": "e3", "timestamp": "2026-10-23T00:01:02Z", "parentId": "e2",
            },
            {
                "type": "tool.execution_complete",
                "data": {"toolCallId": "tc1", "turnId": "t1", "interactionId": "i1", "success": True, "result": {"content": "ok"}},
                "id": "e4", "timestamp": "2026-10-23T00:01:03Z", "parentId": "e3",
            },
            {
                "type": "assistant.message",
                "data": {"messageId": "m3", "content": "Answer", "reasoningText": "", "toolRequests": [], "interactionId": "i1", "turnId": "t2"},
                "id": "e5", "timestamp": "2026-10-23T00:01:04Z", "parentId": "e4",
            },
        ]
        events = root / "events.jsonl"
        events.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        return workspace, events

    def test_flat_workspace_and_interaction_tool_mapping(self):
        workspace, events = self.make_session()
        self.assertEqual(load_workspace_yaml(workspace)["name"], "Fixture session")
        parsed = parse_copilot_session(workspace, events)
        self.assertTrue(parsed["identity_ok"])
        self.assertEqual(parsed["bad_lines"], 0)
        self.assertEqual(parsed["tool_count"], 1)
        self.assertEqual(len(parsed["turns"]), 1)
        turn = parsed["turns"][0]
        self.assertEqual(turn["user"], "Question")
        self.assertEqual(turn["assistant"], "Answer")
        self.assertIn("Reasoning", turn["reasoning"])
        self.assertIn("Tool: shell (success)", turn["reasoning"])
        self.assertIn("Attachments:", turn["user_context"])

    def test_folded_yaml_title(self):
        workspace, _ = self.make_session()
        workspace.write_text(
            workspace.read_text(encoding="utf-8").replace(
                'name: "Fixture session"', "name: >-\n  Fixture\n  session"
            ),
            encoding="utf-8",
        )
        self.assertEqual(load_workspace_yaml(workspace)["name"], "Fixture session")

    def test_truncated_line_is_partial_and_keeps_valid_turn(self):
        workspace, events = self.make_session()
        with events.open("ab") as stream:
            stream.write(b'{"type":')
        parsed = parse_copilot_session(workspace, events)
        self.assertEqual(parsed["bad_lines"], 1)
        self.assertEqual(len(parsed["turns"]), 1)

    def test_limits_reject_large_line(self):
        workspace, events = self.make_session()
        parsed = parse_copilot_session(
            workspace, events, limits=ParseLimits(max_line_bytes=10)
        )
        self.assertGreater(parsed["bad_lines"], 0)

    def test_provider_discovers_and_loads_fixture(self):
        self.make_session()
        provider = CopilotCLIProvider(self.root)
        sessions = provider.discover_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["provider"], "copilot-cli")
        self.assertEqual(sessions[0]["turn_count"], 1)
        detail = provider.load(sessions[0]["id"])
        self.assertEqual(detail["total"], 1)
        self.assertEqual(detail["turns"][0]["assistant"], "Answer")

    def test_identity_mismatch_is_error(self):
        workspace, events = self.make_session()
        workspace.write_text(
            workspace.read_text(encoding="utf-8").replace(
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
                1,
            ),
            encoding="utf-8",
        )
        session = CopilotCLIProvider(self.root).discover_sessions()[0]
        self.assertEqual(session["content_status"], "error")
        self.assertFalse(session["has_transcript"])

    def test_delete_moves_entire_session_directory_to_trash(self):
        workspace, events = self.make_session()
        session_dir = events.parent
        provider = CopilotCLIProvider(self.root)
        session = provider.discover_sessions()[0]
        result = provider.delete(session["id"])
        self.assertTrue(result["recoverable"])
        self.assertFalse(session_dir.exists())
        trashed_events = list(
            (self.root / provider.trash_dir_name).rglob("events.jsonl")
        )
        self.assertEqual(len(trashed_events), 1)
        self.assertTrue((trashed_events[0].parent / "workspace.yaml").is_file())
        self.assertEqual(provider.discover_sessions(), [])


if __name__ == "__main__":
    unittest.main()
