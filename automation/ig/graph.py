"""A small, honest, dependency-free HTTP client for the Graph API.

Why not `requests`: the whole repo installs and runs on the Python standard
library so a fresh clone can post a Reel without a package manager. `requests`
costs one line to add later if this ever needs it.

Why a class instead of scattered urlopen calls: every outbound call has to pass
through the same gate. That gate is where rate limits, the kill switch and the
audit log live, and there must be exactly one of it.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from . import config


class GraphError(RuntimeError):
    """A Graph API call failed. The message is safe to print."""

    def __init__(self, message: str, *, code: int | None = None, subcode: int | None = None,
                 kind: str = "error", payload: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.kind = kind
        self.payload = dict(payload or {})

    @property
    def retryable(self) -> bool:
        # 4 = app rate limit, 17 = user request limit, 32/613 = call-volume throttle,
        # 1/2 = transient server, 9007 = media not ready yet.
        return self.code in {1, 2, 4, 17, 32, 613, 9007} or self.kind in {"timeout", "network"}


@dataclass
class Usage:
    """What Meta says we have left, from headers on every response."""

    call_count: int = 0
    total_cputime: int = 0
    total_time: int = 0
    regain_in_minutes: int | None = None
    publishing_used: int | None = None
    publishing_total: int | None = None


@dataclass
class Client:
    graph: config.Graph = field(default_factory=lambda: config.GRAPH)
    timeout: int = 60
    retries: int = 3
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        self._last_call = 0.0
        self.min_interval = float(config.env("IG_MIN_CALL_INTERVAL", "0.35") or 0.35)

    # -- request plumbing --------------------------------------------------
    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()

    def _read_usage(self, headers: Mapping[str, str]) -> None:
        raw = headers.get("x-business-use-case-usage") or headers.get(
            "x-app-usage") or headers.get("x-ad-account-usage")
        if raw:
            try:
                parsed = json.loads(raw)
                first = parsed[list(parsed)[0]] if isinstance(parsed, dict) else parsed
                if isinstance(first, list):
                    first = first[0]
                self.usage.call_count = int(first.get("call_count", 0))
                self.usage.total_cputime = int(first.get("total_cputime", 0))
                self.usage.total_time = int(first.get("total_time", 0))
                if first.get("estimated_time_to_regain_access"):
                    self.usage.regain_in_minutes = int(
                        first["estimated_time_to_regain_access"])
            except (ValueError, KeyError, IndexError, TypeError):
                pass

    def _guard(self, what: str) -> None:
        if config.is_paused():
            raise GraphError(
                f"Refusing to {what}: the agent is paused. "
                f"Delete {config.KILL_SWITCH} to resume.",
                kind="paused")
        if self.usage.call_count >= 90 or self.usage.total_cputime >= 90:
            raise GraphError(
                f"Refusing to {what}: call budget is at "
                f"{max(self.usage.call_count, self.usage.total_cputime)}% and Meta is about "
                f"to throttle. Back off for {self.usage.regain_in_minutes or 15} minutes.",
                kind="throttled")

    def request(self, method: str, path: str, params: Mapping[str, Any] | None = None,
                data: Mapping[str, Any] | None = None, *, what: str = "call the API") -> dict:
        """One API call. `path` is relative to the versioned host, e.g. 'me/media'."""
        self._guard(what)
        url = f"{self.graph.host}/{self.graph.version}/{path.lstrip('/')}"
        query = dict(params or {})
        query.setdefault("access_token", self.graph.token)
        if method.upper() in {"GET", "DELETE"} and data is None:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
            body = None
        else:
            body = urllib.parse.urlencode({**query, **dict(data or {})}).encode()

        last: GraphError | None = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                req = urllib.request.Request(url, data=body, method=method.upper())
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self._read_usage(resp.headers)
                    raw = resp.read().decode("utf-8", "replace")
                return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                self._read_usage(dict(exc.headers or {}))
                last = self._parse_error(exc.code, raw)
                if not last.retryable:
                    raise last from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = GraphError(f"Network failure during {what}: {exc}", kind="network")
            if attempt < self.retries:
                time.sleep(min(60, 2 ** attempt * 2))
        raise last or GraphError(f"{what} failed with no error detail.")

    @staticmethod
    def _parse_error(status: int, raw: str) -> GraphError:
        try:
            err = json.loads(raw).get("error", {})
        except ValueError:
            err = {"message": raw[:400]}
        return GraphError(
            f"HTTP {status}: {err.get('message', 'unknown Graph error')}"
            + (f" (code {err.get('code')}/{err.get('error_subcode')})" if err.get("code") else ""),
            code=err.get("code"), subcode=err.get("error_subcode"),
            payload=err, kind="error")

    # -- convenience -------------------------------------------------------
    def get(self, path: str, **params: Any) -> dict:
        return self.request("GET", path, params=params)

    def post(self, path: str, **data: Any) -> dict:
        return self.request("POST", path, data=data)

    def delete(self, path: str, **params: Any) -> dict:
        return self.request("DELETE", path, params=params)

    # -- who am I ----------------------------------------------------------
    def me(self) -> dict:
        return self.get("me", fields="user_id,username,account_type,media_count,followers_count")

    def publishing_usage(self) -> tuple[int, int]:
        """Live publishing quota. Meta's two docs disagree (50 vs 100), so we ask."""
        try:
            payload = self.get("me/content_publishing_limit", fields="quota_usage,config")
        except GraphError:
            return (0, config.LIMITS.posts_per_24h)
        rows = payload.get("data") or [{}]
        row = rows[0] if isinstance(rows, list) else rows
        used = int(row.get("quota_usage", 0) or 0)
        cfg = row.get("config") or {}
        total = int(cfg.get("quota_total", config.LIMITS.posts_per_24h) or
                    config.LIMITS.posts_per_24h)
        self.usage.publishing_used, self.usage.publishing_total = used, total
        return used, total


def check_token() -> dict:
    """Verify the token works and return the account it belongs to."""
    client = Client()
    return client.me()


def refresh_long_lived_token(secret: str | None = None) -> dict:
    """Extend a 60-day token by 60 days.

    Meta does not issue a new token on refresh: it pushes the expiry out. That
    matters operationally, because it means the token in .env stays valid and
    nothing has to be redeployed. Run this weekly from cron and the account never
    goes quiet mid-campaign, which is the only failure here nobody notices fast.
    """
    secret = secret or config.require("META_APP_SECRET")
    token = config.require("IG_ACCESS_TOKEN")
    url = ("https://graph.instagram.com/refresh_access_token"
           f"?grant_type=ig_refresh_token&access_token={token}")
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise GraphError(
            f"token refresh failed HTTP {exc.code}: {detail}. A token that will not "
            f"refresh is usually older than 60 days: mint a new one from the Meta app "
            f"and update IG_ACCESS_TOKEN.") from None
