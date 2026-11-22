# Operations

How the account is actually run, day by day and week by week, plus what to do
when something breaks at 8am and a post is due.

---

## The daily loop, in the order it happens

### 08:00 — the morning pass, 10 minutes

```bash
cd automation
python3 -m ig queue                      # anything approved and waiting?
python3 -m ig plan                       # what the week looks like
ls ../state/PAUSED 2>/dev/null && echo "PAUSED — resume before anything"
```

Then one file, the only one that matters: **`state/needs_human.jsonl`**. It has
every comment and DM the agent refused to answer. Answer those yourself, in the
owner's voice, because those are the questions where a wrong automated answer
gets screenshotted.

### 08:10 — publish, if a slot is due

Nothing to do if `AUTOPUBLISH=on` and the item was approved yesterday. Otherwise:

```bash
python3 -m ig publish                    # whatever is due
```

### During the day — the inbox

The webhook handles keyword deliveries and simple questions inside the policy.
What it refuses lands in `needs_human.jsonl`. The escalation DMs (tax, legal,
portfolio, complaints) have a promised reply time in them, so they are the ones
with a clock on them. Reply within one working day or the promise becomes a lie
with the owner's name on it.

### 20:00 — one thing, 5 minutes

Either:
- **Review tomorrow's approved item** (read the script out loud; if it does not
  survive being said, it does not survive being posted), or
- **Log what happened today** in `state/metrics.jsonl`: the number that surprised
  you, a comment worth turning into a post, a DM that repeated four times.

That second one is where next week's content comes from. A log that is empty by
Friday means Monday starts from "what should I post", which is the most expensive
sentence in content.

---

## The weekly rhythm

| Day | 20 minutes | Why |
| --- | --- | --- |
| **Sunday** | Read `ig-viral` output, write the week's five ideas, fill slots | The plan is the cheapest thing to fix and the most expensive to skip |
| **Monday** | Write and render the week's two reels | Reels are the only format that reaches non-followers |
| **Tuesday** | One carousel, one story set | Carousels go deep with people who already follow |
| **Wednesday** | Audit last week: `ig-audit`, ranked by outlier multiple | Raw views lie; a multiple over the account's own median does not |
| **Thursday** | Rewrite one older post that underperformed | The same idea, said better, is the highest-yield post available |
| **Friday** | Inbox sweep + escalate the week's complaints | The account's reputation is the unanswered DM |
| **Saturday** | Nothing | A daily account with no day off becomes a chore the audience can feel |

---

## The runbook: something is wrong

### "Nothing published today"

In this order, and stop at the first hit:

```bash
cd automation
ls ../state/PAUSED                    # 1. paused? (the most common answer)
python3 -m ig queue --status approved # 2. is anything approved?
python3 -m ig doctor                  # 3. is the machine configured?
python3 -m ig whoami                  # 4. is the token still alive?
tail -20 ../state/logs/tick.log       # 5. what did the scheduler say?
```

### "Publishing fails with a container ERROR"

The codec. Every time, in this order: is the file under 300MB, is the video
H.264 (not H.265), is the audio AAC, is it 1080x1920, does the URL `curl` from
outside your network. `ffmpeg` can fix all of it:

```bash
ffmpeg -i in.mp4 -c:v libx264 -crf 20 -preset medium -pix_fmt yuv420p \
  -c:a aac -b:a 160k -ar 48000 -movflags +faststart out.mp4
```

### "The agent is saying something wrong"

```bash
python3 -m ig pause --by "wrong replies in DMs"
```

Then read `state/needs_human.jsonl` and `state/logs/webhook_outcomes.jsonl` and
find the draft. The cause is almost always one of three things:

1. **`brand/voice.md` is blank or generic** — the model is filling the gap with
   its own voice, which is why it sounds like nobody.
2. **The intent router mis-sorted** — a question classified as praise, so it got
   a thank-you. Add the phrasing to `detect_intent` in `replies.py` under the
   right regex, then add a test.
3. **The model is over-confident** — lower `MIN_CONFIDENCE` and more drafts will
   go to a human instead of out.

Fix the cause, then `python3 -m ig resume`.

### "The webhook stopped receiving"

