"""Build the large poem corpus for the optional GPU route: data/tang-song-poems.jsonl

第 13 章“TinyLLM 在 GPU 上完整实现”用的大语料：《全唐诗》加《全宋诗》的全部诗作（不限五言），约 1,700 万字。
文件约 90 MB，不放进仓库和网站。读者有两种方式拿到它，结果逐字节相同，校验值记在
docs/public/tinyllm/data/manifest-large.json，脚本最后都会自动核对：
  1. 直接下载（推荐）：从本仓库 GitHub Release 的附件下载 gzip 压缩包（约 30 MB）并解压，不需要 OpenCC；
  2. 本地生成：从 chinese-poetry 源数据重新清洗一遍（约 130 MB 源数据，几分钟）。

来源：chinese-poetry（MIT 许可证）固定版本 b8594f81 的《全唐诗》《全宋诗》（poet.tang.*.json、poet.song.*.json）。
处理：
  1. 正文只能由汉字和常用中文标点（，。？！；：、）组成，长度 10～400 字；带注释、缺字（□）的诗作整首丢弃；
  2. 繁体转简体（OpenCC t2s），按正文去重；
  3. 按固定随机种子打乱，“前 N 首”是稳定的子集；
  4. 按正文的 SHA-256 固定划分：约 5% 验证集、5% 测试集，其余训练集（和统一唐诗语料的规则相同）。

依赖：pip install opencc-python-reimplemented==0.1.7（繁简转换的结果依赖词典版本）；需要联网下载源数据（约 130 MB，缓存在 .cache/，可断点续传）。
用法：python scripts/prepare-tinyllm-large-corpus.py --download   # 从 GitHub Release 直接下载并核对（推荐）
      python scripts/prepare-tinyllm-large-corpus.py              # 从源数据本地生成 data/tang-song-poems.jsonl 并核对
      python scripts/prepare-tinyllm-large-corpus.py --write-manifest   # 维护者：更新 manifest-large.json
      python scripts/prepare-tinyllm-large-corpus.py --pack       # 维护者：把已核对的文件压成 data/tang-song-poems.jsonl.gz，
                                                                   # 记进 manifest，再上传到 Release（tag 见 RELEASE_TAG）
"""

from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/tang-song-poems.jsonl"
MANIFEST = ROOT / "docs/public/tinyllm/data/manifest-large.json"
CACHE = ROOT / ".cache/chinese-poetry"
COMMIT = "b8594f81a89752241442f2ce267d6f66f96704ee"
RAW = f"https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/{COMMIT}/"
SOURCES = [(f"全唐诗/poet.tang.{i}.json", "全唐诗") for i in range(0, 58000, 1000)] + \
          [(f"全唐诗/poet.song.{i}.json", "全宋诗") for i in range(0, 255000, 1000)]
