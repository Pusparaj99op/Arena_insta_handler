---
name: igf-publish
description: >-
  Get content onto the real Instagram account through Meta's official API without
  getting it restricted: the container flow, quotas, the approval gate, the
  kill switch, and what to do when Meta returns an error. Use when the user says
  "post it", "schedule this", "why did publishing fail", "connect the account",
  "set up the webhook", or anything about tokens, quotas or API errors.
---

# igf-publish — the last mile, and the only one that touches the account

Everything before this is text and files. This is the part that puts something
in front of a real audience on a real account, so it is the part with a human
gate in it.

The code is `automation/ig/publish.py`. Read it before changing anything: it
refuses four things on purpose and every refusal is a scar.

---

## Setup, once

### 1. A professional account and a Meta app

The Content Publishing API only works for **Business or Creator** accounts.
Personal accounts have no API, and any tool that says otherwise is a browser
bot.

1. Instagram app → Settings → Account type → switch to Professional.
2. `developers.facebook.com` → Create app → type **Business**.
3. Add the **Instagram** product. Use **Instagram Login** if you do not want a
   linked Facebook Page; use **Facebook Login** if you do.
4. Scopes needed: `instagram_basic`, `instagram_content_publish`,
   `instagram_manage_comments`, `instagram_manage_messages`, `pages_show_list`.
5. App Review is required for anything outside your own account's testers. Budget
   a week and write the screencast: Meta wants to see the actual flow.

### 2. A long-lived token

A short-lived token lasts an hour and will expire mid-campaign. Exchange it:

```bash
curl -s "https://graph.instagram.com/access_token?grant_type=ig_exchange_token\
&client_secret=$META_APP_SECRET&access_token=$SHORT_TOKEN"
```

That returns a 60-day token. Refresh it before day 60 with
`grant_type=ig_refresh_token`; refreshing keeps the same token alive rather than
issuing a new one. **Put the refresh in cron and forget it**, because the day it
expires is the day the account goes quiet and nobody notices for a week.

### 3. A public base URL for media

Meta does not accept an upload; it fetches a URL. So the render output has to be
reachable over HTTPS.

- Simplest: an S3/R2 bucket with a CDN, or a VPS with nginx serving
  `build/publish/`.
- `PUBLIC_MEDIA_BASE_URL` points at that root, and **only files inside
  `build/publish/` are addressable**. That is deliberate: a public directory
  listing of the build folder would expose voice notes and client numbers.

### 4. The webhook

```bash
cd automation
IG_WEBHOOK_VERIFY_TOKEN=$(openssl rand -hex 16) python3 -m ig webhook --port 8080
```

Point the Meta app's callback at `https://your-host/webhook`, subscribe to
`comments` and `messages`, and set `META_APP_SECRET` so every POST is signature
verified. Without the secret the server rejects every event with a 403, which is
the correct default.

### 5. Verify before trusting

```bash
cd automation
python3 -m ig doctor        # config, policy, environment
python3 -m ig whoami        # which account this token belongs to, and quota
```

`whoami` is the one that catches a token pasted from the wrong app. Run it before
the first publish, not after.

---

## The publish flow, and why it is in this order

```
 build/publish/reel.mp4
        │  (must be a public HTTPS URL that Meta can fetch)
        ▼
 POST me/media  ──►  container id
        │               │
        │               ├─ video: poll status_code until FINISHED
        │               │   (usually 10-60s, up to several minutes for 4K)
        │               │
        ▼               ▼
 POST me/media_publish  creation_id=...  ──►  media id  ──►  permalink
```

Four things that bite, all handled in `publish.py`:

| Trap | What happens | What the code does |
| --- | --- | --- |
| Containers expire in 24h | Create one on Monday, publish Wednesday, it is gone | Creates at publish time, never ahead |
| `status_code` is absent for images | Polling forever on a still | Polls video only, images publish straight away |
| The two docs disagree (50 vs 100 posts) | You plan for 100 and get refused at 50 | Asks `content_publishing_limit`, then applies `LIMIT_POSTS_24H` on top |
| Reels need `share_to_feed` | Post publishes but never appears on the grid | Passes `share_to_feed=true` by default |

### Quotas, as numbers rather than vibes

- **100 API-published posts per rolling 24h**, carousel = 1 post. Meta's
  reference page still says 50 in places; ask the API, do not trust the prose.
- **4,800 × impressions** calls/24h on most endpoints. A new account has a tiny
  budget because it has no impressions: read `x-business-use-case-usage` on every
  response, which `graph.py` does, and back off at 90%.
