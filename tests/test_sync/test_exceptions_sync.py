from unittest.mock import MagicMock, patch

import pytest

from gchat_mirror.common.exceptions import SyncError
from gchat_mirror.sync.daemon import SyncDaemon


def test_start_raises_on_integrity_failure(tmp_path, monkeypatch):
    cfg = {}
    daemon = SyncDaemon(tmp_path, cfg)

    # Stub chat_db to simulate integrity failure
    fake_db = MagicMock()
    fake_db.db_path = tmp_path / "sync" / "chat.db"
    fake_db.connect.return_value = None
    fake_db.integrity_check.return_value = False
    daemon.chat_db = fake_db

    with pytest.raises(SyncError):
        daemon.start()


def test_start_raises_on_missing_connection(tmp_path, monkeypatch):
    cfg = {}
    daemon = SyncDaemon(tmp_path, cfg)

    # Stub chat_db to pass integrity but have no conn after connect
    fake_db = MagicMock()
    fake_db.db_path = tmp_path / "sync" / "chat.db"
    fake_db.connect.return_value = None
    fake_db.integrity_check.return_value = True
    fake_db.conn = None
    daemon.chat_db = fake_db

    # Stub authenticate and GoogleChatClient to avoid further errors
    monkeypatch.setattr('gchat_mirror.sync.daemon.authenticate', lambda k: {})

    with patch('gchat_mirror.sync.daemon.GoogleChatClient') as mock_gc:
        mock_gc.return_value = MagicMock()
        with pytest.raises(SyncError):
            daemon.start()
