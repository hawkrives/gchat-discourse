# ABOUTME: HTTP health check endpoint for monitoring
# ABOUTME: Provides status information on port 4981

from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any

import structlog
from gchat_mirror.common.metrics import metrics as metrics_module

if TYPE_CHECKING:
    from gchat_mirror.sync.daemon import SyncDaemon

logger = structlog.get_logger()


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Handle health check HTTP requests."""

    def do_GET(self) -> None:
        """Handle GET request."""
        if self.path == "/health":
            self.send_health_response()
        elif self.path == "/metrics":
            self.send_metrics_response()
        else:
            self.send_not_found()

    def send_health_response(self) -> None:
        """Send health check response."""
        # Get status from daemon
        daemon: SyncDaemon = self.server.daemon  # type: ignore

        status = {
            "status": "ok" if daemon.running else "stopped",
            "timestamp": datetime.now().isoformat(),
            "spaces_synced": daemon.get_space_count(),
            "messages_synced": daemon.get_message_count(),
            "last_sync": daemon.get_last_sync_time(),
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(status).encode())

    def send_metrics_response(self) -> None:
        """Send metrics in Prometheus format."""
        # Use centralized metrics container if available; fall back to daemon counters
        try:
            payload = metrics_module.to_prometheus()
            # Ensure the 'up' metric is present and reflects daemon state
            daemon: SyncDaemon = self.server.daemon  # type: ignore
            payload += "\n# HELP gchat_mirror_up Whether the sync daemon is running\n"
            payload += "# TYPE gchat_mirror_up gauge\n"
            payload += f"gchat_mirror_up {1 if daemon.running else 0}\n"

            # Append legacy metric names expected by some tests/consumers
            # Use daemon counters for legacy metric names to match expectations
            spaces = daemon.get_space_count()
            messages = daemon.get_message_count()
            attachments = int(
                getattr(
                    daemon,
                    "attachments_downloaded",
                    getattr(metrics_module, "attachments_downloaded", 0),
                )
            )

            payload += "\n# Legacy metric names for compatibility\n"
            payload += f"gchat_mirror_spaces_total {spaces}\n"
            payload += f"gchat_mirror_messages_total {messages}\n"
            payload += f"gchat_mirror_attachments_downloaded {attachments}\n"
        except Exception:
            # Fallback to daemon-provided counters; produce full prometheus exposition
            daemon: SyncDaemon = self.server.daemon  # type: ignore
            payload = (
                "# HELP gchat_mirror_spaces_total Total number of spaces\n"
                "# TYPE gchat_mirror_spaces_total gauge\n"
                f"gchat_mirror_spaces_total {daemon.get_space_count()}\n\n"
                "# HELP gchat_mirror_messages_total Total number of messages\n"
                "# TYPE gchat_mirror_messages_total gauge\n"
                f"gchat_mirror_messages_total {daemon.get_message_count()}\n\n"
                "# HELP gchat_mirror_attachments_downloaded Total attachments downloaded\n"
                "# TYPE gchat_mirror_attachments_downloaded gauge\n"
                f"gchat_mirror_attachments_downloaded {getattr(daemon, 'attachments_downloaded', 0)}\n\n"
                "# HELP gchat_mirror_up Whether the sync daemon is running\n"
                "# TYPE gchat_mirror_up gauge\n"
                f"gchat_mirror_up {1 if daemon.running else 0}\n"
            )

        # Send HTTP response
        self.send_response(200)
        # Keep header simple for tests and compatibility
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(payload.encode())

    def send_not_found(self) -> None:
        """Send 404 response."""
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Override to use structlog."""
        logger.info(
            "health_check_request",
            method=self.command,
            path=self.path,
            client=self.client_address[0],
        )


class HealthCheckServer:
    """HTTP server for health checks."""

    def __init__(self, daemon: SyncDaemon, port: int = 4981):
        self.daemon = daemon
        self.port = port
        self.server: HTTPServer | None = None

    def start(self) -> None:
        """Start the health check server (non-blocking setup only)."""
        self.server = HTTPServer(("0.0.0.0", self.port), HealthCheckHandler)
        self.server.daemon = self.daemon  # type: ignore
        logger.info("health_check_server_started", port=self.port)

    def stop(self) -> None:
        """Stop the health check server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("health_check_server_stopped")
