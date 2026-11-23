# The skills

**111 skills, 11 sources, all vendored into `.claude/skills/`.** Claude Code, and
any agent that reads `SKILL.md` folders, discovers them automatically. Each one
is a folder with a `SKILL.md` entry point and, where needed, runnable tools
beside it.

Why vendor instead of clone: a skill that loads a path outside the project breaks
the moment the repo moves, and eleven `git clone`s is not a setup step anybody
does twice. Everything here is committed, version-pinned and works offline.

The one thing vendoring costs is upstream updates. `skills.lock.json` records the
exact commit each pack came from, and a section at the bottom explains how to
refresh one.

---

## The five written for this account

Read `igf-run` first. The other four are the ones it routes to.

| Skill | Job |
| --- | --- |
| **`igf-run`** | The operator's entry point: the niche rules, the approval gate, the workflow from idea to published, and the map of which upstream skill handles which step. |
| **`igf-finance-content`** | The niche layer. The four post shapes that work on money content (Reframe, Rule stress-tested, Loss with mechanism, Ecommerce economics), the five hook formulas that carry this niche and how each gets ruined, the compliance line as a writer, and the visual language for numbers. |
| **`igf-produce`** | Script to mp4: the ffmpeg renderer, the card rules, the caption presets, the three voice providers, the motion-engine escalation path, and a troubleshooting table keyed to the error you actually see. |
| **`igf-dm`** | The inbox: Meta's four rules, the triage table, the keyword funnel, escalation in the owner's voice, and the inbox metrics that actually matter. |
| **`igf-publish`** | The API: Meta app setup, the 60-day token, media hosting, the webhook, the container flow, the quotas as numbers, the gate and how not to weaken it, and every error code with its fix. |

---

## Vendored, by source

Sizes are approximate and were true when vendored. "Self-contained" means the
skill works from its own folder; "vendored deps" means the upstream repo kept
tools at its root and they have been copied in beside the skill.

### Jake Schincariol — `instagram-agent-skill` · MIT · 13 skills

The reason the content side of this repo works: everything here is opinionated
about what makes an Instagram post finish.

| Skill | What it does |
| --- | --- |
| `ig-reel` | One idea → three scored hooks off 26 formulas, script, on-screen text, timed beat sheet |
| `ig-caption` | The caption, linted, with the 125-character feed window printed as a box |
| `ig-carousel` | Swipe posts: the cover that earns the swipe, slide copy, 1080x1350 files |
| `ig-story` | The daily story sequence and the DM funnel that starts with them moving first |
| `ig-profile` | Scores the profile out of 100 against a 12-part rubric, then rewrites in fix-first order |
| `ig-plan` | The week: what to post, which format, when, and who to engage with |
| `ig-human` | The humanizer: strips invisible characters, em dashes and 154 stock phrases, then scores it |
| `ig-comment` | Comments on other people's posts, nine types, never "🔥🔥🔥" |
| `ig-reply` | The thread under your own post, sorted into keyword/lead/substance/question/support/noise |
| `ig-dm` | The keyword delivery, first message, collab pitch, and exactly two follow-ups |
| `ig-repurpose` | One video, podcast or newsletter into a week of pieces that each stand alone |
| `ig-audit` | Post-mortem ranked by outlier multiple, and sent per reach rather than per view |
| `ig-viral` | Finds what is working in the niche and ranks it by multiple over each account's own median |

The five runnable tools (`hookscore.py`, `beats.py`, `caption.py`,
`humanize.py`, `detect.py`, `swipe.py`) are wired into `automation/ig/skills.py`
so a cron job can use them without a human in a chat.

### Jake Schincariol — `master-skills` · MIT · 3 skills

| Skill | What it does |
| --- | --- |
| `edit` | Talking-head and short-form editing end to end: dead space, word-timed captions, dynamic visuals, stop motion, -14 LUFS. Tools: `deadspace.py`, `captions.py`, `probe.py`, `stopmotion.py`. |
| `virality` | Find the outlier, break down why it worked, rewrite it in your voice, score the hook. |
| `build` | From "an app that does X" to a deployed product, with a real browser QA pass. Useful for the offer's landing page. |

### Jake Schincariol — `video-production-skills` · no license file · 13 skills

The HyperFrames engine: composition, animation, audio, media sourcing, render.
Entry point is `hyperframes`. Self-contained.

`hyperframes`, `hyperframes-core`, `hyperframes-animation`,
`hyperframes-keyframes`, `hyperframes-audio`, `hyperframes-cli`,
`hyperframes-creative`, `hyperframes-registry`, `general-video`,
`talking-head-recut`, `product-launch-video`, `media-use`, `media-router`.

