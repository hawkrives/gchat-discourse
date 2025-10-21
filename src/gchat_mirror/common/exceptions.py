# ABOUTME: Typed exceptions used across gchat-mirror
# ABOUTME: Defines base and domain-specific exceptions


class GChatMirrorError(Exception):
    """Base exception for gchat-mirror."""


class SyncError(GChatMirrorError):
    """Errors raised by the sync subsystem."""


class ExportError(GChatMirrorError):
    """Errors raised by exporter subsystems (e.g. Discourse exporter)."""
