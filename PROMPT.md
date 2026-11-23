# MASTER PROMPT
## Fintech Instagram Agent — Daily 3D Reels with Natural Voice and Telegram Control

**Paste everything below into your agent.** It is written to be read top-to-bottom by
an agent with file access to this repository, and it assumes the repository already
contains the merged work from `main` at `4e4197a` or later (111 skills, `automation/ig/`,
`brand/`, `state/`).

Version 2.0 · scope: daily output, 3D motion, natural voice, Telegram operations.

---

# 0. What we are building, in one paragraph

We are building an **autonomous content studio for one real Instagram account** in the
trading, personal-finance and ecommerce-education niche. It runs **one Reel every single
day**, and each Reel is a **short 3D-motion explainer** narrated in a **natural human
voice**, built from a **script that is measured before it is shot** — hook scored, timing
verified, claims gated. A **Telegram bot is the admin surface**: the account owner
approves, rejects, edits, pauses and reviews everything from their phone, because the
agent must never publish unsupervised. Everything runs on the owner's own machine or a
small VPS, with no media leaving it except to Instagram.

The account is **educational and unregistered**. It explains mechanisms, maths and
process. It never gives advice, never issues a recommendation, never promises an outcome.
That constraint is the single most important design input, and it is enforced in code,
not in prose.

---

# 1. Non-negotiable operating rules

Read these first. Everything below assumes them.

1. **Nothing is published, DM'd, or commented without passing the gate.** The gate is
   `python3 -m ig approve <id>`, and in production it is a button in Telegram. A human
   presses it. The agent may never press it on its own behalf, including in "autonomous"
   mode, unless `AUTOPUBLISH=on` and the owner turned it on explicitly.
2. **The compliance gate outranks the content brief.** If the brief asks for something
   `brand/compliance.json` blocks, the answer is a rewrite, not an exception. Rule IDs
   come back in the report; the message names the line that caused it.
3. **Every number is real.** If the owner has not supplied a figure, the output contains
   `{{your number}}` and a flag. Never invent a metric, a P&L, a win rate, or a follower
   count.
4. **One voice, forever.** The account's narration voice is chosen once and recorded in
   `brand/voice.md` and `.env`. A different voice per video is the difference between a
   channel and a pile of clips.
5. **No browser automation, no scraping behind a login, no cold DMs.** The official API
   only. These are not limitations to route around; each one is a way real accounts get
   permanently disabled.
6. **Everything is reviewable.** Scripts are text, compositions are source files, renders
   are reproducible from a spec. If the owner cannot diff it, it does not ship.

---

# 2. The account

| Field | Value |
| --- | --- |
| Niche | Trading, personal finance, ecommerce economics |
| Audience | 25–40, salaried or small-business, has lost money at least once, wants a system rather than a tip |
| Format | Vertical Reel, 1080×1920, 7–60s (target 25–40s) |
| Cadence | **One Reel per day.** Plus 2 carousels/week and daily Stories |
| Voice | Natural human narration, English, measured pace 140–165 wpm |
| Visual language | 3D motion explainers — depth, camera movement, data as objects |
| Compliance profile | `educational_unregistered` |
| Timezone | `Asia/Kolkata` (edit `state/content_plan.json` if wrong) |

**The content shapes that work in this niche** (from `igf-finance-content`, use these —
do not invent a fifth):

- **The Reframe** — the arithmetic that breaks a belief the audience holds.
- **The Rule, stress-tested** — state the rule, then show where it fails.
- **The Loss with the mechanism** — a real loss, the number, the rule that would have
  prevented it. No motivation, no "this taught me so much".
- **Ecommerce economics** — unit economics without the guru voice.

---

# 3. The daily pipeline

This is the machine. Each stage writes state, so a run can stop and resume.

