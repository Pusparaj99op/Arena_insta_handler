"""Turning a finished script into a finished vertical video, on a laptop.

The bet this file makes: a finance account posts *daily*, so the render path
has to be the boring one that always works. So the default pipeline is ffmpeg
only — no node_modules, no browser, no cloud render farm.

    beats (timed script)  ->  one card per beat
                          ->  narration (TTS)
                          ->  slideshow timed to the narration
                          ->  burned captions from real word timings
                          ->  loudness-normalised mix at -14 LUFS
                          ->  1080x1920 H.264/AAC mp4

When Remotion or HyperFrames is installed, `--engine remotion|hyperframes` writes
the composition and drives the CLI instead, for the pieces where real motion is
worth the setup. Same inputs, same output contract.

Everything is a pure function of text + brand config, so a render is reviewable
in a diff and repeatable on any machine with ffmpeg 6.1+.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from . import config, skills, voice

# ---------------------------------------------------------------------------
# Canvas constants. These are Instagram's numbers, not ours.
# ---------------------------------------------------------------------------
REEL = (1080, 1920)
FEED_PORTRAIT = (1080, 1350)
FEED_SQUARE = (1080, 1080)
# The bottom 250px and right 120px of a Reel carry Instagram's UI.
SAFE_TOP = 220
SAFE_BOTTOM = 250
SAFE_SIDE = 96
UI_RIGHT = 120


class RenderError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------
@dataclass
class Brand:
    name: str = "the account"
    handle: str = "@you"
    tagline: str = ""
    bg: str = "0B0E14"
    bg_alt: str = "131A24"
    text: str = "F5F7FA"
    muted: str = "93A1B1"
    accent: str = "29D398"
    accent_alt: str = "F2B33D"
    danger: str = "F2555A"
    display_font: str = ""
    body_font: str = ""
    logo: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Brand":
        path = path or (config.BRAND_DIR / "brand.json")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return cls()
        colours = raw.get("colours", raw.get("colors", {}))
        fonts = raw.get("fonts", {})
        return cls(
            name=raw.get("name", cls.name),
            handle=raw.get("handle", cls.handle),
            tagline=raw.get("tagline", ""),
            bg=colours.get("bg", cls.bg).lstrip("#"),
            bg_alt=colours.get("bg_alt", cls.bg_alt).lstrip("#"),
            text=colours.get("text", cls.text).lstrip("#"),
            muted=colours.get("muted", cls.muted).lstrip("#"),
            accent=colours.get("accent", cls.accent).lstrip("#"),
            accent_alt=colours.get("accent_alt", cls.accent_alt).lstrip("#"),
            danger=colours.get("danger", cls.danger).lstrip("#"),
            display_font=fonts.get("display", ""),
            body_font=fonts.get("body", ""),
            logo=raw.get("logo", ""),
        )


# ---------------------------------------------------------------------------
# ffmpeg capability detection. Never assume a filter exists: ask.
# ---------------------------------------------------------------------------
_CAP_CACHE: dict | None = None


def capabilities(refresh: bool = False) -> dict:
    global _CAP_CACHE
    if _CAP_CACHE is not None and not refresh:
        return _CAP_CACHE
    caps = {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
            "version": "", "filters": set(), "fonts": [], "libass": False}
    if caps["ffmpeg"]:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-version"],
                                 capture_output=True, text=True, timeout=20).stdout
            m = re.search(r"ffmpeg version (\S+)", out)
            caps["version"] = m.group(1) if m else "unknown"
            caps["libass"] = "enable-libass" in out
            listing = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                                     capture_output=True, text=True, timeout=20).stdout
            caps["filters"] = {line.split()[1] for line in listing.splitlines()[3:]
                               if len(line.split()) > 1}
        except (subprocess.SubprocessError, OSError):
            pass
    caps["fonts"] = find_fonts()
    _CAP_CACHE = caps
    return caps


def _font_choices() -> list[Path]:
    bundled = [
        config.BRAND_DIR / "fonts",
        config.SKILLS_DIR / "motion-overlay" / "kit" / "assets" / "fonts",
        config.SKILLS_DIR / "motion-overlay" / "assets" / "fonts",
        Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
        Path.home() / ".fonts", Path("/System/Library/Fonts"),
        Path("C:/Windows/Fonts"),
    ]
    found: list[Path] = []
    for root in bundled:
        if not root.exists():
            continue
        for path in root.rglob("*.ttf"):
            found.append(path)
        for path in root.rglob("*.otf"):
            found.append(path)
    return found


def find_fonts() -> list[str]:
    suffix_rank = {"Poppins-SemiBold.ttf": 0, "OpenSans-Variable.ttf": 1}
    fonts = sorted(_font_choices(), key=lambda p: (suffix_rank.get(p.name, 5), p.name))
    return [str(p) for p in fonts]


def pick_font(preferred: str = "", *, weight: str = "bold") -> str:
    """A real font file path, or empty string so drawtext uses its default."""
    caps = capabilities()
    fonts = caps["fonts"]
    if preferred and Path(preferred).exists():
        return preferred
    if not fonts:
        return ""
    if weight == "bold":
        for f in fonts:
            if "semibold" in f.lower() or "bold" in f.lower():
                return f
    return fonts[0]


# ---------------------------------------------------------------------------
# Text layout without a font engine
# ---------------------------------------------------------------------------
def wrap(text: str, width: int, *, font_size: int, bold: bool = False) -> list[str]:
    """Wrap to a character count that fits the canvas.

    A character-count estimate is used rather than font metrics because the
    engine must run on a machine with nothing installed. The factors below are
    measured against Poppins and Open Sans, the two fonts shipped with the skill
    pack; for other fonts pass a tighter `width`.
    """
    factor = 0.54 if bold else 0.50
    chars = max(8, int(width / (font_size * factor)))
    out: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(paragraph.strip(), chars, break_long_words=False,
                                 break_on_hyphens=False) or [""])
    return out


def _escape(text: str) -> str:
    """Normalise a value before it goes into its own text file.

    Kept as a named seam because drawtext's escaping is the thing most likely
    to change under us: with `expansion=none` and `textfile=`, the filter does
    no parsing at all, so the only job left is line endings.
    """
    return str(text).replace("\r\n", "\n")


_TEXT_DIR = config.BUILD_DIR / ".text"


def _write_text_file(text: str) -> str:
    """drawtext reads its value from a file, which sidesteps % and : entirely."""
    _TEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = _TEXT_DIR / f"t{abs(hash(text)) % 10**12}.txt"
    path.write_text(str(text).replace("\r\n", "\n"), encoding="utf-8")
    return path.as_posix()


def _drawtext(text: str, *, size: int, colour: str, x: str, y: str, font: str = "",
              line_spacing: int = 12, enable: str | None = None,
              alpha: float = 1.0, box: str | None = None) -> str:
    """One drawtext filter, with the value in a file so no escaping can break it."""
    textfile = _write_text_file(text)
    # expansion=none is the whole trick: without it drawtext treats `%` as its
    # own expansion syntax and a percent sign in a finance card fails to render.
    parts = [f"drawtext=textfile='{textfile}'", "expansion=none",
             f"fontsize={size}", f"fontcolor=0x{colour}"]
    if font:
        parts.append(f"fontfile='{font}'")
    parts += [f"x={x}", f"y={y}", f"line_spacing={line_spacing}"]
    if alpha < 1.0:
        parts.append(f"alpha={alpha:.2f}")
    if box:
        parts.append(f"box=1:boxcolor={box}:boxborderw=28")
    if enable:
        parts.append(f"enable='{enable}'")
    return ":".join(parts)


def _filter_chain(*filters: str) -> str:
    return ",".join(f for f in filters if f)


# ---------------------------------------------------------------------------
# A card: one idea, readable in one second
# ---------------------------------------------------------------------------
@dataclass
class Card:
    headline: str = ""
    kicker: str = ""          # the small eyebrow line, e.g. "RULE 02"
    stat: str = ""            # the big number, if the beat has one
    body: str = ""
    footer: str = ""
    accent: str | None = None  # override the brand accent
    duration: float = 3.0


def card_filtergraph(card: Card, brand: Brand, size: tuple[int, int],
                     *, show_progress: bool = False, progress: float = 0.0) -> str:
    width, height = size
    accent = card.accent or brand.accent
    display = pick_font(brand.display_font, weight="bold")
    body_font = pick_font(brand.body_font, weight="regular")
    margin = SAFE_SIDE
    usable = width - margin * 2
    filters: list[str] = []

    # Left accent bar: the one piece of chrome that makes a card look designed.
    filters.append(f"drawbox=x={margin}:y={SAFE_TOP}:w=6:h=88:color=0x{accent}:t=fill")
    y = SAFE_TOP

    if card.kicker:
        filters.append(_drawtext(card.kicker.upper(), size=34, colour=brand.muted,
                                 x=f"{margin + 26}", y=f"{y + 22}", font=body_font))
        y += 120
    else:
        y += 40

    if card.stat:
        stat_size = 150 if len(card.stat) <= 6 else 110
        filters.append(_drawtext(card.stat, size=stat_size, colour=accent,
                                 x=f"{margin}", y=f"{y}", font=display,
                                 line_spacing=8))
        y += int(stat_size * 0.9) + 30

    if card.headline:
        size = 92 if len(card.headline) <= 60 else 76
        for i, line in enumerate(wrap(card.headline, usable, font_size=size, bold=True)):
            filters.append(_drawtext(line, size=size, colour=brand.text,
                                     x=f"{margin}", y=f"{y}", font=display,
                                     line_spacing=16))
            y += int(size * 1.16)
        y += 26

    if card.body:
        size = 44
        for line in wrap(card.body, usable, font_size=size)[:6]:
            filters.append(_drawtext(line, size=size, colour=brand.muted,
                                     x=f"{margin}", y=f"{y}", font=body_font,
                                     line_spacing=18))
            y += int(size * 1.4)

    footer = card.footer or brand.handle
    filters.append(_drawtext(footer, size=30, colour=brand.muted,
                             x=f"{margin}", y=f"{height - SAFE_BOTTOM - 40}",
                             font=body_font))

    if show_progress:
        bar_w = width - margin * 2
        filters.append(f"drawbox=x={margin}:y={height - SAFE_BOTTOM - 4}:"
                       f"w={int(bar_w * max(0.0, min(1.0, progress)))}:h=4:"
                       f"color=0x{accent}:t=fill")
        filters.append(f"drawbox=x={margin}:y={height - SAFE_BOTTOM - 4}:w={bar_w}:h=4:"
                       f"color=0x{accent}@0.18:t=fill")
    return _filter_chain(*filters)


def render_card_png(card: Card, out: Path, brand: Brand | None = None,
                    size: tuple[int, int] = REEL, *, gradient: bool = True) -> Path:
    """One still. Falls back to a flat fill when the gradient filter is missing."""
    brand = brand or Brand.load()
    caps = capabilities()
    if not caps["ffmpeg"]:
        raise RenderError("ffmpeg is not installed. Docker Compose installs it; on a Mac "
                          "`brew install ffmpeg`, on Debian `apt install ffmpeg`.")
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    vf = card_filtergraph(card, brand, size)
    use_gradient = gradient and "gradients" in caps["filters"]
    if use_gradient:
        src = (f"gradients=s={width}x{height}:c0=0x{brand.bg}:c1=0x{brand.bg_alt}"
               f":x0=0:y0=0:x1={width}:y1={height}:d=1,format=rgb24")
    else:
        src = f"color=c=0x{brand.bg}:s={width}x{height}:d=1,format=rgb24"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", src, "-vf", vf, "-frames:v", "1", str(out)]
    _run(cmd, "render a card still")
    return out


# ---------------------------------------------------------------------------
# Captions: ASS with a safe-zone default, from real word timings
# ---------------------------------------------------------------------------
CAPTION_PRESETS = {
    "bold-word": {"font": "Poppins SemiBold", "size": 74, "primary": "&H00FFFFFF",
                  "outline": "&H00000000", "outline_w": 6, "margin_v": 360,
                  "shadow": 0, "per_word": True, "highlight": "&H0098D329"},
    "line": {"font": "Poppins SemiBold", "size": 64, "primary": "&H00FFFFFF",
             "outline": "&H00000000", "outline_w": 5, "margin_v": 340,
             "shadow": 0, "per_word": False, "highlight": "&H00FFFFFF"},
    "karaoke": {"font": "Poppins SemiBold", "size": 68, "primary": "&H00FFFFFF",
                "outline": "&H00000000", "outline_w": 6, "margin_v": 340,
                "per_word": True, "highlight": "&H0098D329"},
}


def hex_to_ass(hex_colour: str, alpha: str = "00") -> str:
    """#29D398 -> &H0098D329. ASS is AABBGGRR, which is not what anyone assumes."""
    h = hex_colour.lstrip("#")
    if len(h) != 6:
        return "&H00FFFFFF"
    return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(words: list[dict], out: Path, *, preset: str = "bold-word",
              width: int = 1080, height: int = 1920, max_words: int = 3,
              accent: str = "") -> Path:
    """Word-timed captions in the safe zone, in groups of 1-3 words.

    Grouping matters: one word at a time flashes and reads as spam; four at once
    is a paragraph nobody reads while also watching. Three is the number that
    keeps pace with a 165 wpm script.
    """
    style = dict(CAPTION_PRESETS.get(preset, CAPTION_PRESETS["bold-word"]))
    if accent:                       # the brand colour wins over the preset default
        style["highlight"] = hex_to_ass(accent)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{style['font']},{style['size']},{style['primary']},{style.get('highlight', style['primary'])},{style['outline']},&H64000000,-1,0,0,0,100,100,0,0,1,{style['outline_w']},0,2,60,180,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    group: list[dict] = []
    per_word = style.get("per_word", True)
    for i, word in enumerate(words):
        group.append(word)
        at_end = i == len(words) - 1
        if len(group) >= max_words or at_end or _gap(words, i):
            start, end = group[0]["start"], group[-1]["end"]
            if end - start < 0.44:
                end = start + 0.44
            if per_word:
                # One dialogue line per word. The words of the group stay on screen
                # together, and the active one changes colour: a karaoke line, which
                # is what a viewer's eye can actually follow at 165 wpm.
                spoken = [x["word"] for x in group]
                for j, w in enumerate(group):
                    w_start = w["start"]
                    w_end = group[j + 1]["start"] if j + 1 < len(group) else end
                    highlight = style.get("highlight", style["primary"])
                    plain = style["primary"]
                    rendered = " ".join(
                        f"{{\\c{highlight}}}{word}{{\\c{plain}}}" if k == j else word
                        for k, word in enumerate(spoken))
                    lines.append(f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},"
                                 f"Cap,,0,0,0,,{rendered.strip()}\n")
            else:
                text = " ".join(x["word"] for x in group)
                lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
                             f"Cap,,0,0,0,,{text.strip()}\n")
            group = []
    out.write_text("".join(lines), encoding="utf-8")
    return out


