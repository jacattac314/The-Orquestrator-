"""
OpenClaw — Gmail email tracking tool.

Provides Gmail integration for reading, searching, and tracking emails
and follow-ups like a personal assistant.

Setup:
  1. Go to https://console.cloud.google.com/
  2. Create a project → enable the Gmail API and Google Calendar API
  3. Create OAuth 2.0 credentials (Desktop app) → download as credentials.json
  4. Save as ~/.openclaw/google_credentials.json
  5. Run: python scripts/google_setup.py  (first-time auth)

Environment variables:
  GOOGLE_CREDENTIALS_FILE — path to credentials.json
  GOOGLE_TOKEN_FILE       — where the OAuth token is cached
  GMAIL_USER_ID           — Gmail address to act as (default: "me")
"""

from __future__ import annotations

import base64
import os
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from openclaw.tools.google_auth import get_service, token_path as _token_path, credentials_path as _credentials_path


def _get_gmail_service():
    """Return an authenticated Gmail API service object, or raise ImportError/FileNotFoundError."""
    return get_service("gmail", "v1")


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    parts = payload.get("parts", [])
    if parts:
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        # Recurse into first multipart part
        for part in parts:
            result = _decode_body(part)
            if result:
                return result
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""


def _format_message_summary(msg: dict) -> str:
    headers = msg.get("payload", {}).get("headers", [])
    subject = _header(headers, "Subject") or "(no subject)"
    sender = _header(headers, "From") or "unknown"
    date_str = _header(headers, "Date") or ""
    snippet = msg.get("snippet", "")
    msg_id = msg.get("id", "")
    labels = ", ".join(msg.get("labelIds", []))
    return (
        f"ID: {msg_id}\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Date: {date_str}\n"
        f"Labels: {labels}\n"
        f"Snippet: {snippet}\n"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public tool functions (called by AgentIQ tools)
# ──────────────────────────────────────────────────────────────────────────────

def list_inbox_emails(max_results: int = 10, unread_only: bool = True) -> str:
    """List recent inbox emails.

    Args:
        max_results: How many messages to retrieve (1–50).
        unread_only: If True, only return unread messages.

    Returns:
        Formatted list of recent messages with IDs, senders, subjects, and snippets.
    """
    try:
        svc = _get_gmail_service()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    user_id = os.environ.get("GMAIL_USER_ID", "me")
    query = "in:inbox"
    if unread_only:
        query += " is:unread"

    try:
        result = svc.users().messages().list(userId=user_id, q=query, maxResults=min(max_results, 50)).execute()
        messages = result.get("messages", [])
        if not messages:
            label = "unread inbox" if unread_only else "inbox"
            return f"No messages found in {label}."

        lines = [f"{'Unread ' if unread_only else ''}Inbox ({len(messages)} messages):\n"]
        for item in messages:
            msg = svc.users().messages().get(userId=user_id, id=item["id"], format="metadata",
                                             metadataHeaders=["From", "Subject", "Date"]).execute()
            lines.append(_format_message_summary(msg))
            lines.append("─" * 40)
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Failed to list emails: {exc}"


def read_email(message_id: str) -> str:
    """Read the full content of an email by its ID.

    Args:
        message_id: The Gmail message ID (e.g. from list_inbox_emails).

    Returns:
        Full email headers and body text.
    """
    try:
        svc = _get_gmail_service()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    user_id = os.environ.get("GMAIL_USER_ID", "me")
    try:
        msg = svc.users().messages().get(userId=user_id, id=message_id, format="full").execute()
        headers = msg.get("payload", {}).get("headers", [])
        subject = _header(headers, "Subject") or "(no subject)"
        sender = _header(headers, "From") or "unknown"
        to = _header(headers, "To") or "unknown"
        date_str = _header(headers, "Date") or ""
        body = _decode_body(msg.get("payload", {}))
        body = body[:3000] + ("…[truncated]" if len(body) > 3000 else "")
        return (
            f"ID: {message_id}\n"
            f"From: {sender}\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            f"Date: {date_str}\n"
            f"Labels: {', '.join(msg.get('labelIds', []))}\n"
            f"\n--- Body ---\n{body}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Failed to read email {message_id}: {exc}"


def search_emails(query: str, max_results: int = 10) -> str:
    """Search Gmail using a query string.

    Supports all Gmail search operators (from:, to:, subject:, has:attachment, etc.)

    Args:
        query: Gmail search query (e.g. 'from:boss@company.com subject:report').
        max_results: Maximum number of results (1–50).

    Returns:
        Formatted list of matching messages.
    """
    try:
        svc = _get_gmail_service()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    user_id = os.environ.get("GMAIL_USER_ID", "me")
    try:
        result = svc.users().messages().list(userId=user_id, q=query, maxResults=min(max_results, 50)).execute()
        messages = result.get("messages", [])
        if not messages:
            return f"No messages found for query: {query!r}"

        lines = [f"Search results for {query!r} ({len(messages)} messages):\n"]
        for item in messages:
            msg = svc.users().messages().get(userId=user_id, id=item["id"], format="metadata",
                                             metadataHeaders=["From", "Subject", "Date"]).execute()
            lines.append(_format_message_summary(msg))
            lines.append("─" * 40)
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Search failed: {exc}"


def check_followups(days_threshold: int = 3) -> str:
    """Find sent emails that have received no reply after N days.

    Checks your Sent folder for emails where the thread has only one message
    (i.e. no reply received) and the email is older than days_threshold days.

    Args:
        days_threshold: Number of days after which an unreplied email is flagged (default 3).

    Returns:
        A list of emails that may need follow-up, with sender, subject, and age in days.
    """
    try:
        svc = _get_gmail_service()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    user_id = os.environ.get("GMAIL_USER_ID", "me")
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days_threshold)
    # Search sent mail older than threshold
    after_ts = int((cutoff - timedelta(days=30)).timestamp())  # look back 30 days max
    query = f"in:sent after:{after_ts}"

    try:
        result = svc.users().messages().list(userId=user_id, q=query, maxResults=50).execute()
        messages = result.get("messages", [])
        if not messages:
            return "No sent emails found in the search window."

        followups = []
        for item in messages:
            msg = svc.users().messages().get(userId=user_id, id=item["id"], format="metadata",
                                             metadataHeaders=["Subject", "To", "Date"]).execute()
            headers = msg.get("payload", {}).get("headers", [])
            date_str = _header(headers, "Date")
            subject = _header(headers, "Subject") or "(no subject)"
            to = _header(headers, "To") or "unknown"
            thread_id = msg.get("threadId", "")

            # Parse date
            try:
                sent_dt = parsedate_to_datetime(date_str).astimezone(timezone.utc) if date_str else None
            except Exception:  # noqa: BLE001
                sent_dt = None

            if sent_dt is None or sent_dt > cutoff:
                continue  # Too recent, skip

            # Check if thread has more than one message (i.e. reply exists)
            thread = svc.users().threads().get(userId=user_id, id=thread_id, format="minimal").execute()
            thread_msgs = thread.get("messages", [])
            if len(thread_msgs) > 1:
                continue  # Reply exists, not a follow-up

            age_days = (datetime.now(tz=timezone.utc) - sent_dt).days
            followups.append((age_days, to, subject, item["id"]))

        if not followups:
            return f"Great — no unreplied sent emails older than {days_threshold} days."

        followups.sort(reverse=True)  # oldest first
        lines = [f"Emails needing follow-up (no reply after {days_threshold}+ days):\n"]
        for age, to, subject, msg_id in followups:
            lines.append(f"  ID:      {msg_id}")
            lines.append(f"  To:      {to}")
            lines.append(f"  Subject: {subject}")
            lines.append(f"  Age:     {age} day(s)")
            lines.append("─" * 40)
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Follow-up check failed: {exc}"


def mark_as_followup(message_id: str) -> str:
    """Star an email to mark it for follow-up.

    Args:
        message_id: The Gmail message ID to star/mark.

    Returns:
        Confirmation message.
    """
    try:
        svc = _get_gmail_service()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    user_id = os.environ.get("GMAIL_USER_ID", "me")
    try:
        svc.users().messages().modify(
            userId=user_id,
            id=message_id,
            body={"addLabelIds": ["STARRED"]},
        ).execute()
        return f"Email {message_id} starred and marked for follow-up."
    except Exception as exc:  # noqa: BLE001
        return f"Failed to mark email: {exc}"


def get_email_summary(max_unread: int = 20) -> str:
    """Get a personal-assistant-style summary of your current inbox state.

    Returns counts of unread messages, flagged/starred items, and any
    emails awaiting follow-up (sent > 3 days ago with no reply).

    Args:
        max_unread: How many unread messages to scan for the summary (default 20).

    Returns:
        A concise inbox briefing.
    """
    try:
        svc = _get_gmail_service()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    user_id = os.environ.get("GMAIL_USER_ID", "me")
    lines = ["── Gmail Inbox Briefing ──\n"]

    # Unread count
    try:
        profile = svc.users().getProfile(userId=user_id).execute()
        email_address = profile.get("emailAddress", "unknown")
        lines.append(f"Account: {email_address}")

        labels_result = svc.users().labels().get(userId=user_id, id="INBOX").execute()
        unread = labels_result.get("messagesUnread", "?")
        total = labels_result.get("messagesTotal", "?")
        lines.append(f"Inbox: {unread} unread / {total} total\n")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"(Could not fetch inbox stats: {exc})\n")

    # Recent unread senders/subjects
    try:
        result = svc.users().messages().list(
            userId=user_id, q="in:inbox is:unread", maxResults=min(max_unread, 50)
        ).execute()
        msgs = result.get("messages", [])
        if msgs:
            lines.append(f"Latest {len(msgs)} unread messages:")
            for item in msgs[:10]:
                msg = svc.users().messages().get(userId=user_id, id=item["id"], format="metadata",
                                                 metadataHeaders=["From", "Subject", "Date"]).execute()
                headers = msg.get("payload", {}).get("headers", [])
                sender = _header(headers, "From") or "unknown"
                subject = _header(headers, "Subject") or "(no subject)"
                lines.append(f"  • [{sender}] {subject}")
            lines.append("")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"(Could not fetch unread messages: {exc})\n")

    # Starred (follow-up flagged)
    try:
        result = svc.users().messages().list(
            userId=user_id, q="is:starred", maxResults=10
        ).execute()
        starred = result.get("messages", [])
        lines.append(f"Starred / follow-up flagged: {len(starred)} message(s)")
        for item in starred[:5]:
            msg = svc.users().messages().get(userId=user_id, id=item["id"], format="metadata",
                                             metadataHeaders=["From", "Subject"]).execute()
            headers = msg.get("payload", {}).get("headers", [])
            sender = _header(headers, "From") or "unknown"
            subject = _header(headers, "Subject") or "(no subject)"
            lines.append(f"  ★ [{sender}] {subject}")
        lines.append("")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"(Could not fetch starred messages: {exc})\n")

    # Quick follow-up check
    try:
        result = svc.users().messages().list(
            userId=user_id,
            q=f"in:sent after:{int((datetime.now(tz=timezone.utc) - timedelta(days=30)).timestamp())}",
            maxResults=30,
        ).execute()
        sent_msgs = result.get("messages", [])
        needs_followup = 0
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=3)
        for item in sent_msgs:
            msg = svc.users().messages().get(userId=user_id, id=item["id"], format="metadata",
                                             metadataHeaders=["Date"]).execute()
            headers = msg.get("payload", {}).get("headers", [])
            date_str = _header(headers, "Date")
            try:
                sent_dt = parsedate_to_datetime(date_str).astimezone(timezone.utc) if date_str else None
            except Exception:  # noqa: BLE001
                sent_dt = None
            if sent_dt and sent_dt < cutoff:
                thread = svc.users().threads().get(
                    userId=user_id, id=msg.get("threadId", ""), format="minimal"
                ).execute()
                if len(thread.get("messages", [])) == 1:
                    needs_followup += 1
        lines.append(f"Sent emails awaiting reply (>3 days): {needs_followup}")
        if needs_followup > 0:
            lines.append("  → Use check_followups tool for details")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"(Could not check follow-ups: {exc})")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# CLI: first-time OAuth setup
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Run: python scripts/google_setup.py  to authorise Google access.")
