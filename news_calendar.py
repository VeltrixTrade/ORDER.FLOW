"""
Economic Calendar Filter Module for XAU/USD Trading Bot.

Fetches upcoming economic news events from a free Forex Factory mirror API,
filters for USD-related high-impact events, and generates bilingual
Telegram alerts (Arabic + English).
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pytz
import requests

logger = logging.getLogger(__name__)

# Free Forex Factory calendar mirror
CALENDAR_API_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Request timeout in seconds
REQUEST_TIMEOUT = 10


class NewsCalendar:
    """Economic calendar filter for USD news events relevant to XAU/USD trading."""

    def __init__(self):
        self._cached_events: list[dict] = []
        self._last_fetch: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=15)  # Re-fetch every 15 minutes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_upcoming_news(self) -> list[dict]:
        """Fetch upcoming USD economic news events.

        Returns a list of dicts with keys:
            - time     (datetime)  – event time in UTC
            - title    (str)       – event title / name
            - impact   (str)       – 'high', 'medium', or 'low'
            - currency (str)       – currency code (always 'USD' after filtering)

        Uses a local cache (15-min TTL) to avoid hammering the API.
        Returns an empty list on any failure so the bot never crashes.
        """
        now_utc = datetime.now(pytz.utc)

        # Return cache if still fresh
        if (
            self._last_fetch is not None
            and (now_utc - self._last_fetch) < self._cache_ttl
            and self._cached_events
        ):
            return self._cached_events

        try:
            response = requests.get(CALENDAR_API_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            raw_events = response.json()

            parsed: list[dict] = []
            for event in raw_events:
                parsed_event = self._parse_event(event)
                if parsed_event is not None:
                    parsed.append(parsed_event)

            # Sort by time ascending
            parsed.sort(key=lambda e: e["time"])

            # Keep only future events
            self._cached_events = [e for e in parsed if e["time"] > now_utc]
            self._last_fetch = now_utc

            logger.info(
                "Fetched %d upcoming USD news events from calendar API.",
                len(self._cached_events),
            )
            return self._cached_events

        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to fetch economic calendar: %s", exc)
            return []
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Failed to parse economic calendar data: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001 – never crash the bot
            logger.error("Unexpected error in fetch_upcoming_news: %s", exc)
            return []

    def is_high_impact_soon(self, minutes_before: int = 30) -> bool:
        """Return True if a HIGH-impact USD event is within *minutes_before* minutes."""
        now_utc = datetime.now(pytz.utc)
        window_end = now_utc + timedelta(minutes=minutes_before)

        for event in self.fetch_upcoming_news():
            if event["impact"] == "high" and now_utc <= event["time"] <= window_end:
                return True
        return False

    def get_next_high_impact(self) -> Optional[dict]:
        """Return the next upcoming high-impact USD event, or None."""
        now_utc = datetime.now(pytz.utc)

        for event in self.fetch_upcoming_news():
            if event["impact"] == "high" and event["time"] > now_utc:
                return event
        return None

    def format_news_alert(self) -> str:
        """Build an HTML-formatted bilingual Telegram alert for upcoming news.

        Returns an empty string if there is no upcoming high-impact event.
        """
        event = self.get_next_high_impact()
        if event is None:
            return ""

        now_utc = datetime.now(pytz.utc)
        delta = event["time"] - now_utc
        minutes_remaining = max(int(delta.total_seconds() / 60), 0)

        event_time_str = event["time"].strftime("%H:%M UTC")
        title = event["title"]

        # Build a bilingual (Arabic + English) alert with emoji
        alert_lines = [
            "⚠️ <b>تنبيه أخبار اقتصادية | Economic News Alert</b>",
            "",
            f"🔴 خبر قوي خلال <b>{minutes_remaining}</b> دقيقة | "
            f"High Impact News in <b>{minutes_remaining}</b> min",
            f"📰 {title}",
            f"🕐 الوقت | Time: <b>{event_time_str}</b>",
            f"💵 العملة | Currency: <b>{event['currency']}</b>",
            "",
            "⛔ يُنصح بالحذر في التداول خلال فترة الأخبار",
            "⛔ Trade with caution during news events",
        ]

        return "\n".join(alert_lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_event(raw: dict) -> Optional[dict]:
        """Parse a single raw calendar event from the API.

        Returns a structured dict filtered to USD only, or None if the
        event should be skipped.
        """
        try:
            currency = (raw.get("country") or "").strip().upper()
            if currency != "USD":
                return None

            # Impact mapping – the API uses 'High', 'Medium', 'Low', etc.
            raw_impact = (raw.get("impact") or "").strip().lower()
            impact_map = {
                "high": "high",
                "medium": "medium",
                "low": "low",
                "holiday": "low",
                "non-economic": "low",
            }
            impact = impact_map.get(raw_impact)
            if impact is None:
                # Unknown impact level; treat as low
                impact = "low"

            title = (raw.get("title") or "Unknown Event").strip()

            # Parse the date + time from the API.
            # The API typically provides "date" as e.g. "2026-07-08T12:30:00-04:00"
            date_str = raw.get("date", "")
            event_dt = _parse_datetime(date_str)
            if event_dt is None:
                return None

            return {
                "time": event_dt,
                "title": title,
                "impact": impact,
                "currency": currency,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping unparseable calendar event: %s", exc)
            return None


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _parse_datetime(date_str: str) -> Optional[datetime]:
    """Try multiple formats to parse the API date string into a UTC datetime."""
    if not date_str:
        return None

    # Formats observed from the Forex Factory mirror API
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",       # ISO with offset  (e.g. 2026-07-08T12:30:00-04:00)
        "%Y-%m-%dT%H:%M:%S",          # ISO without offset
        "%Y-%m-%d %H:%M:%S",          # Space-separated
        "%Y-%m-%d",                    # Date only
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # Ensure timezone-aware (assume UTC if no tzinfo)
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            else:
                dt = dt.astimezone(pytz.utc)
            return dt
        except ValueError:
            continue

    logger.debug("Could not parse date string: %s", date_str)
    return None
