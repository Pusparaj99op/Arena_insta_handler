# Arena_insta_handler

An operating system for one real Instagram account in the trading, personal-finance
and ecommerce-education niche. An AI agent writes the script, scores the hook,
renders the video, burns the captions, voices it, writes the caption, answers the
comments and the DMs, and publishes on a schedule.

**It does all of that through Meta's official API, and it publishes nothing until
a human says yes.** Those two sentences are the whole design.

---

## What is in here

```
.claude/skills/     106 skills from 11 open-source packs (see SKILLS.md)
  igf-run           ← start here: the operator's entry point
  igf-finance-content  the niche rules: what a fintech post must contain
  igf-dm            the inbox: policy, triage, escalation
  igf-produce       script -> mp4, with ffmpeg alone or Remotion/HyperFrames
  igf-publish       the API, the quotas, the errors, the gate
  ig-*, edit, hyperframes, remotion-*, media-use, ...   the upstream packs

automation/ig/      the engine that touches the account (pure stdlib Python)
  config.py         env, paths, limits, policy switches
  graph.py          Graph API client: throttling, usage headers, retries
  publish.py        container flow: images, carousels, Reels, Stories
  social.py         comments and DMs, with Meta's four rules enforced in code
  replies.py        intent -> draft -> escalation, in the account's voice
  compliance.py     the fintech gate: the claims this account may never make
  render.py         cards, slideshow, ASS captions, -14 LUFS mix (ffmpeg only)
  voice.py          narration (ElevenLabs / OpenAI / local) and word timings
  schedule.py       the week, and what is due now
  webhook.py        Meta's webhook, signature-verified, ack-then-work
  skills.py         bridge to the skill pack's runnable tools
  cli.py            `python3 -m ig <command>`

brand/              the account's own truth. Fill this first.
  voice.md          how the person talks (the skills read it)
  brand.json        colours, fonts, handle (the renderer reads it)
  compliance.json   forbidden claims, required disclosures, escalations
  keywords.json     comment keywords and what they deliver

state/              queue, plan, conversations, needs_human (git-ignored)
build/publish/      the only directory a public URL may serve (git-ignored)
examples/           a reel spec and a carousel spec, ready to render
licenses/           every upstream license, kept with the code it covers
```

---

## The five-minute version

```bash
# 1. What can this machine do?
cd automation && python3 -m ig doctor

# 2. Fill the account's truth: name, voice, what it may never claim
$EDITOR ../brand/voice.md
$EDITOR ../brand/compliance.json

# 3. Connect the account (see SETUP.md for the Meta app walkthrough)
cp .env.example .env && chmod 600 .env && $EDITOR .env
python3 -m ig whoami                      # confirms the token is the right account

# 4. Make one reel
python3 -m ig render ../examples/reel-spec.json

# 5. Gate it, then publish it
python3 -m ig compliance "the caption you wrote"
python3 -m ig approve <item-id>
python3 -m ig publish <item-id>
```

Nothing above needs Node, a database, a cloud service, or a paid API except the
voiceover and the DM model. `ffmpeg` is the only hard dependency, and only for
video.

---

## The gate, which is the point

```
idea ──► script ──► hook score ──► beat sheet ──► render ──► caption
                                                             │
                    publish ◄── approved ◄── compliance ◄─────┘
                                    ▲
                              a human, here
```

`approve` refuses on exactly three things: **nothing to publish**, **the caption
linter says FIX**, **the compliance gate says BLOCK**. Everything else is a
warning printed in front of the human: a weak hook, no call to action, a low
human score. The approval command *is* the review, so refusing on warnings would
just teach people to bypass it.

Three switches in `.env` decide how much runs unattended, all off by default:

| Switch | Off | Turn it on when |
| --- | --- | --- |
| `AUTOSEND_DMS` | Keyword deliveries are drafted, not sent | Two weeks of correct drafts |
| `AUTOPUBLISH` | Cron publishes only what a human approved | The queue has been right for a month |
| `AUTOCREATE_COMMENTS` | Public replies are drafted only | Last, because public is the most visible |

And one that is not a switch:

```bash
python3 -m ig pause --by "something looks wrong"
```

Every outbound path checks `state/PAUSED`: publishing, DMs, comment replies, the
scheduler. The cost of pausing is a missed post. The cost of not pausing is a
screenshot.

---

## What the agent will not do

Not "will not by configuration" — will not, because the code does not implement
it and the reason is written next to the refusal:

- **Cold DMs.** Meta's messaging API starts a conversation only when the person
  moves first. Tools that do otherwise are browser bots, and browser bots get
  real accounts permanently disabled. `social.allowed_dm()` returns
  `rule-1: they have never messaged this account` and refuses.
- **Follow, unfollow, mass-like.** Not in the API. This is the single most common
  cause of an action-blocked account.
- **Scrape Instagram.** `/ig-viral` reads public pages at human speed. That is
  the boundary, and it is where the account stays safe.
- **Promise returns.** `compliance.check()` blocks guaranteed returns, stated
  periodic returns, multiplier claims, buy/sell price levels, fake registrations
  and profit screenshots used as proof.
- **Answer tax, legal, portfolio or complaint questions.** `needs_human()` routes
  those to a person, in the owner's name, with a real reply time.
- **Invent a number.** The skills return `{{your number}}` instead. An invented
  number in a finance post is the one mistake that cannot be walked back.

The interesting part is not that these are blocked. It is that each one has a
better alternative implemented in its place: the keyword DM funnel instead of
cold outreach, outlier-multiple research instead of scraping, mechanism-explained
posts instead of predictions.

---

## The niche, in one paragraph

Fintech content fails in three ways: it promises outcomes, it disguises tips as
education, and it is generic. So every post here is a **Reframe** (the arithmetic
that breaks a belief), a **Rule stress-tested** (the rule, then where it fails),
a **Loss with the mechanism** (no motivation), or **Ecommerce economics** (unit
economics without the guru voice). The hook must contain something checkable — a
number, a rate, a named mistake — within eight words. `igf-finance-content` has
the full shape, and `hookscore.py` measures the check that matters.

---

## Video, without a render farm

The default path is ffmpeg and nothing else:

```
script ─► narration (real duration) ─► cards, one idea each
       ─► slideshow with a slow zoom ─► word-timed ASS captions
       ─► music ducked under the voice ─► -14 LUFS ─► 1080x1920 H.264/AAC
```

Every step degrades with a named warning instead of failing the render, and
`python3 -m ig doctor` says what this machine is missing before you find out
halfway. When the piece needs real motion, `/hyperframes` and `/remotion-create`
are installed; both need Node 22+, and both are worth it for animation but not
for a talking number.

---

## Documentation

| File | What it answers |
| --- | --- |
| `SETUP.md` | The Meta app, the token, the webhook, media hosting — once, properly |
| `SKILLS.md` | The 106 skills, where each came from, and which one to load when |
| `OPERATIONS.md` | Daily and weekly rhythm, the runbook, what to do when it breaks |
| `.claude/skills/igf-*/SKILL.md` | The five skills written for this account |
| `automation/ig/*.py` | Each module opens with why it exists, not what it does |

---

## License and credit

The engine, the brand files and the five `igf-*` skills are yours. The 106
upstream skills keep their own licenses, all MIT or Apache-2.0, all kept in
`licenses/` and attributed in `SKILLS.md`. Two of the source repos carry no
license file; that is stated plainly in `SKILLS.md` where it applies, because a
repo with no license is not the same as a repo you may copy.

Remotion is free for individuals and teams up to three; larger teams need a
license from Remotion. Check that before this account becomes a business with
employees.
