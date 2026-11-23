"""Voiceover: natural English narration, the account's own voice.

Three providers, in this order, because they fail differently:

1. **ElevenLabs** — the closest thing to a human read at 30 seconds of script.
   Best prosody, needs a key and costs per character.
2. **Any OpenAI-compatible TTS** — cheaper, flatter, fine for explainers where
   the visuals carry the video.
3. **Local** — Piper or Kokoro on the machine, no key, no cost, no data leaving
   the box. Slower to set up, best for a series where consistency matters.

The account owner's voice profile decides *what* it says. `beats.py` decides
how long each line is. This module only turns text into audio and refuses to
guess a duration it does not know.

Chunking matters: every provider caps text length and, worse, resets prosody at
the boundary between calls. So we split on sentence boundaries, carry the
previous and next sentence as `previous_text`/`next_text` (ElevenLabs uses these
for continuity), and concatenate losslessly with ffmpeg.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import config, skills


class VoiceError(RuntimeError):
    pass


MAX_CHARS = 1800  # conservative for every provider


@dataclass
class Chunk:
    index: int
    text: str
    path: Path | None = None


@dataclass
class Narration:
    text: str
    audio_path: Path | None
    seconds: float
    provider: str
    chunks: list[Chunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
def provider() -> str:
    explicit = (config.env("VOICE_PROVIDER") or "").lower()
    if explicit in {"elevenlabs", "openai", "local"}:
        return explicit
    if config.env("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    if config.env("OPENAI_API_KEY"):
        return "openai"
    if shutil.which("piper") or shutil.which("kokoro"):
        return "local"
    raise VoiceError(
        "No voiceover provider configured. Pick one:\n"
        "  ELEVENLABS_API_KEY (best quality) — elevenlabs.io, starter tier is enough\n"
        "  OPENAI_API_KEY    (cheap, decent)   — model gpt-4o-mini-tts\n"
        "  piper on PATH     (free, local)     — pip install piper-tts\n"
        "Put the key in automation/.env and set VOICE_PROVIDER only if you want to force one.")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def split_sentences(text: str) -> list[str]:
    """Split on sentence ends without a NLP dependency. Good enough for scripts,
    because a script is already written in short sentences by design."""
    import re
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip())
    return [p.strip() for p in parts if p.strip()]


def make_chunks(text: str, max_chars: int = MAX_CHARS) -> list[Chunk]:
    sentences = split_sentences(text)
    chunks: list[Chunk] = []
    buf: list[str] = []
    size = 0
    for sentence in sentences:
        if len(sentence) > max_chars:
            # A single monster sentence: split on commas, then hard-wrap.
            for piece in sentence.split(", "):
                if size + len(piece) > max_chars and buf:
                    chunks.append(Chunk(len(chunks), " ".join(buf)))
                    buf, size = [], 0
                buf.append(piece)
                size += len(piece) + 2
            continue
        if size + len(sentence) > max_chars and buf:
            chunks.append(Chunk(len(chunks), " ".join(buf)))
            buf, size = [], 0
        buf.append(sentence)
        size += len(sentence) + 1
    if buf:
        chunks.append(Chunk(len(chunks), " ".join(buf)))
    return chunks


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
def _http_post(url: str, payload: dict, headers: dict, *, raw_binary: bool,
               timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        return body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise VoiceError(f"TTS request failed HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VoiceError(f"TTS request failed: {exc}") from None


def _elevenlabs_chunk(chunk: Chunk, chunks: list[Chunk], voice_id: str,
                      out: Path) -> Path:
    prev_text = chunks[chunk.index - 1].text if chunk.index > 0 else None
    next_text = chunks[chunk.index + 1].text if chunk.index + 1 < len(chunks) else None
    payload: dict = {
        "text": chunk.text,
        "model_id": config.env("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        "voice_settings": {
            "stability": float(config.env("VOICE_STABILITY", "0.45") or 0.45),
            "similarity_boost": float(config.env("VOICE_SIMILARITY", "0.8") or 0.8),
            "style": float(config.env("VOICE_STYLE", "0.15") or 0.15),
            "use_speaker_boost": True,
        },
    }
    if prev_text:
        payload["previous_text"] = prev_text[-500:]
    if next_text:
        payload["next_text"] = next_text[:500]
    body = _http_post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        payload, {"xi-api-key": config.require("ELEVENLABS_API_KEY")}, raw_binary=True)
    out.write_bytes(body)
    return out


def _openai_chunk(chunk: Chunk, voice: str, out: Path) -> Path:
    payload = {
        "model": config.env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        "voice": voice,
        "input": chunk.text,
        "response_format": "mp3",
        "instructions": config.env(
            "VOICE_DIRECTION",
            "Speak like a calm finance teacher talking to one person. Measured pace, "
            "short pauses at commas, no radio-host energy, no upward inflection at "
            "the end of statements."),
    }
    body = _http_post("https://api.openai.com/v1/audio/speech", payload,
                      {"Authorization": f"Bearer {config.require('OPENAI_API_KEY')}"},
                      raw_binary=True)
    out.write_bytes(body)
    return out


def _local_chunk(chunk: Chunk, out: Path) -> Path:
    """Piper first, Kokoro second. Both offline, both free.

    Piper's `--length-scale` is the one dial that matters for finance narration:
    1.0 is audiobook pace and rushes numbers, 1.15 is measured. It is read from
    the env so `tools/setup_voice.py --use` can set it once and every future
    render inherits the same voice at the same pace.
    """
    model = config.env("PIPER_MODEL") or config.env("LOCAL_TTS_MODEL")
    if shutil.which("piper") and model:
        wav = out.with_suffix(".wav")
        cmd = ["piper", "--model", model, "--output_file", str(wav),
               "--length-scale", config.env("VOICE_LENGTH_SCALE", "1.15") or "1.15",
               "--sentence-silence", config.env("VOICE_SENTENCE_SILENCE", "0.35") or "0.35",
               "--normalize"]
        proc = subprocess.run(cmd, input=chunk.text.encode(), capture_output=True)
        if proc.returncode != 0:
            # Some installs put the CLI behind the module rather than on PATH.
            proc = subprocess.run([sys.executable, "-m", "piper", *cmd[1:]],
                                  input=chunk.text.encode(), capture_output=True)
        if proc.returncode == 0 and wav.exists():
            return wav
        raise VoiceError(
            f"piper failed: {proc.stderr.decode()[-300:]}\n"
            f"Check the model path with: python3 tools/setup_voice.py --list")
    if shutil.which("kokoro"):
        proc = subprocess.run(["kokoro", "--text", chunk.text, "--output", str(out)],
                              capture_output=True)
        if proc.returncode != 0:
            raise VoiceError(f"kokoro failed: {proc.stderr.decode()[-300:]}")
        return out
    if not model and _piper_module_present():
        raise VoiceError(
            "piper is installed but PIPER_MODEL is not set. Pick a voice once:\n"
            "  python3 tools/setup_voice.py --voice en_US-lessac-medium --use")
    raise VoiceError(
        "Local TTS found no usable engine. Either:\n"
        "  python3 -m pip install piper-tts\n"
        "  python3 tools/setup_voice.py --voice en_US-lessac-medium --use\n"
        "or set ELEVENLABS_API_KEY for a hosted voice.")


def _piper_module_present() -> bool:
    import importlib.util
    return importlib.util.find_spec("piper") is not None


def _concat(parts: list[Path], out: Path) -> Path:
    if len(parts) == 1:
        parts[0].replace(out)
        return out
    if not skills.ffmpeg_ready():
        raise VoiceError(
            f"narration came back in {len(parts)} chunks and ffmpeg is missing, so they "
            f"cannot be joined. Install ffmpeg, or keep the script under "
            f"{MAX_CHARS} characters per call.")
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts))
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
         "-safe", "0", "-i", str(listing), "-c", "copy", str(out)],
        capture_output=True, text=True)
    listing.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise VoiceError(f"ffmpeg could not join the chunks: {proc.stderr[:400]}")
    return out


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------
def duration_of(path: Path) -> float:
    """Real duration in seconds. Zero only when nothing can measure it.

    ffprobe first, then `ffmpeg -i`, because a surprising number of machines
    ship ffmpeg without ffprobe (static builds, some Docker images, and every
    python imageio install). Parsing ffmpeg's stderr is ugly, but the
    alternative is a renderer that quietly reports an estimated length as if it
    had measured one.
    """
    path = Path(path)
    if not path.exists():
        return 0.0
    if shutil.which("ffprobe"):
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True)
        with_dot = _as_seconds(proc.stdout.strip())
        if with_dot:
            return with_dot
    if shutil.which("ffmpeg"):
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)],
                              capture_output=True, text=True)
        for line in proc.stderr.splitlines():
            if "Duration:" in line:
                stamp = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
                parsed = _as_seconds(_hms_to_seconds(stamp))
                if parsed:
                    return parsed
    return 0.0


def _hms_to_seconds(stamp: str) -> str:
    try:
        hours, minutes, seconds = stamp.split(":")
        return str(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    except (ValueError, AttributeError):
        return ""


def _as_seconds(value: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    # A nonsense duration (negative, or a stream with no timestamps) is no better
    # than no answer, so it is treated as one.
    return round(number, 2) if 0 < number < 86_400 else 0.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def narrate(text: str, out_path: str | Path, *, dry_run: bool = False) -> Narration:
    """Turn a finished script into a narration file.

    `text` must already be the spoken script: hook, beats, CTA. Do not pass
    on-screen text or captions here, they are not written to be said out loud.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = text.strip()
    if not text:
        raise VoiceError("nothing to narrate")

    prov = provider()
    voice_id = config.env("ELEVENLABS_VOICE_ID") or config.env("OPENAI_TTS_VOICE") or ""

    if prov == "elevenlabs" and not config.env("ELEVENLABS_VOICE_ID"):
        raise VoiceError(
            "ELEVENLABS_VOICE_ID is not set. Use brand/voice.md's voice, not the default "
            "library voice: a consistent voice is the difference between a channel and a "
            "pile of clips. Find the id in the ElevenLabs voice library.")
    if prov == "openai":
        voice_id = voice_id or "onyx"

    chunks = make_chunks(text)
    warnings: list[str] = []
    if prov == "elevenlabs" and not skills.ffmpeg_ready() and len(chunks) > 1:
        warnings.append(
            f"script needs {len(chunks)} TTS calls and ffmpeg is missing, so they cannot "
            f"be joined; the first chunk will be written alone.")

    if dry_run:
        plan = {"provider": prov, "voice": voice_id, "chars": len(text),
                "chunks": [{"index": c.index, "chars": len(c.text)} for c in chunks],
                "out": str(out_path)}
        (out_path.with_suffix(".plan.json")).write_text(json.dumps(plan, indent=2))
        return Narration(text, None, 0.0, prov, chunks, warnings + ["dry run, no audio"])

    made: list[Path] = []
    for chunk in chunks:
        part = out_path.with_name(f"{out_path.stem}.part{chunk.index:02d}.mp3")
        if prov == "elevenlabs":
            _elevenlabs_chunk(chunk, chunks, config.require("ELEVENLABS_VOICE_ID"), part)
        elif prov == "openai":
            _openai_chunk(chunk, voice_id, part)
        else:
            part = _local_chunk(chunk, part)
        chunk.path = part
        made.append(part)

    final = _concat(made, out_path)
    seconds = duration_of(final)
    if not seconds:
        # Fall back to the beats estimate rather than lying with 0.
        fits, estimate = skills.script_fits(text, target_seconds=10_000)
        seconds = estimate
        warnings.append("no ffprobe on this machine; duration is the beats.py estimate")
    for part in made:
        if part.exists() and part != final:
            part.unlink(missing_ok=True)
    return Narration(text, final, seconds, prov, chunks, warnings)


