"""Webhook receiver: Meta pushes comments and DMs here, we answer in seconds.

Standard library HTTP server, because the volume on one account is dozens of
events a day and a framework would be a dependency with no payoff.

Two things this must get right or it is useless:

* **Verify the signature.** Meta signs every payload with the app secret. An
  endpoint that skips this lets anyone on the internet put words in the
  account's mouth, and Instagram will not care whose fault it was.
* **Answer 200 fast.** Meta retries an event for up to ~7 hours if the webhook
  is slow or errors, and duplicates turn one comment into fifteen DMs. So the
  handler enqueues and acks; the work happens after the response.

Run:  python3 -m ig webhook --port 8080
Then point the Meta app's callback URL at https://your-host/webhook and subscribe
to `comments` and `messages`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import config, replies, social, store
from .graph import Client

SEEN: dict[str, float] = {}
SEEN_LOCK = threading.Lock()
DEDUPE_SECONDS = 600
MAX_BODY = 1_000_000


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify_signature(body: bytes, header: str | None) -> bool:
    secret = config.env("META_APP_SECRET")
    if not secret:
        return False
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def verify_challenge(mode: str | None, token: str | None) -> bool:
    expected = config.env("IG_WEBHOOK_VERIFY_TOKEN")
    return mode == "subscribe" and bool(expected) and token == expected


def _seen_once(key: str) -> bool:
    with SEEN_LOCK:
        now = time.time()
        for k, ts in list(SEEN.items()):
            if now - ts > DEDUPE_SECONDS:
                SEEN.pop(k, None)
        if key in SEEN:
            return True
        SEEN[key] = now
        return False


# ---------------------------------------------------------------------------
# Event handling
# ---------------------------------------------------------------------------
def handle_payload(payload: dict) -> list[dict]:
    """Route every entry/change to the right handler. Never raises."""
    outcomes: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field = change.get("field")
            value = change.get("value", {}) or {}
            try:
                if field == "comments":
                    outcomes.append(_on_comment(value))
                elif field in {"messages", "message_reactions"}:
                    outcomes.append(_on_message(value))
                elif field == "mentions":
                    store.append_jsonl(config.STATE_DIR / "mentions.jsonl", value)
                    outcomes.append({"action": "logged_mention"})
            except Exception as exc:                     # noqa: BLE001
                store.append_jsonl(config.STATE_DIR / "webhook_errors.jsonl",
                                   {"field": field, "error": str(exc), "value": value})
                outcomes.append({"action": "error", "field": field, "error": str(exc)})
    return outcomes


def _on_comment(value: dict) -> dict:
    comment = value.get("comment") or value
    comment_id = comment.get("id") or value.get("id")
    if not comment_id or _seen_once(f"comment:{comment_id}"):
        return {"action": "duplicate_comment", "id": comment_id}
    media = value.get("media") or {"id": value.get("media_id", ""),
                                   "caption": value.get("media_caption", "")}
    if not comment.get("from"):
        comment["from"] = {"id": value.get("from", {}).get("id"),
                           "username": value.get("from", {}).get("username")}
    return replies.handle_comment(comment, media)


def _on_message(value: dict) -> dict:
    igsid = (value.get("sender") or {}).get("id")
    message = (value.get("message") or {})
    msg_id = message.get("mid") or value.get("id")
    if not igsid or not msg_id:
        return {"action": "ignored", "reason": "no sender or message id"}
    if message.get("is_echo") or (value.get("recipient") or {}).get("id") == igsid:
        return {"action": "ignored", "reason": "our own outgoing message echoed back"}
    if _seen_once(f"msg:{msg_id}"):
        return {"action": "duplicate_message", "id": msg_id}

    state = social.load_dm_state()
    record = state["conversations"].setdefault(
        social.conversation_key(value.get("conversation", {}).get("id", igsid)
                                if isinstance(value.get("conversation"), dict)
                                else igsid),
        {"conversation_id": igsid, "igsid": igsid, "history": [],
         "last_inbound_at": None, "last_outbound_at": None,
         "first_contact_done": False, "human_takeover": False})
    record["igsid"] = igsid
    record["last_inbound_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record["history"].append({"id": msg_id, "direction": "in",
                              "text": message.get("text", ""),
                              "at": record["last_inbound_at"],
                              "attachments": [a.get("type") for a in
                                              (message.get("attachments") or [])]})
    social.save_dm_state(state)
    return replies.handle_dm(record, message, client=Client())


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ig-agent/1.0"
    quiet = True

    def log_message(self, fmt: str, *args: Any) -> None:
        if not self.quiet:
            store.append_jsonl(config.LOG_DIR / "webhook.jsonl",
                               {"at": store._now(), "line": fmt % args})

    def _send(self, code: int, body: str = "", ctype: str = "text/plain") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:                                    # noqa: N802
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(self.path)
        if parsed.path not in {"/webhook", "/"}:
            return self._send(404, "not found")
        if parsed.path == "/":
            health = {"ok": True, "paused": config.is_paused(),
                      "time": store._now(), "service": "instagram agent webhook"}
            return self._send(200, json.dumps(health), "application/json")
        query = parse_qs(parsed.query)
        mode = query.get("hub.mode", [None])[0]
        token = query.get("hub.verify_token", [None])[0]
        challenge = query.get("hub.challenge", [""])[0]
        if verify_challenge(mode, token):
            return self._send(200, challenge)
        return self._send(403, "verification failed")

    def do_POST(self) -> None:                                   # noqa: N802
        from urllib.parse import urlparse
        if urlparse(self.path).path != "/webhook":
            return self._send(404, "not found")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, "payload too large")
        body = self.rfile.read(length)
        if not verify_signature(body, self.headers.get("X-Hub-Signature-256")):
            return self._send(403, "bad signature")

        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError:
            return self._send(400, "not json")

        # Ack first. Meta retries anything it thinks failed, and a retry storm is
        # how one comment becomes a dozen DMs.
        self._send(200, "ok")
        threading.Thread(target=_work, args=(payload,), daemon=True).start()


def _work(payload: dict) -> None:
    outcomes = handle_payload(payload)
    if outcomes:
        store.append_jsonl(config.LOG_DIR / "webhook_outcomes.jsonl",
                           {"at": store._now(), "batch": str(uuid.uuid4())[:8],
                            "outcomes": outcomes})


def serve(host: str = "0.0.0.0", port: int = 8080, *, quiet: bool = True) -> None:
    Handler.quiet = quiet
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"webhook listening on http://{host}:{port}/webhook")
    if not config.env("META_APP_SECRET"):
        print("WARNING: META_APP_SECRET is not set; every POST will be rejected with 403.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
