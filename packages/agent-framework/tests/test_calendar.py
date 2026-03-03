"""Tests for the FastMail JMAP calendar tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_framework.tools.fastmail.calendar import (
    _format_calendar,
    _format_event,
    get_calendar_events,
    list_calendars,
)


class TestFormatCalendar:
    """Tests for calendar formatting helper."""

    def test_format_calendar(self):
        """Test calendar formatting."""
        calendar = {
            "id": "cal-123",
            "name": "Work",
            "color": "#0060ff",
            "isVisible": True,
            "isSubscribed": True,
            "description": "Work calendar",
            "sortOrder": 1,
        }

        result = _format_calendar(calendar)

        assert result["id"] == "cal-123"
        assert result["name"] == "Work"
        assert result["color"] == "#0060ff"
        assert result["is_visible"] is True
        assert result["is_subscribed"] is True
        assert result["description"] == "Work calendar"
        assert result["sort_order"] == 1

    def test_format_calendar_defaults(self):
        """Test calendar formatting with missing fields."""
        calendar = {"id": "cal-456", "name": "Personal"}

        result = _format_calendar(calendar)

        assert result["id"] == "cal-456"
        assert result["name"] == "Personal"
        assert result["color"] is None
        assert result["is_visible"] is True
        assert result["is_subscribed"] is True
        assert result["description"] == ""
        assert result["sort_order"] == 0


class TestFormatEvent:
    """Tests for event formatting helper."""

    def test_format_event(self):
        """Test event formatting with all fields."""
        event = {
            "id": "evt-123",
            "calendarIds": {"cal-123": True},
            "title": "Team Standup",
            "description": "Daily standup meeting",
            "start": "2025-03-15T09:00:00",
            "timeZone": "America/New_York",
            "duration": "PT30M",
            "locations": {
                "loc-1": {"name": "Conference Room A"},
            },
            "participants": {
                "p-1": {
                    "name": "Alice",
                    "sendTo": {"imip": "mailto:alice@example.com"},
                    "kind": "individual",
                    "participationStatus": "accepted",
                },
                "p-2": {
                    "name": "Bob",
                    "sendTo": {"imip": "mailto:bob@example.com"},
                    "kind": "individual",
                    "participationStatus": "tentative",
                },
            },
            "status": "confirmed",
            "updated": "2025-03-14T12:00:00Z",
        }

        result = _format_event(event)

        assert result["id"] == "evt-123"
        assert result["calendar_ids"] == ["cal-123"]
        assert result["title"] == "Team Standup"
        assert result["description"] == "Daily standup meeting"
        assert result["start"] == "2025-03-15T09:00:00"
        assert result["time_zone"] == "America/New_York"
        assert result["duration"] == "PT30M"
        assert result["location"] == "Conference Room A"
        assert len(result["participants"]) == 2
        assert result["participants"][0]["name"] == "Alice"
        assert result["participants"][0]["email"] == "alice@example.com"
        assert result["participants"][1]["participation_status"] == "tentative"
        assert result["status"] == "confirmed"
        assert result["updated_at"] == "2025-03-14T12:00:00Z"

    def test_format_event_minimal(self):
        """Test event formatting with minimal fields."""
        event = {
            "id": "evt-456",
            "calendarIds": {},
            "start": "2025-03-15T10:00:00",
        }

        result = _format_event(event)

        assert result["id"] == "evt-456"
        assert result["title"] == "(no title)"
        assert result["description"] == ""
        assert result["location"] is None
        assert result["participants"] == []

    def test_format_event_multiple_locations(self):
        """Test event formatting with multiple locations."""
        event = {
            "id": "evt-789",
            "calendarIds": {},
            "locations": {
                "loc-1": {"name": "Room A"},
                "loc-2": {"name": "Room B"},
            },
        }

        result = _format_event(event)
        # Both locations should be joined
        assert "Room A" in result["location"]
        assert "Room B" in result["location"]


class TestListCalendars:
    """Tests for list_calendars function."""

    @pytest.mark.asyncio
    async def test_list_calendars_success(self):
        """Test successful calendar listing."""
        mock_response = {
            "methodResponses": [
                [
                    "Calendar/get",
                    {
                        "list": [
                            {
                                "id": "cal-1",
                                "name": "Personal",
                                "color": "#ff0000",
                                "isVisible": True,
                                "isSubscribed": True,
                                "description": "",
                                "sortOrder": 0,
                            },
                            {
                                "id": "cal-2",
                                "name": "Work",
                                "color": "#0000ff",
                                "isVisible": True,
                                "isSubscribed": True,
                                "description": "Work stuff",
                                "sortOrder": 1,
                            },
                        ]
                    },
                    "calendar-list",
                ]
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await list_calendars()

            assert result["status"] == "success"
            assert result["total_count"] == 2
            assert len(result["calendars"]) == 2
            assert result["calendars"][0]["name"] == "Personal"
            assert result["calendars"][1]["name"] == "Work"

    @pytest.mark.asyncio
    async def test_list_calendars_empty(self):
        """Test listing when no calendars exist."""
        mock_response = {
            "methodResponses": [
                [
                    "Calendar/get",
                    {"list": []},
                    "calendar-list",
                ]
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await list_calendars()

            assert result["status"] == "success"
            assert result["total_count"] == 0
            assert result["calendars"] == []

    @pytest.mark.asyncio
    async def test_list_calendars_jmap_error(self):
        """Test JMAP error response handling."""
        mock_response = {
            "methodResponses": [
                [
                    "error",
                    {"type": "forbidden", "description": "No calendar access"},
                    "calendar-list",
                ]
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await list_calendars()

            assert result["status"] == "error"
            assert "calendar query failed" in result["message"]

    @pytest.mark.asyncio
    async def test_list_calendars_auth_error(self):
        """Test authentication error handling."""
        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Unauthorized",
                    request=MagicMock(),
                    response=MagicMock(status_code=401),
                )
            )
            mock_get_client.return_value = mock_client

            result = await list_calendars()

            assert result["status"] == "error"
            assert result["error_type"] == "AuthenticationError"
            assert result["status_code"] == 401


class TestGetCalendarEvents:
    """Tests for get_calendar_events function."""

    @pytest.mark.asyncio
    async def test_get_events_success(self):
        """Test successful event retrieval."""
        mock_response = {
            "methodResponses": [
                [
                    "CalendarEvent/query",
                    {"ids": ["evt-1", "evt-2"], "total": 2},
                    "event-query",
                ],
                [
                    "CalendarEvent/get",
                    {
                        "list": [
                            {
                                "id": "evt-1",
                                "calendarIds": {"cal-1": True},
                                "title": "Meeting",
                                "description": "",
                                "start": "2025-03-15T09:00:00",
                                "timeZone": "America/New_York",
                                "duration": "PT1H",
                                "locations": None,
                                "participants": None,
                                "status": "confirmed",
                                "updated": "2025-03-14T12:00:00Z",
                            },
                            {
                                "id": "evt-2",
                                "calendarIds": {"cal-1": True},
                                "title": "Lunch",
                                "description": "Team lunch",
                                "start": "2025-03-15T12:00:00",
                                "timeZone": "America/New_York",
                                "duration": "PT1H",
                                "locations": {"loc-1": {"name": "Cafe"}},
                                "participants": None,
                                "status": "confirmed",
                                "updated": "2025-03-14T12:00:00Z",
                            },
                        ]
                    },
                    "event-get",
                ],
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_calendar_events(
                after="2025-03-15T00:00:00",
                before="2025-03-15T23:59:59",
            )

            assert result["status"] == "success"
            assert result["total_count"] == 2
            assert len(result["events"]) == 2
            assert result["events"][0]["title"] == "Meeting"
            assert result["events"][1]["title"] == "Lunch"
            assert result["events"][1]["location"] == "Cafe"

    @pytest.mark.asyncio
    async def test_get_events_with_calendar_filter(self):
        """Test event retrieval with calendar filter."""
        mock_response = {
            "methodResponses": [
                [
                    "CalendarEvent/query",
                    {"ids": [], "total": 0},
                    "event-query",
                ],
                [
                    "CalendarEvent/get",
                    {"list": []},
                    "event-get",
                ],
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_calendar_events(
                after="2025-03-15T00:00:00",
                before="2025-03-15T23:59:59",
                calendar_id="cal-work",
            )

            assert result["status"] == "success"
            assert result["total_count"] == 0

            # Verify the filter included inCalendars
            call_args = mock_client._call.call_args[0][0]
            query_filter = call_args[0][1]["filter"]
            assert query_filter["inCalendars"] == ["cal-work"]

    @pytest.mark.asyncio
    async def test_get_events_with_title_filter(self):
        """Test event retrieval with title filter."""
        mock_response = {
            "methodResponses": [
                [
                    "CalendarEvent/query",
                    {"ids": [], "total": 0},
                    "event-query",
                ],
                [
                    "CalendarEvent/get",
                    {"list": []},
                    "event-get",
                ],
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_calendar_events(
                after="2025-03-01T00:00:00",
                before="2025-03-31T23:59:59",
                title="standup",
            )

            assert result["status"] == "success"

            # Verify the filter included title
            call_args = mock_client._call.call_args[0][0]
            query_filter = call_args[0][1]["filter"]
            assert query_filter["title"] == "standup"

    @pytest.mark.asyncio
    async def test_get_events_empty(self):
        """Test event retrieval with no results."""
        mock_response = {
            "methodResponses": [
                [
                    "CalendarEvent/query",
                    {"ids": [], "total": 0},
                    "event-query",
                ],
                [
                    "CalendarEvent/get",
                    {"list": []},
                    "event-get",
                ],
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_calendar_events(
                after="2025-03-15T00:00:00",
                before="2025-03-15T23:59:59",
            )

            assert result["status"] == "success"
            assert result["total_count"] == 0
            assert result["events"] == []
            assert result["has_more"] is False

    @pytest.mark.asyncio
    async def test_get_events_jmap_error(self):
        """Test JMAP error during event query."""
        mock_response = {
            "methodResponses": [
                [
                    "error",
                    {"type": "invalidArguments", "description": "Bad date format"},
                    "event-query",
                ]
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_calendar_events(
                after="bad-date",
                before="bad-date",
            )

            assert result["status"] == "error"
            assert "event query failed" in result["message"]

    @pytest.mark.asyncio
    async def test_get_events_network_error(self):
        """Test network error handling."""
        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )
            mock_get_client.return_value = mock_client

            result = await get_calendar_events(
                after="2025-03-15T00:00:00",
                before="2025-03-15T23:59:59",
            )

            assert result["status"] == "error"
            assert result["error_type"] == "RequestError"

    @pytest.mark.asyncio
    async def test_get_events_incomplete_response(self):
        """Test handling of incomplete JMAP response."""
        mock_response = {
            "methodResponses": [
                [
                    "CalendarEvent/query",
                    {"ids": ["evt-1"], "total": 1},
                    "event-query",
                ],
                # Missing CalendarEvent/get response
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_calendar_events(
                after="2025-03-15T00:00:00",
                before="2025-03-15T23:59:59",
            )

            assert result["status"] == "error"
            assert "Incomplete response" in result["message"]

    @pytest.mark.asyncio
    async def test_get_events_has_more(self):
        """Test has_more flag when total exceeds returned count."""
        mock_response = {
            "methodResponses": [
                [
                    "CalendarEvent/query",
                    {"ids": ["evt-1"], "total": 5},
                    "event-query",
                ],
                [
                    "CalendarEvent/get",
                    {
                        "list": [
                            {
                                "id": "evt-1",
                                "calendarIds": {},
                                "title": "Event",
                                "start": "2025-03-15T09:00:00",
                            },
                        ]
                    },
                    "event-get",
                ],
            ]
        }

        with patch("agent_framework.tools.fastmail.calendar._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_calendar_events(
                after="2025-03-15T00:00:00",
                before="2025-03-15T23:59:59",
                limit=1,
            )

            assert result["status"] == "success"
            assert result["total_count"] == 5
            assert result["has_more"] is True
