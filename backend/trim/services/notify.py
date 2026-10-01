"""Outbound notifications to a chat webhook (Slack- and Teams-compatible JSON).

Only HTTPS URLs are accepted, the request has a short timeout, and a failure is
logged, never raised: a broken webhook must not block an access decision.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, webhook_url: str = "", timeout: float = 5.0) -> None:
        self.url = webhook_url.strip()
        if self.url:
            parsed = urlparse(self.url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("TRIM_WEBHOOK_URL must be an https:// URL")
        self.timeout = timeout
        self.sent: list[str] = []  # kept for tests and the in-app activity feed

    def send(self, text: str) -> bool:
        self.sent.append(text)
        if not self.url:
            return False
        try:
            r = httpx.post(self.url, json={"text": text}, timeout=self.timeout, follow_redirects=False)
            r.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("webhook notification failed: %s", type(exc).__name__)
            return False
