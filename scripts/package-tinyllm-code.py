"""Pack all TinyLLM chapter code into docs/public/tinyllm/tinyllm-code.zip.

The archive is what readers download from https://lewislau86.github.io/tinyllm/setup :

    tinyllm-code/
      README.md            (docs/public/tinyllm/code/README.md)
      requirements.txt     (docs/public/tinyllm/requirements.txt)
      code/<chapter>.py    (docs/public/tinyllm/code/*.py)
      notebooks/<chapter>.ipynb
      data/                (docs/public/tinyllm/data/：统一唐诗语料及说明)

File order, timestamps and line endings (LF) are fixed, so the zip only changes when its content changes.
scripts/build-tinyllm-code.py calls this after regenerating notebooks, and
scripts/check-tinyllm-outputs.py checks that the committed zip is up to date.

Usage: python scripts/package-tinyllm-code.py
"""

from pathlib import Path
import io
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/public/tinyllm"
TARGET = PUBLIC / "tinyllm-code.zip"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def members() -> list[tuple[str, Path]]:
    files = [("tinyllm-code/README.md", PUBLIC / "code/README.md"),
             ("tinyllm-code/requirements.txt", PUBLIC / "requirements.txt")]
    files += [(f"tinyllm-code/code/{p.name}", p) for p in sorted((PUBLIC / "code").glob("*.py"))]
    files += [(f"tinyllm-code/notebooks/{p.name}", p) for p in sorted((PUBLIC / "notebooks").glob("*.ipynb"))]
    files += [(f"tinyllm-code/data/{p.name}", p) for p in sorted((PUBLIC / "data").iterdir()) if p.is_file()]
    return files


def content(path: Path) -> bytes:
    """统一用 LF 换行：Windows 上 git 可能把文件检出成 CRLF，zip 的内容不应随检出方式变化。"""
    return path.read_bytes().replace(b"\r\n", b"\n")


def build() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, path in members():
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, content(path))
    return buf.getvalue()


def main() -> None:
    data = build()
    if TARGET.exists() and TARGET.read_bytes() == data:   # 内容没变就不重写，避免无意义的提交
        print(f"[zip] {TARGET.relative_to(ROOT)} 已是最新")
        return
    TARGET.write_bytes(data)
    print(f"[zip] {TARGET.relative_to(ROOT)}（{len(members())} 个文件，{len(data) / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
