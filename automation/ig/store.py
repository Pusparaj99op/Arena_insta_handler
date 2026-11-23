"""Durable local state: the queue, the posted log, metrics, conversations.

A JSON file per concern, written atomically, guarded by a lock file. When a
scheduler runs every hour for a year, "it probably wrote" is not good enough:
a half-written queue.json loses a week of approved work and nobody notices until
the account goes quiet. So every write is temp-file-then-rename, and every
append is newline-delimited JSON so a crash costs one line, not the file.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from . import config

LOCK = config.STATE_DIR / ".lock"
LOCK_STALE_AFTER = 900  # seconds


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """One writer at a time across processes. Stale locks expire, squeaky-clean."""
    config.ensure_dirs()
    deadline = time.monotonic() + 30
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time()}".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - LOCK.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > LOCK_STALE_AFTER:
                with contextlib.suppress(FileNotFoundError):
                    LOCK.unlink()
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"{LOCK} is held by another process for {int(age)}s. If that is a "
                    f"crashed run, delete the file.")
            time.sleep(0.1)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            LOCK.unlink()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except ValueError:
        backup = path.with_suffix(path.suffix + f".corrupt.{int(time.time())}")
        with contextlib.suppress(OSError):
            path.rename(backup)
        return default


def write_json(path: Path, data: Any) -> None:
    config.ensure_dirs()
    tmp = path.with_suffix(path.suffix + f".tmp{secrets.token_hex(3)}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False),
                   encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, record: dict) -> None:
    config.ensure_dirs()
    with _locked():
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# The queue: everything waiting for a human, or waiting for its moment.
# A post flows: planned -> drafted -> approved -> scheduled -> publishing ->
# published, and any of those can become failed or rejected.
# ---------------------------------------------------------------------------
QUEUED_STATES = {"planned", "drafted", "approved", "scheduled"}
TERMINAL_STATES = {"published", "failed", "rejected", "cancelled"}


@dataclass
class Item:
    id: str
    status: str
    format: str                 # reel | carousel | single | story
    created_at: str
    updated_at: str
    data: dict

    @property
    def is_live(self) -> bool:
        return self.status in QUEUED_STATES

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_queue() -> list[dict]:
    return read_json(config.QUEUE, [])


def save_queue(items: list[dict]) -> None:
    with _locked():
        write_json(config.QUEUE, items)


def new_item(fmt: str, **data: Any) -> dict:
    item_id = data.pop("id", None) or f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    stamp = _now()
    return {"id": item_id, "status": "planned", "format": fmt,
            "created_at": stamp, "updated_at": stamp, "data": data}


def add_item(item: dict) -> dict:
    items = load_queue()
    if any(i["id"] == item["id"] for i in items):
        raise ValueError(f"queue item {item['id']} already exists")
    items.append(item)
    save_queue(items)
    return item


def find_item(item_id: str | None = None, **match: Any) -> dict | None:
    for item in load_queue():
        if item_id and item["id"] != item_id:
            continue
        if all(item.get(k) == v for k, v in match.items()):
            return item
    return None


def update_item(item_id: str, **patch: Any) -> dict:
    items = load_queue()
    for item in items:
        if item["id"] == item_id:
            for key, value in patch.items():
                if key in {"status", "format", "id"}:
                    item[key] = value
                else:
                    item["data"][key] = value
            item["updated_at"] = _now()
            save_queue(items)
            return item
    raise KeyError(f"no queue item {item_id}")


# ---------------------------------------------------------------------------
# Posted log and metrics: append-only, one line per event.
# ---------------------------------------------------------------------------
def log_posted(record: dict) -> None:
    append_jsonl(config.POSTED_LOG, {"at": _now(), **record})


def log_metric(record: dict) -> None:
    append_jsonl(config.METRICS, {"at": _now(), **record})


def published_rate(hours: int = 24) -> int:
    cutoff = time.time() - hours * 3600
    count = 0
    for row in read_jsonl(config.POSTED_LOG):
        stamp = row.get("published_at_epoch") or 0
        if stamp >= cutoff:
            count += 1
    return count
