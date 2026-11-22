"""The compliance gate. The reason this repo can touch a fintech account at all.

A trading/finance/ecommerce page is a regulated-content page in a way a fitness
page is not. The things that get an account restricted or sued are consistent:

* promised returns ("guaranteed 20% a month", "risk free")
* personalised advice ("you should buy X now") from an account that is not a
  registered adviser — in India that is SEBI's Investment Adviser regulations,
  in the US it is the SEC/FTC line on testimonials, in the EU MiFID II
* implied credentials ("SEBI registered", "certified analyst") that are not true
* screenshots of profits used as proof of future profit
* fear/urgency ("the market will crash tomorrow, act now")
* buy/sell calls on specific securities

The gate does not try to be a lawyer. It blocks the shapes that are known bad,
adds required context where a claim needs it, and escalates everything else to a
human. `rules/compliance.json` is meant to be edited by whoever owns the
account's risk; the code only knows how to apply the rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config

RULES_PATH = config.BRAND_DIR / "compliance.json"

# Used when brand/compliance.json is missing, so the gate is never silently off.
DEFAULT_RULES: dict = {
    "blocked_patterns": [
        {"id": "guaranteed-returns",
         "pattern": r"\b(guarantee[sd]?|assured|sure[- ]?shot|risk[- ]?free|can'?t lose)\b[^.!?\n]{0,40}\b(return|profit|money|gain|%|rupee|dollar)",
         "why": "Promising an outcome on a financial product is a regulatory problem, not a copy problem."},
        {"id": "percentage-promise",
         "pattern": r"\b\d{1,3}(\.\d+)?\s?%\s?(per|a|every|each)?\s?(day|week|month|yearly|annually)\b",
         "why": "A stated periodic return reads as a performance promise regardless of intent."},
        {"id": "double-your-money",
         "pattern": r"\b(double|triple|10x|100x)\b[^.!?\n]{0,25}\b(money|capital|account|investment)\b",
         "why": "Multiplier claims are the classic pump language."},
        {"id": "personalised-advice",
         "pattern": r"\b(you should|i suggest you|my advice to you|buy this now|sell now|you must buy|book profit now)\b",
         "why": "Personalised buy/sell instruction on an educational account is unregistered advice."},
        {"id": "fake-credentials",
         "pattern": r"\b(sebi|sec|fca|irdai|rbi)\b[^.!?\n]{0,20}\b(registered|certified|approved|licensed)\b",
         "why": "Never claim a registration you do not hold. Add the real number or cut the line."},
        {"id": "profit-screenshot-proof",
         "pattern": r"\b(my|this|our)\s+(p&l|profit|pnl)\b[^.!?\n]{0,30}\b(screenshot|proof|proof that|see)\b",
         "why": "Profit screenshots presented as proof imply repeatability. Show method, not wins."},
        {"id": "urgency-fear",
         "pattern": r"\b(crash|collapse|meltdown)\b[^.!?\n]{0,30}\b(tomorrow|next week|any day|now)\b|\bact (now|fast|today)\b",
         "why": "Manufactured urgency about markets is both a compliance and a trust problem."},
        {"id": "specific-tip",
         "pattern": r"\b(buy|short|long)\b[^.!?\n]{0,18}?\b(at|above|below)\s*[₹$€]?\s?\d",
         "why": "A price-level instruction is advice about a security, not education."},
    ],
    "required_context": [
        {"id": "risk-disclosure",
         "pattern": r"\b(stock|equity|option|futures?|f&o|intraday|crypto|mutual fund|nifty|banknifty)\b",
         "add": "Educational content, not investment advice. Markets carry risk of loss.",
         "applies_to": ["reel", "carousel", "single", "story"]}
    ],
    "forbidden_claims": [
        "we predict the market", "no loss strategy", "100% accuracy", "sure profit",
        "guaranteed income", "passive income guaranteed",
    ],
    "disclosure_footer": "Educational content only. Not investment advice. Markets carry risk of loss.",
    "escalate_topics": ["tax", "legal", "specific stock", "portfolio review", "loan", "insurance claim",
                        "refund", "grievance", "sebi complaint", "money recovery"],
}


@dataclass
class Finding:
    level: str          # block | warn | note
    rule_id: str
    excerpt: str
    why: str


@dataclass
class Report:
    verdict: str                     # PASS | NEEDS_EDIT | BLOCK
    findings: list[Finding] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == "PASS"

    def to_dict(self) -> dict:
        return {"verdict": self.verdict,
                "findings": [f.__dict__ for f in self.findings],
                "fixes": self.fixes}


def load_rules(path: Path = RULES_PATH) -> dict:
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return DEFAULT_RULES
    merged = dict(DEFAULT_RULES)
    merged.update(rules or {})
    return merged


def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


def check(text: str, *, fmt: str = "reel", rules: dict | None = None) -> Report:
    """Run the gate. `fmt` decides which required disclosures apply."""
    rules = rules or load_rules()
    findings: list[Finding] = []
    fixes: list[str] = []
    body = text or ""

    for rule in rules.get("blocked_patterns", []):
        m = _compile(rule["pattern"]).search(body)
        if m:
            findings.append(Finding("block", rule["id"], m.group(0).strip(), rule["why"]))
            fixes.append(f"Rewrite the '{rule['id']}' line: {rule['why']}")

    for claim in rules.get("forbidden_claims", []):
        if claim.lower() in body.lower():
            findings.append(Finding(
                "block", "forbidden-claim", claim,
                "This exact claim is on the account's forbidden list."))
            fixes.append(f"Remove the phrase \"{claim}\".")

    for rule in rules.get("required_context", []):
        if fmt not in rule.get("applies_to", []):
            continue
        if _compile(rule["pattern"]).search(body) and rule["add"].lower() not in body.lower():
            findings.append(Finding(
                "warn", rule["id"], rule["add"],
                "The post names a regulated instrument, so the disclosure has to be in it."))
            fixes.append(f"Append the disclosure: \"{rule['add']}\"")

    hard = [f for f in findings if f.level == "block"]
    verdict = "BLOCK" if hard else ("NEEDS_EDIT" if findings else "PASS")
    return Report(verdict=verdict, findings=findings, fixes=fixes)


def needs_human(text: str, rules: dict | None = None) -> str | None:
    """Return the topic that forces a human handover, or None.

    Tax, legal, portfolio and grievance questions are the ones where a wrong
    automated answer costs real money. The bot's job there is to acknowledge,
    set expectations, and hand over — visibly.
    """
    rules = rules or load_rules()
    low = (text or "").lower()
    for topic in rules.get("escalate_topics", []):
        if topic.lower() in low:
            return topic
    return None


def apply(text: str, *, fmt: str = "reel", rules: dict | None = None) -> Report:
    """Check and attach the footer if the post needs one. Returns the report only;
    call `finalise()` to get the text back."""
    return check(text, fmt=fmt, rules=rules)


def finalise(text: str, *, fmt: str = "reel", rules: dict | None = None) -> tuple[str, Report]:
    rules = rules or load_rules()
    report = check(text, fmt=fmt, rules=rules)
    out = text
    if report.verdict == "PASS" and any(
            f.rule_id == "risk-disclosure" for f in report.findings) is False:
        pass
    # A post that names a market instrument always carries the footer, pass or not.
    mentions_instrument = _compile(rules["required_context"][0]["pattern"]).search(out) if \
        rules.get("required_context") else None
    footer = rules.get("disclosure_footer", "").strip()
    if mentions_instrument and footer and footer.lower() not in out.lower():
        out = f"{out.rstrip()}\n\n{footer}"
        report.fixes.append("Footer added automatically.")
    return out, report
