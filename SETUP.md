# Setup

The parts that are annoying once and then never again: the Meta app, the token,
the webhook, and somewhere for Meta to fetch video from.

Read this in order. Step 4 is the one everybody skips and then loses a day to.

---

## 0. What you need before you start

| Thing | Why | Cost |
| --- | --- | --- |
| Instagram **Business or Creator** account | The API does not exist for personal accounts | free |
| A Meta developer app | Owns the token and the webhook | free |
| ffmpeg 6.1+ with libass | Rendering video and burning captions | free |
| Python 3.10+ | The engine is stdlib only, no pip installs | free |
| Node 22+ | Only if you want Remotion or HyperFrames | free |
| A public HTTPS host | Meta fetches media by URL | a VPS or a bucket |
| A voice provider | Narration | ElevenLabs ~$5/mo, or local piper, free |
| A model API key | Answering DMs in the 24h window | ~$2–10/mo at this volume |

Two things are **not** needed: a database, and a browser. The state is JSON
files and the API is HTTP.

---

## 1. Switch the account to professional

Instagram app → **Settings → Account type and tools → Switch to professional
account → Business** (Creator also works; Business exposes more messaging
features).

Then connect it to a Facebook Page **only if** you use Facebook Login. With
Instagram Login you do not need a Page at all, which is one less thing to break.

---

## 2. Create the Meta app

1. `developers.facebook.com` → **My Apps → Create app** → type **Business**.
2. Add the **Instagram** product.
3. Choose your login path:

   | | Instagram Login | Facebook Login |
   | --- | --- | --- |
   | Needs a Facebook Page | no | yes |
   | Token endpoint | `graph.instagram.com` | `graph.facebook.com` |
   | Graph host in `.env` | default | `IG_GRAPH_HOST=https://graph.facebook.com` |
   | Simplest for one account | ✅ | |
   | Needed for some messaging features | | sometimes |

   **For one account, choose Instagram Login.** Fewer moving parts.
4. Request these scopes:

   ```
   instagram_basic
   instagram_content_publish
   instagram_manage_comments
   instagram_manage_messages
   ```

5. **App Review** is required before anything outside your own testers works.
   Meta wants a screencast of the real flow: a post published, a comment
   answered, a DM replied to. Record it once, carefully, and keep it; renewal
   comes around.

   While in development mode, add your own Instagram account as a **tester** and
   everything works without review. That is the right way to build this.

---

## 3. Get a token that lasts

A short-lived token dies in an hour. Exchange it for 60 days:

```bash
# 1. From the app dashboard: Instagram → API setup → Generate token  (short-lived)
export SHORT_TOKEN="..."

# 2. Exchange it (Instagram Login)
curl -s "https://graph.instagram.com/access_token\
?grant_type=ig_exchange_token\
&client_secret=$META_APP_SECRET\
&access_token=$SHORT_TOKEN"
```

The response has `access_token` and `expires_in` (seconds). Put that token in
`automation/.env` as `IG_ACCESS_TOKEN`.

Then make the refresh automatic, because the day it expires is the day the
account goes quiet and nobody notices for a week:

```bash
# cron: every Sunday at 03:00
0 3 * * 0 cd /path/to/repo/automation && python3 -m ig refresh-token >> ../state/logs/token.log 2>&1
```

The refresh extends the *same* token by 60 days; nothing needs redeploying.
`docker-compose.yml` has this as a container if you would rather not use cron.

**Verify before you trust it:**

```bash
cd automation && python3 -m ig whoami
```

That prints the username, the account type, the follower count and the live
publishing quota. If the username is not the account you meant, stop: you have a
token from the wrong app or a different tester account, and every later failure
will look like a bug in this repo.

---

## 4. Somewhere for Meta to fetch media

This is the step people skip. Meta does not accept a file upload for publishing:
it **fetches a URL**. So `build/publish/` has to be reachable over HTTPS from
Meta's servers.

