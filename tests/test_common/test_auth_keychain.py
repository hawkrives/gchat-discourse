from gchat_mirror.common import auth_keychain


def test_store_and_fetch_secret(monkeypatch):
    called = {}

    def fake_set_password(service, username, secret):
        called["service"] = service
        called["username"] = username
        called["secret"] = secret

    def fake_get_password(service, username):
        if service == called.get("service") and username == called.get("username"):
            return called.get("secret")
        return None

    monkeypatch.setattr(auth_keychain.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(auth_keychain.keyring, "get_password", fake_get_password)

    auth_keychain.store_secret("gchat-mirror", "test_user", "s3cr3t")
    assert auth_keychain.fetch_secret("gchat-mirror", "test_user") == "s3cr3t"