```
 06:00  ┌─ IDEA ────────────────────────────────────────────────────────┐
        │ pick from the week's plan + swipe file + last week's outliers  │
        └────────────────────────────────────────────────────────────────┘
                                  │
 06:10  ┌─ SCRIPT ──────────────────────────────────────────────────────┐
        │ ig-reel: 3 hooks off 26 formulas → hookscore.py ranks them    │
        │ winner → spoken script → beats.py gives a timed beat sheet     │
        │ hard gate: hook ≤ 3s, total within target, loop back to line 1 │
        └────────────────────────────────────────────────────────────────┘
                                  │
 06:25  ┌─ VISUAL PLAN ─────────────────────────────────────────────────┐
        │ one scene per beat. scene = beat.start, beat.dur, beat.label   │
        │ choose depth treatment per scene (see §5)                      │
        └────────────────────────────────────────────────────────────────┘
                                  │
 06:40  ┌─ VOICE ───────────────────────────────────────────────────────┐
        │ natural TTS → narration.mp3 → REAL duration measured           │
        │ word timings → captions. Duration is measured, never estimated │
        └────────────────────────────────────────────────────────────────┘
                                  │
 07:00  ┌─ RENDER ──────────────────────────────────────────────────────┐
        │ Remotion/HyperFrames comp built to the measured narration      │
        │ render 1080×1920 30fps → captions burned → −14 LUFS mix        │
        └────────────────────────────────────────────────────────────────┘
                                  │
 07:30  ┌─ GATE ────────────────────────────────────────────────────────┐
        │ caption lint + compliance + human score + video QA             │
        │ everything the machine can check, checked. Then: STOP.         │
        └────────────────────────────────────────────────────────────────┘
                                  │
 08:00  ┌─ TELEGRAM ────────────────────────────────────────────────────┐
        │ video + caption + script + warnings → owner's phone            │
        │ [Approve] [Edit] [Reject] [Re-record voice]                    │
        └────────────────────────────────────────────────────────────────┘
                                  │
 09:00  ┌─ PUBLISH ─────────────────────────────────────────────────────┐
        │ on approval: container → poll → publish → permalink            │
        │ receipt back to Telegram                                        │
        └────────────────────────────────────────────────────────────────┘
```

**Why this order.** Voice before render, because narration duration decides every scene's
length. If you render first and voice second, the video and audio drift apart and no
amount of editing fixes it cleanly. Gate before Telegram, because sending the owner
something that will be refused wastes the one resource they do not have.

---

# 4. Voice — natural narration

## 4.1 What "natural" means, concretely

Not "sounds like a robot". The four things that make a TTS read sound synthetic, in
order of how much they hurt:

| Problem | What it sounds like | Fix |
| --- | --- | --- |
| **Flat prosody** | Every sentence ends the same way | Choose a model with real prosody; chunk with context (see 4.3) |
| **Wrong pace** | Numbers blur; "2%" becomes "two-percent?" | Measure wpm, target 140–165, slow down for figures |
| **Number mishandling** | "7.8%" → "seven point eight percent" rushed into the next clause | Put every number in its own short sentence in the script |
| **Reset at chunk boundaries** | Voice changes character mid-video | Pass previous/next text as context; split on sentence boundaries only |

## 4.2 Provider decision, already made

The owner chose **free and local**. That is `piper` (2 runtimes, ~50MB per voice, CPU,
~10× realtime). Current state: `automation/ig/voice.py` supports `piper` and `kokoro`
locally, with `tools/setup_voice.py` shipping four curated voices and pace presets.

**But "Google voice or any GitHub repo" was in the ask.** So here is the full ladder, and
the rule for when to climb it:

| Tier | Engine | When to use | Cost |
| --- | --- | --- | --- |
| 1 | **Piper** (`pip install piper-tts`) | Default. Daily output, iteration, no cost. | free |
| 2 | **Kokoro-82M** (Apache-2.0, `kokoro` on PyPI) | If Piper's prosody is too flat for you. Better on long sentences. | free |
| 3 | **Chatterbox / XTTS-v2** (Coqui, MIT) | Voice cloning from a real sample. Best free quality, needs GPU. | free |
| 4 | **Google Cloud TTS** (Chirp 3: HD / Neural2) | The "Google voice" in the ask. Excellent prosody. | ~$16/1M chars |
| 5 | **ElevenLabs** | Best overall, and cloning is trivial. | ~$5/mo |