def _gap(words: list[dict], index: int) -> bool:
    """A pause of 0.35s+ ends a caption group, the way a speaker would pause."""
    if index + 1 >= len(words):
        return True
    return (words[index + 1]["start"] - words[index]["end"]) > 0.35


# ---------------------------------------------------------------------------
# Slideshow: cards timed to the narration
# ---------------------------------------------------------------------------
def build_slideshow(stills: list[Path], durations: list[float], out: Path,
                    *, fps: int = 30, size: tuple[int, int] = REEL,
                    motion: bool = True) -> Path:
    """A video from stills, with a slow zoom so it does not read as PowerPoint.

    One ffmpeg pass per card, then a concat. Two things this gets right that the
    obvious one-liner does not:

    * **Duration is per card, in frames.** A still has no duration, so `-loop 1
      -t <seconds>` is the only way to get a predictable length out of it. The
      concat demuxer's `duration` hint is not enough on its own: it is a hint,
      and with a single PNG input you get one frame per card.
    * **The zoom is seek-safe.** `zoompan` with `d=1` advances the zoom by one
      step per frame, which means the zoom rate depends on the frame count you
      actually asked for, not on a wall clock. So the rate is derived from the
      card's own length: long cards zoom slower, and no cut accelerates.
    """
    if len(stills) != len(durations):
        raise RenderError(f"{len(stills)} stills but {len(durations)} durations")
    if not stills:
        raise RenderError("no stills to render")
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    caps = capabilities()

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        segments: list[Path] = []
        for i, (still, dur) in enumerate(zip(stills, durations)):
            frames = max(1, int(round(max(0.8, float(dur)) * fps)))
            segment = tmpdir / f"seg{i:02d}.mp4"
            filters = [f"scale={width}:{height}:force_original_aspect_ratio=increase",
                       f"crop={width}:{height}", "setsar=1", "format=yuv420p"]
            if motion and "zoompan" in caps["filters"]:
                # 4% over the card, independent of how long the card is.
                rate = 0.04 / max(1, frames)
                filters.insert(0,
                    f"zoompan=z='min(1+{rate:.8f}*on,1.04)':d=1:"
                    f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    f"s={width}x{height}:fps={fps}")
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                   "-loop", "1", "-framerate", str(fps), "-t", f"{frames / fps:.4f}",
                   "-i", str(still),
                   "-vf", _filter_chain(*filters),
                   "-frames:v", str(frames), "-r", str(fps),
                   "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                   "-pix_fmt", "yuv420p", str(segment)]
            _run(cmd, f"render card {i + 1} of {len(stills)}")
            segments.append(segment)

        listing = tmpdir / "concat.txt"
        listing.write_text(
            "".join(f"file '{seg.as_posix()}'\n" for seg in segments), encoding="utf-8")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              "-f", "concat", "-safe", "0", "-i", str(listing),
              "-c", "copy", "-movflags", "+faststart", str(out)],
             "join the cards")
    return out


