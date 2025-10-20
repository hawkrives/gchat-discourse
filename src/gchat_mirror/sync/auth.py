# ABOUTME: Google OAuth authentication and credential management
# ABOUTME: Handles OAuth flow, token refresh, and keychain storage

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import keyring
import structlog

logger = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.memberships.readonly",
]

_SERVICE_NAME = "gchat-mirror"


def authenticate(credential_key: str = "gchat-sync") -> Credentials:
    """Authenticate with Google Chat API, returning valid credentials."""
    creds = load_credentials(credential_key)

    if creds and creds.valid:
        logger.info("credentials_loaded", source="keyring")
        return cast(Credentials, creds)

    if creds and creds.expired and creds.refresh_token:
        logger.info("credentials_refreshing")
        creds.refresh(Request())
        refreshed = cast(Credentials, creds)
        save_credentials(credential_key, refreshed)
        return refreshed

    logger.info("credentials_requesting_oauth")
    secrets_path = Path("client_secrets.json")
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    new_creds = flow.run_local_server(port=0)
    casted = cast(Credentials, new_creds)
    save_credentials(credential_key, casted)
    return casted


def load_credentials(credential_key: str) -> Optional[Credentials]:
    """Load credentials from system keychain."""
    stored = keyring.get_password(_SERVICE_NAME, credential_key)
    if not stored:
        return None

    try:
        data = json.loads(stored)
    except json.JSONDecodeError:
        logger.warning("credentials_invalid_json", credential_key=credential_key)
        return None

    creds = Credentials.from_authorized_user_info(data, scopes=SCOPES)
    return cast(Credentials, creds)


def save_credentials(credential_key: str, creds: Credentials) -> None:
    """Save credentials to system keychain."""
    serialized = creds.to_json()
    keyring.set_password(_SERVICE_NAME, credential_key, serialized)
    logger.info("credentials_saved", credential_key=credential_key)
