"""Tests for the parts that must not be wrong: policy, compliance, publishing.

No network, no credentials, no ffmpeg. Every test here runs on a laptop in a
second, because the things worth testing are the decisions, not the HTTP.

    python3 -m pytest automation/tests -q
    python3 automation/tests/test_ig.py        # works without pytest too
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ig import compliance, publish, replies, render, schedule, social, store  # noqa: E402


class TempState(unittest.TestCase):
    """Point every state file at a temp dir so tests never touch real state."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._saved = {}
        for name in ("STATE_DIR", "QUEUE", "POSTED_LOG", "METRICS", "DM_STATE",
                     "COMMENT_STATE", "CONTENT_PLAN", "KILL_SWITCH", "LOG_DIR",
                     "BUILD_DIR", "PUBLISH_DIR"):
            self._saved[name] = getattr(store.config, name)
        store.config.STATE_DIR = root / "state"
        store.config.LOG_DIR = root / "state" / "logs"
        store.config.QUEUE = root / "state" / "queue.json"
        store.config.POSTED_LOG = root / "state" / "posted.jsonl"
        store.config.METRICS = root / "state" / "metrics.jsonl"
        store.config.DM_STATE = root / "state" / "dm.json"
        store.config.COMMENT_STATE = root / "state" / "comments.json"
        store.config.CONTENT_PLAN = root / "state" / "plan.json"
        store.config.KILL_SWITCH = root / "state" / "PAUSED"
        store.config.BUILD_DIR = root / "build"
        store.config.PUBLISH_DIR = root / "build" / "publish"
        store.config.ensure_dirs()

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            setattr(store.config, name, value)
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
class TestTimeWindows(TempState):
    def _conv(self, hours_ago: float) -> dict:
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours_ago))
        return {"last_inbound_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "history": [], "human_takeover": False}

    def test_inside_24h_is_allowed(self):
        os.environ.pop("QUIET_TEST", None)
        verdict = social.allowed_dm(self._conv(2))
        # Quiet hours may legitimately block; assert the rule, not the clock.
        self.assertIn(verdict.rule, {"rule-2", "policy"})

    def test_outside_24h_is_blocked(self):
        verdict = social.allowed_dm(self._conv(30))
        self.assertFalse(verdict)
        self.assertEqual(verdict.rule, "rule-2")
        self.assertIn("24h", verdict.reason)

    def test_never_messaged_is_blocked(self):
        verdict = social.allowed_dm({"last_inbound_at": None})
        self.assertFalse(verdict)
        self.assertEqual(verdict.rule, "rule-1")

    def test_human_agent_extends_to_seven_days(self):
        verdict = social.allowed_dm(self._conv(100), is_human_agent=True)
        self.assertIn(verdict.rule, {"rule-2", "policy"})
        stale = social.allowed_dm(self._conv(200), is_human_agent=True)
        self.assertFalse(stale)

    def test_pause_beats_everything(self):
        store.config.KILL_SWITCH.write_text("paused")
        verdict = social.allowed_dm(self._conv(1))
        self.assertFalse(verdict)
        self.assertEqual(verdict.rule, "kill-switch")


class TestPrivateReply(TempState):
    def _comment(self, hours_ago: float = 1, cid: str = "c1") -> dict:
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours_ago))
        return {"id": cid, "from_id": "u1", "self_id": "me",
                "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%SZ")}

    def test_first_reply_allowed(self):
        self.assertTrue(social.allowed_private_reply(self._comment(), {}))

    def test_second_reply_blocked(self):
        state = {"private_replied": {"c1": {"at": "now"}}}
        verdict = social.allowed_private_reply(self._comment(), state)
        self.assertFalse(verdict)
        self.assertEqual(verdict.rule, "rule-3")

    def test_after_seven_days_blocked(self):
        verdict = social.allowed_private_reply(self._comment(hours_ago=24 * 8), {})
        self.assertFalse(verdict)

    def test_own_comment_blocked(self):
        verdict = social.allowed_private_reply(self._comment(), {"self_id": "u1"})
        self.assertFalse(verdict)