**The engineering rule:** the engine is a **provider behind one interface**, exactly as
`voice.py` is structured today. Adding Google Cloud is one function
`_google_chunk()` beside `_openai_chunk()`, selected by `VOICE_PROVIDER=google`. Adding
Chatterbox is `VOICE_PROVIDER=chatterbox`. Do not fork the pipeline per provider.

**The professional recommendation, stated plainly:** start on Piper for iteration speed
during script work, and render the **final** cut on the best engine the owner will pay
for. Rendering a Reel five times a day while tuning it should be free; the one render the
audience hears should not be the worst available. Implement the render step with a
`--voice-quality draft|final` flag that switches tiers.

## 4.3 The contract for voice in the codebase

```
voice.narrate(text, out_path, *, quality="final") -> Narration
Narration(
    text, audio_path, seconds,            # seconds is MEASURED, never estimated
    provider, chunks, warnings
)
```

Rules the implementation must keep:

- **Chunk on sentence boundaries, never mid-sentence.** Each chunk gets the previous and
  next sentence as context so prosody does not reset.
- **Measure duration with `ffprobe`, and fall back to parsing `ffmpeg -i`** because many
  machines ship ffmpeg without ffprobe. (Already implemented — do not regress it.)
- **Never estimate duration when audio exists.** An estimate used as a fact is how
  captions drift, and drifting captions read as "bot".
- **Persist the voice id in `.env`**, not in prompt text, so the same voice is used by a
  cron job at 06:00 with nobody watching.

---

# 5. 3D — what we actually mean, and what to build

This is the section most likely to go wrong, so it is written as a decision rather than a
vibe.

## 5.1 Three tiers of "3D", in ascending cost

| Tier | What it is | Engine | Render time | Use when |
| --- | --- | --- | --- | --- |
| **A. CSS 3D** | Depth via `perspective` + `translateZ` + `rotateX/Y` on DOM. Text and panels in space. | HyperFrames (`hyperframes-animation` has 7 rules: `3d-camera-flight`, `orbit-3d-entry`, `3d-text-depth-layers`, …) | seconds | **Default.** 90% of finance explainers. Fast, diffable, deterministic. |
| **B. WebGL / Three.js** | Real geometry, materials, lighting, shaders. Charts as objects, coins, buildings. | HyperFrames `three` adapter **or** Remotion + `@remotion/three` | 1–5 min | When the object must be real — a 3D bar chart the camera flies through, a rotating coin, a building made of candles. |
| **C. Generated video** | AI video clips | Any provider | minutes + cost | Almost never. Cannot be factually controlled, and finance cannot afford a hallucinated chart. **Use only for abstract background plates, never for data.** |

**Rule: data is never decorative in tier C.** A chart in a finance Reel must be computed
from real numbers and rendered as geometry (tier B) or DOM (tier A). An AI-generated
"stock chart" is a fabricated number, which is the one thing this account may not do.

## 5.2 The contract that makes 3D render correctly

Both 3D paths have the same trap: **render from a timeline, not from a clock.** A 3D scene
that advances on `requestAnimationFrame` renders different frames on different machines,
and a 30s Reel becomes non-reproducible.

**HyperFrames + Three.js** (`.claude/skills/hyperframes-animation/adapters/three.md`):

- Create scene, camera, renderer, materials **synchronously**.
- Listen for `hf-seek` and render exactly that time. Never own the clock.
- **Always set `data-duration="<seconds>"` on the root composition element.** The `three`
  adapter does not infer duration, so omitting it fails with *"Composition has zero
  duration"* — and `npx hyperframes lint` catches it as
  `root_composition_missing_duration_source`.
- Load models, textures and HDRIs **before** seeking starts. Never fetch at seek time.

**Remotion + `@remotion/three`** (`.claude/skills/remotion-markup/3d.md`):

- Install with `npx remotion add @remotion/three`.
- Drive everything from `useCurrentFrame()` and `interpolate()`. No `useEffect` animation,
  no `Date.now()`, no CSS transitions on 3D properties.
- `useThree` for imperative access inside a `<ThreeCanvas>`.

## 5.3 The 5 scene archetypes this account needs

