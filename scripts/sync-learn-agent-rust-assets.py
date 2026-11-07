"""Fetch or check unmodified reference figures using the recorded SHA-256.

python3 scripts/sync-learn-agent-rust-assets.py --fetch
python3 scripts/sync-learn-agent-rust-assets.py --check
The default is a local check; network downloads are explicit.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts/learn-agent-rust-upstream-assets.json"
OUT = ROOT / "docs/public/learn-agent-rust/figures/upstream"


def fetch(url):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Learn-Agent-by-Rust asset sync)"})
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.5)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fetch", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = manifest["assets"] + [manifest["license"]]
    names = [item["local_name"] for item in records]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate asset name")
    # Validate every file first, then publish; a source change must not rewrite
    # the local version or silently update the manifest's expected hash.
    pending = []
    for item in records:
        name = item["local_name"]
        if Path(name).name != name:
            raise ValueError("Asset name must be a basename")
        path = OUT / name
        if path.exists() and digest(path.read_bytes()) == item["sha256"]:
            data = path.read_bytes()
        elif args.fetch:
            data = fetch(item["source_url"])
            if digest(data) != item["sha256"]:
                raise ValueError("Source changed; review manifest before replacing: " + name)
            pending.append((path, data))
        else:
            raise ValueError("Missing or changed asset (use --fetch to restore): " + name)
        if name.endswith(".svg"):
            document = ET.fromstring(data)
            if document.tag != "{http://www.w3.org/2000/svg}svg":
                raise ValueError("Not an SVG: " + name)
    if args.fetch:
        OUT.mkdir(parents=True, exist_ok=True)
        for path, data in pending:
            path.write_bytes(data)
    attribution = ["# Learn Agent by Rust：参考原图来源", "",
                   "本文件由 scripts/sync-learn-agent-rust-assets.py 生成。原图来自 Learn Claude Code 网站，按实际文件的 SHA-256 固定快照，未修改 SVG。", "",
                   "网站采用 20 章目录，关联仓库固定快照采用 17 章目录；两者编号及图中文字分别记录。原图中的 Python/Claude 接口、工具数量和效果不代表 Rust 版已经实现或验证。", "",
                   "上游：shareAI-lab/learn-claude-code；Copyright (c) 2024 shareAI Lab；MIT。", "",
                   "许可来源：" + manifest["license"]["source_url"], "",
                   "许可固定 commit：`" + manifest["license"]["repository_commit"] + "`。完整许可保留于同目录 UPSTREAM-LICENSE.txt。网站图片以内容校验值标识版本，不宣称与许可 commit 的同名图片字节一致。", "",
                   "| 本地文件 | 原始章节 | 原图 | 日期 | SHA-256 |", "| --- | --- | --- | --- | --- |"]
    for item in manifest["assets"]:
        attribution.append("| `{}` | [{}]({}) | [source]({}) | {} | `{}` |".format(
            item["local_name"], item["lesson_id"], item["page_url"], item["source_url"], item["retrieved_on"], item["sha256"]))
    content = "\n".join(attribution) + "\n"
    attribution_path = OUT / "ATTRIBUTION.md"
    if args.fetch:
        attribution_path.write_text(content, encoding="utf-8")
    elif not attribution_path.exists() or attribution_path.read_text(encoding="utf-8") != content:
        raise ValueError("Attribution is outdated; run --fetch")
    print("{} reference figures and upstream license checked; {} file(s) restored".format(len(manifest["assets"]), len(pending)))


if __name__ == "__main__":
    main()