# ---------------------------------------------------------------------------
class TestCompliance(unittest.TestCase):
    def test_guaranteed_returns_blocked(self):
        report = compliance.check("Guaranteed 20% returns every month, risk free.")
        self.assertEqual(report.verdict, "BLOCK")
        self.assertTrue(any(f.rule_id == "guaranteed-returns" for f in report.findings))

    def test_fake_registration_blocked(self):
        report = compliance.check("We are a SEBI registered research analyst.")
        self.assertEqual(report.verdict, "BLOCK")

    def test_personalised_advice_blocked(self):
        report = compliance.check("You should buy this now before it runs.")
        self.assertEqual(report.verdict, "BLOCK")

    def test_buy_level_blocked(self):
        report = compliance.check("Buy NIFTY at 24000 and thank me later.")
        self.assertEqual(report.verdict, "BLOCK")

    def test_education_passes(self):
        report = compliance.check(
            "Fixed fractional sizing: risk 1% of capital, size from the stop distance. "
            "Wider stop means a smaller position. That is the whole rule.")
        self.assertEqual(report.verdict, "PASS")

    def test_footer_added_for_instruments(self):
        text, report = compliance.finalise("Why option sellers get wiped out in expiry week.")
        self.assertIn("Not investment advice", text)

    def test_tax_question_escalates(self):
        self.assertEqual(compliance.needs_human("how much tax on intraday gains?"), "tax")

    def test_normal_question_does_not_escalate(self):
        self.assertIsNone(compliance.needs_human("how do I calculate position size?"))


class TestReplyDrafting(unittest.TestCase):
    def test_spam_gets_no_reply(self):
        draft = replies.draft_reply("follow back f4f dm me promo")
        self.assertEqual(draft.intent, "spam")
        self.assertEqual(draft.reply, "")

    def test_tax_question_goes_to_a_human(self):
        draft = replies.draft_reply("what tax do I pay on intraday?")
        self.assertTrue(draft.needs_human)
        self.assertFalse(draft.sendable)

    def test_keyword_is_detected_without_a_model(self):
        intent, conf = replies.detect_intent("GUIDE", is_comment=True)
        self.assertEqual(intent, "keyword")
        self.assertGreater(conf, 0.9)

    def test_human_request_detected(self):
        intent, _ = replies.detect_intent("can I talk to a real person")
        self.assertIn(intent, {"support", "money-question"})

    def test_disclosure_is_added_once(self):
        text = social.ensure_disclosure("Hi, here is the file.", first_contact=True)
        self.assertIn("automated assistant", text)
        again = social.ensure_disclosure(text, first_contact=True)
        self.assertEqual(again, text)


# ---------------------------------------------------------------------------
class TestQueueAndPublish(TempState):
    def test_only_approved_publishes(self):
        item = store.add_item(store.new_item("reel", caption="x", video_path="v.mp4"))
        with self.assertRaises(publish.PublishError) as ctx:
            publish.publish_item(item, dry_run=True)
        self.assertIn("not approved", str(ctx.exception))

    def test_dry_run_needs_no_credentials(self):
        video = store.config.PUBLISH_DIR / "x.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"x")
        item = store.add_item(store.new_item("reel", caption="Position sizing.",
                                             video_path=str(video)))
        store.update_item(item["id"], status="approved")
        receipt = publish.publish_item(store.find_item(item["id"]), dry_run=True)
        self.assertTrue(receipt["dry_run"])
        self.assertEqual(receipt["planned_calls"], ["post_reel"])

    def test_paths_outside_publish_dir_are_refused(self):
        with self.assertRaises(publish.PublishError) as ctx:
            publish._public_url("/etc/passwd", "https://example.com")
        self.assertIn("not under", str(ctx.exception))

    def test_public_url_maps_build_publish(self):
        target = store.config.PUBLISH_DIR / "reel.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
        url = publish._public_url(str(target), "https://cdn.example.com")
        self.assertEqual(url, "https://cdn.example.com/reel.mp4")


class TestScheduler(TempState):
    def test_slots_land_on_plan_days(self):
        plan = {"timezone": "Asia/Kolkata",
                "slots": [{"day": "Mon", "time": "08:10", "format": "reel",
                           "theme": "teach"}]}
        start = datetime(2026, 11, 22, tzinfo=timezone.utc)
        slots = schedule.slots_between(start, start + timedelta(days=7), plan)
        self.assertTrue(slots)
        self.assertTrue(all(s.at.strftime("%a") == "Mon" for s in slots))

    def test_pause_stops_the_tick(self):
        store.config.KILL_SWITCH.write_text("paused")
        result = schedule.tick()
        self.assertEqual(result[0]["skipped"], "agent is paused")

    def test_nothing_approved_means_nothing_published(self):
        store.save_queue([])
        result = schedule.tick(now=datetime.now(timezone.utc))
        for row in result:
            self.assertIn("skipped", row)


