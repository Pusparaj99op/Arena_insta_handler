#!/usr/bin/env python3
"""Refresh one vendored skill pack from upstream, without touching igf-*.

    python3 tools/refresh_skills.py --list
    python3 tools/refresh_skills.py remotion-dev/skills --dry-run
    python3 tools/refresh_skills.py remotion-dev/skills

Vendoring eleven packs is the right call for a repo that has to work offline and
on a fresh clone. The cost is that upstream moves, so this is the escape hatch:
it clones the pack at its latest commit, shows you a real diff against what is
committed, and only writes when you say so.

The five `igf-*` skills are never refreshed. They are this repo's own, and they
are where the account's opinions live.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".claude" / "skills"
LOCK = ROOT / "skills.lock.json"
PROTECTED = {"igf-run", "igf-dm", "igf-produce", "igf-publish", "igf-finance-content"}

# How each pack maps source folders to installed skill folders. Kept here rather
# than inferred, because two packs needed hand fixes (see SKILLS.md) and a
# refresh that silently undoes those fixes is worse than no refresh.
MAPS: dict[str, dict] = {
    "Jakeschincariol/instagram-agent-skill": {
        "glob": "skills/ig-*", "transform": None},
    "Jakeschincariol/master-skills": {
        "glob": "skills/{edit,virality,build}", "transform": None},
    "Jakeschincariol/video-production-skills": {
        "glob": "{hyperframes,hyperframes-core,hyperframes-animation,"
                "hyperframes-keyframes,hyperframes-audio,hyperframes-cli,"
                "hyperframes-creative,hyperframes-registry,general-video,"
                "talking-head-recut,product-launch-video,media-use,media-router}",
        "transform": None},
    "kajisho5/ffmpeg-skill": {
        "root": ".", "transform": "ffmpeg_flat"},
    "iamaanahmad/agents-video-editing-skills": {
        "glob": "skills/*", "transform": None},
    "remotion-dev/skills": {
        "glob": "skills/*", "transform": None},
    "DojoCodingLabs/remotion-superpowers": {
        "glob": "skills/*", "transform": None},
    "Mozahid-AIUB/MozahidFlow": {
        "glob": ".claude/skills/{color-grading,motion-broll,sound-effects}",
        "rename": {"color-grading": "motion-color-grading"},
        "transform": None},
    "JFerrerH/ai-video-editor": {
        "glob": ".claude/skills/{character-video,motion-graphics,short-form-pro}",
        "transform": "jferrer_tools"},
    "prathameshp107/video-editing": {
        "glob": ".agents/skills/*", "transform": "prathamesh_kit"},
    "notivn/AIEV": {
        "glob": ".claude/skills/{ai-illustrations,auto-cut,background-music,gsap,"
                "make-a-video,noti-tiktok-full-text,noti-tiktok-vn,"
                "noti-youtube-edit,offline-voice,remotion-assemble,"
                "short-form-video,video-pipeline}",
        "transform": "aiev_assets"},
}


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{proc.stderr[:800]}")
    return proc.stdout


def _expand(patterns: str) -> list[str]:
    import glob as _glob
    if "{" in patterns:
        # brace expansion by hand: no shell here
        import itertools
        head, _, tail = patterns.partition("{")
        options, _, rest = tail.partition("}")
        return [_glob for opt in options.split(",")
                for _glob in [head + opt + rest]]
    return [patterns]


def latest_commit(repo: str) -> str:
    out = _run(["git", "ls-remote", f"https://github.com/{repo}.git", "HEAD"])
    return out.split()[0]


def vendor(repo: str, workdir: Path) -> list[Path]:
    """Clone upstream at HEAD and stage the mapped folders into `workdir`."""
    clone = workdir / "upstream"
    _run(["git", "clone", "--depth", "1", "-q",
          f"https://github.com/{repo}.git", str(clone)])
    mapping = MAPS.get(repo)
    if not mapping:
        raise SystemExit(f"no mapping for {repo}. Add one to MAPS in this file, "
                         f"because the source layout is not guessable.")

    staged: list[Path] = []
    if mapping.get("root") == ".":
        target = workdir / Path(repo).name.split("/")[-1]
        target.mkdir(parents=True, exist_ok=True)
        for name in ("LICENSE", "README.md", "SKILL.md", "scripts", "references",
                     "templates", "mcp", "examples", "bin"):
            src = clone / name
            if not src.exists():
                continue
            dest = target / name
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
        staged.append(target)
        return staged

    for pattern in _expand(mapping.get("glob", "")):
        for src in sorted(clone.glob(pattern)):
            if not src.is_dir():
                continue
            name = mapping.get("rename", {}).get(src.name, src.name)
            dest = workdir / name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            staged.append(dest)

    transform = mapping.get("transform")
    if transform == "jferrer_tools":
        for dest in staged:
            tools = dest / "tools"
            tools.mkdir(exist_ok=True)
            for py in (clone / "tools").glob("*.py"):
                shutil.copy2(py, tools / py.name)
            tpl = dest / "templates"
            tpl.mkdir(exist_ok=True)
            for f in (clone / "templates").glob("*"):
                if f.is_file():
                    shutil.copy2(f, tpl / f.name)
    elif transform == "prathamesh_kit":
        for dest in staged:
            kit = dest / "kit"
            kit.mkdir(exist_ok=True)
            for name in ("scripts", "templates"):
                src = clone / name
                if src.exists():
                    shutil.copytree(src, kit / name, dirs_exist_ok=True)
    elif transform == "aiev_assets":
        assets = workdir / "_assets"
        if (clone / "assets").exists():
            shutil.copytree(clone / "assets", assets, dirs_exist_ok=True)
    return staged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", help="owner/repo, as it appears in skills.lock.json")
    ap.add_argument("--list", action="store_true", help="show the packs and their pins")
    ap.add_argument("--dry-run", action="store_true", help="show the diff, write nothing")
    ap.add_argument("--all", action="store_true", help="refresh every vendored pack")
    args = ap.parse_args()

    lock = json.loads(LOCK.read_text())
    if args.list or not (args.repo or args.all):
        print(f"{'pack':45s} {'pinned':14s} license")
        print("-" * 80)
        for name, meta in lock["packs"].items():
            print(f"{name:45s} {meta['commit'][:12]:14s} {meta['license']}")
        return 0

    targets = list(lock["packs"]) if args.all else [args.repo]
    for repo in targets:
        if repo not in lock["packs"]:
            raise SystemExit(f"{repo} is not a vendored pack. `--list` shows them.")
        pinned = lock["packs"][repo]["commit"]
        head = latest_commit(repo)
        if head.startswith(pinned[:12]) or pinned.startswith(head[:12]):
            print(f"{repo}: already at {pinned[:12]}, nothing to do")
            continue
        print(f"{repo}\n  pinned {pinned[:12]} -> head {head[:12]}")

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            staged = vendor(repo, work)
            for dest in staged:
                if dest.name in PROTECTED:
                    print(f"  skip {dest.name}: this repo's own skill")
                    continue
                committed = SKILLS / dest.name
                if dest.name == "_assets":
                    committed = ROOT / ".claude" / "assets"
                diff = subprocess.run(
                    ["diff", "-rq", str(committed), str(dest)],
                    capture_output=True, text=True).stdout
                added = len([l for l in diff.splitlines() if l.startswith("Only in")])
                changed = len([l for l in diff.splitlines() if l.startswith("Files")])
                print(f"  {dest.name}: {changed} changed, {added} added/removed")
                if not args.dry_run and (changed or added):
                    if committed.exists():
                        shutil.rmtree(committed)
                    shutil.copytree(dest, committed)
            if not args.dry_run:
                lock["packs"][repo]["commit"] = head
                lock["packs"][repo]["committed"] = _run(
                    ["git", "-C", str(work / "upstream"), "log", "-1",
                     "--format=%cI"]).strip()
                LOCK.write_text(json.dumps(lock, indent=2) + "\n")
                print(f"  updated, and skills.lock.json pins {head[:12]}")
            else:
                print("  dry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
