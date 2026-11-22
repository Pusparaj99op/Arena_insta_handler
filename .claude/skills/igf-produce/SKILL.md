---
name: igf-produce
description: >-
  Turn an approved fintech script into a finished vertical video on any machine:
  cards, narration, karaoke captions, loudness, and the publish-ready file, with
  ffmpeg alone or with Remotion/HyperFrames when they are installed. Use when the
  user says "make the video", "render this", "turn this script into a reel",
  "add a voiceover", "the render failed", "captions are off", or when a script is
  approved and needs to become an mp4.
---

# igf-produce — script in, postable mp4 out

There are four ways to make a video in this repo. Pick by what the piece needs,
not by what is installed. The rule: **the boring path that renders in two
minutes beats the beautiful path that renders tomorrow**, because this account
posts daily.

| The piece | Use | Why |
| --- | --- | --- |
| Numbers, rules, a talking script | `python3 -m ig render` | ffmpeg only, no node, deterministic, fast |
| A real person talking to camera | `/edit` (master-skills) | It cuts dead space and captions a real take |
| Motion, transitions, data animation | `/hyperframes` or `/remotion-create` | Real motion engines, worth the setup |
| A talking head recut with overlays | `/talking-head-recut` | Built for exactly this |

---

## Path A: the ffmpeg renderer (default)

```bash
cd automation
python3 -m ig doctor                    # what this machine can do, first
python3 -m ig render ../examples/reel-spec.json
```

The spec is a JSON file with a script and a list of cards:

```json
{
  "kind": "reel",
  "out_dir": "build/2026-11-24-position-sizing",
  "script": "Most traders size by confidence...",
  "narration_text": "Most traders size by confidence...",
  "wpm": 165,
  "caption_preset": "bold-word",
  "cards": [
    {"kicker": "RULE 01", "stat": "1%", "headline": "Risk per trade, fixed",
     "body": "Not confidence. Not conviction. One percent of capital, every time."},
    {"kicker": "THE MATHS", "stat": "4 losses",
     "headline": "2% vs 1% after a bad week",
     "body": "2% sizing: 7.8% down. 1% sizing: 3.9% down. Same four losses."}
  ]
}
```

What happens, in order:

1. **Narration** — generated first, because its real duration decides how long
   each card stays on screen. If no voice provider is configured, it estimates
   from `beats.py` and says so in the warnings.
2. **Stills** — one PNG per card at 1080x1920, safe-zone aware (`SAFE_TOP=220`,
   `SAFE_BOTTOM=250`, so the Reel UI never covers a word).
3. **Slideshow** — cards concat'd with a slow zoom, so it does not read as a
   PowerPoint. `zoompan` is used only if this ffmpeg has it.
4. **Mix** — narration wins; music sits at -26dB and is sidechain-ducked under
   the voice; the whole thing lands at -14 LUFS, the loudness every platform
   normalises to.
5. **Captions** — word timings from whisper (local first, API second), ASS karaoke
   in the safe zone, burned in. If this ffmpeg has no libass, the `.ass` is
   written next to the video and the warning says to burn it elsewhere.
6. **Mux** — H.264/AAC, `+faststart`, ready for the container upload.

Every step degrades with a named warning instead of failing the whole render.
Read the `warnings` array before you call a render done: it is the difference
between "rendered" and "postable".

### Cards that work on a phone

- **One idea per card**, six words in the headline at most.
- **The number is the visual.** 150-200px, accent colour, nothing competing
  with it.
- **Body is optional.** If the card needs a paragraph, it is two cards.
- **The first card is the hook** and it is on screen for under 2 seconds. If the
  hook needs reading time, the video loses before it starts.

### The caption presets

| Preset | Look | When |
| --- | --- | --- |
| `bold-word` | One to three words, the active word in the brand accent | The default for talking-number reels |
| `line` | A whole line at a time, white on a shadow | When the line is a sentence worth reading |
| `karaoke` | Three words, the spoken one highlighted | Fast scripts, 175 wpm and up |

---

## Path B: real footage

If the owner films, `/edit` is the right tool and it is better than anything
this repo does with footage.

```bash
# inside the /edit skill, T = its tools/ directory
python3 "$T/deadspace.py" take.mp4 --out cut.mp4
python3 "$T/captions.py" cut.mp4 --out subs.ass
```

