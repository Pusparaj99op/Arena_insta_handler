# What else to add — ranked by the risk you are not currently covering

You asked what should be added. This is not a feature wishlist; it is ordered by **what
breaks you** if it is missing, and it ends with the questions I need answered before
building any of it.

---

## Tier 1 — add these before daily output starts

Daily cadence multiplies every weakness by 30. These four are the difference between
"posts every day" and "posts every day and is still alive in a year".

### 1. The Idea Engine (the real bottleneck, not the renderer)

**Everyone thinks daily output fails at rendering. It fails at idea #6, on day 6.**

You need ~365 ideas a year with something checkable in each. That does not come from a
content calendar; it comes from a *capture system*. Build:

- **A capture inbox.** One Telegram command, `/idea <text>`, appends to
  `state/ideas.jsonl` with a timestamp. Half-formed is fine — the pipeline refines it.
- **A weekly harvest from the feed.** `/ig-viral` already ranks what is working in the
  niche by outlier multiple. Turn its output into *angles*, not copies: "this Reframe
  about breakeven maths did 12× — the account has no post on breakeven after averaging
  down".
- **A bank that must stay above 14.** If `state/ideas.jsonl` has fewer than 14 unformatted
  ideas, the agent's job that day is capture, not production, and it says so in the
  morning message.

Measured reality: a finance account needs about 3 raw ideas to produce 1 good Reel. A bank
of 14 is one week of buffer. Running dry is the #1 reason daily accounts die at week 3.

### 2. Analytics that write back into the system

`/ig-audit` exists. What is missing is the **loop**: the numbers must change what gets made
next week, without a human remembering to look.

