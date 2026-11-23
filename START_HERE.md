# Your setup, in the order that matters

You already have the Meta app. You want a free local voice. You want 4–5 posts a
week. The account is pure education with no registration.

Those four answers are already wired into the repo. This file is the shortest
path from here to your first published Reel, skipping everything that does not
apply to you.

---

## What is already configured for you

| Your answer | What it changed |
| --- | --- |
| Meta app exists | Nothing to build. `SETUP.md` steps 2 is done; go to the token exchange in step 3. |
| Free local voice | `tools/setup_voice.py` ready with four curated voices and finance pacing. `VOICE_PROVIDER=local` is the path. |
| 4–5 posts/week | `state/content_plan.json` defaults to 3 Reels + 2 carousels + daily stories, 7 slots a week. `LIMIT_POSTS_24H=8` is comfortably above it. |
| Education only, no registration | `brand/compliance.json` runs the `educational_unregistered` profile: 13 blocking rules, including recommendation language, price targets, win rates and third-party results. |

---

## Step 1 — connect the account (10 minutes)

You have the app; you need three values out of it and a place for Meta to fetch
media. Run the checklist first, and fix from the top:

```bash
cd automation
python3 -m ig connect
```

It checks nine things in the order they fail. Everything it lists is fixable in
under two minutes except media hosting.

### The token, since your app exists

```bash
# In the Meta app: Instagram > API setup with Instagram login > Generate token
# (this is a SHORT-LIVED token; exchange it now or it dies in an hour)

export META_APP_SECRET="<app settings > basic>"
export SHORT_TOKEN="<the token you just generated>"

curl -s "https://graph.instagram.com/access_token\
?grant_type=ig_exchange_token\
&client_secret=$META_APP_SECRET\
&access_token=$SHORT_TOKEN"
```

The response has `access_token` (60 days) and `expires_in`. Put the `access_token`
in `automation/.env` as `IG_ACCESS_TOKEN`, and the account id from the same app
page as `IG_USER_ID`.

Then confirm — this is the check that catches a token from the wrong app:

```bash
python3 -m ig whoami
```

The username it prints must be your account. If it is not, stop; every later
failure will look like a bug in this repo instead of what it is.

### Media hosting, the one thing you cannot skip

Meta does not accept an upload; it fetches a URL. Any of these works:

```bash
# a) A bucket, 5 minutes, no server
rclone sync build/publish/ r2:ig-media/ --progress
#   PUBLIC_MEDIA_BASE_URL=https://media.yourdomain.com

# b) While testing: a tunnel (URL changes on restart, so not for production)
cloudflared tunnel --url http://localhost:8000
cd build/publish && python3 -m http.server 8000
```

---

## Step 2 — the local voice (5 minutes, once)

```bash
python3 -m pip install piper-tts

# See the four voices curated for finance, with why each exists
python3 tools/setup_voice.py --list

# Pick one, hear a sample from your own script, and make it the default
python3 tools/setup_voice.py --voice en_US-lessac-medium --use --try
```

It prints the measured speaking rate, because that is the number that decides
whether a finance script survives being read out loud:

```
sample: build/voice-test.wav
length: 18.2s for 44 words = 145 wpm
  A finance read wants 140-165 wpm. Above 175 the numbers blur;
  below 130 it drags.
```

If the rate is off, `--length-scale` is the dial, or pass
`VOICE_LENGTH_SCALE` in `.env`. The defaults in the tool are already slowed down
from audiobook pace to 1.10–1.15 for exactly this reason.

**Why lessac first:** most Piper voices are trained on audiobooks, and audiobook
cadence treats a number as narrative colour. `en_US-lessac-medium` holds a flat,
measured delivery, which is what "seven point eight percent" needs to land.
`en_GB-alba-medium` is the alternative if lessac sounds sleepy to you.

**One voice, forever.** A different voice per video is the difference between a
channel and a pile of clips. If you ever change it, change it deliberately and
keep the old renders.

---

## Step 3 — your first Reel, end to end (20 minutes)

The renderer is verified working in this repo: cards, timing, karaoke captions in
the safe zone, and a -14 LUFS mix.

```bash
cd automation

# 1. Render the example spec, which is a real finance reel
python3 -m ig render ../examples/reel-spec.json

# 2. Watch it. On your phone, not your laptop.
open ../build/2026-11-24-position-sizing/reel.mp4
```