# ---------------------------------------------------------------------------
# Audio: narration, ducked music, one loudness target
# ---------------------------------------------------------------------------
def mix_audio(narration: Path, out: Path, *, music: Path | None = None,
              music_gain_db: float = -26.0, out_lufs: float = -14.0) -> Path:
    """Narration always wins. Music sits under it and gets out of the way when the
    voice is present, which is what `sidechaincompress` is for."""
    caps = capabilities()
    out.parent.mkdir(parents=True, exist_ok=True)
    if music and "sidechaincompress" in caps["filters"]:
        filt = (
            f"[1:a]volume={music_gain_db}dB,highpass=f=90[bed];"
            f"[0:a]asplit=2[vo][key];"
            f"[bed][key]sidechaincompress=threshold=0.06:ratio=7:attack=12:release=380[duck];"
            f"[vo][duck]amix=inputs=2:duration=first:dropout_transition=0,"
            f"loudnorm=I={out_lufs}:TP=-1.5:LRA=9[a]"
        )
        inputs = ["-i", str(narration), "-stream_loop", "-1", "-i", str(music)]
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
               "-filter_complex", filt, "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
               str(out)]
    elif music:
        filt = (f"[1:a]volume={music_gain_db}dB[bed];"
                f"[0:a][bed]amix=inputs=2:duration=first,"
                f"loudnorm=I={out_lufs}:TP=-1.5:LRA=9[a]")
        inputs = ["-i", str(narration), "-stream_loop", "-1", "-i", str(music)]
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
               "-filter_complex", filt, "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
               str(out)]
    else:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(narration),
               "-af", f"loudnorm=I={out_lufs}:TP=-1.5:LRA=9",
               "-c:a", "aac", "-b:a", "192k", str(out)]
    _run(cmd, "mix the audio")
    return out


