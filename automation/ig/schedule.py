"""The scheduler: what goes out today, and whether it is allowed to.

Two independent decisions, deliberately separated:

* **When** — a slot from `state/content_plan.json`, in the account's timezone.
  Slots are informed by the niche (fintecph audiences in India read before the
  open and after the close) but they are the owner's to edit.
* **Whether** — `publish.publish_item` refuses anything not approved, over
  quota, or paused. This module does not second-guess that.

Run it from cron every 10 minutes. Idempotent: a slot already published or
already attempted in this window is skipped, so a slow cron overlap cannot
double-post, which is the one failure that actually embarrasses an account.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from . import config, publish, store

try:                                    # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:                     # pragma: no cover
    ZoneInfo = None                     # type: ignore


DEFAULT_PLAN = {
    "timezone": "Asia/Kolkata",
    "slots": [
        {"day": "Mon", "time": "08:10", "format": "reel", "theme": "teach"},
        {"day": "Tue", "time": "13:30", "format": "carousel", "theme": "teach"},
        {"day": "Wed", "time": "08:10", "format": "reel", "theme": "proof"},
        {"day": "Thu", "time": "19:45", "format": "reel", "theme": "opinion"},
        {"day": "Fri", "time": "08:10", "format": "reel", "theme": "story"},
        {"day": "Sat", "time": "11:00", "format": "carousel", "theme": "offer"},
        {"day": "Sun", "time": "18:00", "format": "story", "theme": "engage"},
    ],
    "stories_per_day": 2,
    "notes": "Four to five feed posts a week, at least three Reels, stories daily. "
             "Edit this, the agent reads it as the truth.",
}

DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


@dataclass
class Slot:
    at: datetime
    fmt: str
    theme: str
    label: str


def load_plan() -> dict:
    plan = store.read_json(config.CONTENT_PLAN, None)
    if not plan:
        config.ensure_dirs()
        store.write_json(config.CONTENT_PLAN, DEFAULT_PLAN)
        return DEFAULT_PLAN
    return plan


def tz_of(plan: dict) -> timezone:
    name = plan.get("timezone", "Asia/Kolkata")
    if ZoneInfo:
        try:
            return ZoneInfo(name)          # type: ignore[return-value]
        except Exception:
            pass
    return timezone.utc


def slots_between(start: datetime, end: datetime, plan: dict | None = None) -> list[Slot]:
    plan = plan or load_plan()
    tz = tz_of(plan)
    out: list[Slot] = []
    day = start.astimezone(tz).date()
    last = end.astimezone(tz).date()
    while day <= last:
        for entry in plan.get("slots", []):
            if DAYS.get(entry.get("day", ""), -1) != day.weekday():
                continue
            hour, minute = (int(x) for x in entry.get("time", "09:00").split(":"))
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            if start <= at <= end:
                out.append(Slot(at=at, fmt=entry.get("format", "reel"),
                                theme=entry.get("theme", "teach"),
                                label=f"{entry.get('day')} {entry.get('time')}"))
        day += timedelta(days=1)
    return sorted(out, key=lambda s: s.at)


def due_now(*, window_minutes: int = 15, now: datetime | None = None) -> list[Slot]:
    """Slots that should fire between now and now+window."""
    now = now or datetime.now(timezone.utc)
    return slots_between(now, now + timedelta(minutes=window_minutes))


def _attempted_recently(item_id: str, hours: int = 6) -> bool:
    cutoff = time.time() - hours * 3600
    for row in store.read_jsonl(config.POSTED_LOG):
        if row.get("item_id") == item_id and (row.get("published_at_epoch") or 0) >= cutoff:
            return True
    return False


def _approved_for(fmt: str, theme: str) -> dict | None:
    """Oldest approved item that matches the slot, or any approved item.

    Matching the theme first keeps the weekly shape the plan asked for, but a
    slot with no matching item still publishes something approved rather than
    going dark: consistency beats the theme.
    """
    items = [i for i in store.load_queue() if i.get("status") == "approved"]
    if not items:
        return None
    themed = [i for i in items if i.get("data", {}).get("theme") == theme
              and i.get("format") == fmt]
    by_format = [i for i in items if i.get("format") == fmt]
    pool = themed or by_format or items
    return sorted(pool, key=lambda i: i.get("created_at", ""))[0]


def tick(*, dry_run: bool = False, now: datetime | None = None) -> list[dict]:
    """One scheduler pass. Returns what it did, or would have done."""
    results: list[dict] = []
    if config.is_paused():
        return [{"skipped": "agent is paused", "hint": f"delete {config.KILL_SWITCH}"}]

    for slot in due_now(now=now):
        item = _approved_for(slot.fmt, slot.theme)
        if not item:
            results.append({"slot": slot.label, "skipped": "nothing approved",
                            "hint": f"draft one: python3 -m ig plan then draft a {slot.fmt}"})
            continue
        if _attempted_recently(item["id"]):
            results.append({"slot": slot.label, "skipped": "already published",
                            "item": item["id"]})
            continue
        if not config.POLICY.autopublish:
            results.append({"slot": slot.label, "skipped": "AUTOPUBLISH is off",
                            "item": item["id"], "would_publish": item["format"]})
            continue
        try:
            receipt = publish.publish_item(item, dry_run=dry_run)
            results.append({"slot": slot.label, "published": receipt})
        except Exception as exc:                       # noqa: BLE001 - report, never crash cron
            store.update_item(item["id"], status="failed", error=str(exc))
            results.append({"slot": slot.label, "failed": str(exc), "item": item["id"]})
    return results


def week_view(plan: dict | None = None, *, start: datetime | None = None) -> str:
    """A printable week, because a scheduler nobody can read is a scheduler nobody trusts."""
    plan = plan or load_plan()
    start = start or datetime.now(tz_of(plan))
    end = start + timedelta(days=7)
    lines = [f"WEEK OF {start.strftime('%d %b %Y')}  ·  {plan.get('timezone', 'UTC')}", "=" * 62]
    slots = slots_between(start, end, plan)
    for slot in slots:
        approved = _approved_for(slot.fmt, slot.theme)
        status = f"ready: {approved['id']}" if approved else "nothing approved"
        lines.append(f"  {slot.at.strftime('%a %d %b  %H:%M')}  {slot.fmt:<9}"
                     f"{slot.theme:<9}{status}")
    if not slots:
        lines.append("  no slots in the plan")
    return "\n".join(lines)
