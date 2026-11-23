"""Commenting, replying and DMing — with the policy baked into the code.

There are four rules from Meta that the entire conversation layer exists inside:

1. A conversation starts when the *person* moves: they DM, reply to a story, or
   comment on a post. The business cannot start one.
2. Free-form messages are allowed for 24 hours after their last message.
3. One private reply per comment, ever, within 7 days of the comment.
4. Automated chats must disclose that they are automated and must have a route
   to a human. Meta's platform rules say so; the EU AI Act makes it law.

Rules 1-3 are enforced by this module, not by good intentions. `allowed()` is
the only thing that decides whether a message is sent, and it returns a reason
even when the answer is yes, so the audit log can explain itself later.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config, store
from .graph import Client, GraphError


# ---------------------------------------------------------------------------
# Time windows
# ---------------------------------------------------------------------------
def _epoch(value: str | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return 0.0


def _hours_since(value: str | int | float | None) -> float:
    stamp = _epoch(value)
    if not stamp:
        return float("inf")
    return (time.time() - stamp) / 3600


def in_quiet_hours() -> bool:
    start, end = config.POLICY.quiet_hours_utc
    hour = datetime.now(timezone.utc).hour
    return hour >= start or hour < end if start > end else start <= hour < end


# ---------------------------------------------------------------------------
# Whether a send is allowed. One gate. Everything else calls it.
# ---------------------------------------------------------------------------
@dataclass
class Verdict:
    allowed: bool
    reason: str
    rule: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def _hourly_usage(kind: str) -> int:
    path = config.STATE_DIR / f"send_log_{kind}.jsonl"
    cutoff = time.time() - 3600
    return sum(1 for row in store.read_jsonl(path) if (row.get("epoch") or 0) >= cutoff)


def _record_send(kind: str, **meta) -> None:
    store.append_jsonl(config.STATE_DIR / f"send_log_{kind}.jsonl",
                       {"epoch": time.time(), "at": store._now(), **meta})


def allowed_dm(conversation: dict, *, is_human_agent: bool = False) -> Verdict:
    """Decide whether we may send a free-form message into this conversation."""
    if config.is_paused():
        return Verdict(False, "agent paused", "kill-switch")
    last_inbound = conversation.get("last_inbound_at")
    age = _hours_since(last_inbound)
    if not last_inbound:
        return Verdict(False, "they have never messaged this account; we cannot start", "rule-1")
    if is_human_agent:
        if age > config.LIMITS.human_agent_window_hours:
            return Verdict(False, f"last message was {age:.0f}h ago; human-agent window is "
                                  f"7 days", "rule-2")
    elif age > config.LIMITS.dm_window_hours:
        return Verdict(
            False,
            f"last message was {age:.1f}h ago and the free-form window is 24h. Only the "
            f"HUMAN_AGENT tag (7 days, app review, a human typing) is allowed past this.",
            "rule-2")
    if in_quiet_hours():
        return Verdict(False, "inside quiet hours; hold until the morning", "policy")
    return Verdict(True, f"inside the 24h window ({age:.1f}h since their message)", "rule-2")


def allowed_private_reply(comment: dict, state: dict) -> Verdict:
    """Decide whether we may send the one private reply this comment earns."""
    if config.is_paused():
        return Verdict(False, "agent paused", "kill-switch")
    comment_id = comment.get("id", "")
    if not comment_id:
        return Verdict(False, "no comment id", "input")
    if comment_id in state.get("private_replied", {}):
        return Verdict(False, "already sent the one private reply this comment allows",
                       "rule-3")
    if comment.get("from_is_self"):
        return Verdict(False, "that comment is ours; do not reply to ourselves", "common-sense")
    if comment.get("from_id") and comment.get("from_id") == (state.get("self_id")
                                                            or comment.get("self_id")):
        return Verdict(False, "that comment is ours; do not reply to ourselves", "common-sense")
    age = _hours_since(comment.get("timestamp"))
    if age > config.LIMITS.private_reply_window_hours:
        return Verdict(False, f"comment is {age / 24:.1f} days old; the window is 7 days",
                       "rule-3")
    if _hourly_usage("private_reply") >= config.LIMITS.private_replies_per_hour:
        return Verdict(False, "hourly private-reply ceiling reached", "rate")
    return Verdict(True, f"first private reply, {age / 24:.1f} days into the 7-day window",
                   "rule-3")


def allowed_comment_reply(parent: dict, state: dict) -> Verdict:
    if config.is_paused():
        return Verdict(False, "agent paused", "kill-switch")
    if parent.get("id") in state.get("replied_comments", {}):
        return Verdict(False, "already replied to this comment", "duplicate")
    if parent.get("from_is_self"):
        return Verdict(False, "our own comment", "common-sense")
    if parent.get("from_id") and parent.get("from_id") == (state.get("self_id")
                                                          or parent.get("self_id")):
        return Verdict(False, "our own comment", "common-sense")
    if _hourly_usage("comment_reply") >= config.LIMITS.comment_replies_per_hour:
        return Verdict(False, "hourly comment-reply ceiling reached", "rate")
    return Verdict(True, "new question on our post", "ok")


# ---------------------------------------------------------------------------
# Disclosures
# ---------------------------------------------------------------------------
DISCLOSURE_MARKERS = ("automated assistant", "assistant", "bot", "ai ")


def has_disclosure(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in DISCLOSURE_MARKERS)


def ensure_disclosure(text: str, first_contact: bool, handle: str = "this account") -> str:
    """Meta's AI-assistant rules (and EU law) require the first contact to say
    what it is. We add it, once, without pretending to be a person."""
    if not first_contact or has_disclosure(text):
        return text
    return (f"{text}\n\n"
            f"(This is {handle}'s automated assistant. Reply HUMAN any time and a person "
            f"will take over.)")


# ---------------------------------------------------------------------------
# Sending. Thin wrappers so every call has one shape and one audit line.
# ---------------------------------------------------------------------------
class Messenger:
    def __init__(self, client: Client | None = None):
        self.client = client or Client()
        self.handle = config.env("IG_HANDLE", "this account") or "this account"

    # -- DMs ---------------------------------------------------------------
    def send_dm(self, igsid: str, text: str, *, conversation: dict,
                tag: str | None = None, first_contact: bool = False) -> dict:
        verdict = allowed_dm(conversation, is_human_agent=tag == "HUMAN_AGENT")
        if not verdict:
            raise PermissionError(f"Not sending: {verdict.reason} [{verdict.rule}]")
        if not config.POLICY.autosend_dms:
            return {"queued_for_review": True, "text": text, "reason": verdict.reason}

        body: dict = {"recipient": {"id": igsid},
                      "message": {"text": ensure_disclosure(text, first_contact, self.handle)}}
        if tag:
            body["tag"] = tag
        result = self.client.post("me/messages", **body)
        _record_send("dm", igsid=igsid, message_id=result.get("message_id"),
                     rule=verdict.rule, tag=tag)
        return result

    def send_private_reply(self, comment_id: str, text: str, *, comment: dict,
                           state: dict, reply_to: str | None = None) -> dict:
        verdict = allowed_private_reply(comment, state)
        if not verdict:
            raise PermissionError(f"Not sending: {verdict.reason} [{verdict.rule}]")
        if not config.POLICY.autosend_dms:
            return {"queued_for_review": True, "text": text, "reason": verdict.reason}

        text = ensure_disclosure(text, first_contact=True, handle=self.handle)
        payload: dict = {"message": text}
        if reply_to:
            # Commenting back in public on the thread is a separate, useful move.
            payload["reply_to"] = reply_to
        result = self.client.post(f"{comment_id}/private_replies", **payload)
        state.setdefault("private_replied", {})[comment_id] = {
            "at": store._now(), "message_id": result.get("message_id")}
        _record_send("private_reply", comment_id=comment_id, rule=verdict.rule)
        return result

    # -- Comments ----------------------------------------------------------
    def reply_comment(self, comment_id: str, text: str, *, parent: dict,
                      state: dict) -> dict:
        verdict = allowed_comment_reply(parent, state)
        if not verdict:
            raise PermissionError(f"Not sending: {verdict.reason} [{verdict.rule}]")
        if not config.POLICY.autocreate_comments:
            return {"queued_for_review": True, "text": text, "reason": verdict.reason}
        result = self.client.post(f"{comment_id}/replies", message=text)
        state.setdefault("replied_comments", {})[comment_id] = {
            "at": store._now(), "reply_id": result.get("id")}
        _record_send("comment_reply", comment_id=comment_id, rule=verdict.rule)
        return result


# ---------------------------------------------------------------------------
# Inbox reading
# ---------------------------------------------------------------------------
def fetch_conversations(client: Client | None = None, limit: int = 25) -> list[dict]:
    client = client or Client()
    payload = client.get(
        "me/conversations",
        platform="instagram",
        fields="id,updated_time,participants,"
               "messages.limit(6){id,created_time,from,to,message,attachments}",
        limit=limit)
    return payload.get("data", [])


def fetch_comments(media_id: str, client: Client | None = None) -> list[dict]:
    client = client or Client()
    payload = client.get(
        f"{media_id}/comments",
        fields="id,text,timestamp,from,like_count,replies{id,text,timestamp,from}",
        limit=100)
    return payload.get("data", [])


def fetch_mentions(client: Client | None = None, limit: int = 25) -> list[dict]:
    client = client or Client()
    payload = client.get("me/mentioned_media", fields="id,caption,media_type,permalink",
                         limit=limit)
    return payload.get("data", [])


# ---------------------------------------------------------------------------
# Conversation bookkeeping
# ---------------------------------------------------------------------------
def load_dm_state() -> dict:
    return store.read_json(config.DM_STATE, {"conversations": {}, "seen_message_ids": []})


def save_dm_state(state: dict) -> None:
    store.write_json(config.DM_STATE, state)


def load_comment_state() -> dict:
    return store.read_json(config.COMMENT_STATE,
                           {"private_replied": {}, "replied_comments": {}, "handled": {}})


def save_comment_state(state: dict) -> None:
    store.write_json(config.COMMENT_STATE, state)


def conversation_key(igsid: str) -> str:
    return hashlib.sha256(igsid.encode()).hexdigest()[:16]


def ingest_conversation(state: dict, conversation: dict, self_id: str) -> dict:
    """Normalise one API conversation into our record, newest message first."""
    cid = conversation.get("id", "")
    messages = (conversation.get("messages") or {}).get("data") or []
    record = state["conversations"].setdefault(
        conversation_key(cid), {"conversation_id": cid, "igsid": None,
                                "history": [], "last_inbound_at": None,
                                "last_outbound_at": None, "first_contact_done": False,
                                "human_takeover": False})
    for msg in sorted(messages, key=lambda m: str(m.get("created_time", ""))):
        sender = (msg.get("from") or {}).get("id")
        recipients = [r.get("id") for r in (msg.get("to") or {}).get("data", [])]
        if sender and sender != self_id and not record["igsid"]:
            record["igsid"] = sender
        if msg.get("id") in {(h.get("id")) for h in record["history"]}:
            continue
        inbound = sender != self_id and (not recipients or self_id in recipients)
        record["history"].append({
            "id": msg.get("id"), "at": msg.get("created_time"), "direction":
            "in" if inbound else "out", "text": msg.get("message", ""),
            "attachments": [a.get("type") for a in
                            (msg.get("attachments") or {}).get("data", [])],
        })
        if inbound:
            record["last_inbound_at"] = msg.get("created_time")
        else:
            record["last_outbound_at"] = msg.get("created_time")
    return record
