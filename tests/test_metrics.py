from gchat_mirror.common.metrics import metrics


def test_to_prometheus_contains_values():
    metrics.spaces_synced = 5
    metrics.messages_synced = 10
    metrics.attachments_downloaded = 2

    out = metrics.to_prometheus()
    assert "gchat_mirror_spaces_synced 5" in out
    assert "gchat_mirror_messages_synced 10" in out
    assert "gchat_mirror_attachments_downloaded 2" in out