Build these five as **reusable components**, then compose them. A daily account cannot
afford to art-direct every video from scratch.

1. **The Number in Depth** — the hero figure at 150–200px, on a plane pushed back in Z,
   camera drifts forward as it is spoken. Caption sits in the safe zone.
2. **The Arithmetic Stack** — 3–5 lines of a calculation arriving as stacked cards in 3D,
   each one landing on its beat. The maths happens in front of the viewer.
3. **The Chart the Camera Flies Through** — a real series rendered as 3D bars or a ribbon;
   camera travels along the time axis. **Numbers come from a CSV, never from imagination.**
4. **The Split / Compare** — two panels rotated apart in space: `2% vs 1%`, `before vs
   after`, `what you think vs what happens`.
5. **The Rule Card** — brand-consistent, flat, fast. Used as the CTA and the loop-back
   frame, so the last second echoes the first and a second watch is free.

## 5.4 Render budget, which decides the architecture

One Reel per day, every day. So:

- **Total render time must stay under ~10 minutes** on the owner's machine. Above that,
  iteration dies and the owner starts skipping days, which is the real failure mode.
- Tier A renders in seconds → safe for daily.
- Tier B in 1–5 minutes → budget **one** tier-B scene per Reel, maximum, and pre-render
  reusable 3D assets (coin, cube, grid) to disk so they are not rebuilt each time.
- **Cache aggressively**: if the script and the scene graph hash are unchanged, reuse the
  render. Hash the inputs, store the mp4 keyed by that hash.
- Render overnight for the next morning's slot if a Reel uses tier B. The 06:00 pipeline
  is for the 90% case; anything heavy moves to the night before.

---

# 6. Scripting — measured, not vibes

The script is the product. The video is packaging.

## 6.1 The gates a script must pass before render

```bash
# every one of these must pass, or the script is not done
python3 .claude/skills/ig-reel/hookscore.py hooks.txt     # hook ≥ 70, SPECIFICITY ≥ 60
python3 .claude/skills/ig-reel/beats.py script.txt --target 35
python3 -m ig compliance "$(cat script.txt)"              # PASS
python3 .claude/skills/ig-human/detect.py script.txt      # human score ≥ 65
```

`beats.py` returns the structure every downstream stage consumes:

```json
{"wpm": 165, "total_seconds": 18.4, "total_words": 51,
 "beats": [{"n": 1, "start": 0.0, "dur": 1.82,
            "text": "Most traders size by confidence.",
            "concrete": 0, "label": "HOOK", "flags": []}],
 "notes": ["..."]}
```

`beat.start` and `beat.dur` are the **scene timings**. This is the handshake between the
script and the 3D composition: one scene per beat, no scene longer than 4s without a
visual change, and the last beat echoes a word from the first.

## 6.2 Hard rules, from the niche

- **The hook contains something checkable within 8 words** — a number, a rate, a named
  mistake. `hookscore.py` measures this as SPECIFICITY, and it is the check that actually
  predicts whether a finance hook travels.
- **Hook runs ≤ 3 seconds.** Past that the thumb has already decided.
- **No beat longer than 4 seconds** without a visual change. A static frame is where
  people leave.
- **Numbers get their own sentence.** "Risk one percent of capital. Every trade." reads;
  "risk one percent of capital every trade" blurs.
- **The last line loops to the first.** Second watches are free reach.
- **No advice, no recommendation, no target, no win rate, no testimonial result.** The gate
  blocks these; write so it does not have to.

---

# 7. Telegram — the admin surface

This exists because the owner will not be at a terminal at 07:30. It is also the only
place a human approval happens in production.

## 7.1 What the bot must do

**Approval loop (the core):**

| Command / button | Behaviour |
| --- | --- |
| `/today` | Today's draft: video, caption, script, every warning from every gate |
| `[Approve]` | Marks approved → scheduler publishes at the slot |
| `[Edit caption]` | Opens a text prompt, re-runs caption lint + compliance, re-sends |
| `[Reject]` | Kills the item with a reason, which is logged and read at the weekend |
| `[Re-record voice]` | Re-runs narration with a different take/pace, re-renders |
| `[Publish now]` | Bypasses the slot, still requires approval |