Pick one:

**a. A bucket + CDN (recommended, no server to run)**

```bash
# Cloudflare R2 or S3, then sync the publish dir
rclone sync build/publish/ r2:ig-media/ --progress
# PUBLIC_MEDIA_BASE_URL=https://media.yourdomain.com
```

**b. nginx on a VPS**

```nginx
location /media/ {
    alias /srv/Arena_insta_handler/build/publish/;
    autoindex off;              # a public file listing exposes drafts
    add_header Cache-Control "public, max-age=300";
    types { video/mp4 mp4; image/jpeg jpg; image/png png; }
}
```

**c. While developing: a tunnel**

```bash
cloudflared tunnel --url http://localhost:8000
cd build/publish && python3 -m http.server 8000
```

A tunnel URL changes on restart, so it is fine for testing the flow end to end
and wrong for production.

**Only files inside `build/publish/` can ever be addressed.** `publish.py`
resolves the path and refuses anything else, on purpose: a public root pointing
at `build/` would serve voice notes, drafts and whatever else is in there.

Test it from outside your own network before believing it:

```bash
curl -I https://media.yourdomain.com/test.mp4
```

Must be `200` with `Content-Type: video/mp4`. A redirect chain is usually fine;
a `403` is not, and Meta reports it as a vague media-fetch error an hour later.

---

## 5. The webhook, so DMs arrive in seconds

Meta pushes comments and messages to a URL you own. Without it the agent works
by polling, which is slower and rate-limited; with it, replies land in seconds.

```bash
cd automation
export IG_WEBHOOK_VERIFY_TOKEN=$(openssl rand -hex 16)
python3 -m ig webhook --port 8080
```

In the Meta app → **Webhooks → Instagram**:

| Field | Value |
| --- | --- |
| Callback URL | `https://your-host/webhook` |
| Verify token | the same `IG_WEBHOOK_VERIFY_TOKEN` |
| Subscriptions | `comments`, `messages`, `mentions` |

Meta sends a `GET` with `hub.challenge`; the server echoes it back if the token
matches. Then it `POST`s events, each signed with your app secret in
`X-Hub-Signature-256`.

**Set `META_APP_SECRET` or every POST is rejected with 403.** That is the correct
default: an unsigned endpoint lets anyone on the internet put words in the
account's mouth, and Instagram will not care whose fault it was.

Two design points worth knowing, because they are what make it reliable:

- The server **acks with 200 before doing the work.** Meta retries anything slow
  or failing, for hours, and a retry storm turns one comment into fifteen DMs.
- **Every event is deduped by id** for ten minutes, for the same reason.

---

## 6. The model and the voice

**Model** (answers DMs; also drafts when a human is not in the loop):

```bash
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
# Any OpenAI-compatible endpoint works:
# LLM_BASE_URL=https://openrouter.ai/api/v1
# LLM_BASE_URL=http://localhost:11434/v1     (Ollama, local, free)
```

Leave it empty and everything still works: the agent drafts through the Claude
skills in `.claude/skills/`, where a human is in the loop anyway. It just cannot
answer a DM inside the 24-hour window.

**Voice** — pick one, in this order of quality:

```bash
# ElevenLabs: closest to a human read
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...        # from the voice library, or a clone of the owner

# OpenAI: cheap, decent, flatter
OPENAI_API_KEY=...             # same key as above
OPENAI_TTS_VOICE=onyx

# Local: free, private, slower to set up
pip install piper-tts
PIPER_MODEL=/path/to/en_US-voice.onnx
```

Whatever you choose, **one voice, forever.** A different voice per video is the
difference between a channel and a pile of clips.

---

## 7. Fill in the account's truth

This step decides whether any of the above produces something worth posting.

1. **`brand/voice.md`** — how the person actually talks. If this is still a
   template with blanks, every draft after it will be rewritten.