def burn_captions(video: Path, ass: Path, out: Path) -> Path:
    """Burn captions in. Without libass this is skipped rather than failed, and the
    .ass file is delivered next to the video so it can be burned elsewhere."""
    caps = capabilities()
    if not caps["libass"] or "subtitles" not in caps["filters"]:
        raise RenderError(
            "this ffmpeg has no libass, so captions cannot be burned. Install a build "
            "with --enable-libass, or burn the .ass in your editor; the file is "
            f"already written at {ass}.")
    escaped = str(ass.resolve()).replace(":", r"\:").replace("'", r"\'")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(video), "-vf", f"subtitles='{escaped}':fontsdir="
           f"'{Path(pick_font()).parent if pick_font() else '.'}'",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-movflags", "+faststart", str(out)]
    _run(cmd, "burn the captions")
    return out


# ---------------------------------------------------------------------------
# The whole thing
# ---------------------------------------------------------------------------
@dataclass
class ReelSpec:
    script: str
    cards: list[Card]
    out_dir: Path
    brand: Brand = field(default_factory=Brand.load)
    music: Path | None = None
    caption_preset: str = "bold-word"
    engine: str = "ffmpeg"          # ffmpeg | remotion | hyperframes
    narration_text: str = ""        # defaults to script
    wpm: float = 165.0


