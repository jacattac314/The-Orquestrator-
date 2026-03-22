#!/usr/bin/env python3
"""
OpenClaw — Google OAuth2 first-time setup helper.

Run this once before using Gmail or Calendar tools:

    python scripts/google_setup.py

It will:
  1. Check that google_credentials.json exists in the right location
  2. Open a browser window so you can authorise access to Gmail + Calendar
  3. Save a token file so subsequent runs are fully automatic

Prerequisites
─────────────
1. Go to https://console.cloud.google.com/
2. Create (or select) a project
3. APIs & Services → Enable APIs:
      • Gmail API
      • Google Calendar API
4. APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
   • Application type: Desktop app
   • Download the JSON file
5. Save it as:
      ~/.openclaw/google_credentials.json          (default)
   or set GOOGLE_CREDENTIALS_FILE to a custom path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make sure the src package is importable when run from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def main() -> None:
    from openclaw.tools.google_auth import credentials_path, token_path

    cred_file = credentials_path()
    tok_file = token_path()

    print("═" * 60)
    print("  OpenClaw — Google OAuth2 Setup")
    print("  Covers: Gmail + Google Calendar")
    print("═" * 60)

    if not cred_file.exists():
        print(f"\nERROR: credentials file not found at:\n  {cred_file}")
        print(
            "\nTo fix this:\n"
            "  1. Go to https://console.cloud.google.com/\n"
            "  2. Enable Gmail API and Google Calendar API\n"
            "  3. Create OAuth2 credentials (Desktop app)\n"
            "  4. Download JSON and save it as:\n"
            f"       {cred_file}\n"
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
            "\nERROR: Google client libraries not installed.\n"
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2\n"
            "  or: pip install -e '.[gmail]'"
        )
        sys.exit(1)

    print("Google client libraries installed  ✓")
    print("\nOpening browser for OAuth2 authorisation…")
    print("(Scopes: Gmail read/modify + Google Calendar full access)")
    print("If the browser doesn't open, check the terminal for a URL.\n")

    try:
        from openclaw.tools.google_auth import get_service

        # Authenticate Gmail
        gmail_svc = get_service("gmail", "v1")
        profile = gmail_svc.users().getProfile(userId="me").execute()
        print(f"Gmail authenticated as: {profile['emailAddress']}  ✓")

        # Authenticate Calendar (reuses the same token)
        cal_svc = get_service("calendar", "v3")
        cal = cal_svc.calendarList().get(calendarId="primary").execute()
        print(f"Calendar authenticated: {cal.get('summary', 'primary')}  ✓")

        print(f"\nToken saved to: {tok_file}")
        print("\nSetup complete! You can now use Gmail and Calendar tools in OpenClaw.")
    except FileNotFoundError as exc:
        print(f"\nSetup failed: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\nSetup failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
