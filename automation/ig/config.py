"""Configuration, secrets and paths.

One file, one place to look. Values come from the environment first, then from
``automation/.env`` (git-ignored). Nothing secret is ever written to the repo.

    IG_USER_ID              Instagram professional account id
    IG_ACCESS_TOKEN         long-lived token from the Meta app
    META_APP_SECRET         used to verify webhook signatures
    IG_WEBHOOK_VERIFY_TOKEN our own random string, echoed back to Meta
    OPENAI_API_KEY          replies, DMs, scripts (optional but expected)
    ELEVENLABS_API_KEY      voiceover (optional)
    ELEVENLABS_VOICE_ID     default voice
    PUBLIC_MEDIA_BASE_URL   https host serving build/publish/  (required to post)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Paths. Everything the agent produces lands under build/<date>/<slug>/.
# ---------------------------------------------------------------------------
CLAUDE_DIR = ROOT / ".claude"
SKILLS_DIR = CLAUDE_DIR / "skills"
BRAND_DIR = ROOT / "brand"
STATE_DIR = ROOT / "state"
BUILD_DIR = ROOT / "build"
PUBLISH_DIR = BUILD_DIR / "publish"      # the only directory exposed via PUBLIC_MEDIA_BASE_URL
LOG_DIR = STATE_DIR / "logs"

CONTENT_PLAN = STATE_DIR / "content_plan.json"
QUEUE = STATE_DIR / "queue.json"
POSTED_LOG = STATE_DIR / "posted.jsonl"
METRICS = STATE_DIR / "metrics.jsonl"
DM_STATE = STATE_DIR / "dm_conversations.json"
COMMENT_STATE = STATE_DIR / "comment_state.json"
KILL_SWITCH = STATE_DIR / "PAUSED"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader. Real env always wins; no dependency on python-dotenv."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / "automation" / ".env")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if value is not None:
        value = value.strip()
    return value or default


def require(name: str) -> str:
    value = env(name)
    if not value:
        raise ConfigError(
            f"{name} is not set. Put it in automation/.env (see .env.example) "
            f"or export it before running."
        )
    return value


class ConfigError(RuntimeError):
    """Raised when the account is not configured yet. Message says what to do."""


@dataclass(frozen=True)
class Graph:
    """Instagram Graph API settings for the account owner's own content."""

    version: str = field(default_factory=lambda: env("IG_GRAPH_VERSION", "v23.0") or "v23.0")
    host: str = "https://graph.instagram.com"

    @property
    def user_id(self) -> str:
        return require("IG_USER_ID")

    @property
    def token(self) -> str:
        return require("IG_ACCESS_TOKEN")


@dataclass(frozen=True)
class Limits:
    """Meta's documented ceilings, with headroom built in.

    These are policy numbers, not suggestions. The engine refuses to cross them
    rather than letting Meta return an error mid-campaign.
    """

    # Content publishing: 100 API-published posts per rolling 24h (carousel = 1).
    posts_per_24h: int = int(env("LIMIT_POSTS_24H", "8") or 8)
    # Private replies to comments: 750/hour documented; we keep a wide margin.
    private_replies_per_hour: int = int(env("LIMIT_PRIVATE_REPLIES_HOUR", "60") or 60)
    # Messaging: only inside 24h of the user's last message (7d for click-to-DM ads).
    dm_window_hours: int = 24
    human_agent_window_hours: int = 168
    # Private reply must go within 7 days of the comment.
    private_reply_window_hours: int = 168
    # Comments we answer per hour, to stay human-paced.
    comment_replies_per_hour: int = int(env("LIMIT_COMMENT_REPLIES_HOUR", "30") or 30)


@dataclass(frozen=True)
class Policy:
    """Switches a human owner sets, not switches the agent can flip for itself."""

    # When False the agent drafts everything and publishes nothing.
    autopublish: bool = (env("AUTOPUBLISH", "off") or "off").lower() in {"on", "1", "true", "yes"}
    # When False the agent drafts DM and comment replies into state/ for review.
    autosend_dms: bool = (env("AUTOSEND_DMS", "off") or "off").lower() in {"on", "1", "true", "yes"}
    autocreate_comments: bool = (env("AUTOCREATE_COMMENTS", "off") or "off").lower() in {
        "on", "1", "true", "yes"
    }
    # Regulated-industry guard: never state returns, never promise outcomes.
    require_compliance_pass: bool = True
    # Anything the model is less sure about than this gets a human, not a send.
    min_confidence: float = float(env("MIN_CONFIDENCE", "0.72") or 0.72)
    quiet_hours_utc: tuple[int, int] = (19, 2)  # don't DM 19:00–02:00 UTC


GRAPH = Graph()
LIMITS = Limits()
POLICY = Policy()


def public_base() -> str:
    return require("PUBLIC_MEDIA_BASE_URL").rstrip("/")


def ensure_dirs() -> None:
    for path in (STATE_DIR, BUILD_DIR, PUBLISH_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def is_paused() -> bool:
    """The kill switch. Presence of state/PAUSED stops every outbound action."""
    return KILL_SWITCH.exists()
