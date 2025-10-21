# ABOUTME: Metrics container and Prometheus exporter
# ABOUTME: Exposes a small Metrics dataclass and to_prometheus formatter
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Metrics:
    spaces_synced: int = 0
    messages_synced: int = 0
    attachments_downloaded: int = 0

    def to_prometheus(self) -> str:
        lines = [
            "# TYPE gchat_mirror_spaces_synced gauge",
            f"gchat_mirror_spaces_synced {self.spaces_synced}",
            "# TYPE gchat_mirror_messages_synced gauge",
            f"gchat_mirror_messages_synced {self.messages_synced}",
            "# TYPE gchat_mirror_attachments_downloaded gauge",
            f"gchat_mirror_attachments_downloaded {self.attachments_downloaded}",
        ]
        return "\n".join(lines) + "\n"


metrics = Metrics()
