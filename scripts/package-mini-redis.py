"""Rebuild the mini-redis study package (ZIP) from the published source snapshot.

Run from any directory: python scripts/package-mini-redis.py
Input:  docs/public/mini-redis/source/   (mini-redis source code, tests, examples, docs/labs)
Output: docs/public/mini-redis/mini-redis-study.zip

The tutorial itself lives on the website (docs/mini-redis/); the package only carries
code and the runnable labs, so the two never drift apart. Timestamps are fixed so that
rebuilding without content changes produces an identical file.
"""

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/public/mini-redis/source"
TARGET = ROOT / "docs/public/mini-redis/mini-redis-study.zip"
SKIP_DIRS = {"target", ".git"}

files = sorted(p for p in SOURCE.rglob("*")
               if p.is_file() and not SKIP_DIRS & set(p.relative_to(SOURCE).parts))
assert (SOURCE / "Cargo.toml").exists() and (SOURCE / "docs/labs/Cargo.toml").exists(), "snapshot incomplete"

with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        info = zipfile.ZipInfo("mini-redis-study/" + path.relative_to(SOURCE).as_posix(), (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, path.read_bytes())

print(f"Packed {len(files)} files into {TARGET.relative_to(ROOT)}")
