"""Calendar operations for FastMail.

Contains list_calendars and get_calendar_events functions using JMAP CalendarEvent API.
"""

import logging
from datetime import datetime
from typing import Any

from .client import _get_client
from .helpers import _handle_jmap_error

logger = logging.getLogger(__name__)


def _format_calendar(calendar: dict[str, Any]) -> dict[str, Any]:
    """Format a calendar for display."""
    return {
        "id": calendar.get("id"),
        "name": calendar.get("name"),
        "color": calendar.get("color"),
        "is_visible": calendar.get("isVisible", True),
        "is_subscribed": calendar.get("isSubscribed", True),
        "description": calendar.get("description", ""),
        "sort_order": calendar.get("sortOrder", 0),
    }


def _format_event(event: dict[str, Any]) -> dict[str, Any]:
    """Format a calendar event for display."""
    # Extract participants list
    participants_raw = event.get("participants") or {}
    participants = []
    for _, participant in participants_raw.items():
        participants.append(
            {
                "name": participant.get("name", ""),
                "email": participant.get("sendTo", {}).get("imip", "").replace("mailto:", ""),
                "kind": participant.get("kind", ""),
                "participation_status": participant.get("participationStatus", ""),
            }
        )

    # Build locations list
    locations_raw = event.get("locations") or {}
    locations = []
    for _, loc in locations_raw.items():
        name = loc.get("name", "")
        if name:
            locations.append(name)

    return {
        "id": event.get("id"),
        "calendar_ids": list(event.get("calendarIds", {}).keys()),
        "title": event.get("title", "(no title)"),
        "description": event.get("description", ""),
        "start": event.get("start"),
        "time_zone": event.get("timeZone"),
        "duration": event.get("duration"),
        "location": ", ".join(locations) if locations else None,
        "participants": participants,
        "status": event.get("status"),
        "updated_at": event.get("updated"),
    }


async def list_calendars(
    api_token: str | None = None,
) -> dict[str, Any]:
    """List all calendars in the FastMail account.

    Returns calendars with their name, color, visibility, and subscription status.

    Args:
        api_token: Optional FastMail API token. If not provided, uses
            FASTMAIL_API_TOKEN from environment.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - calendars: List of calendar objects
            - total_count: Number of calendars
            - message: Status message
    """
    logger.info("Listing FastMail calendars")

    try:
        client = _get_client(api_token)
        await client._ensure_session()

        response = await client._call(
            [
                [
                    "Calendar/get",
                    {
                        "accountId": client.account_id,
                        "properties": [
                            "id",
                            "name",
                            "color",
                            "isVisible",
                            "isSubscribed",
                            "description",
                            "sortOrder",
                        ],
                    },
                    "calendar-list",
                ]
            ]
        )

        method_responses = response.get("methodResponses", [])
        if not method_responses:
            return {
                "status": "error",
                "message": "No response from JMAP server",
            }

        result = method_responses[0]
        if result[0] == "error":
            logger.error(f"JMAP error listing calendars: {result[1].get('description')}")
            return {
                "status": "error",
                "message": "JMAP error: calendar query failed",
            }

        if result[0] != "Calendar/get":
            return {
                "status": "error",
                "message": "Unexpected response from JMAP server",
            }

        calendars = result[1].get("list", [])
        formatted = [_format_calendar(c) for c in calendars]

        # Sort by sort_order then name
        formatted.sort(key=lambda c: (c["sort_order"], c["name"]))

        logger.info(f"Found {len(formatted)} calendars")
        return {
            "status": "success",
            "calendars": formatted,
            "total_count": len(formatted),
            "message": f"Found {len(formatted)} calendars",
        }

    except Exception as e:
        return _handle_jmap_error(e, "listing calendars")


async def get_calendar_events(
    after: str,
    before: str,
    calendar_id: str | None = None,
    title: str | None = None,
    limit: int = 50,
    api_token: str | None = None,
) -> dict[str, Any]:
    """Query calendar events by date range.

    Retrieves events within the specified date range, optionally filtered
    by calendar and title text.

    Args:
        after: Start of date range (ISO 8601, e.g. "2025-03-01T00:00:00").
        before: End of date range (ISO 8601, e.g. "2025-03-31T23:59:59").
        calendar_id: Optional calendar ID to filter by.
        title: Optional title text to filter by (partial match).
        limit: Maximum number of events to return (1-100, default: 50).
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - events: List of formatted event objects
            - total_count: Total matching events
            - message: Status message
    """
    # Validate date parameters locally before sending to JMAP
    for label, value in [("after", after), ("before", before)]:
        try:
            datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return {
                "status": "error",
                "message": f"Invalid {label} date format. Use ISO 8601 (e.g. '2025-03-01T00:00:00').",
            }

    logger.info(f"Getting calendar events: {after} to {before}")

    try:
        client = _get_client(api_token)
        await client._ensure_session()

        # Build filter
        event_filter: dict[str, Any] = {
            "after": after,
            "before": before,
        }
        if calendar_id:
            event_filter["inCalendars"] = [calendar_id]
        if title:
            event_filter["title"] = title

        # Clamp limit
        limit = max(1, min(100, limit))

        response = await client._call(
            [
                [
                    "CalendarEvent/query",
                    {
                        "accountId": client.account_id,
                        "filter": event_filter,
                        "sort": [{"property": "start", "isAscending": True}],
                        "limit": limit,
                        "calculateTotal": True,
                    },
                    "event-query",
                ],
                [
                    "CalendarEvent/get",
                    {
                        "accountId": client.account_id,
                        "#ids": {
                            "resultOf": "event-query",
                            "name": "CalendarEvent/query",
                            "path": "/ids",
                        },
                        "properties": [
                            "id",
                            "calendarIds",
                            "title",
                            "description",
                            "start",
                            "timeZone",
                            "duration",
                            "locations",
                            "participants",
                            "status",
                            "updated",
                        ],
                    },
                    "event-get",
                ],
            ]
        )

        method_responses = response.get("methodResponses", [])

        query_result = None
        get_result = None
        for resp in method_responses:
            if resp[0] == "CalendarEvent/query":
                query_result = resp[1]
            elif resp[0] == "CalendarEvent/get":
                get_result = resp[1]
            elif resp[0] == "error":
                logger.error(f"JMAP error getting events: {resp[1].get('description')}")
                return {
                    "status": "error",
                    "message": "JMAP error: calendar event query failed",
                }

        if not query_result or not get_result:
            return {
                "status": "error",
                "message": "Incomplete response from JMAP server",
            }

        events = get_result.get("list", [])
        formatted = [_format_event(e) for e in events]
        total = query_result.get("total", len(formatted))

        logger.info(f"Retrieved {len(formatted)} events (total: {total})")
        return {
            "status": "success",
            "events": formatted,
            "total_count": total,
            "has_more": len(formatted) < total,
            "message": f"Retrieved {len(formatted)} of {total} events",
        }

    except Exception as e:
        return _handle_jmap_error(e, "getting calendar events")
