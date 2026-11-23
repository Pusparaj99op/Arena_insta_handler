#!/usr/bin/env python3
"""Set up a free, local narration voice. No API key, no per-word cost.

    python3 tools/setup_voice.py --list
    python3 tools/setup_voice.py --voice en_US-lessac-medium
    python3 tools/setup_voice.py --voice en_US-lessac-medium --try "Risk one percent of capital."

Piper voices are small (20-60MB ONNX files) and run on a CPU: about 10x realtime
on a laptop. For a finance account that means a 30-second reel is voiced in
three seconds, offline, as many times as you like while iterating on a script.

**Which voice, for this niche.** Most Piper voices are read from audiobook
corpora, and audiobook cadence is wrong for finance: it swells at the end of
statements and treats numbers as narrative colour. The three below are the ones
that hold a flat, measured delivery on numbers. The tool tells you what each
one is good at rather than dumping a list of 40 names.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_DIR = ROOT / "brand" / "voices"
ENV_PATH = ROOT / "automation" / ".env"

# Curated, with the reason. `length_scale` > 1 slows the read down, which is
# what a script full of numbers needs: "seven point eight percent" spoken fast
# sounds like a question.
RECOMMENDED = {
    "en_US-lessac-medium": {
        "why": "Calm, low, flat on statements. The safest default for explanations.",
        "accent": "neutral American", "length_scale": 1.15, "sentence_silence": 0.35,
        "best_for": "talking numbers, rule explanations",
    },
    "en_GB-alba-medium": {
        "why": "Scottish, dry, unhurried. Reads as credible rather than salesy.",
        "accent": "British (Scottish)", "length_scale": 1.12, "sentence_silence": 0.38,
        "best_for": "opinion posts, ecommerce economics",
    },
    "en_US-ryan-high": {
        "why": "Higher fidelity, slightly more energy. Use if lessac sounds sleepy.",
        "accent": "neutral American", "length_scale": 1.10, "sentence_silence": 0.30,
        "best_for": "shorter, punchier reels",
    },
    "en_US-amy-medium": {
        "why": "Warmer and more conversational. Weaker on long numbers.",
        "accent": "neutral American", "length_scale": 1.12, "sentence_silence": 0.35,
        "best_for": "stories, DM-adjacent content",
    },
}

TEST_LINE = ("Most traders size by confidence. Bigger when it feels obvious. "
             "That is backwards. Fix the risk at one percent of capital, then let "
             "the stop distance decide the size.")


def have_piper() -> bool:
    return bool(shutil.which("piper")) or _module_present()


def _module_present() -> bool:
    import importlib.util
    return importlib.util.find_spec("piper") is not None


def download(voice: str) -> Path:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    target = VOICE_DIR / f"{voice}.onnx"
    if target.exists():
        print(f"already here: {target}")
        return target
    cmd = [sys.executable, "-m", "piper.download_voices", voice,
           "--download-dir", str(VOICE_DIR)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"download failed:\n{proc.stderr[-600:]}\n\n"
            f"Install piper first:  python3 -m pip install piper-tts\n"
            f"Then fetch a voice by hand if the downloader is blocked:\n"
            f"  https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/"
            f"{voice.split('-')[1]}/medium\n"
            f"Put both the .onnx and .onnx.json in {VOICE_DIR}/")
    if not target.exists():
        found = list(VOICE_DIR.glob(f"{voice}*.onnx"))
        if not found:
            raise SystemExit(f"downloaded, but no .onnx found in {VOICE_DIR}")
        target = found[0]
    print(f"voice ready: {target}  ({target.stat().st_size / 1e6:.0f} MB)")
    return target


def synth(text: str, voice: str, out: Path, *, length_scale: float | None = None,
          sentence_silence: float | None = None) -> Path:
    cfg = RECOMMENDED.get(voice, {})
    scale = length_scale or cfg.get("length_scale", 1.15)
    silence = sentence_silence if sentence_silence is not None else cfg.get(
        "sentence_silence", 0.35)
    model = VOICE_DIR / f"{voice}.onnx"
    if not model.exists():
        model = download(voice)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["piper", "--model", str(model), "--output_file", str(out),
           "--length-scale", str(scale), "--sentence-silence", str(silence),
           "--normalize"]
    proc = subprocess.run(cmd, input=text.encode(), capture_output=True)
    if proc.returncode != 0:
        fallback = [sys.executable, "-m", "piper", *cmd[1:]]
        proc = subprocess.run(fallback, input=text.encode(), capture_output=True)
    if proc.returncode != 0 or not out.exists():
        raise SystemExit(f"piper failed:\n{proc.stderr.decode()[-500:]}")
    return out


def write_env(voice: str, model: Path) -> None:
    """Write the four lines the engine reads, leaving the rest of .env alone."""
    lines = {
        "VOICE_PROVIDER": "local",
        "PIPER_MODEL": str(model),
        "VOICE_LENGTH_SCALE": str(RECOMMENDED.get(voice, {}).get("length_scale", 1.15)),
        "VOICE_SENTENCE_SILENCE": str(RECOMMENDED.get(voice, {}).get(
            "sentence_silence", 0.35)),
    }
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if ENV_PATH.exists():
        existing = ENV_PATH.read_text(encoding="utf-8").splitlines()
    out, seen = [], set()
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in lines:
            out.append(f"{key}={lines[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in lines.items():
        if key not in seen:
            out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote VOICE_PROVIDER=local to {ENV_PATH}")


def duration(path: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                           "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                           str(path)], capture_output=True, text=True)
    try:
        return round(float(proc.stdout.strip()), 2)
    except ValueError:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="the recommended voices")
    ap.add_argument("--voice", help="e.g. en_US-lessac-medium")
    ap.add_argument("--try", dest="try_text", help="synthesise this text instead of the sample")
    ap.add_argument("--out", default=str(ROOT / "build" / "voice-test.wav"))
    ap.add_argument("--length-scale", type=float,
                    help=">1 is slower. 1.15 suits numbers.")
    ap.add_argument("--sentence-silence", type=float, help="seconds between sentences")
    ap.add_argument("--use", action="store_true",
                    help="make this voice the default in automation/.env")
    args = ap.parse_args()

    if args.list or not args.voice:
        print("Recommended for finance narration (all free, all local):\n")
        for name, meta in RECOMMENDED.items():
            here = "  [downloaded]" if (VOICE_DIR / f"{name}.onnx").exists() else ""
            print(f"  {name}{here}")
            print(f"      {meta['why']}")
            print(f"      accent: {meta['accent']}  ·  best for: {meta['best_for']}")
            print(f"      pace: length-scale {meta['length_scale']} "
                  f"(slower than default, on purpose)\n")
        print("Install:  python3 -m pip install piper-tts")
        print("Then:     python3 tools/setup_voice.py --voice en_US-lessac-medium --use --try")
        return 0

    if not have_piper():
        raise SystemExit(
            "piper is not installed. Two commands:\n"
            "  python3 -m pip install piper-tts\n"
            "  python3 tools/setup_voice.py --voice en_US-lessac-medium --use")

    model = download(args.voice)
    text = args.try_text or TEST_LINE
    out = Path(args.out)
    synth(text, args.voice, out, length_scale=args.length_scale,
          sentence_silence=args.sentence_silence)
    seconds = duration(out)
    words = len(text.split())
    print(f"sample: {out}")
    if seconds:
        print(f"length: {seconds}s for {words} words = {words / seconds * 60:.0f} wpm")
        print("  A finance read wants 140-165 wpm. Above 175 the numbers blur;")
        print("  below 130 it drags. Re-run with --length-scale to adjust "
              f"(currently {args.length_scale or RECOMMENDED.get(args.voice, {}).get('length_scale')}).")
    if args.use:
        write_env(args.voice, model)
    else:
        print(f"\nTo make it the default: add --use, or set in automation/.env:\n"
              f"  VOICE_PROVIDER=local\n  PIPER_MODEL={model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
