"""A thin bridge between this engine and the skill pack in `.claude/skills/`.

The skills are markdown playbooks with small Python tools attached. Two ways to
use them:

* An agent (Claude Code, or any MCP-capable client) reads SKILL.md and decides
  what to run. That is the normal path, and nothing here is needed for it.
* A scheduler or a cron job needs to run the same tools without a human in a
  chat: check a caption, score a hook, time a script, humanise a draft. This
  module is that path.

It calls the tools that are pure functions of text. It does not try to
re-implement the judgement: the skills keep that.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass
class ToolResult:
    ok: bool
    stdout: str
    stderr: str
    data: dict | None = None

    def __bool__(self) -> bool:
        return self.ok


def _run(args: list[str], *, timeout: int = 120, stdin: str | None = None) -> ToolResult:
    try:
        proc = subprocess.run(
            [sys.executable, *args], capture_output=True, text=True,
            timeout=timeout, input=stdin, cwd=str(config.ROOT))
    except FileNotFoundError as exc:
        return ToolResult(False, "", f"tool missing: {exc}")
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", f"tool timed out after {timeout}s")
    return ToolResult(proc.returncode == 0, proc.stdout, proc.stderr,
                      _maybe_json(proc.stdout))


def _maybe_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text.startswith("{"):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def skill_path(*parts: str) -> Path:
    return config.SKILLS_DIR.joinpath(*parts)


# ---------------------------------------------------------------------------
# Captions: the 125-character window and the linter
# ---------------------------------------------------------------------------
def lint_caption(caption: str, keywords: list[str] | None = None) -> ToolResult:
    """Run /ig-caption's linter. Returns JSON with pass/warn per check."""
    args = [str(skill_path("ig-caption", "caption.py")), "-", "--json"]
    if keywords:
        args += ["--keywords", ",".join(keywords)]
    return _run(args, stdin=caption)


def caption_verdict(caption: str) -> str:
    result = lint_caption(caption)
    if not result.data:
        return "unknown"
    return result.data.get("verdict", "unknown")


# ---------------------------------------------------------------------------
# Hooks and timing: /ig-reel's two tools
# ---------------------------------------------------------------------------
def score_hooks(hooks: list[str]) -> ToolResult:
    return _run([str(skill_path("ig-reel", "hookscore.py")), "-", "--json"],
                stdin="\n".join(hooks))


def best_hook(hooks: list[str]) -> str | None:
    result = score_hooks(hooks)
    if not result.data:
        return None
    rows = result.data if isinstance(result.data, list) else result.data.get("hooks", [])
    # hookscore.py --json emits a list of {hook, checks, weakest, flags, score, verdict}
    ranked = sorted(rows, key=lambda r: r.get("score", 0), reverse=True)
    return ranked[0].get("hook") if ranked else None


def beat_sheet(script: str, target_seconds: int = 30, wpm: float = 165) -> ToolResult:
    return _run([str(skill_path("ig-reel", "beats.py")), "-", "--json",
                 "--target", str(target_seconds), "--wpm", str(wpm)], stdin=script)


def script_fits(script: str, target_seconds: int = 30) -> tuple[bool, float]:
    """True when the spoken script lands inside the slot, with the actual seconds."""
    result = beat_sheet(script, target_seconds)
    if not result.data:
        return (False, 0.0)
    seconds = float(result.data.get("total_seconds") or result.data.get("seconds") or 0)
    return (seconds <= target_seconds * 1.08, seconds)


# ---------------------------------------------------------------------------
# The humanizer: strip the machine fingerprint before anything ships
# ---------------------------------------------------------------------------
def humanize(text: str) -> str:
    result = _run([str(skill_path("ig-human", "humanize.py")), "-", "--json"], stdin=text)
    if result.data and isinstance(result.data.get("text"), str):
        return result.data["text"].strip()
    return text.strip()


def human_score(text: str) -> float | None:
    result = _run([str(skill_path("ig-human", "detect.py")), "-", "--json"], stdin=text)
    if not result.data:
        return None
    return result.data.get("human_score") or result.data.get("overall", {}).get("score")


def human_checks(text: str) -> dict:
    result = _run([str(skill_path("ig-human", "detect.py")), "-", "--json"], stdin=text)
    return (result.data or {}).get("checks", {})


def polish(text: str, *, min_score: float = 65.0) -> tuple[str, float | None]:
    """Clean the text, then measure it. Returns (text, score)."""
    cleaned = humanize(text)
    return cleaned, human_score(cleaned)


# ---------------------------------------------------------------------------
# Media: what is on disk, and whether it is postable
# ---------------------------------------------------------------------------
def probe_media(path: str | Path) -> ToolResult:
    """ffprobe via the ffmpeg-skill, which knows the flags and the JSON shape."""
    return _run([str(skill_path("ffmpeg-skill", "scripts", "probe.py")),
                 str(path), "--json"], timeout=180)


def ffmpeg_ready() -> bool:
    import shutil
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def describe_environment() -> dict:
    """What this machine can actually do, so the agent plans around it."""
    import importlib.util
    import shutil
    return {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "node": shutil.which("node"),
        "npx": bool(shutil.which("npx")),
        "python": sys.version.split()[0],
        "pillow": importlib.util.find_spec("PIL") is not None,
        "skills": len([p for p in config.SKILLS_DIR.iterdir()
                       if p.is_dir() and (p / "SKILL.md").exists()])
        if config.SKILLS_DIR.exists() else 0,
    }