2. **`brand/compliance.json`** — the claims this account may never make. Read
   the four `regulated_notes` at the bottom; if you have a real registration
   number, add it to `brand/credentials.json` and reference it, otherwise leave
   the fake-credentials rule on.
3. **`brand/keywords.json`** — your comment keywords and what each delivers. The
   `how_to` line is what the person reads in the DM: only you know whether the
   file is a PDF, a link or a ManyChat flow.
4. **`brand/brand.json`** — colours and handle. The default palette is designed
   to be readable on a phone in daylight; change it only if you have a reason.

Then check the whole machine understands itself:

```bash
cd automation && python3 -m ig doctor
```

---

## 8. First real post, carefully

Do not start with `AUTOPUBLISH=on`. Do this instead:

```bash
cd automation

# a) render something
python3 -m ig render ../examples/reel-spec.json

# b) look at the file. Actually watch it, on your phone.
#    build/2026-11-24-position-sizing/reel.mp4

# c) copy it into the served directory and confirm the URL works
mkdir -p ../build/publish/first && cp ../build/2026-11-24-position-sizing/reel.mp4 ../build/publish/first/
curl -I https://your-host/first/reel.mp4

# d) create the queue item, fill in the caption and video path
python3 -m ig draft reel --theme teach --title "position sizing"

# e) gate it
python3 -m ig approve <item-id>

# f) publish, once, watching
python3 -m ig publish <item-id>
```

If step (f) fails, the error message names the step and the usual cause. The
`ERROR`-with-no-detail case is almost always the codec: H.264 video, AAC audio,
MP4 container, under 300MB, 1080x1920.

---

## 9. Then, and only then, automate

```bash
# crontab -e
*/10 * * * *  cd /path/to/repo/automation && python3 -m ig tick >> ../state/logs/tick.log 2>&1
0 3 * * 0     cd /path/to/repo/automation && python3 -m ig refresh-token >> ../state/logs/token.log 2>&1
```

Or `docker compose up -d`, which runs the webhook, the scheduler and the token
refresh with restarts.

Watch it for two weeks with every `AUTO*` switch off. Read what it *would* have
said. Then turn on `AUTOSEND_DMS` for keyword deliveries first, because that is
the one path with no judgement in it, and work forward from there.

---

## Troubleshooting, by the symptom

| Symptom | Cause | Fix |
| --- | --- | --- |
| `IG_USER_ID is not set` | `.env` not created or not read | `cp automation/.env.example automation/.env`, run from `automation/` |
| `whoami` returns the wrong account | Token from a different app or tester | Regenerate, exchange, verify again |
| Webhook verification fails | Token mismatch, or a proxy eating query params | Check `IG_WEBHOOK_VERIFY_TOKEN` on both sides |
| Every webhook POST is 403 | `META_APP_SECRET` unset or wrong | Set it; the server refuses unsigned payloads by design |
| Publish: `media fetch failed` | URL not public, not HTTPS, or 403 | `curl -I` the URL from another network |
| Publish: container `ERROR`, no detail | Codec, size or aspect ratio | H.264 + AAC, MP4, 1080x1920, <300MB |
| `quota exhausted (code 9)` | 100 posts in 24h, or your own lower ceiling | Wait; check `LIMIT_POSTS_24H` |
| `token refresh failed` | Token older than 60 days | Mint a new one; put the refresh in cron |
| Render: `ffmpeg is missing` | Not installed | `apt install ffmpeg` / `brew install ffmpeg`, or Docker |
| Render: tofu boxes instead of text | No font with the glyph | Put a `.ttf` in `brand/fonts/` |
| Captions sit under the Instagram UI | Margin wrong | Bottom safe zone is 250px |
| DMs not answered | `AUTOSEND_DMS=off` or fine inside quiet hours | Check `state/needs_human.jsonl`, then the switch |
| Nothing published on schedule | No approved item, or paused | `python3 -m ig queue`, then `ls state/PAUSED` |
