"""Small provider registry used by the v2 session API."""


class SessionRegistry:
    def __init__(self, providers=()):
        self.providers = {provider.provider_id: provider for provider in providers}
        self.errors = {}

    def discover(self):
        sessions = []
        self.errors = {}
        for provider in self.providers.values():
            try:
                sessions.extend(provider.discover_sessions())
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                self.errors[provider.provider_id] = type(exc).__name__
        return sessions

    def load(self, session_id):
        provider_id = session_id.split(":", 1)[0]
        provider = self.providers.get(provider_id)
        if provider is None:
            return None
        return provider.load(session_id)

    def delete(self, session_id):
        provider_id = session_id.split(":", 1)[0]
        provider = self.providers.get(provider_id)
        if provider is None:
            return None
        return provider.delete(session_id)

    def provider_infos(self):
        labels = {
            "codex": "Codex",
            "copilot-cli": "Copilot CLI",
            "vscode-chat": "VS Code Chat",
        }
        return [
            {
                "id": provider_id,
                "label": labels.get(provider_id, provider_id),
                "status": "error" if provider_id in self.errors else "ready",
                "error": self.errors.get(provider_id),
            }
            for provider_id in self.providers
        ]