Non-negotiables for this account's footage:

- **Captions land in the safe zone**, not on the face and not under the UI.
- **Cut the "so, um, basically"**, but never clip a word: a clipped word reads
  as a mistake even when nobody can say why.
- **-14 LUFS**, no compressor on the voice. A loud voice on a quiet phone is the
  most common audio mistake on finance content.
- **Keep the breath before the number.** It is a beat of attention and it is the
  difference between a read and a recital.

---

## Path C: real motion

When the piece is an animation rather than a talking number, stop trying to do
it in ffmpeg.

**HyperFrames** (`/hyperframes`) renders HTML/CSS compositions. Best for kinetic
type, data animation, and anything with choreography.

```bash
npx hyperframes init my-reel
npx hyperframes lint && npx hyperframes check
npx hyperframes preview --background        # show the owner before rendering
npx hyperframes render --quality high
```

**Remotion** (`/remotion-create`, `/remotion-render`) renders React. Best for
reusable series intros, charts driven by real data, and anything that should
look identical every week.

```bash
npx create-video@latest
npx remotion studio                          # preview
npx remotion render Reel out/reel.mp4
```

Both need Node 22+. If it is not on the machine, do not start: write the
`composition.md` brief, hand it to the owner, and ship the ffmpeg version today.
A brief is not a video, and the account needs a video.

---

## Voiceover that does not sound generated

The provider is chosen in `automation/ig/voice.py`: ElevenLabs, then any
OpenAI-compatible TTS, then local Piper/Kokoro. What matters more than the
provider is these five things:

1. **One voice, forever.** A changing voice per video means no channel. Set
   `ELEVENLABS_VOICE_ID` once and never change it without a reason.
2. **Slow down on numbers.** "Two percent" read at speed is "two... percent?"
   and the viewer hears a question. The scripts should already put the number in
   its own short beat; `beats.py` measures that.
3. **Never let it read a list.** The model's default is a list-reading cadence:
   "first, ... second, ... third, ...". Rewrite lists as sentences before TTS.
4. **Directions in the voice profile, not the script.** `brand/voice.md` has a
   "For the automated voice" section. Put tone there, keep the script clean.
5. **Chunk with context.** Long scripts are split on sentence boundaries with
   the previous and next sentence passed as context, so the prosody does not
   reset mid-thought. `voice.py` does this; do not concatenate raw calls.

If the owner's own voice samples exist and ElevenLabs supports a clone on their
plan, clone it. Their real voice outperforms every synthetic one on trust, and
trust is the product here.

---

## Troubleshooting, by the error you actually see

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ffmpeg is missing` | Not installed | `apt install ffmpeg` / `brew install ffmpeg`, or use the Docker image |
| Cartons of tofu `□□□` where text should be | No font for the glyph | Add a `.ttf` to `brand/fonts/`; the renderer picks the first one it finds |
| Captions under the Instagram UI | Wrong margin | Bottom safe zone is 250px; raise `margin_v` in the preset |
| Video is black | `drawtext` missing from this ffmpeg | `python3 -m ig doctor`; install a full ffmpeg build |
| Audio quiet on phone | Not normalised | The mix targets -14 LUFS; if it is quiet, the narration was already quiet: re-narrate |
| Model refused the render | Template/spec mismatch | `python3 -m ig render spec.json` prints the failing step and command |
| `Container ERROR` on publish | Codec/ratio/size | H.264 + AAC, 9:16, under 300MB, Moov atom at the front |

---

## Before you call it finished

- [ ] Duration is 7 to 60 seconds. A finance reel over 90 seconds needs a reason.
- [ ] The hook is legible in the first 2 seconds, and it has a number in it.
- [ ] No text sits under the Reel UI (bottom 250px) or the caption overlay.
- [ ] Captions match the audio word for word, and the numbers are spelled right.
- [ ] Loudness is -14 LUFS (or the mix has a reason not to be).
- [ ] `warnings` from the render were read, and none of them is silent video.
- [ ] The file is in `build/publish/<slug>/` so `PUBLIC_MEDIA_BASE_URL` can serve
      it to Meta. A video anywhere else cannot be published.