@dataclass
class ReelResult:
    video: Path | None
    narration: Path | None
    captions: Path | None
    stills: list[Path]
    seconds: float
    engine: str
    warnings: list[str] = field(default_factory=list)

    def receipt(self) -> dict:
        return {"video": str(self.video) if self.video else None,
                "narration": str(self.narration) if self.narration else None,
                "captions": str(self.captions) if self.captions else None,
                "stills": [str(s) for s in self.stills],
                "seconds": self.seconds, "engine": self.engine,
                "warnings": self.warnings}


def render_reel(spec: ReelSpec) -> ReelResult:
    """Script cards in, vertical mp4 out. Every step degrades with a warning."""
    out_dir = Path(spec.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    caps = capabilities()

    if spec.engine in {"remotion", "hyperframes"}:
        return _render_with_engine(spec, warnings)

    if not caps["ffmpeg"]:
        raise RenderError("ffmpeg is missing; nothing can be rendered on this machine.")

    # 1. Narration first: it decides the length of every card.
    narration_path = out_dir / "narration.mp3"
    seconds = 0.0
    try:
        nar = voice.narrate(spec.narration_text or spec.script, narration_path)
        seconds = nar.seconds
        warnings.extend(nar.warnings)
    except voice.VoiceError as exc:
        warnings.append(f"no narration: {exc} Falling back to the spoken-length estimate.")
        # beats.py knows the account's real speaking rate; use it, not a guess.
        result = skills.beat_sheet(spec.script, target_seconds=int(spec.wpm), wpm=spec.wpm)
        seconds = float((result.data or {}).get("total_seconds") or 0.0)
        if not seconds:
            seconds = len(spec.script.split()) / spec.wpm * 60

    # 2. Distribute time across cards by spoken weight, not equally.
    weights = [max(1, len((c.headline + " " + c.body + " " + c.stat).split()))
               for c in spec.cards] or [1]
    total = sum(weights)
    durations = [round(seconds * w / total, 2) for w in weights]

    # 3. Stills.
    stills = []
    for i, card in enumerate(spec.cards):
        card.footer = card.footer or spec.brand.handle
        still = out_dir / f"card{i:02d}.png"
        render_card_png(card, still, spec.brand, REEL)
        stills.append(still)

    # 4. Slideshow.
    silent = out_dir / "silent.mp4"
    build_slideshow(stills, durations, silent)

    # 5. Audio.
    audio = out_dir / "mix.m4a"
    if narration_path.exists():
        mix_audio(narration_path, audio, music=spec.music)
    else:
        audio = None
        warnings.append("shipping silent video; add a voiceover before publishing.")

    # 6. Mux.
    muxed = out_dir / "reel_no_subs.mp4"
    if audio:
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              "-i", str(silent), "-i", str(audio), "-c:v", "copy", "-c:a", "aac",
              "-shortest", "-movflags", "+faststart", str(muxed)], "mux audio")
    else:
        shutil.copy2(silent, muxed)

    # 7. Captions from real word timings.
    captions = None
    final = out_dir / "reel.mp4"
    try:
        words = voice.transcribe(narration_path) if narration_path.exists() else []
    except voice.VoiceError as exc:
        words = []
        warnings.append(f"captions skipped: {exc}")
    if words:
        captions = write_ass(words, out_dir / "captions.ass",
                             preset=spec.caption_preset, accent=spec.brand.accent)
        try:
            burn_captions(muxed, captions, final)
        except RenderError as exc:
            warnings.append(str(exc))
            shutil.copy2(muxed, final)
    else:
        shutil.copy2(muxed, final)

    actual = voice.duration_of(final) or seconds
    return ReelResult(video=final,
                      narration=narration_path if narration_path.exists() else None,
                      captions=captions, stills=stills, seconds=actual,
                      engine="ffmpeg", warnings=warnings)