```bash
curl -s https://your-host/ | python3 -m json.tool   # health endpoint
```

Then check, in this order: is the container running, is the callback URL still
right in the Meta app, has the app moved out of development mode, is the tunnel
URL different from yesterday (it is, if you use `cloudflared`). Meta disables a
webhook after repeated failures, and re-subscribing in the app dashboard is a
one-click fix nobody remembers.

### "Token expired"

```bash
python3 -m ig refresh-token
```

If that fails, the token is over 60 days old and needs minting again (SETUP.md
step 3). **This is the one failure that goes silently for a week**, which is why
the refresh is in cron in `docker-compose.yml` and in SETUP.md.

### "The account got a warning or a restriction"

Pause first, diagnose second.

```bash
python3 -m ig pause --by "account warning"
```

Then check, honestly, in this order:
1. Did anything post a claim that reads as advice? `grep -i` the queue for the
   compliance rule ids.
2. Did the DM volume spike? `wc -l state/send_log_dm.jsonl`.
3. Did anyone else get access to the token?
4. Was there any browser automation or third-party tool touching this account?
   If yes, remove it before anything else. That is the cause nine times in ten.

Then read Meta's notice properly: a content warning and an action block are
different problems with different fixes, and "appeal" is only the answer to one
of them.

---

## What to watch, and what the numbers mean

| Metric | Where | Healthy | What a bad number means |
| --- | --- | --- | --- |
| **Outlier multiple** (a post's views ÷ the account's median) | `ig-audit` | 1+ post above 3x a month | Nothing is travelling: the hooks, not the topic |
| **Saves per reach** | Insights | above 1% | Useful, not just agreeable. Finance content lives on saves |
| **Escalation rate** (DMs needing a human) | `needs_human.jsonl` | under 1 in 5 | The content is inviting the wrong questions |
| **Keyword reply rate** | comment count vs DM deliveries | above 60% | The file is wrong, not the automation |
| **Time to first reply** | `send_log_*.jsonl` | under 15 min | Over an hour and the conversation is already cold |
| **Posts per week** | `posted.jsonl` | 4–5 | Under 3 and the algorithm forgets you; over 7 and the audience does |

Deliberately not on this list: followers, likes, and raw views. None of them
predicts whether this account makes money, and all three reward the wrong posts.

---

## The monthly review, 45 minutes

1. **`ig-audit` over the last 20 posts**, ranked by outlier multiple. Write down
   the top three and what they had in common. That is the formula for next month.
2. **Read the last 30 escalations.** If the same question appears four times, it
   is a post, not a DM. Write it.
3. **Check the compliance gate's findings count.** If `BLOCK` almost never fires,
   the model has learned the account's voice and the gate is doing its job. If it
   fires every week, `brand/voice.md` is teaching the wrong things.
4. **Refresh the token** and confirm the cron is alive (`state/logs/token.log`
   should have four entries this month).
5. **Read one script out loud**, start to finish. If it does not survive being
   spoken, everything upstream of it is decoration.

---

## Backups, because `state/` is the account's memory

`state/` is git-ignored and holds the queue, the conversations and what was
posted. Losing it means losing the record of what the account already said, which
is how an account starts repeating itself.

```bash
# nightly, keep 30 days
0 2 * * * cd /path/to/repo && tar czf /backups/ig-state-$(date +\%F).tgz state && \
  find /backups -name 'ig-state-*.tgz' -mtime +30 -delete
```

The rest of the repo is regenerable from git. `state/` is not.

---

## When to stop automating something

A useful test, once a month: for each automation, ask **"if this went wrong
quietly for a week, what would it cost?"**

| Automation | Cost of a quiet week of wrong | Verdict |
| --- | --- | --- |
| Keyword delivery | Someone did not get a file | Fine to automate fully |
| Comment replies | Slightly robotic public replies | Automate, review weekly |
| DM answers | A wrong answer in a screenshot | Automate only under the confidence floor, review daily |
| Publishing | A post the owner would not have made | Automate only after a month of correct queue |
| Compliance | Fines, or an account restriction | Never automate the decision; the gate only ever *blocks* |

That table is the actual policy. Everything in `.env` is a way of expressing it.