> **License note.** This repo ships **no license file** and no license statement
> in its README. That is not the same as permissive: absent a license, default
> copyright applies, and copying it into a commercial repo is a risk the owner of
> this account should decide on knowingly. It is vendored because you asked for
> it, and `licenses/` records the absence. If this account ever becomes a business
> with lawyers, either get permission or replace these thirteen with the
> Remotion packs, which are explicit.

### kajisho5 — `ffmpeg-skill` · MIT · 1 skill

42 editing tools behind one router: cut, join, reframe, speed, captions,
overlays, silence removal, sync, loudness, HDR→SDR, platform exports and checks.
Python stdlib only, needs ffmpeg 6.1+.

Vendored from the repo root (canonical `SKILL.md`), with the plugin-mirror copy,
CI scripts, docs gallery, tests, fuzz and evals stripped: 64MB → 4MB. The
`scripts/`, `references/`, `templates/` and `mcp/` layout the SKILL expects is
intact, so every documented invocation still works.

### iamaanahmad — `agents-video-editing-skills` · MIT (with NOTICE) · 14 skills

The practical remit: ffmpeg, Remotion, moviepy, captions, voiceover, audio
mixing, screen recordings, vertical shorts, platform export, QA. Self-contained.

`audio-mixing`, `captions-subtitles`, `ffmpeg-essentials`, `motion-design-craft`,
`moviepy-python-video`, `platform-export`, `remotion-programmatic-video`,
`screen-recording-demos`, `thumbnails`, `vertical-shorts`,
`video-editing-router`, `video-planning`, `video-qa`, `voiceover-tts`.

### remotion-dev — `skills` · (offical Remotion, see note) · 16 skills

The official Remotion agent skills, version 4.0.545: create, markup, captions,
render, studio, multimedia, maps, licensing, and best practices. Self-contained.

`remotion-best-practices`, `remotion-create`, `remotion-captions`,
`remotion-docs`, `remotion-interactivity`, `remotion-license`, `remotion-maps`,
`remotion-markup`, `remotion-multimedia`, `remotion-render`, `remotion-saas`,
`remotion-studio`, `remotion-upgrade`, plus three `remotion-best-practices/*`
sub-skills that ship as their own folders.

> **Note.** The repo has no LICENSE file because it lives inside the Remotion
> monorepo; Remotion's own license applies. Remotion is **free for individuals
> and companies of up to three people**; larger companies need a paid company
> license. `remotion-license` explains it, and it is worth checking before this
> account becomes a team.

### DojoCodingLabs — `remotion-superpowers` · MIT · 15 skills

Workflow-shaped skills on top of Remotion: `create-short` (the 9:16 pipeline
with hook-first structure), `create-video`, `add-captions`, `add-music`,
`add-voiceover`, `add-transitions`, `analyze-footage`, `find-footage`,
`generate-clip`, `generate-image`, `review-video`, `transcribe`, `setup`,
`setup-guide`, `remotion-production`. Self-contained.

Note: `create-short` depends on an MCP server called `remotion-production`.
Without it the SKILL still reads and instructs correctly; the MCP steps fail
loudly rather than silently.

### Mozahid-AIUB — `MozahidFlow` · no license file · 3 skills

| Vendored as | What it does |
| --- | --- |
| `motion-color-grading` | Shot matching and grades; 22 files of references |
| `motion-broll` | B-roll selection and placement |
| `sound-effects` | 110 SFX with a licence manifest and a mixing script (`sound_pass.py`) |

> **License note.** No license file at the repo root. The `sound-effects` skill
> carries its own MIT license plus a per-file `LICENSES.md` (Mixkit Free + CC0),
> so the audio is properly licensed. The other two are vendored as-is; same
> caveat as video-production-skills.

### JFerrerH — `ai-video-editor` · no license file · 3 skills

Conversational editing with real Python tooling: `shortform.py` (100KB),
`storyboard.py`, `edit_plan.py`, `overlay_schema.py`, `preview_qa.py`,
`person_matte.py`, `sfx_synth.py`. Vendored: `character-video`,
`motion-graphics`, `short-form-pro`, each with the root `tools/*.py` and
`templates/` copied into `<skill>/tools/` and `<skill>/templates/`, because
upstream addresses them from the repo root.

Dropped: the ten `openspec-*` skills (a spec-workflow harness, not video), the
duplicate `remotion-*` set, and the empty `video-use` stub (upstream clones it
from `browser-use/video-use` at setup time; a zero-byte folder is worse than
none).

> **License note.** No license file. Same caveat.

### prathameshp107 — `video-editing` · no license file · 16 skills

The most disciplined set of the lot: each skill has a narrow job and says when
not to use it. `video-editor` is the router.

