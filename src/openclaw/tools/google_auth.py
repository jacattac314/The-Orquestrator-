"""
OpenClaw — shared Google OAuth2 authentication helper.

Handles a single OAuth2 token that covers both Gmail and Google Calendar,
so the user only needs to authorise once for all Google tools.

Environment variables:
  GOOGLE_CREDENTIALS_FILE  — path to credentials.json
                             (default: ~/.openclaw/google_credentials.json)
                             Also accepts legacy GMAIL_CREDENTIALS_FILE.
  GOOGLE_TOKEN_FILE        — where the OAuth token is cached
                             (default: ~/.openclaw/google_token.json)
                             Also accepts legacy GMAIL_TOKEN_FILE.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_DIR = Path.home() / ".openclaw"

# Combined scopes — covers all OpenClaw Google tools
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]


def credentials_path() -> Path:
    # Accept both new and legacy env var names
    val = (
        os.environ.get("GOOGLE_CREDENTIALS_FILE")
        or os.environ.get("GMAIL_CREDENTIALS_FILE")
        or str(_DEFAULT_DIR / "google_credentials.json")
    )
    return Path(val)


def token_path() -> Path:
    val = (
        os.environ.get("GOOGLE_TOKEN_FILE")
        or os.environ.get("GMAIL_TOKEN_FILE")
        or str(_DEFAULT_DIR / "google_token.json")
    )
    return Path(val)


def get_service(service_name: str, version: str):
    """Return an authenticated Google API service object.

    Args:
        service_name: e.g. "gmail", "calendar"
        version:      e.g. "v1", "v3"

    Raises:
        ImportError: if google client libraries are not installed.
        FileNotFoundError: if credentials.json is missing.
    """
    try:
        from google.oauth2.credentials import Credentials  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "Google client libraries not installed.\n"
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2\n"
            "  or: pip install -e '.[gmail]'"
        ) from exc

    cred_file = credentials_path()
    tok_file = token_path()
    tok_file.parent.mkdir(parents=True, exist_ok=True)

    creds = None
    if tok_file.exists():
        creds = Credentials.from_authorized_user_file(str(tok_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred_file.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found at:\n  {cred_file}\n\n"
                    "To fix this:\n"
                    "  1. Go to https://console.cloud.google.com/\n"
                    "  2. Enable Gmail API and Google Calendar API\n"
                    "  3. Credentials → Create → OAuth 2.0 Client ID (Desktop app)\n"
                    "  4. Download JSON and save as:\n"
                    f"       {cred_file}\n"
                    "  5. Run: python scripts/google_setup.py"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), SCOPES)
            creds = flow.run_local_server(port=0)
        tok_file.write_text(creds.to_json())

    return build(service_name, version, credentials=creds)
