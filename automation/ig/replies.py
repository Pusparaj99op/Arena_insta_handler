"""The conversation brain: what to say to a comment or a DM, and when not to.

Design rules this file follows, in order of importance:

1. **A human always has an exit.** Every automated first contact says it is an
   assistant and offers the word HUMAN. `human_takeover` is sticky: once set, no
   automated message goes into that thread until a human clears it.
2. **Money questions get answers, not opinions.** Tax, legal, specific stocks,
   portfolio reviews and complaints are escalated, not answered. The DM that
   says "a person will reply within a working day" is worth more than the one
   that guesses and is wrong in a screenshot.
3. **The reply that earns a follow is short.** Long DMs get skimmed and read as
   marketing. Three short paragraphs, one question, no links unless asked.
4. **Nothing is sent from here.** This module drafts and classifies; `social.py`
   decides whether a send is legal and performs it. Two modules, one gate.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config, compliance, llm, skills, social, store

# ---------------------------------------------------------------------------
# Intent classification. Cheap heuristics first, model second.
# ---------------------------------------------------------------------------
INTENTS = {
    "keyword": "they commented a keyword the account uses to deliver something",
    "question": "they asked a factual or how-to question",
    "lead": "they asked about price, services, mentorship, or joining something",
    "support": "they have a problem with something they bought or accessed",
    "collab": "a brand or creator proposing a partnership",
    "praise": "they liked it; no action needed beyond a warm one-liner",
    "troll": "hostile, mocking, or baiting",
    "spam": "promotional, from a bot, or a follow-for-follow offer",
    "money-question": "tax, legal, complaint, portfolio, or a specific security",
    "other": "none of the above",
}

KEYWORD_FILE = config.BRAND_DIR / "keywords.json"

DEFAULT_KEYWORDS = {
    # word the account asks people to comment -> what gets delivered
    "GUIDE": {"kind": "dm-guide", "file": "resources/position-sizing-guide.pdf",
              "reply": "sent, check your DMs"},
    "SHEET": {"kind": "dm-guide", "file": "resources/risk-calculator.xlsx",
              "reply": "sent, it opens in Excel or Sheets"},
}

ESCALATION_PHRASES = (
    "human", "person", "agent", "support", "talk to someone", "real person",
    "complaint", "refund", "lawyer", "sebi", "sec ", "ombudsman",
)


def keywords() -> dict:
    try:
        return json.loads(KEYWORD_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return DEFAULT_KEYWORDS


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_intent(text: str, *, is_comment: bool = False) -> tuple[str, float]:
    """A first pass that costs nothing. The model gets the hard cases."""
    low = normalise(text)
    if not low:
        return ("other", 0.2)
    for phrase in ESCALATION_PHRASES:
        if phrase in low:
            return ("money-question" if phrase not in {"human", "person", "real person",
                                                       "talk to someone", "agent"}
                    else "support", 0.9)
    if compliance.needs_human(text):
        return ("money-question", 0.85)
    if re.search(r"\b(follow (me|back)|f4f|l4l|dm me|check my page|promo)\b", low):
        return ("spam", 0.85)
    if re.search(r"\b(scam|fraud|liar|stupid|idiot|clown|useless|shut up)\b", low):
        return ("troll", 0.8)
    if re.search(r"\b(price|cost|fees?|charge|mentorship|course|join|enroll|book a call)\b", low):
        return ("lead", 0.75)
    if re.search(r"\b(collab|partnership|sponsor|brand deal|promote)\b", low):
        return ("collab", 0.8)
    if re.search(r"\b(thanks?|thank you|great|love this|helpful|brilliant|fire)\b", low) \
            and len(low) < 90:
        return ("praise", 0.7)
    if "?" in text or re.match(r"^(how|what|why|when|where|which|can|should|does|is|do)\b", low):
        return ("question", 0.7)
    word = low.strip("!\"' ").upper()
    if word in keywords():
        return ("keyword", 0.95)
    # A DM that opens with a keyword plus a couple of words ("GUIDE please") is
    # still the keyword flow, not a question.
    first = word.split()[0] if word.split() else ""
    if first in keywords() and len(word.split()) <= 4:
        return ("keyword", 0.85)
    return ("other", 0.3)


# ---------------------------------------------------------------------------
# Voice context, read from the files the skills already use
# ---------------------------------------------------------------------------
def voice_profile() -> str:
    for path in (config.BRAND_DIR / "voice.md",
                 Path.home() / ".claude" / "instagram" / "voice.md"):
        if path.exists():
            text = path.read_text(encoding="utf-8")
            return text[:4000]
    return ("No voice profile filled in yet. Write plainly, no hype, no emoji, "
            "short sentences, never promise returns.")


def style_guide() -> str:
    path = config.BRAND_DIR / "style.md"
    if path.exists():
        return path.read_text(encoding="utf-8")[:3000]
    return ""


SYSTEM = """You are the person behind one Instagram account in the trading, \
personal-finance and ecommerce education niche. You are answering real people, \
some of whom have real money at stake. You are NOT a financial adviser and you \
never sound like one.

