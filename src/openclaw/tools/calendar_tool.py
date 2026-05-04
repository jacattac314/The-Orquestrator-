"""
OpenClaw — Google Calendar tool.

Allows the agent to act as a personal scheduling assistant:
list, search, create, update, and delete calendar events.

Setup (one-time):
  python scripts/google_setup.py

Environment variables:
  GOOGLE_CREDENTIALS_FILE — path to OAuth2 credentials JSON
  GOOGLE_TOKEN_FILE       — where the auth token is cached
  GOOGLE_CALENDAR_ID      — calendar to use (default: "primary")
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any

from openclaw.tools.google_auth import get_service

_CALENDAR_ID = lambda: os.environ.get("GOOGLE_CALENDAR_ID", "primary")  # noqa: E731

# ISO 8601 format used by the Calendar API
_DT_FMT = "%Y-%m-%dT%H:%M:%S"


def _cal():
    """Return an authenticated Calendar API service, or raise."""
    return get_service("calendar", "v3")


def _fmt_event(event: dict) -> str:
    """Format a single calendar event for display."""
    summary = event.get("summary", "(no title)")
    start = event.get("start", {})
    end = event.get("end", {})
    start_str = start.get("dateTime", start.get("date", "?"))
    end_str = end.get("dateTime", end.get("date", "?"))
    location = event.get("location", "")
    description = event.get("description", "")
    attendees = event.get("attendees", [])
    event_id = event.get("id", "")
    link = event.get("htmlLink", "")

    lines = [
        f"ID:       {event_id}",
        f"Title:    {summary}",
        f"Start:    {start_str}",
        f"End:      {end_str}",
    ]
    if location:
        lines.append(f"Location: {location}")
    if description:
        lines.append(f"Notes:    {description[:200]}")
    if attendees:
        names = ", ".join(a.get("email", "") for a in attendees[:5])
        lines.append(f"Guests:   {names}")
    if link:
        lines.append(f"Link:     {link}")
    return "\n".join(lines)


def _parse_dt(dt_str: str) -> datetime:
    """Parse a human-friendly or ISO datetime string into a timezone-aware datetime."""
    dt_str = dt_str.strip()
    # Try ISO formats
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Date only — treat as all-day
    try:
        d = date.fromisoformat(dt_str)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except ValueError:
        pass
    raise ValueError(
        f"Cannot parse datetime: {dt_str!r}. "
        "Use format: YYYY-MM-DD or YYYY-MM-DD HH:MM or YYYY-MM-DDTHH:MM:SS"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tool functions
# ──────────────────────────────────────────────────────────────────────────────

def list_upcoming_events(days: int = 7, max_results: int = 20) -> str:
    """List upcoming calendar events for the next N days.

    Args:
        days: How many days ahead to look (default 7).
        max_results: Maximum events to return (default 20).

    Returns:
        Formatted list of upcoming events with titles, times, and IDs.
    """
    try:
        svc = _cal()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    now = datetime.now(tz=timezone.utc)
    end = now + timedelta(days=days)

    try:
        result = svc.events().list(
            calendarId=_CALENDAR_ID(),
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            maxResults=min(max_results, 50),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        if not events:
            return f"No events in the next {days} day(s)."

        lines = [f"Upcoming events (next {days} day(s)) — {len(events)} found:\n"]
        for evt in events:
            lines.append(_fmt_event(evt))
            lines.append("─" * 40)
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Failed to list events: {exc}"


def search_events(query: str, days_back: int = 30, days_forward: int = 60) -> str:
    """Search calendar events by keyword.

    Args:
        query: Text to search for in event titles, descriptions, and locations.
        days_back: How many days in the past to search (default 30).
        days_forward: How many days in the future to search (default 60).

    Returns:
        Matching events with full details.
    """
    try:
        svc = _cal()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    now = datetime.now(tz=timezone.utc)
    try:
        result = svc.events().list(
            calendarId=_CALENDAR_ID(),
            q=query,
            timeMin=(now - timedelta(days=days_back)).isoformat(),
            timeMax=(now + timedelta(days=days_forward)).isoformat(),
            maxResults=20,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        if not events:
            return f"No events found matching {query!r}."

        lines = [f"Events matching {query!r} ({len(events)} found):\n"]
        for evt in events:
            lines.append(_fmt_event(evt))
            lines.append("─" * 40)
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Search failed: {exc}"


def create_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: str = "",
) -> str:
    """Create a new calendar event.

    Args:
        title: Event title / summary.
        start: Start datetime — e.g. "2024-06-15 14:00" or "2024-06-15T14:00:00".
               For all-day events use "2024-06-15".
        end:   End datetime — same formats as start.
               For all-day events use "2024-06-16" (day after the last day).
        description: Optional notes or agenda for the event.
        location: Optional location string (address or room name).
        attendees: Comma-separated email addresses to invite, e.g. "alice@x.com,bob@x.com".

    Returns:
        Confirmation with the created event ID and calendar link.
    """
    try:
        svc = _cal()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    # Detect all-day vs timed event
    all_day = len(start.strip()) == 10 and "T" not in start and " " not in start.strip()[4:]

    if all_day:
        start_body: dict[str, Any] = {"date": start.strip()}
        end_body: dict[str, Any] = {"date": end.strip()}
    else:
        try:
            start_dt = _parse_dt(start)
            end_dt = _parse_dt(end)
        except ValueError as exc:
            return str(exc)
        start_body = {"dateTime": start_dt.strftime(_DT_FMT), "timeZone": "UTC"}
        end_body = {"dateTime": end_dt.strftime(_DT_FMT), "timeZone": "UTC"}

    body: dict[str, Any] = {
        "summary": title,
        "start": start_body,
        "end": end_body,
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": e.strip()} for e in attendees.split(",") if e.strip()]

    try:
        event = svc.events().insert(calendarId=_CALENDAR_ID(), body=body, sendUpdates="all").execute()
        return (
            f"Event created successfully!\n"
            f"ID:    {event.get('id')}\n"
            f"Title: {event.get('summary')}\n"
            f"Start: {event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))}\n"
            f"End:   {event.get('end', {}).get('dateTime', event.get('end', {}).get('date'))}\n"
            f"Link:  {event.get('htmlLink', '')}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Failed to create event: {exc}"


def update_event(
    event_id: str,
    title: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    location: str = "",
) -> str:
    """Update an existing calendar event (only provided fields are changed).

    Args:
        event_id: The event ID (from list_upcoming_events or search_events).
        title: New title (leave blank to keep existing).
        start: New start datetime (leave blank to keep existing).
        end: New end datetime (leave blank to keep existing).
        description: New description (leave blank to keep existing).
        location: New location (leave blank to keep existing).

    Returns:
        Confirmation with updated event details.
    """
    try:
        svc = _cal()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    try:
        event = svc.events().get(calendarId=_CALENDAR_ID(), eventId=event_id).execute()
    except Exception as exc:  # noqa: BLE001
        return f"Could not fetch event {event_id}: {exc}"

    if title:
        event["summary"] = title
    if description:
        event["description"] = description
    if location:
        event["location"] = location
    if start:
        try:
            start_dt = _parse_dt(start)
            event["start"] = {"dateTime": start_dt.strftime(_DT_FMT), "timeZone": "UTC"}
        except ValueError as exc:
            return str(exc)
    if end:
        try:
            end_dt = _parse_dt(end)
            event["end"] = {"dateTime": end_dt.strftime(_DT_FMT), "timeZone": "UTC"}
        except ValueError as exc:
            return str(exc)

    try:
        updated = svc.events().update(calendarId=_CALENDAR_ID(), eventId=event_id, body=event).execute()
        return (
            f"Event updated!\n"
            f"ID:    {updated.get('id')}\n"
            f"Title: {updated.get('summary')}\n"
            f"Start: {updated.get('start', {}).get('dateTime', updated.get('start', {}).get('date'))}\n"
            f"End:   {updated.get('end', {}).get('dateTime', updated.get('end', {}).get('date'))}\n"
            f"Link:  {updated.get('htmlLink', '')}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Failed to update event: {exc}"


def delete_event(event_id: str) -> str:
    """Delete a calendar event by its ID.

    Args:
        event_id: The event ID to delete (from list_upcoming_events or search_events).

    Returns:
        Confirmation that the event was deleted.
    """
    try:
        svc = _cal()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    try:
        # Fetch title first for a meaningful confirmation message
        event = svc.events().get(calendarId=_CALENDAR_ID(), eventId=event_id).execute()
        title = event.get("summary", "(no title)")
        svc.events().delete(calendarId=_CALENDAR_ID(), eventId=event_id, sendUpdates="all").execute()
        return f"Deleted event: {title!r} (ID: {event_id})"
    except Exception as exc:  # noqa: BLE001
        return f"Failed to delete event {event_id}: {exc}"


def get_free_slots(date_str: str, duration_minutes: int = 60) -> str:
    """Find free time slots on a given day for scheduling a meeting.

    Args:
        date_str: The date to check, e.g. "2024-06-15".
        duration_minutes: Minimum free block size in minutes (default 60).

    Returns:
        List of free time windows during working hours (09:00 – 18:00 UTC).
    """
    try:
        svc = _cal()
    except (ImportError, FileNotFoundError) as exc:
        return str(exc)

    try:
        d = date.fromisoformat(date_str.strip())
    except ValueError:
        return f"Invalid date: {date_str!r}. Use YYYY-MM-DD format."

    day_start = datetime(d.year, d.month, d.day, 9, 0, tzinfo=timezone.utc)
    day_end = datetime(d.year, d.month, d.day, 18, 0, tzinfo=timezone.utc)

    try:
        result = svc.freebusy().query(body={
            "timeMin": day_start.isoformat(),
            "timeMax": day_end.isoformat(),
            "items": [{"id": _CALENDAR_ID()}],
        }).execute()

        busy_periods = result.get("calendars", {}).get(_CALENDAR_ID(), {}).get("busy", [])

        # Build busy intervals
        busy: list[tuple[datetime, datetime]] = []
        for period in busy_periods:
            s = datetime.fromisoformat(period["start"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(period["end"].replace("Z", "+00:00"))
            busy.append((s, e))
        busy.sort()

        # Find free gaps
        free_slots = []
        cursor = day_start
        for b_start, b_end in busy:
            if cursor < b_start:
                gap_minutes = int((b_start - cursor).total_seconds() / 60)
                if gap_minutes >= duration_minutes:
                    free_slots.append((cursor, b_start))
            cursor = max(cursor, b_end)
        if cursor < day_end:
            gap_minutes = int((day_end - cursor).total_seconds() / 60)
            if gap_minutes >= duration_minutes:
                free_slots.append((cursor, day_end))

        if not free_slots:
            return f"No free slots of {duration_minutes}+ minutes on {date_str} (09:00–18:00 UTC)."

        lines = [f"Free slots on {date_str} (≥{duration_minutes} min, 09:00–18:00 UTC):\n"]
        for s, e in free_slots:
            lines.append(f"  {s.strftime('%H:%M')} – {e.strftime('%H:%M')} UTC")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Free/busy check failed: {exc}"