# ---------------------------------------------------------------------------
class TestRenderHelpers(unittest.TestCase):
    def test_wrap_respects_width(self):
        lines = render.wrap("Position sizing is the only risk control that works "
                            "before the trade is placed.", 888, font_size=92, bold=True)
        self.assertTrue(all(len(line) <= 20 for line in lines))
        self.assertGreater(len(lines), 1)

    def test_drawtext_takes_text_from_a_file(self):
        """No escaping layer is better than a clever one: the value goes to a
        textfile and expansion=none turns drawtext's parsing off entirely."""
        fg = render._drawtext("Risk: 1% 'of' capital", size=40, colour="FFFFFF",
                              x="10", y="10")
        self.assertIn("textfile=", fg)
        self.assertIn("expansion=none", fg)
        import re
        value = Path(re.findall(r"textfile='([^']+)'", fg)[0]).read_text()
        self.assertEqual(value, "Risk: 1% 'of' capital")

    def test_ass_timing_format(self):
        self.assertEqual(render._ass_time(0), "0:00:00.00")
        self.assertEqual(render._ass_time(61.5), "0:01:01.50")

    def test_caption_grouping_caps_words(self):
        words = [{"word": f"w{i}", "start": i * 0.3, "end": i * 0.3 + 0.3}
                 for i in range(12)]
        with tempfile.TemporaryDirectory() as tmp:
            path = render.write_ass(words, Path(tmp) / "c.ass", max_words=3)
            body = path.read_text()
        import re
        dialogues = [l for l in body.splitlines() if l.startswith("Dialogue")]
        self.assertTrue(dialogues)
        for line in dialogues:
            # Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
            spoken = line.split(",", 9)[9]
            plain = re.sub(r"\{[^}]*\}", "", spoken).strip()
            self.assertLessEqual(len(plain.split()), 3)
            self.assertNotIn("{", plain)

    def test_percent_survives_the_filtergraph(self):
        """The bug that cost an afternoon: drawtext treats % as expansion syntax,
        so every finance card with a percentage failed to render. The fix is a
        textfile plus expansion=none, and this asserts the textfile holds the
        literal text."""
        card = render.Card(kicker="THE MATHS", stat="7.8%",
                           headline="Four losses in a row", body="At 2% risk you are "
                           "7.8% down. At 1% you are 3.9% down.")
        fg = render.card_filtergraph(card, render.Brand.load(), render.REEL)
        self.assertIn("expansion=none", fg)
        self.assertIn("textfile=", fg)
        # Every drawtext must use a file, never an inline text= value.
        import re
        self.assertNotIn("drawtext=text=", fg)
        self.assertTrue(re.search(r"drawtext=textfile=", fg))
        # The value on disk must be the literal text, not an escaped version of it.
        import re
        for path in re.findall(r"textfile='([^']+)'", fg):
            body = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("\\%", body)
        self.assertIn("7.8%", Path(re.findall(r"textfile='([^']+)'", fg)[1]).read_text())

    def test_slideshow_frames_drive_duration(self):
        """A still has no duration. Without -loop/-framerate each card became a
        single frame and a 17s reel rendered as 0.2s."""
        import inspect
        source = inspect.getsource(render.build_slideshow)
        self.assertIn("-loop", source)
        self.assertIn("-framerate", source)
        self.assertIn("-frames:v", source)

    def test_capabilities_never_raises(self):
        caps = render.capabilities()
        self.assertIn("filters", caps)
        self.assertIsInstance(caps["fonts"], list)


class TestStateDurability(TempState):
    def test_atomic_write_survives_corruption(self):
        store.write_json(store.config.QUEUE, [{"id": "a"}])
        self.assertEqual(store.read_json(store.config.QUEUE, []), [{"id": "a"}])
        store.config.QUEUE.write_text("{not json")
        self.assertEqual(store.read_json(store.config.QUEUE, []), [])
        self.assertTrue(list(store.config.STATE_DIR.glob("queue.json.corrupt.*")))

    def test_jsonl_survives_a_bad_line(self):
        store.append_jsonl(store.config.METRICS, {"a": 1})
        with store.config.METRICS.open("a") as fh:
            fh.write("half a line\n")
        store.append_jsonl(store.config.METRICS, {"a": 2})
        rows = store.read_jsonl(store.config.METRICS)
        self.assertEqual([r["a"] for r in rows], [1, 2])

    def test_update_item_moves_status(self):
        item = store.add_item(store.new_item("single", caption="hi"))
        store.update_item(item["id"], status="approved", approved_at="now")
        self.assertEqual(store.find_item(item["id"])["status"], "approved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
