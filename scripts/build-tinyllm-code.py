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

Outputs a script writes to its working directory are discarded, except the files listed in
ARTIFACTS, which are copied to where the figure scripts expect them.
"""

from pathlib import Path
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


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check_only = "--check" in sys.argv
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


if __name__ == "__main__":
    main()