**Operations:**

| Command | Behaviour |
| --- | --- |
| `/status` | Queue depth, next slot, publishing quota used, paused?, token age |
| `/queue` | Approved/pending/failed items with IDs |
| `/pause` / `/resume` | The kill switch — writes `state/PAUSED` |
| `/week` | The printable week (`ig plan`) |
| `/inbox` | Everything in `state/needs_human.jsonl` |
| `/reply <id> <text>` | Send a human reply into an escalated thread |
| `/stats` | Last 30 days: posted, published, failed, outlier multiple |

**Monitoring (push, not pull):**

- **Every failure pushes.** Publish failed, render failed, token expiring in <7 days,
  webhook down, quota at 80%. Silence means healthy — that is the contract.
- **A daily 20:00 digest**: what published, what is queued for tomorrow, what needs a
  human, one number worth knowing.

## 7.2 Architecture

```
Telegram  ──webhook or long-poll──►  bot.py  ──►  ig queue / publish / pause
    ▲                                   │
    │                                   ├── long-poll avoids needing a public URL
    └──── video + inline keyboard ◄─────┘    (better for a home machine)
```

Two decisions worth making once:

- **Long-poll (`getUpdates`), not webhook.** A home machine or a laptop behind NAT cannot
  receive Meta-style webhooks from Telegram, and long-polling is a supported first-class
  mode. Less to expose, less to break.
- **Buttons carry the item id**, never free text. `approve:20261124-0812-a3f1`. A bot that
  parses "yes" will eventually approve the wrong thing.
- **Text yes. Video, no.** Send the render as a **video** to Telegram, not a file, so the
  owner can watch it on a phone in one tap. This single detail decides whether approvals
  happen at all.

## 7.3 Security

- Bot token in `.env`, never in code. `chmod 600`.
- **Allowlist the owner's Telegram user id.** A bot that accepts `/pause` from anyone who
  finds it is a denial-of-service on the account.
- Every command that changes state writes an audit line to `state/telegram_audit.jsonl`
  with the user id, the command, and the item.

---

# 8. The system, in modules

Do not restructure what exists. Extend it.

```
automation/ig/
  config.py      env, paths, limits, policy switches          [exists]
  graph.py       Graph API client, throttling, token refresh   [exists]
  publish.py     container flow: image/carousel/reel/story     [exists]
  social.py      comments + DMs, Meta's 4 rules in code        [exists]
  replies.py     intent → draft → escalation                   [exists]
  compliance.py  the fintech gate                              [exists]
  render.py      ffmpeg card renderer (tier A fallback)        [exists]
  voice.py       narration + measured duration                 [EXTEND: google, kokoro, chatterbox, draft/final]
  schedule.py    the week, what is due now                     [EXTEND: daily slot]
  webhook.py     Meta webhook                                  [exists]
  cli.py         python3 -m ig <cmd>                           [EXTEND: new cmds]
  telegram.py    ★ NEW: bot, approval loop, push alerts
  scenes/        ★ NEW: the five 3D archetypes, as reusable comps
  video3d.py     ★ NEW: HyperFrames/Remotion dispatch + render cache
```

**New CLI commands to add:**

```
ig telegram          run the bot
ig notify <msg>      push a line to the owner
ig render3d <spec>   tier-B render (HyperFrames or Remotion)
ig script <idea>     scaffold a script file with the gate commands pre-filled
```

---

# 9. Tooling, already in the repo — use it, do not rebuild it

| Need | Use | Not this |
| --- | --- | --- |
| Hook scoring | `ig-reel/hookscore.py` | your own taste |
| Timing | `ig-reel/beats.py` | estimating words ÷ 150 |
| Caption lint | `ig-caption/caption.py` | eyeballing 125 chars |
| Humanising | `ig-human/humanize.py` | "make it sound natural" |
| Editing real footage | `edit` skill | re-encoding by hand |
| CSS 3D motion | `hyperframes` + `hyperframes-animation` | hand-written GSAP |
| WebGL 3D | `hyperframes-animation/adapters/three.md` or `@remotion/three` | a bespoke three.js app |
| Rendering | `hyperframes-cli`, `remotion-render` | ffmpeg filter chains for 3D |
| Voice | `voice.py` + `tools/setup_voice.py` | a new TTS integration |
| Compliance | `source: (compliance.py)` + `brand/compliance.json` | a prompt instruction |