Voice rules, non-negotiable:
{sstyle}

Write like this:
- Short sentences. One idea each. The reader is on a phone, in a queue.
- No em dashes. No "in today's video". No "let's dive in". No "game-changer".
- No emoji unless the voice profile allows them.
- Never state or imply a return, a guarantee, or a win rate.
- Never tell someone what to buy or sell. Explain the rule, the risk, the maths.
- If the answer depends on their situation, say which facts would change it.
- One question at the end, answerable in a few words, only when it moves things on.

Disclosure rules:
- Educational content, never advice. If you name an instrument, say it is not advice.
- You cannot give tax, legal, or portfolio-specific answers: hand those to a human.
"""


def _prompt(kind: str, text: str, *, context: str = "", history: list[dict] | None = None) -> str:
    parts = [f"Message type: {kind}", "", "Their message:", text.strip()]
    if context:
        parts += ["", "What this replies to:", context.strip()]
    if history:
        recent = history[-6:]
        rendered = "\n".join(
            f"{'THEM' if h.get('direction') == 'in' else 'US'}: {h.get('text', '')}"
            for h in recent)
        parts += ["", "Recent thread:", rendered]
    parts += ["", "Write the reply. Return JSON only: "
                  '{"reply": "...", "confidence": 0.0-1.0, "needs_human": true|false, '
                  '"reason": "one short line"}',
              "confidence is your belief that this reply is correct and safe to send "
              "without a human reading it."]
    return "\n".join(parts)


@dataclass
class Draft:
    reply: str
    intent: str
    confidence: float
    needs_human: bool
    reason: str = ""
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__

    @property
    def sendable(self) -> bool:
        return (not self.needs_human and self.reply.strip() != ""
                and self.confidence >= config.POLICY.min_confidence)


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------
TEMPLATES = {
    "keyword": ("{name}, it is in your DMs.\n\n{how_to}"),
    "praise": ("Thanks {name}. {specific}\n\n"
               "If you want the next one, it goes out on Thursday."),
    "lead": ("{name}, short version: {offer_line}.\n\n"
             "If that sounds right, reply with the word DETAILS and I will send the "
             "full breakdown. No call unless you want one."),
    "support": ("{name}, sorry about that. I have flagged it to a person who can fix it "
                "properly and they will reply here within one working day.\n\n"
                "Nothing else needed from you right now."),
    "money-question": ("{name}, that one needs a human answer, not a quick one from me. "
                       "I have passed it to the desk, and a person will reply in this "
                       "thread within one working day.\n\n"
                       "I would rather be slow here than confidently wrong about money."),
    "collab": ("Thanks for thinking of me. Send the one-paragraph version: what it is, "
               "what it pays, and when it has to go live. If it fits, I will say yes or "
               "no within two days."),
    "spam": "",
    "troll": "",
    "other": ("{name}, {ack}\n\n{answer}\n\n{question}"),
}


def draft_reply(text: str, *, kind: str = "comment", context: str = "",
                history: list[dict] | None = None, sender_name: str = "there") -> Draft:
    """Draft an answer, or decide that there should not be one."""
    intent, heuristic_conf = detect_intent(text, is_comment=(kind == "comment"))

    # Hard stops that never need a model call.
    if intent in {"spam", "troll"}:
        return Draft("", intent, 0.95, needs_human=False,
                     reason=f"{intent}: no reply is the right reply")
    forced_human = compliance.needs_human(text)
    if forced_human:
        return Draft(
            _escalation_hold(sender_name, forced_human), "money-question", 0.9,
            needs_human=True, reason=f"regulated topic: {forced_human}")

    if not llm.available():
        return _template_draft(text, intent, sender_name, heuristic_conf)

    messages = [
        llm.Message("system", SYSTEM.format(sstyle=voice_profile())),
        llm.Message("user", _prompt(kind, text, context=context, history=history)),
    ]
    try:
        payload = llm.complete_json(messages, temperature=0.55)
    except llm.LLMError as exc:
        draft = _template_draft(text, intent, sender_name, heuristic_conf)
        draft.reason = f"model unavailable ({exc}); template used"
        draft.confidence = min(draft.confidence, 0.6)
        return draft

    reply = str(payload.get("reply", "")).strip()
    reply = skills.humanize(reply)          # strips em dashes and the slop lexicon
    report = compliance.check(reply, fmt="story")
    findings = report.fixes

    confidence = float(payload.get("confidence", heuristic_conf) or heuristic_conf)
    needs_human = bool(payload.get("needs_human")) or report.verdict == "BLOCK"
    if report.verdict == "BLOCK":
        confidence = 0.0

    return Draft(reply, intent, confidence, needs_human,
                 str(payload.get("reason", "")), findings)


def _template_draft(text: str, intent: str, name: str, confidence: float) -> Draft:
    """No model, no problem: the templates are what most DMs actually need."""
    kw = keywords()
    upper = normalise(text).strip("!.\"' ").upper()
    if intent == "keyword" and upper in kw:
        entry = kw[upper]
        reply = TEMPLATES["keyword"].format(
            name=name.title(), how_to=_delivery_line(entry))
        return Draft(reply, "keyword", 0.95, False, "keyword match, no model needed")
    if intent == "support":
        return Draft(TEMPLATES["support"].format(name=name.title()), intent, 0.8, True,
                     "support needs a human to actually fix it")
    if intent == "spam" or intent == "troll":
        return Draft("", intent, 0.95, False, "no reply")
    return Draft("", intent, min(0.5, confidence), True,
                 "no model configured and no template for this one")


def safe_name(raw: str | None, fallback: str = "there") -> str:
    """Instagram usernames arrive as null more often than anyone expects."""
    name = (raw or "").strip()
    return name if name else fallback


def _delivery_line(entry: dict) -> str:
    """One line on what to do with the file.

    `brand/keywords.json` supplies the line, because only the owner knows whether
    the thing is a PDF, a link, or a message in ManyChat. Falling back to an
    invented instruction is how automated accounts end up telling people to tap
    a file that was never there.
    """
    return (entry.get("how_to")
            or "It is attached to this message. If it does not open, reply and I "
               "will send it another way.")


def _escalation_hold(name: str, topic: str) -> str:
    return (f"{name.title()}, I am not going to guess at that one. Anything to do with "
            f"{topic} depends on your situation, and a wrong answer here costs real "
            f"money.\n\n"
            f"A person from the desk will reply in this thread within one working day.")


# ---------------------------------------------------------------------------
# The handler used by the scheduler and the webhook
# ---------------------------------------------------------------------------
def handle_comment(comment: dict, media: dict, *, client=None) -> dict:
    """Decide and (maybe) act on one comment. Returns an outcome record."""
    state = social.load_comment_state()
    text = comment.get("text", "") or ""
    author = ((comment.get("from") or {}).get("username") or "there").strip() or "there"
    outcome = {"comment_id": comment.get("id"), "media_id": media.get("id"),
               "intent": None, "action": "none", "reason": ""}

    intent, conf = detect_intent(text, is_comment=True)
    outcome["intent"] = intent

    if intent == "keyword" and normalise(text).strip("!.\"' ").upper() in keywords():
        word = normalise(text).strip("!.\"' ").upper()
        entry = keywords()[word]
        draft = Draft(TEMPLATES["keyword"].format(
            name=author.title(), how_to=_delivery_line(entry)),
            "keyword", 0.95, False, "keyword delivery")
        verdict = social.allowed_private_reply(comment, state)
        if not verdict:
            outcome.update(action="blocked", reason=verdict.reason)
            return outcome
        try:
            messenger = social.Messenger(client)
            result = messenger.send_private_reply(comment["id"], draft.reply,
                                                  comment=comment, state=state)
            social.save_comment_state(state)
            outcome.update(action="private_reply",
                           reason="delivered the keyword file",
                           review=result.get("queued_for_review", False))
        except PermissionError as exc:
            outcome.update(action="blocked", reason=str(exc))
        return outcome

    if intent in {"spam", "troll"}:
        outcome.update(action="ignored", reason=f"{intent} needs no reply")
        return outcome

    draft = draft_reply(text, kind="comment", context=media.get("caption", "")[:600],
                        sender_name=author)
    outcome.update(intent=draft.intent, confidence=draft.confidence,
                   draft=draft.reply, needs_human=draft.needs_human,
                   reason=draft.reason)

    if draft.needs_human or not draft.sendable:
        _queue_for_human(outcome)
        outcome["action"] = "queued_for_review"
        return outcome

    verdict = social.allowed_comment_reply(comment, state)
    if not verdict:
        outcome.update(action="blocked", reason=verdict.reason)
        return outcome
    try:
        result = social.Messenger(client).reply_comment(
            comment["id"], draft.reply, parent=comment, state=state)
        social.save_comment_state(state)
        outcome.update(action="comment_reply",
                       review=result.get("queued_for_review", False))
    except PermissionError as exc:
        outcome.update(action="blocked", reason=str(exc))
    return outcome


def handle_dm(conversation: dict, message: dict, *, client=None) -> dict:
    state = social.load_dm_state()
    text = message.get("message", "") or _attachment_note(message)
    outcome = {"conversation_id": conversation.get("conversation_id"),
               "message_id": message.get("id"), "action": "none", "intent": None}

    if any(p in normalise(text) for p in ("human", "real person", "talk to someone")):
        conversation["human_takeover"] = True
        social.save_dm_state(state)
        outcome.update(action="human_takeover",
                       reason="the person asked for a human; automation stops here")
        return outcome

    if conversation.get("human_takeover"):
        outcome.update(action="skipped", reason="a human owns this thread")
        return outcome

    sender = conversation.get("igsid")
    handle = (message.get("from") or {}).get("username")

    handle = safe_name(handle)
    intent, _conf = detect_intent(text)
    if intent == "keyword":
        word = normalise(text).strip("!\"' ").upper().split()[0]
        entry = keywords().get(word, {})
        draft = Draft(
            TEMPLATES["keyword"].format(name=handle.title(),
                                        how_to=_delivery_line(entry)),
            "keyword", 0.95, False, f"keyword {word}")
    else:
        draft = draft_reply(text, kind="dm", history=conversation.get("history", []),
                            sender_name=handle)
    outcome.update(intent=draft.intent, confidence=draft.confidence, draft=draft.reply,
                   needs_human=draft.needs_human, reason=draft.reason)

    verdict = social.allowed_dm(conversation)
    if not verdict:
        _queue_for_human(outcome)
        outcome.update(action="blocked", reason=verdict.reason)
        return outcome

    if draft.needs_human or not draft.sendable or not sender:
        _queue_for_human(outcome)
        outcome["action"] = "queued_for_review"
        return outcome

    first_contact = not conversation.get("first_contact_done")
    try:
        result = social.Messenger(client).send_dm(
            sender, draft.reply, conversation=conversation, first_contact=first_contact)
        conversation["first_contact_done"] = True
        social.save_dm_state(state)
        outcome.update(action="dm_sent" if not result.get("queued_for_review")
                       else "queued_for_review", review=result.get("queued_for_review"))
    except PermissionError as exc:
        outcome.update(action="blocked", reason=str(exc))
    return outcome


def _attachment_note(message: dict) -> str:
    kinds = message.get("attachments") or []
    if kinds:
        return f"[sent a {', '.join(kinds)}]"
    return ""


def _queue_for_human(outcome: dict) -> None:
    """Everything the bot would not say goes where a human actually looks."""
    path = config.STATE_DIR / "needs_human.jsonl"
    store.append_jsonl(path, outcome)


def review_queue(limit: int = 50) -> list[dict]:
    rows = store.read_jsonl(config.STATE_DIR / "needs_human.jsonl")
    return [r for r in rows if not r.get("handled")][-limit:]


def mark_handled(index: int) -> None:
    """Append a handled marker rather than rewriting history."""
    rows = store.read_jsonl(config.STATE_DIR / "needs_human.jsonl")
    if 0 <= index < len(rows):
        store.append_jsonl(config.STATE_DIR / "needs_human.jsonl",
                           {"handled": True, "ref": rows[index].get("message_id")
                            or rows[index].get("comment_id")})
