"""Fetch the pinned ADK-Rust source used by Learn Agent by Rust (ADK-Rust 3.0 chapters).

ADK-Rust 3.0 is not on crates.io yet. Every migrated chapter ships `.cargo/config.toml`
with path patches to `../adk-rust/<crate>`, so the source must sit next to the chapter
directory (for the whole-book bundle: `chapters/adk-rust`). The revision comes from
`scripts/learn-agent-rust-adk.json`.

Usage:
    python3 scripts/fetch-adk-rust.py DEST            # DEST/ becomes the adk-rust checkout
    python3 scripts/fetch-adk-rust.py DEST --check    # verify an existing checkout
    python3 scripts/fetch-adk-rust.py DEST --method cdn

Methods:
    git (default)  shallow fetch of exactly the pinned commit (needs git and GitHub access)
    cdn            per-file download from jsDelivr using the GitHub tree API; skips docs/,
                   examples/, tests/ and benches/, which builds do not need. Slower, resumable:
                   rerun until it reports 0 missing files.
"""

import argparse
import concurrent.futures as futures
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 在网站仓库里读 scripts/learn-agent-rust-adk.json；章节下载包把这两个文件一起放在章节目录里
BASELINE_FILE = next(p for p in (HERE / "learn-agent-rust-adk.json",
                                 HERE.parent / "scripts/learn-agent-rust-adk.json") if p.exists())
BASELINE = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
REV = BASELINE["rev"]
REPO = BASELINE["repository"]
TREE_URL = f"https://api.github.com/repos/zavora-ai/adk-rust/git/trees/{REV}?recursive=1"
CDN = f"https://cdn.jsdelivr.net/gh/zavora-ai/adk-rust@{REV}/"
SKIP_TOP = {"docs", "examples", ".github", "assets", "changelog.d"}
SKIP_SEGMENTS = ("/tests/", "/benches/", "/examples/", "/fuzz/")


def needed(path: str) -> bool:
    return path.split("/")[0] not in SKIP_TOP and not any(s in path for s in SKIP_SEGMENTS)


def tree(dest: Path):
    cache = dest / ".adk-tree.json"
    if not cache.exists():
        dest.mkdir(parents=True, exist_ok=True)
        data = urllib.request.urlopen(TREE_URL, timeout=120).read()
        cache.write_bytes(data)
    body = json.loads(cache.read_text())
    if body.get("truncated") or body.get("sha") != REV:
        raise SystemExit("GitHub tree listing is truncated or for another revision")
    return [e for e in body["tree"] if e["type"] == "blob" and needed(e["path"])]


def missing(dest: Path, entries):
    return [e for e in entries
            if not (dest / e["path"]).is_file() or (dest / e["path"]).stat().st_size != e["size"]]


def via_cdn(dest: Path, budget: float):
    entries = tree(dest)
    todo = missing(dest, entries)
    print(f"{len(entries)} files needed, {len(todo)} missing", flush=True)
    deadline = time.time() + budget

    def get(entry):
        if time.time() > deadline:
            return "deferred"
        target = dest / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = urllib.request.urlopen(CDN + entry["path"], timeout=30).read()
        except Exception as error:  # transient 403/timeouts: the next run retries
            return f"failed {entry['path']}: {error}"
        if len(data) != entry["size"]:
            return f"failed {entry['path']}: size {len(data)} != {entry['size']}"
        target.write_bytes(data)
        return "ok"

    counts = {}
    with futures.ThreadPoolExecutor(10) as pool:
        for result in pool.map(get, todo):
            key = result.split()[0]
            counts[key] = counts.get(key, 0) + 1
    left = len(missing(dest, entries))
    print(f"downloaded {counts.get('ok', 0)}, failed {counts.get('failed', 0)}, "
          f"deferred {counts.get('deferred', 0)}; {left} still missing")
    return left


def via_git(dest: Path):
    if not (dest / ".git").exists():
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
        subprocess.run(["git", "remote", "add", "origin", REPO + ".git"], cwd=dest, check=True)
    subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", REV], cwd=dest, check=True)
    subprocess.run(["git", "checkout", "-q", "--detach", REV], cwd=dest, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, check=True,
                          capture_output=True, text=True).stdout.strip()
    if head != REV:
        raise SystemExit(f"checked out {head}, expected {REV}")
    print(f"adk-rust {REV[:12]} checked out in {dest}")
    return 0


def check(dest: Path):
    if (dest / ".git").exists():
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True,
                              text=True).stdout.strip()
        if head != REV:
            raise SystemExit(f"{dest} is at {head or 'unknown'}, expected {REV}")
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=dest,
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            raise SystemExit(f"{dest} has local changes:\n{dirty}")
        print(f"ok: git checkout at {REV[:12]}")
        return 0
    left = missing(dest, tree(dest))
    if left:
        raise SystemExit(f"{len(left)} files missing or wrong size, e.g. {left[0]['path']}")
    print(f"ok: all files present for {REV[:12]}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--method", choices=["git", "cdn"], default="git")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--budget", type=float, default=140.0, help="cdn: seconds to spend per run")
    args = parser.parse_args()
    dest = args.dest.resolve()
    if args.check:
        sys.exit(check(dest))
    sys.exit(via_git(dest) if args.method == "git" else (1 if via_cdn(dest, args.budget) else 0))


if __name__ == "__main__":
    main()
