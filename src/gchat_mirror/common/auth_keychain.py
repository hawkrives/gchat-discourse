# ABOUTME: macOS keychain helper using python-keyring for storing credentials
# ABOUTME: Provides simple store/retrieve helpers with small abstraction
from __future__ import annotations

from typing import Optional

import keyring


def store_secret(service: str, username: str, secret: str) -> None:
    """Store a secret in the system keyring.

    Args:
        service: A service name (e.g., 'gchat-mirror')
        username: The account/user key under the service
        secret: The secret value to store
    """
    keyring.set_password(service, username, secret)


def fetch_secret(service: str, username: str) -> Optional[str]:
    """Fetch a secret from the system keyring.

    Returns None if not found.
    """
    return keyring.get_password(service, username)
