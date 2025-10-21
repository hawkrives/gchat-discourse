# ABOUTME: HTTP health check endpoint for monitoring
# ABOUTME: Provides status information on port 4981

from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import TYPE_CHECKING, Any

import structlog

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
        daemon: SyncDaemon = self.server.daemon  # type: ignore

        metrics = f"""# HELP gchat_mirror_spaces_total Total number of spaces
# TYPE gchat_mirror_spaces_total gauge
gchat_mirror_spaces_total {daemon.get_space_count()}

# HELP gchat_mirror_messages_total Total number of messages
# TYPE gchat_mirror_messages_total gauge
gchat_mirror_messages_total {daemon.get_message_count()}

# HELP gchat_mirror_up Whether the sync daemon is running
# TYPE gchat_mirror_up gauge
gchat_mirror_up {1 if daemon.running else 0}
"""

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(metrics.encode())

    def send_not_found(self) -> None:
        """Send 404 response."""
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Override to use structlog."""
        logger.info("health_check_request", method=self.command, path=self.path, client=self.client_address[0])


class HealthCheckServer:
    """HTTP server for health checks."""

    def __init__(self, daemon: SyncDaemon, port: int = 4981):
        self.daemon = daemon
        self.port = port
        self.server: HTTPServer | None = None
        self.thread: Thread | None = None

    def start(self) -> None:
        """Start the health check server."""
        self.server = HTTPServer(("0.0.0.0", self.port), HealthCheckHandler)
        self.server.daemon = self.daemon  # type: ignore

        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        logger.info("health_check_server_started", port=self.port)

    def stop(self) -> None:
        """Stop the health check server."""
        if self.server:
            self.server.shutdown()
            logger.info("health_check_server_stopped")