def transcribe(audio_path: str | Path, *, model: str = "whisper-1") -> list[dict]:
    """Word-timed transcript for captions. Local whisper first, API second.

    Returns [{"word", "start", "end"}] and raises with install instructions when
    neither path is available. Guessing timings produces captions that drift, and
    drifting captions are the most visible sign of an automated account.
    """
    path = Path(audio_path)
    if not path.exists():
        raise VoiceError(f"{path} does not exist")
    exe = shutil.which("whisper") or shutil.which("faster-whisper")
    if exe:
        out_dir = path.parent
        cmd = [exe, str(path), "--model", config.env("WHISPER_MODEL", "small"),
               "--output_format", "json", "--word_timestamps", "True",
               "--output_dir", str(out_dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        candidate = out_dir / f"{path.stem}.json"
        if proc.returncode == 0 and candidate.exists():
            payload = json.loads(candidate.read_text())
            return _words_from_whisper(payload)
        raise VoiceError(f"local whisper failed: {proc.stderr[-400:]}")

    if config.env("OPENAI_API_KEY"):
        boundary = "----igboundary7d91"
        body = _multipart(
            boundary,
            {"model": model, "response_format": "verbose_json",
             "timestamp_granularities[]": "word"},
            {"file": (path.name, path.read_bytes(), "audio/mpeg")})
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "Authorization": f"Bearer {config.require('OPENAI_API_KEY')}"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read().decode())
        return [{"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in payload.get("words", [])]

    raise VoiceError(
        "No transcriber available. Either install faster-whisper "
        "(pip install faster-whisper) or set OPENAI_API_KEY. Captions need real word "
        "timings; estimating them is how automated accounts get spotted.")


def _words_from_whisper(payload: dict) -> list[dict]:
    words = []
    for segment in payload.get("segments", []):
        for w in segment.get("words", []) or []:
            words.append({"word": w.get("word", "").strip(),
                          "start": float(w.get("start", 0)),
                          "end": float(w.get("end", 0))})
    return [w for w in words if w["word"]]


def _multipart(boundary: str, fields: dict, files: dict) -> bytes:
    lines: list[bytes] = []
    for name, value in fields.items():
        lines += [f"--{boundary}".encode(), f'Content-Disposition: form-data; name="{name}"'
                  .encode(), b"", str(value).encode()]
    for name, (filename, content, ctype) in files.items():
        lines += [f"--{boundary}".encode(),
                  f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'
                  .encode(),
                  f"Content-Type: {ctype}".encode(), b"", content]
    lines += [f"--{boundary}--".encode(), b""]
    return b"\r\n".join(lines)
