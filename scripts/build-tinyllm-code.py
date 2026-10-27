"""Run every TinyLLM chapter script and rebuild its notebook.

Each chapter's code lives in exactly one file: docs/public/tinyllm/code/<chapter>.py.
- The chapter Markdown shows excerpts with VitePress snippet imports, e.g.
  <<< @/public/tinyllm/code/first-run.py#model
  which read the `# region model` ... `# endregion model` block of that file.
- The notebook docs/public/tinyllm/notebooks/<chapter>.ipynb is generated from the same
  file: `# %%` starts a code cell, `# %% [markdown]` a Markdown cell. Region marker lines
  are dropped from the notebook.

Usage (needs torch, nbformat, nbclient, ipykernel):
  python scripts/build-tinyllm-code.py              # run all scripts, rebuild all notebooks
  python scripts/build-tinyllm-code.py first-run    # only some chapters
  python scripts/build-tinyllm-code.py --check      # only run the scripts, write nothing
  python scripts/build-tinyllm-code.py --pages      # only re-render the in-site notebook viewer pages

Each notebook also gets a read-only viewer page docs/tinyllm/notebooks/<chapter>.md (code cells,
saved outputs, links to Colab / download / GitHub), served at /tinyllm/notebooks/<chapter>.

Outputs a script writes to its working directory are discarded, except the files listed in
ARTIFACTS, which are copied to where the figure scripts expect them.
"""

from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "docs/public/tinyllm/code"
NOTEBOOKS = ROOT / "docs/public/tinyllm/notebooks"
REGION = re.compile(r"^# ?(end)?region [\w*-]+$")
# 脚本运行后需要保留的产物：(章节, 文件名) → 目标路径
ARTIFACTS = {("first-run", "first_run_log.json"): ROOT / "scripts/data/tinyllm-first-run-log.json"}


def run_script(path: Path, workdir: Path) -> None:
    print(f"[run] {path.name}")
    result = subprocess.run([sys.executable, str(path)], cwd=workdir, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-4000:])
        raise SystemExit(f"{path.name} failed")
    for line in result.stdout.strip().splitlines()[-3:]:
        print("      " + line)


def to_notebook(path: Path, workdir: Path, target: Path) -> None:
    import nbformat
    from nbclient import NotebookClient

    source = path.read_text(encoding="utf-8")
    source = "\n".join(line for line in source.splitlines() if not REGION.match(line.strip()))
    cells = []
    for chunk in re.split(r"^# %%", source, flags=re.M)[1:]:
        if chunk.startswith(" [markdown]"):
            body = chunk[len(" [markdown]"):].strip("\n")
            md = "\n".join(l[2:] if l.startswith("# ") else l.lstrip("#") for l in body.splitlines())
            cells.append(nbformat.v4.new_markdown_cell(md.strip()))
        else:
            cells.append(nbformat.v4.new_code_cell(chunk.strip("\n")))
    nb = nbformat.v4.new_notebook(cells=cells)
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.metadata["language_info"] = {"name": "python"}
    NotebookClient(nb, timeout=1200, kernel_name="python3", resources={"metadata": {"path": str(workdir)}}).execute()
    nbformat.write(nb, target)
    print(f"[ipynb] {target.relative_to(ROOT)}")


PAGES = ROOT / "docs/tinyllm/notebooks"
REPO = "https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks"
COLAB = "https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _text(value) -> str:
    return "".join(value) if isinstance(value, list) else (value or "")


def _fence(body: str, lang: str = "text") -> str:
    body = body.rstrip("\n")
    lines = body.splitlines()
    if len(lines) > 200:  # 很长的输出只保留开头，完整内容在 notebook 里
        body = "\n".join(lines[:200] + [f"…（共 {len(lines)} 行，其余见 notebook）"])
    fence = "````" if "```" in body else "```"
    return f"{fence}{lang}\n{body}\n{fence}"


