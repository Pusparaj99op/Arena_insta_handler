"""`python3 -m ig <command>` — one entry point for humans, cron and the agent.

The commands are deliberately boring and mostly print JSON, because the most
frequent caller is not a person: it is an agent following a skill, or a cron job
at 08:00. A command that prints a table a human enjoys is a command an agent
cannot parse.

    ig doctor                 what this machine can actually do
    ig whoami                 which account the token belongs to
    ig plan                   print the week
    ig draft <format>         create a queue item to fill in
    ig approve <id>           the human gate
    ig publish [<id>]         publish one approved item, or whatever is due
    ig queue                  list the queue
    ig check-comment <text>   what the agent would do with a comment
    ig check-dm <text>        what the agent would say to a DM
    ig webhook                run the webhook server
    ig tick                   one scheduler pass (cron uses this)
    ig pause / ig resume      the kill switch
    ig render <spec>          reel or carousel from a spec json
    ig narrate <file>         voiceover for a script
    ig compliance <text>      the fintech gate, on its own
    ig refresh-token          extend the 60-day token (cron weekly)

Every command prints JSON except `plan`, which prints a week a person can read.
Exit code 0 means it worked; 1 means the operation failed and the message says
why; 2 means the account is not configured yet; 3 means it is paused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (compliance, config, publish, render, replies, schedule, skills,
               social, store, voice)
from .graph import Client, GraphError, check_token


def _out(data) -> None:
    if isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
def cmd_doctor(args) -> int:
    report = {
        "environment": skills.describe_environment(),
        "render": render.doctor(),
        "config": {
            "IG_USER_ID": bool(config.env("IG_USER_ID")),
            "IG_ACCESS_TOKEN": bool(config.env("IG_ACCESS_TOKEN")),
            "META_APP_SECRET": bool(config.env("META_APP_SECRET")),
            "IG_WEBHOOK_VERIFY_TOKEN": bool(config.env("IG_WEBHOOK_VERIFY_TOKEN")),
            "PUBLIC_MEDIA_BASE_URL": config.env("PUBLIC_MEDIA_BASE_URL"),
            "model": config.env("LLM_MODEL", "gpt-4.1-mini")
            if config.env("OPENAI_API_KEY") else None,
            "voice_provider": config.env("VOICE_PROVIDER") or "auto",
        },
        "policy": {
            "autopublish": config.POLICY.autopublish,
            "autosend_dms": config.POLICY.autosend_dms,
            "autocreate_comments": config.POLICY.autocreate_comments,
            "paused": config.is_paused(),
            "min_confidence": config.POLICY.min_confidence,
        },
        "skills_installed": len([p for p in config.SKILLS_DIR.iterdir()
                                 if p.is_dir()]) if config.SKILLS_DIR.exists() else 0,
        "state_files": {p.name: p.exists() for p in
                        (config.QUEUE, config.CONTENT_PLAN, config.POSTED_LOG)},
    }
    missing = [k for k, v in report["config"].items()
               if k != "voice_provider" and v in {None, False}]
    report["next_step"] = (
        "fill automation/.env with the missing keys: " + ", ".join(missing)
        if missing else "configured. run `python3 -m ig whoami` to confirm the account.")
    _out(report)
    return 0


def cmd_whoami(args) -> int:
    try:
        me = check_token()
        used, total = Client().publishing_usage()
        me["publishing_used_24h"] = f"{used}/{total}"
        _out(me)
        return 0
    except config.ConfigError as exc:
        _out({"error": str(exc)})
        return 2
    except GraphError as exc:
        _out({"error": str(exc)})
        return 1


def cmd_refresh_token(args) -> int:
    from .graph import refresh_long_lived_token
    try:
        payload = refresh_long_lived_token()
        expires_in = int(payload.get("expires_in", 0))
        _out({"refreshed": True, "expires_in_days": round(expires_in / 86400, 1),
              "token_type": payload.get("token_type"),
              "note": "the token in automation/.env is unchanged and now lasts longer; "
                      "nothing to redeploy"})
        return 0
    except (config.ConfigError, GraphError) as exc:
        _out({"error": str(exc)})
        return 1


def cmd_plan(args) -> int:
    plan = schedule.load_plan()
    if args.json:
        _out(plan)
    else:
        print(schedule.week_view(plan))
    return 0


def cmd_draft(args) -> int:
    item = store.new_item(args.format, theme=args.theme,
                          title=args.title or "", caption="", script="",
                          created_by="cli")
    store.add_item(item)
    _out({"created": item["id"], "format": item["format"], "status": item["status"],
          "next": f"fill data in {config.QUEUE}, then `python3 -m ig approve {item['id']}`"})
    return 0


def cmd_approve(args) -> int:
    """The human gate. Blocks only on things that are objectively wrong.

    The three verdicts are treated differently on purpose:
      FIX    -> refuse. The linter found a hard problem (truncated first line,
                dead link, wrong hashtag count) and approving it is a mistake.
      REVIEW -> allow, but print the warnings. This command *is* the human
                review; refusing here would just teach people to bypass it.
      BLOCK  -> refuse. The compliance gate found a claim the account cannot make.
    """
    item = store.find_item(args.id)
    if not item:
        _out({"error": f"no item {args.id}"})
        return 2
    data = item.get("data", {})
    problems, warnings = [], []
    caption = data.get("caption", "")
    if not caption:
        problems.append("no caption yet")
    else:
        lint = skills.lint_caption(caption)
        verdict = (lint.data or {}).get("verdict")
        if verdict == "FIX":
            problems.append(f"caption linter says FIX")
            warnings.extend(c["detail"] for c in (lint.data or {}).get("checks", [])
                            if c["status"] in {"FAIL", "WARN"})
        elif verdict == "REVIEW":
            warnings.extend(f"{c['check']}: {c['detail']}"
                            for c in (lint.data or {}).get("checks", [])
                            if c["status"] in {"WARN", "FAIL"})
        gate = compliance.check(caption, fmt=item["format"])
        if gate.verdict == "BLOCK":
            problems.extend(gate.fixes)
        elif gate.verdict == "NEEDS_EDIT":
            warnings.extend(gate.fixes)
        score = skills.human_score(caption)
        if score is not None and score < 55:
            warnings.append(f"human score {score:.0f}/100 is low: it will read like a "
                            f"machine wrote it. Run the /ig-human pass.")
    if item["format"] in {"reel", "video"} and not (data.get("video_path")
                                                    or data.get("video_url")):
        problems.append("no video_path yet")
    if item["format"] == "carousel" and len(data.get("slide_paths") or []) < 2:
        problems.append("fewer than 2 slides")
    if problems:
        _out({"refused": True, "item": item["id"], "problems": problems,
              "warnings": warnings})
        return 1
    store.update_item(item["id"], status="approved", approved_at=store._now())
    _out({"approved": item["id"], "warnings": warnings,
          "next": "AUTOPUBLISH decides whether it goes on its own, else "
                  "`python3 -m ig publish " + item["id"] + "`"})
    return 0


def cmd_publish(args) -> int:
    if config.is_paused():
        _out({"refused": "agent is paused", "hint": f"delete {config.KILL_SWITCH}"})
        return 3
    if not args.id:
        results = schedule.tick(dry_run=args.dry_run)
        _out(results or [{"skipped": "no slot is due right now"}])
        return 0
    item = store.find_item(args.id)
    if not item:
        _out({"error": f"no item {args.id}"})
        return 2
    try:
        _out(publish.publish_item(item, dry_run=args.dry_run))
        return 0
    except publish.PublishError as exc:
        _out({"failed": str(exc), "item": args.id})
        return 1


def cmd_queue(args) -> int:
    items = store.load_queue()
    if args.status:
        items = [i for i in items if i["status"] == args.status]
    _out([{"id": i["id"], "status": i["status"], "format": i["format"],
           "theme": i["data"].get("theme"),
           "title": (i["data"].get("title") or "")[:60],
           "updated": i["updated_at"]} for i in items])
    return 0


def cmd_check_comment(args) -> int:
    draft = replies.draft_reply(args.text, kind="comment", sender_name="there")
    gate = compliance.check(draft.reply, fmt="story")
    _out({"intent": draft.intent, "reply": draft.reply,
          "confidence": round(draft.confidence, 2),
          "needs_human": draft.needs_human, "reason": draft.reason,
          "compliance": gate.verdict, "fixes": gate.fixes,
          "would_send": draft.sendable and gate.verdict != "BLOCK"})
    return 0


def cmd_check_dm(args) -> int:
    conversation = {"last_inbound_at": store._now(), "history": [],
                    "human_takeover": False, "first_contact_done": False}
    draft = replies.draft_reply(args.text, kind="dm", sender_name="there")
    verdict = social.allowed_dm(conversation)
    _out({"intent": draft.intent, "reply": draft.reply,
          "confidence": round(draft.confidence, 2),
          "needs_human": draft.needs_human, "reason": draft.reason,
          "policy": {"allowed": verdict.allowed, "rule": verdict.rule,
                     "why": verdict.reason},
          "would_send": draft.sendable and verdict.allowed})
    return 0


def cmd_webhook(args) -> int:
    from . import webhook
    webhook.serve(host=args.host, port=args.port, quiet=not args.verbose)
    return 0


def cmd_tick(args) -> int:
    _out(schedule.tick(dry_run=args.dry_run))
    return 0


def cmd_pause(args) -> int:
    config.ensure_dirs()
    config.KILL_SWITCH.write_text(
        f"paused at {store._now()} by {args.by or 'cli'}\n"
        f"no outbound action will be taken until this file is deleted\n")
    _out({"paused": True, "file": str(config.KILL_SWITCH)})
    return 0


def cmd_resume(args) -> int:
    if config.KILL_SWITCH.exists():
        config.KILL_SWITCH.unlink()
    _out({"paused": False})
    return 0


def cmd_compliance(args) -> int:
    report = compliance.check(args.text, fmt=args.format)
    _out(report.to_dict())
    return 0 if report.ok else 1


def cmd_narrate(args) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if Path(args.file).exists() \
        else args.file
    try:
        narration = voice.narrate(text, args.out, dry_run=args.dry_run)
        _out({"audio": str(narration.audio_path) if narration.audio_path else None,
              "seconds": narration.seconds, "provider": narration.provider,
              "chunks": len(narration.chunks), "warnings": narration.warnings})
        return 0
    except voice.VoiceError as exc:
        _out({"error": str(exc)})
        return 1


def cmd_render(args) -> int:
    spec_path = Path(args.spec)
    if not spec_path.exists():
        _out({"error": f"{spec_path} not found"})
        return 2
    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    # Accept `cards` and `slides`: both names are natural, and a spec file that
    # fails on the plural is a bad way to spend someone's morning.
    raw_cards = spec_data.get("cards") or spec_data.get("slides") or []
    cards = [render.Card(**c) for c in raw_cards]
    out_dir = Path(spec_data.get("out_dir") or (config.BUILD_DIR / "render"))
    if spec_data.get("kind") == "carousel":
        paths = render.render_carousel(cards, out_dir, render.Brand.load())
        _out({"slides": [str(p) for p in paths]})
        return 0
    spec = render.ReelSpec(
        script=spec_data.get("script", ""), cards=cards, out_dir=out_dir,
        music=Path(spec_data["music"]) if spec_data.get("music") else None,
        caption_preset=spec_data.get("caption_preset", "bold-word"),
        engine=spec_data.get("engine", "ffmpeg"),
        narration_text=spec_data.get("narration_text", spec_data.get("script", "")),
        wpm=float(spec_data.get("wpm", 165)))
    try:
        result = render.render_reel(spec)
        _out(result.receipt())
        return 0
    except render.RenderError as exc:
        _out({"error": str(exc),
              "hint": "run `python3 -m ig doctor` to see what this machine is missing"})
        return 1


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ig", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="what this machine can do").set_defaults(fn=cmd_doctor)
    sub.add_parser("whoami", help="which account the token belongs to").set_defaults(
        fn=cmd_whoami)

    sub.add_parser("refresh-token",
                   help="extend the 60-day token (cron weekly)"
                   ).set_defaults(fn=cmd_refresh_token)

    p = sub.add_parser("plan", help="print the week")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("draft", help="create a queue item")
    p.add_argument("format", choices=["reel", "carousel", "single", "story"])
    p.add_argument("--theme", default="teach")
    p.add_argument("--title", default="")
    p.set_defaults(fn=cmd_draft)

    p = sub.add_parser("approve", help="human gate: approve an item for publishing")
    p.add_argument("id")
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("publish", help="publish one item, or whatever is due")
    p.add_argument("id", nargs="?")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("queue", help="list the queue")
    p.add_argument("--status", default=None)
    p.set_defaults(fn=cmd_queue)

    p = sub.add_parser("check-comment", help="what the agent would do with a comment")
    p.add_argument("text", nargs="+", help="the comment; quoting is optional")
    p.set_defaults(fn=cmd_check_comment, join_text=True)

    p = sub.add_parser("check-dm", help="what the agent would say to a DM")
    p.add_argument("text", nargs="+", help="the message; quoting is optional")
    p.set_defaults(fn=cmd_check_dm, join_text=True)

    p = sub.add_parser("webhook", help="run the webhook server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=cmd_webhook)

    p = sub.add_parser("tick", help="one scheduler pass")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_tick)

    p = sub.add_parser("pause", help="stop every outbound action")
    p.add_argument("--by", default="")
    p.set_defaults(fn=cmd_pause)
    sub.add_parser("resume", help="undo pause").set_defaults(fn=cmd_resume)

    p = sub.add_parser("compliance", help="run the fintech gate on some text")
    p.add_argument("text", nargs="+", help="the text; quoting is optional")
    p.add_argument("--format", default="reel")
    p.set_defaults(fn=cmd_compliance, join_text=True)

    p = sub.add_parser("narrate", help="voiceover from a script file")
    p.add_argument("file")
    p.add_argument("--out", default=str(config.BUILD_DIR / "narration.mp3"))
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_narrate)

    p = sub.add_parser("render", help="render a reel or carousel from a spec json")
    p.add_argument("spec")
    p.set_defaults(fn=cmd_render)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if getattr(args, "join_text", False) and isinstance(args.text, list):
        args.text = " ".join(args.text)
    try:
        return int(args.fn(args) or 0)
    except config.ConfigError as exc:
        print(json.dumps({"error": str(exc), "kind": "config"}))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"stopped": "ctrl-c"}))
        return 130


if __name__ == "__main__":
    sys.exit(main())
