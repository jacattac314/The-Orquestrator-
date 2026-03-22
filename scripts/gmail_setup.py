#!/usr/bin/env python3
"""
OpenClaw — Gmail OAuth2 first-time setup helper.

Run this script once before using the Gmail tools:

    python scripts/gmail_setup.py

It will:
  1. Check that gmail_credentials.json exists in the right location
  2. Open a browser window so you can authorise access to your Gmail
  3. Save a token file so subsequent runs are automatic (no browser needed)

Prerequisites
─────────────
1. Go to https://console.cloud.google.com/
2. Create (or select) a project
3. APIs & Services → Enable APIs → search "Gmail API" → Enable
4. APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
   • Application type: Desktop app
   • Download the JSON file
5. Save it as one of:
   • ~/.openclaw/gmail_credentials.json  (default)
   • Any path you set in GMAIL_CREDENTIALS_FILE env var
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make sure the src package is importable when run from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def main() -> None:
    cred_dir = Path.home() / ".openclaw"
    cred_file = Path(os.environ.get("GMAIL_CREDENTIALS_FILE", cred_dir / "gmail_credentials.json"))
    token_file = Path(os.environ.get("GMAIL_TOKEN_FILE", cred_dir / "gmail_token.json"))

    print("═" * 60)
    print("  OpenClaw — Gmail Setup")
    print("═" * 60)

    if not cred_file.exists():
        print(f"\nERROR: credentials file not found at:\n  {cred_file}")
        print(
            "\nTo fix this:\n"
            "  1. Go to https://console.cloud.google.com/\n"
            "  2. Enable the Gmail API\n"
            "  3. Create OAuth2 credentials (Desktop app)\n"
            "  4. Download the JSON and save it to:\n"
            f"     {cred_file}\n"
            "  5. Re-run this script"
        )
        sys.exit(1)

    print(f"\nCredentials file: {cred_file}  ✓")

    # Check dependencies
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
    except ImportError:
        print(
            "\nERROR: Gmail dependencies not installed.\n"
            "Run:  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2\n"
            "  or: pip install -e '.[gmail]'"
        )
        sys.exit(1)

    print("Gmail dependencies installed  ✓")
    print("\nOpening browser for OAuth2 authorisation…")
    print("(If the browser doesn't open, check the terminal for a URL to visit manually.)\n")

    try:
        from openclaw.tools.gmail_tool import _get_gmail_service, _token_path
        svc = _get_gmail_service()
        profile = svc.users().getProfile(userId="me").execute()
        print(f"Authenticated as: {profile['emailAddress']}  ✓")
        print(f"Token saved to:   {_token_path()}")
        print("\nSetup complete! You can now use the Gmail tools in OpenClaw.")
    except FileNotFoundError as exc:
        print(f"Setup failed: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"Setup failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