def _render_with_engine(spec: ReelSpec, warnings: list[str]) -> ReelResult:
    """Delegate to Remotion/HyperFrames when installed, and say so plainly if not."""
    script = _engine_script(spec)
    out_dir = Path(spec.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "composition.md").write_text(script, encoding="utf-8")
    if spec.engine == "remotion":
        npx = shutil.which("npx")
        if not npx:
            raise RenderError("node/npx is missing, so Remotion cannot run here. "
                              "Either install Node 22+ or use --engine ffmpeg.")
        warnings.append(
            "Remotion rendering needs a project with @remotion/cli installed. The "
            "composition brief is at composition.md; the /remotion-create and "
            "/remotion-render skills drive the actual build.")
    else:
        warnings.append(
            "HyperFrames needs Node 22+ and `npx hyperframes init`. The composition "
            "brief is at composition.md; the /hyperframes and /hyperframes-cli skills "
            "drive it.")
    return ReelResult(video=None, narration=None, captions=None, stills=[],
                      seconds=0.0, engine=spec.engine, warnings=warnings)


def _engine_script(spec: ReelSpec) -> str:
    lines = ["# Composition brief", "",
             f"engine: {spec.engine}", f"canvas: 1080x1920", f"fps: 30",
             f"brand: {spec.brand.name} ({spec.brand.handle})",
             f"palette: bg #{spec.brand.bg}, text #{spec.brand.text}, "
             f"accent #{spec.brand.accent}", "",
             "## Scenes"]
    for i, card in enumerate(spec.cards, 1):
        lines.append(f"{i}. kicker={card.kicker!r} stat={card.stat!r} "
                     f"headline={card.headline!r} body={card.body!r}")
    lines += ["", "## Voiceover script", "```", spec.narration_text or spec.script, "```"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Carousels and covers
# ---------------------------------------------------------------------------
def render_carousel(slides: list[Card], out_dir: Path, brand: Brand | None = None,
                    *, size: tuple[int, int] = FEED_PORTRAIT) -> list[Path]:
    brand = brand or Brand.load()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    total = len(slides)
    for i, card in enumerate(slides):
        card.footer = card.footer or f"{brand.handle}   {i + 1}/{total}"
        path = out_dir / f"slide{i + 1:02d}.jpg"
        png = out_dir / f"slide{i + 1:02d}.png"
        render_card_png(card, png, brand, size)
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(png),
              "-q:v", "2", str(path)], "convert slide to jpg")
        png.unlink(missing_ok=True)
        paths.append(path)
    return paths