- **750 private replies per hour**, documented. The account's own ceiling here
  is 60, because a human cannot approve more than that and an unreviewed burst
  is what gets an app flagged.

`LIMIT_POSTS_24H` defaults to 8. That is not a technical limit, it is a
credibility limit: a fintech account posting 30 times a day is a content farm,
and the audience can tell.

---

## The gate, and how to not weaken it

```
planned ──► drafted ──► approved ──► publishing ──► published
                            ▲                        │
                            └── the only road ───────┴──► failed / cancelled
```

`approve` refuses on three things, and only these three:

1. **No caption / no media** — there is nothing to publish.
2. **The caption linter says FIX** — a hard problem (truncated first line, dead
   link, wrong hashtag count).
3. **The compliance gate says BLOCK** — a claim this account cannot make.

Everything else is a *warning*, printed at approval time: a weak hook, no call
to action, a low human score. The approval command **is** the human review, so
refusing on warnings would only teach people to bypass the gate.

**Do not add a fourth refusal without a real incident behind it.** Every
additional gate makes the queue longer, and a long queue is how a daily posting
habit dies.

---

## Automating vs approving

Three switches in `automation/.env`, all off by default:

| Switch | Off (default) | On |
| --- | --- | --- |
| `AUTOPUBLISH` | One approval per post; cron publishes approved items at their slot | Cron publishes approved items without asking again |
| `AUTOSEND_DMS` | Drafts land in `state/needs_human.jsonl` | Keyword deliveries and replies send themselves inside policy |
| `AUTOCREATE_COMMENTS` | Public comment replies are drafted only | Public replies send inside the 30/hour ceiling |

The sensible progression: run everything off for two weeks, watch what the agent
*would* have said, then turn on `AUTOSEND_DMS` for keyword deliveries only
(because that is the one path with no judgement in it), then `AUTOPUBLISH` once
the queue has been consistently correct for a month. `AUTOCREATE_COMMENTS` last,
because a public reply is the most visible thing an account can say.

### The kill switch

```bash
cd automation && python3 -m ig pause --by "why"
```

Creates `state/PAUSED`. Every outbound path checks it: publishing, DMs, comment
replies, the scheduler. Delete the file to resume. Use it the moment anything
looks wrong; the cost of pausing is a missed post, the cost of not pausing is a
screenshot.

---

## Errors, by the code you actually see

| Code / subcode | Meaning | Fix |
| --- | --- | --- |
| `9` / `2207042` | Publishing quota exhausted | Wait for the window to roll. Do not retry today. |
| `4` or `17` | App or user rate limit | Read `estimated_time_to_regain_access`, back off that long |
| `9004` / `2207005` | Media fetch failed | The URL is not public, not HTTPS, or expired |
| `9007` / `2207027` | Media not ready | Not a failure: poll longer. 4K Reels take minutes. |
| `352` | Cannot see the account | Token is for the wrong app or expired |
| `190` | Invalid token | Refresh the 60-day token, check the refresh cron is alive |
| `36003` with aspect-ratio text | Wrong dimensions | Feed: 4:5 to 1.91:1. Reels: 9:16. 1080x1920 is safe. |
| `2207026` | Unsupported video format | H.264 video, AAC audio, MP4 container |
| Container `ERROR` with no detail | Meta's most unhelpful message | Check codec with `w h`: usually H.265, or a variable frame rate |

The generic `ERROR` with no status message is the one that eats hours. The fast
diagnosis, in order: is the URL public from outside your network (`curl` it from
another host), is the file under 300MB, is the video H.264 at 30fps CFR, is the
audio AAC. Nine times in ten it is the codec.

---

## What is not possible, so do not try

- **Cold DMs.** The API will not do it, and any library that claims to is a
  browser bot that will get the account disabled.
- **Following, unfollowing, mass liking.** Not in the API. Third-party tools
  that do it are the number one cause of real accounts being action-blocked.
- **Reading someone else's DMs or followers.** Not possible, and scraping is a
  Terms violation.
- **Posting to Stories with stickers or links.** The API creates a plain Story
  from an image or video. Interactive stickers are app-only.
- **Scheduling inside Instagram.** The API has no `scheduled_publish_time` for
  Instagram. Scheduling is this repo's cron, which is why the queue exists.

Each of these is not a gap in this tool; it is the boundary that keeps a real
account a real account. `/igf-dm` covers the messaging rules in full.