What you should see: five cards, each one idea, the number in the accent colour,
text above the Reel UI, and a slow zoom so it does not read as PowerPoint. With
no voice configured it renders silent and says so in `warnings`; with the piper
voice from step 2 it narrates, times the cards to the narration, and burns
word-timed captions.

**Then write your own.** Copy the example spec and replace the cards:

```bash
cp ../examples/reel-spec.json ../build/my-first.json
# edit: script, narration_text, and the five card headlines
python3 -m ig render ../build/my-first.json
```

The card rules that matter, from `igf-produce`:

- One idea per card. Six words in the headline, maximum.
- The number is the visual: 150px, accent colour, nothing competing.
- The hook card is on screen under two seconds and contains a checkable number.

---

## Step 4 — the gate, then publish

```bash
cd automation

# The caption, gated by both linters that are code, not judgement
python3 -m ig compliance "your caption text here"

# Create the queue item, then fill in caption + video_path in state/queue.json
python3 -m ig draft reel --theme teach --title "position sizing"

# The human gate. Warnings are printed, hard failures are refused.
python3 -m ig approve <item-id>

# Publish, once, watching
python3 -m ig publish <item-id>
```

`approve` refuses only three things: nothing to publish, the caption linter says
FIX, the compliance gate says BLOCK. Everything else is a warning printed for
you, because the approval command *is* the review.

---

## Step 5 — turn on the conversation layer

The DM side is the part that makes the account feel alive, and the part where
policy matters most. It runs on the webhook:

```bash
# 1. A verify token, and the app secret already in .env
export IG_WEBHOOK_VERIFY_TOKEN=$(openssl rand -hex 16)

# 2. Run it
python3 -m ig webhook --port 8080
```

In the Meta app: **Webhooks > Instagram**, callback
`https://your-host/webhook`, same verify token, subscribe to `comments` and
`messages`.

Then, before turning anything on, watch what it *would* say:

```bash
python3 -m ig check-dm "how do I size a position?"
python3 -m ig check-comment "what's the best strategy for beginners?"
```

Read a dozen of those. When they sound like you, turn on `AUTOSEND_DMS=on` for
keyword deliveries only. Leave `AUTOCREATE_COMMENTS` until last: a public reply
is the most visible thing the account can say.

### Your keyword funnel

`brand/keywords.json` ships with `GUIDE`, `SHEET` and `CHECKLIST`. Each needs the
real `how_to` line: only you know whether the file is a PDF, a link, or a
ManyChat flow. Get that wrong and the bot tells people to tap a file that was
never there.

---

## What the compliance profile means for you day to day

You chose pure education, no registration. That is the safest profile and it
costs you two things, both worth naming now so they are not a surprise later:

**1. You cannot use results as persuasion.** Not your own P&L, not a student's.
The gate blocks third-party results and win rates, because without registration
the advertising safe harbour does not apply. The alternative that works better
anyway: show the *method* surviving a loss, not the win.

**2. You cannot name a stock as actionable.** You can name it to explain a
mechanism ("why option sellers get wiped out in expiry week"). You cannot say
"watch this level" or "I recommend". The gate blocks recommendation language and
price targets.

What you *can* do, and what the five `igf-*` skills are written around: the
Reframe (the arithmetic that breaks a belief), the Rule stress-tested, the Loss
with the mechanism, and Ecommerce economics.

If you ever register, do not relax these rules — add a `profile` to
`brand/compliance.json` and switch. The rules are the reason the account is still
around in a year.

---

## The honest list of what still needs you

Three things the repo cannot do for you, in the order they cost you time:

1. **`brand/voice.md` is still a template.** Every draft written before you fill
   it in is a draft you will rewrite. Ten minutes, and it is the highest-leverage
   ten minutes in this entire repo.

2. **`brand/keywords.json` needs real `how_to` lines** and a real file to send.

3. **The media host.** A tunnel is fine for a week of testing; it is not fine for
   production, because the URL changes and every publish then fails with a vague
   media-fetch error.

Everything else — script, hook scoring, beat timing, render, captions, loudness,
caption linting, compliance, scheduling, comment triage, DM drafting, quota
management, token refresh — is wired and tested.