`video-editor`, `asset-plan`, `audio-finisher`, `broll-curator`, `color-match`,
`cut-audit`, `format-repurposer`, `motion-overlay`, `platform-package`,
`render-review`, `story-editor`, `style-memory`, `video-semantic-search`,
`vlog-editor`, `voiceover-generator`, `watch`.

Upstream keeps `scripts/`, `templates/` and `assets/fonts/` at the repo root and
addresses them as plain relative paths, so each skill gets a `kit/` folder with
all three copied in. It costs ~1MB of duplication and makes every skill work
from its own folder. Fonts additionally only under `motion-overlay/kit/assets/`.

> **License note.** No license file, though the README says "free and
> open-source". Vendor as-is; decide before commercial use.

### notivn — `AIEV` · MIT · 12 skills

Automated editing, motion graphics and subtitles, with a shared media library.

`ai-illustrations`, `auto-cut`, `background-music`, `gsap`, `make-a-video`,
`noti-tiktok-full-text`, `noti-tiktok-vn`, `noti-youtube-edit`, `offline-voice`,
`remotion-assemble`, `short-form-video`, `video-pipeline`.

The skills address shared media as `../../assets/...`, which from
`.claude/skills/<skill>/` resolves to `.claude/assets/` — so the AIEV `assets/`
tree (sound effects, brand logos, styles) is vendored there, matching upstream's
layout exactly. Dropped the three duplicate HyperFrames skills and the two
authoring-harness skills (`skill-authoring`, `webui-design`), and trimmed the
oversized SFX (peeling vegetables, chopping lime) that no finance reel needs.

### This repo · 5 skills

The `igf-*` five at the top of this file.

---

## Not vendored, and why

| Repo | Why not |
| --- | --- |
| `Jakeschincariol/video-production-skills` — partially | Vendored. See the license note. |
| `langchain-ai/langgraph` | A framework, not a skill. Add it if the orchestration moves out of cron and into a graph; nothing here needs it yet. |
| `instaloader/instaloader` | A scraper. The API is the compliant path for this account's own data, and `/ig-viral` reads public pages at human speed on purpose. Loading Instaloader here would make the compliant path one `import` away from the thing that gets accounts restricted. |
| `elevenlabs/elevenlabs-python` | A SDK. `voice.py` calls the REST endpoint with `urllib` in 40 lines, which is one less dependency on every machine that renders. |
| `openai/whisper` | A model runtime. `voice.py` shells out to `whisper` or `faster-whisper` if installed, and falls back to the API; it does not vendor multi-GB weights. |
| `ralphcrisostomo/n8n-nodes-meta-publisher` | An n8n node. This repo's scheduler builds the same container flow in `publish.py` without a second automation runtime to keep alive. |
| `RVC-Boss/GPT-SoVITS` | A voice-cloning training stack, multi-GB, GPU. If the owner wants their own cloned voice, ElevenLabs' clone is the pragmatic path; SoVITS is a weekend project, not a dependency. |
| `rhkiswani/mcp-video` | An MCP server (83 tools) that duplicates ffmpeg-skill and Remotion skills already installed. Not loaded to avoid two tools answering "edit this video" differently. Available upstream if you prefer it. |

---

## Keeping it current

```bash
# Refresh one pack from upstream (example: remotion-dev)
python3 tools/refresh_skills.py remotion-dev --dry-run
python3 tools/refresh_skills.py remotion-dev
```

`skills.lock.json` holds the commit each pack came from, so a refresh is a diff
you can read rather than a surprise. The five `igf-*` skills are never touched by
a refresh: they are this repo's own, and they are where the account's opinion
lives.

---

## Which skill to load, in one table

| The task | Load |
| --- | --- |
| Anything at all, first | `igf-run` |
| "What should I post about finance" | `igf-finance-content` |
| Write a reel | `igf-finance-content` + `ig-reel` |
| Score a hook | `ig-reel` (run `hookscore.py`) |
| Time a script | `ig-reel` (run `beats.py`) |
| Write a caption | `ig-caption` |
| Make a carousel | `igf-finance-content` + `ig-carousel` |
| Render a video | `igf-produce` |
| Animate something properly | `hyperframes` or `remotion-create` |
| Cut a talking head | `edit` |
| Voiceover | `igf-produce` or `media-use` |
| Edit with lots of judgement | `video-editor` (prathamesh's router) |
| Things look AI-generated | `ig-human` |
| Plan the week | `ig-plan` |
| Answer the inbox | `igf-dm` |
| Post it | `igf-publish` |
| Audit last month | `ig-audit` + `ig-viral` |
| Build the offer's landing page | `build` |

**Do not load five of these at once.** Each is a full instruction set, and loading
them together dilutes all of them. Load the one the task needs.
