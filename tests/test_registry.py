import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from providers.base import SessionProvider
from registry import SessionRegistry


class FakeProvider(SessionProvider):
    def __init__(self, provider_id, sessions=None, error=None):
        self.provider_id = provider_id
        self.sessions = sessions or []
        self.error = error

    def discover(self):
        return {}

    def discover_sessions(self):
        if self.error:
            raise self.error
        return list(self.sessions)

    def load(self, session_id):
        return {"id": session_id}

    def delete(self, session_id):
        return {"deleted": session_id, "provider": self.provider_id}


class RegistryTests(unittest.TestCase):
    def test_provider_failure_is_isolated(self):
        good = FakeProvider("good", [{"id": "good:one", "provider": "good"}])
        bad = FakeProvider("bad", error=ValueError("private detail"))
        registry = SessionRegistry([good, bad])
        self.assertEqual(registry.discover(), good.sessions)
        self.assertEqual(registry.errors, {"bad": "ValueError"})

    def test_load_routes_by_provider_prefix(self):
        registry = SessionRegistry([FakeProvider("good")])
        self.assertEqual(registry.load("good:one"), {"id": "good:one"})
        self.assertIsNone(registry.load("missing:one"))

    def test_delete_routes_by_provider_prefix(self):
        registry = SessionRegistry([FakeProvider("good")])
        self.assertEqual(
            registry.delete("good:one"),
            {"deleted": "good:one", "provider": "good"},
        )
        self.assertIsNone(registry.delete("missing:one"))


if __name__ == "__main__":
    unittest.main()