ALLOWED = re.compile(r"^[一-鿿，。？！；：、]{10,400}$")
RELEASE_TAG = "tinyllm-data-v1"
RELEASE_URL = os.environ.get(
    "TINYLLM_LARGE_URL",
    f"https://github.com/lewislau86/lewislau86.github.io/releases/download/{RELEASE_TAG}/tang-song-poems.jsonl.gz")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download() -> None:
    """从 GitHub Release 下载压缩包、解压到 data/tang-song-poems.jsonl，并核对解压后的 SHA-256。"""
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["sha256"]
    if OUT.exists() and sha256_of(OUT) == expected:
        print(f"{OUT.relative_to(ROOT)} 已存在且校验通过")
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    gz = CACHE / "tang-song-poems.jsonl.gz"
    print(f"下载 {RELEASE_URL}")
    with urlopen(RELEASE_URL, timeout=300) as r, gz.open("wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".jsonl.part")
    with gzip.open(gz, "rb") as src, tmp.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    got = sha256_of(tmp)
    if got != expected:
        tmp.unlink()
        raise SystemExit(f"校验值不一致：得到 {got}，应为 {expected}。请删掉 {gz} 重新下载，或改用本地生成。")
    os.replace(tmp, OUT)
    print(f"{OUT.relative_to(ROOT)} 校验通过（{OUT.stat().st_size:,} 字节）")


def pack() -> None:
    """维护者：把已核对的大语料压成可复现的 gzip（mtime=0、不含文件名），记进 manifest，供上传到 Release。"""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not OUT.exists() or sha256_of(OUT) != manifest["sha256"]:
        raise SystemExit(f"{OUT.relative_to(ROOT)} 不存在或校验不通过，先运行本脚本生成它")
    gz = OUT.with_name(OUT.name + ".gz")
    with OUT.open("rb") as src, open(gz, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    manifest["release"] = {"tag": RELEASE_TAG, "asset": gz.name, "bytes": gz.stat().st_size, "sha256": sha256_of(gz)}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"已生成 {gz.relative_to(ROOT)}（{gz.stat().st_size:,} 字节），并写入 {MANIFEST.relative_to(ROOT)}")
    print(f"下一步：在 GitHub 上新建 Release，tag 填 {RELEASE_TAG}，把 {gz.name} 作为附件上传")


def fetch(path: str) -> list:
    CACHE.mkdir(parents=True, exist_ok=True)
    local = CACHE / path.replace("/", "_")
    if not local.exists():
        with urlopen(RAW + quote(path), timeout=120) as r:
            data = r.read()
        local.write_bytes(data)
    return json.loads(local.read_text(encoding="utf-8"))


def main() -> None:
    if "--download" in sys.argv:
        return download()
    if "--pack" in sys.argv:
        return pack()
    from opencc import OpenCC
    t2s = OpenCC("t2s").convert

    def converted(path, source):
        """清洗并繁转简一个源文件；结果缓存起来，中断后重跑不必从头转换。"""
        local = CACHE / ("s2_" + path.replace("/", "_"))
        if local.exists():
            return json.loads(local.read_text(encoding="utf-8"))
        rows = []
        for item in fetch(path):
            raw = "".join(item.get("paragraphs", []))
            if ALLOWED.match(raw):
                rows.append({"text": t2s(raw), "title": t2s(item.get("title", "")), "author": t2s(item.get("author", "")), "source": source})
        local.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return rows

    poems, seen = [], set()
    for k, (path, source) in enumerate(SOURCES):
        for p in converted(path, source):
            if p["text"] not in seen:
                seen.add(p["text"])
                poems.append(p)
        if k % 50 == 0:
            print(f"  已处理 {k + 1}/{len(SOURCES)} 个源文件，累计 {len(poems):,} 首", flush=True)
    random.Random(0).shuffle(poems)

    def split(text):
        h = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % 20
        return "val" if h == 0 else "test" if h == 1 else "train"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for i, p in enumerate(poems):
            f.write(json.dumps({"id": i, "split": split(p["text"]), **p}, ensure_ascii=False) + "\n")
    data = OUT.read_bytes()
    manifest = {
        "file": f"data/{OUT.name}", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "poems": len(poems),
        "chars": sum(len(p["text"]) for p in poems), "vocab": len(set("".join(p["text"] for p in poems))),
        "splits": {s: sum(split(p["text"]) == s for p in poems) for s in ("train", "val", "test")},
        "sources": {s: sum(p["source"] == s for p in poems) for s in ("全唐诗", "全宋诗")},
        "source": {"repo": "https://github.com/chinese-poetry/chinese-poetry", "commit": COMMIT, "license": "MIT"},
        "generator": "scripts/prepare-tinyllm-large-corpus.py",
    }
    print(json.dumps(manifest, ensure_ascii=False))
    if "--write-manifest" in sys.argv:
        old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
        if "release" in old and old.get("sha256") == manifest["sha256"]:
            manifest["release"] = old["release"]
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"已更新 {MANIFEST.relative_to(ROOT)}")
    else:
        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["sha256"]
        if manifest["sha256"] != expected:
            raise SystemExit(f"校验值不一致：得到 {manifest['sha256']}，应为 {expected}。请确认 opencc-python-reimplemented 版本，或删掉 .cache/ 重新下载。")
        print(f"{OUT.relative_to(ROOT)} 校验通过")


if __name__ == "__main__":
    main()
