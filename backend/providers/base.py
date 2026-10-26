from abc import ABC, abstractmethod


class SessionProvider(ABC):
    provider_id = "base"

    @abstractmethod
    def discover(self):
        """Discover sessions or source diagnostics."""

    @abstractmethod
    def discover_sessions(self):
        """Return normalized session summaries."""

    def load(self, session_id):
        raise NotImplementedError

    def delete(self, session_id):
        """Move a session source to provider-managed trash when supported."""
        raise NotImplementedError