If a task needs something not in this table, **check `.claude/skills/` before writing new
code.** There are 111 skills installed; the odds that one already solves it are high.

---

# 10. Definition of done, per day

A Reel is shipped when **all** of these are true:

- [ ] Hook scores ≥ 70 with SPECIFICITY ≥ 60
- [ ] `beats.py` total is within ±10% of target, hook ≤ 3s, no beat > 4s, loops to line 1
- [ ] Compliance gate **PASS** on script and caption
- [ ] Human score ≥ 65 (it does not read as generated)
- [ ] Narration duration is **measured**, and scene timings derive from it
- [ ] 3D renders deterministically — same spec, same file, twice
- [ ] Captions land in the safe zone (bottom 250px clear), word-accurate
- [ ] Audio at −14 LUFS
- [ ] 1080×1920, H.264/AAC, under 300MB, `+faststart`
- [ ] Video, caption and script delivered to Telegram with every warning shown
- [ ] A human pressed **Approve**
- [ ] Publish receipt logged to `state/posted.jsonl` with the permalink
- [ ] Tomorrow's slot has something in `approved` by 20:00 today

If any box is unchecked, the correct output is a message to the owner saying which box,
not a published Reel.

---

# 11. What to build first, in order

Do not build the whole thing. Build the spine, prove it on one Reel, then widen.

| Step | Deliverable | Proves |
| --- | --- | --- |
| **1** | Google/Kokoro voice implemented behind `VOICE_PROVIDER`, `--voice-quality` flag | The voice ladder is real, not aspirational |
| **2** | `scenes/` with archetypes 1, 2, 5 (the depth ones) | 3D that renders in seconds and looks designed |
| **3** | `video3d.py` with the render cache and the determinism check | Daily output is affordable |
| **4** | `telegram.py` with `/today`, `[Approve]`, `/pause`, and failure push | The owner can run this from a phone |
| **5** | One full daily run end to end, with the owner watching | The whole pipeline holds together |
| **6** | Archetypes 3 and 4, plus the nightly pre-render | Depth and variety without blowing the budget |

---

# 12. Things that will go wrong, and the answer

| Symptom | Cause | Answer |
| --- | --- | --- |
| Voice changes character mid-video | Chunk boundary reset | pass prev/next sentence as context |
| "Composition has zero duration" | HyperFrames `three` adapter has no duration inference | set `data-duration` on the root element |
| Captions drift by 0.3s | estimated duration used as fact | measure with ffprobe, then `ffmpeg -i` fallback |
| Render takes 40 minutes | tier-B scene per beat | one tier-B scene max, cache by input hash |
| Telegram shows a file, owner never watches | sent as document | send as `video`, with `supports_streaming` |
| Bot approves the wrong item | buttons parse free text | item id in the callback data, always |
| Reel looks like PowerPoint | no camera movement | every scene needs one camera or one depth change |
| AI-generated chart with fake numbers | tier C used for data | data is computed, tier A or B only |
| Account posts something embarrassing | `AUTOPUBLISH=on` too early | it stays off until the queue is right for a month |

---

# 13. The one-paragraph brief, if you read nothing else

Build a daily 3D finance Reel factory for one real Instagram account. Script first and
measured — hooks scored, timing verified, claims gated. Voice second and measured — a
natural voice whose real duration times every scene. Video third — depth and camera
movement, real numbers rendered as real geometry, deterministic and cacheable so one Reel
costs minutes not hours. Captions and mix last, in the safe zone at −14 LUFS. Then stop and
ask a human on Telegram, who approves from their phone and whose approval is the only thing
that publishes. Keep the account educational and unregistered, which means the machine
talks about mechanisms and never about outcomes, and a gate in code enforces that rather
than hoping a prompt does.