def render_page(nb_path: Path) -> None:
    """把一个 .ipynb 渲染成站内可浏览的页面 docs/tinyllm/notebooks/<章节>.md。"""
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    slug = nb_path.stem
    has_py = (CODE / f"{slug}.py").exists()
    title = slug + ".ipynb"
    for cell in nb["cells"]:
        if cell["cell_type"] == "markdown":
            m = re.search(r"^# (.+)$", _text(cell["source"]), re.M)
            if m:
                title = m.group(1).strip()
            break
    executed = any(cell.get("outputs") for cell in nb["cells"] if cell["cell_type"] == "code")
    parts = [
        "---",
        f'title: "{title}（notebook 在线查看）"',
        "search: false",
        "editLink: false",
        "prev: false",
        "next: false",
        "pageClass: tinyllm-course",
        "---",
        "",
        "<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->",
        "",
        "::: tip 这是 notebook 的只读预览",
        f"[返回教案](/tinyllm/{slug}) · [在 Colab 中运行]({COLAB}/{slug}.ipynb) · "
        f'<a href="/tinyllm/notebooks/{slug}.ipynb" download>下载 .ipynb</a>'
        + (f' · <a href="/tinyllm/code/{slug}.py" download>下载 .py</a>' if has_py else "")
        + f" · [在 GitHub 上查看]({REPO}/{slug}.ipynb)",
        "",
        "下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。"
        + ("" if executed else "这份 notebook 没有保存运行输出，运行后才能看到结果。"),
        ":::",
        "",
    ]
    n_code = 0
    for cell in nb["cells"]:
        src = _text(cell["source"]).strip("\n")
        if cell["cell_type"] == "markdown":
            if src:
                parts += ["::: v-pre", src, ":::", ""]
            continue
        if cell["cell_type"] != "code" or not src:
            continue
        n_code += 1
        parts += [f"<p class=\"nb-label\">In [{n_code}]</p>", "", _fence(src, "python"), ""]
        for out in cell.get("outputs", []):
            kind = out.get("output_type")
            if kind == "stream":
                parts += [_fence(_text(out.get("text"))), ""]
            elif kind == "error":
                parts += [_fence(ANSI.sub("", "\n".join(out.get("traceback", [])))), ""]
            elif kind in ("execute_result", "display_data"):
                data = out.get("data", {})
                if "image/png" in data:
                    img_dir = ROOT / "docs/public/tinyllm/notebooks/img"
                    img_dir.mkdir(parents=True, exist_ok=True)
                    name = f"{slug}-{n_code}.png"
                    import base64
                    (img_dir / name).write_bytes(base64.b64decode(_text(data["image/png"])))
                    parts += [f"![第 {n_code} 格的输出图像](/tinyllm/notebooks/img/{name})", ""]
                elif any(k.startswith("application/vnd.plotly") or k == "text/html" for k in data):
                    parts += ["> 这里是一张交互式图表，网页预览无法显示，请在 Colab 或本地运行查看。", ""]
                elif "text/plain" in data:
                    parts += [_fence(_text(data["text/plain"])), ""]
    PAGES.mkdir(parents=True, exist_ok=True)
    (PAGES / f"{slug}.md").write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")
    print(f"[page] {(PAGES / f'{slug}.md').relative_to(ROOT)}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check_only = "--check" in sys.argv
    if "--pages" in sys.argv:  # 只根据现有 notebook 重新生成在线预览页，不运行代码
        for nb_path in sorted(NOTEBOOKS.glob("*.ipynb")):
            if not args or nb_path.stem in args:
                render_page(nb_path)
        return
    scripts = sorted(CODE.glob("*.py"))
    if args:
        scripts = [p for p in scripts if p.stem in args]
    if not scripts:
        raise SystemExit("no matching scripts in " + str(CODE))
    for path in scripts:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            run_script(path, workdir)
            if check_only:
                continue
            for (chapter, name), dest in ARTIFACTS.items():
                if chapter == path.stem and (workdir / name).exists():
                    shutil.copyfile(workdir / name, dest)
                    print(f"[data] {dest.relative_to(ROOT)}")
            to_notebook(path, workdir, NOTEBOOKS / f"{path.stem}.ipynb")
            render_page(NOTEBOOKS / f"{path.stem}.ipynb")


if __name__ == "__main__":
    main()