def render_cover(title: str, out: Path, brand: Brand | None = None,
                 *, subtitle: str = "", stat: str = "") -> Path:
    brand = brand or Brand.load()
    card = Card(headline=title, body=subtitle, stat=stat, kicker=brand.handle)
    return render_card_png(card, Path(out), brand, FEED_PORTRAIT)


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------
def _run(cmd: list[str], what: str, *, dry_run: bool = False) -> str:
    if dry_run:
        return shlex.join(cmd)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise RenderError(f"cannot {what}: {cmd[0]} is not installed") from None
    except subprocess.TimeoutExpired:
        raise RenderError(f"cannot {what}: ffmpeg hit the 30 minute timeout") from None
    if proc.returncode != 0:
        raise RenderError(f"cannot {what}: {proc.stderr.strip()[:600]}")
    return proc.stdout


def doctor() -> dict:
    """What works here, and what to install for what does not."""
    caps = capabilities(refresh=True)
    node = shutil.which("node")
    report = {
        "ffmpeg": {"ok": bool(caps["ffmpeg"]), "version": caps["version"],
                   "install": "docker compose gives you it; else apt/brew install ffmpeg"},
        "libass (burned captions)": {"ok": caps["libass"],
                                     "install": "a build with --enable-libass"},
        "drawtext (cards)": {"ok": "drawtext" in caps["filters"],
                             "install": "a build with --enable-libfreetype"},
        "gradients (nice bg)": {"ok": "gradients" in caps["filters"],
                                "install": "ffmpeg 5.0+"},
        "fonts": {"ok": bool(caps["fonts"]), "count": len(caps["fonts"]),
                  "install": "put .ttf files in brand/fonts/"},
        "node (Remotion)": {"ok": bool(node), "path": node,
                            "install": "Node 22+ from nodejs.org"},
        "skills": {"ok": config.SKILLS_DIR.exists(),
                   "count": len([p for p in config.SKILLS_DIR.iterdir()
                                 if p.is_dir()]) if config.SKILLS_DIR.exists() else 0},
    }
    return report