- Nightly, pull insights for anything posted in the last 72h → `state/metrics.jsonl`
- Weekly, compute **outlier multiple** (views ÷ the account's own 30-day median) per post.
  Raw views lie; a multiple does not.
- **Push the finding into the plan**: if Reframes average 2.8× and "market updates" average
  0.6×, the next week's slots are weighted toward Reframes *automatically*, and the Telegram
  digest says why in one line.

Without this the account repeats whatever the owner happens to remember, which is how an
account plateaus at the level of its luckiest post.

### 3. A backup and restore story for `state/`

`state/` holds the queue, the conversations, the ideas bank and the record of what was
already said. It is git-ignored, which is correct, and **currently unprotected**, which is
not.

```bash
# nightly: encrypted, off-machine
0 2 * * * cd /repo && tar czf - state | age -r $PUBKEY > /backups/state-$(date +\%F).tgz.age
```

Losing `state/` after a month means the account starts repeating itself and re-asking
questions it already answered — the two things audiences notice fastest.

### 4. A "why did this fail" record

Every gate refusal, every publish error, every rejected idea gets logged with the reason
and swept weekly. The gate is only useful if its refusals teach the writer. A month of
logs is also the fastest way to find that one compliance rule firing 40 times on phrasing
that was actually fine — which is how you tune rules with evidence instead of vibes.

---

## Tier 2 — add in month one

### 5. Carousel and Story as a *scheduled* part of the week, not an afterthought

The brief says one Reel daily. A one-Reel-a-day account that never posts Stories is
leaving the cheapest reach on the platform: Stories are where the audience already is, and
they are the only place a DM funnel starts without shouting.

- Stories: **2/day**, produced in the same batch as the Reel. `ig-story` exists.
- Carousels: **2/week** — they go deep with people who already follow, which Reels do not.
- The Reel earns the reach; the carousel earns the saves; the Story earns the conversation.

### 6. Multi-format repurposing from the same script

One Reel = one script = 25–40s of narration. That script is also a **text post**, a
**carousel** (one beat per slide), and a **Story sequence**. `ig-repurpose` exists.
Producing four assets from one writing session is what makes one-Reel-a-day sustainable
rather than frantic.

### 7. A/B testing of hooks, cheaply

You have 26 formulas and a scorer. Test the *scorer* against reality: for every Reel,
write three hooks, score them, publish the top one, and **record which formula scored
highest vs which the audience actually rewarded**. After 30 posts you will know whether
`hookscore.py`'s SPECIFICITY metric predicts *your* audience, or whether your niche prefers
something it undervalues. That is a genuinely valuable piece of private data, and it costs
one extra line per post.

### 8. Caption/brand consistency as a linted asset

`brand/brand.json` holds the palette and the renderer uses it. Extend that to captions and
thumbnails so a Reel, its cover, and its carousel slide are visibly the same account. The
cheapest way to look established.

---

## Tier 3 — worth doing, not urgent

| # | Add | Why it earns its place |
| --- | --- | --- |
| 9 | **Comment → idea mining** | Every "what about X?" in the comments is a post the audience already asked for. Cluster them weekly. |
| 10 | **A second 3D archetype rendered overnight** | Keeps the visual language from going stale without spending daytime budget. |
| 11 | **Cover-frame design pass** | The cover is the only frame that competes in the grid. One extra card, big return. |
| 12 | **A weekly "one old post, said better"** | Highest-yield post available: proven topic, better execution. |
| 13 | **Publish-time experiments** | Two slots differing by 3h, logged; after a month the account knows its own best hour. |
| 14 | **A public-voice guard for replies** | Public comments are the most visible thing an account says. A second, stricter gate for public vs DM. |

---

## What I would *not* add, and why

| Tempting | Why not |
| --- | --- |
| AI video generation (Sora/Veo/Kling) for the visuals | Cannot be factually controlled. A finance account cannot risk a chart that is subtly wrong — it is the one error that cannot be walked back. Use it for abstract plates only, never data. |
| A LangGraph / multi-agent orchestrator | Cron and a queue already do this, and they are debuggable at 7am. Add orchestration when there is an actual concurrency problem. |
| Scraping competitor accounts at scale | The thing that gets accounts restricted, and it puts the compliant path one import away from the non-compliant one. `/ig-viral` at human speed is the boundary. |
| Auto-reply to *every* comment | Replying to praise and bait trains the audience to write filler. Reply to questions and substance. |
| More platforms (YouTube Shorts, TikTok) | Same video, 3× the policy surface. Prove 30 days on Instagram first. |
| An LLM-generated "personality" for replies | The account's voice is the owner's. The strongest replies are ones they would actually say. |
| Building a web dashboard | Telegram already is the dashboard, and it is the one that gets looked at from a phone. |

---

## Questions I need answered before I build any of this

**Product / strategy**

1. **Who writes the ideas?** Is the owner supplying raw material (a trade, a number, a
   mistake) daily, or is the agent expected to generate topics from the niche alone? This
   decides whether the Idea Engine is capture-first or research-first, and it is the single
   biggest factor in whether the content is any good.
2. **What is the offer?** A course, a community, a paid newsletter, or nothing yet? It
   changes the CTA, the keyword funnel, and what the carousels are for.
3. **Is there real footage of the owner?** Face-on-camera changes the format mix a lot.
   Fully faceless means 3D/typographic only, which makes the 3D investment central rather
   than decorative.

**Technical**

4. **Hardware.** CPU cores, RAM, and is there a GPU? Tier-B 3D on CPU is minutes per Reel;
   with a GPU it is seconds. This decides how much 3D can be in the daily budget.
5. **Always-on host?** A laptop that sleeps breaks a 06:00 cron and a Telegram bot. A small
   VPS or a home mini-PC changes the architecture — which is why the Telegram bot is
   designed for long-polling rather than webhooks.
6. **Voice: clone or character?** A cloned voice needs ~30 min of clean audio and is the
   highest-trust option. A character voice is available today. Which, and is the owner
   willing to record?

**Operations**

7. **Approval latency.** If the owner cannot approve by 09:00, does the post (a) skip the
   day, (b) publish the pre-approved fallback, or (c) wait and publish late? There is no
   wrong answer, but it must be decided, because the pipeline behaviour differs.
8. **Notification budget.** A push per event, or one digest a morning and one a night?
   Over-notifying is how a Telegram bot gets muted, and a muted bot is an unsupervised
   account.
9. **Who owns the compliance profile if the account grows?** If it ever registers, the rules
   change. That is a decision with a real legal edge, and it should have a named owner.

**Answer 1–3 and I can build the Idea Engine properly. Answer 4–5 and I can size the 3D
budget honestly instead of guessing. The rest can wait until the spine works.**
