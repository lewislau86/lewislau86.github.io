"""Generate a standalone chapter-mapped repository and a deterministic download.

Sources remain in docs/public/learn-agent-rust/code. The verified chapter zips
supply their authored READMEs and evidence; this script checks their source bytes.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/public/learn-agent-rust"
DEST = ROOT / "experiments/learn-agent-rust"
ARCHIVE = PUBLIC / "learn-agent-rust-experiments.zip"
PAGE = ROOT / "docs/learn-agent-rust/experiments.md"
REPORT = ROOT / "scripts/data/learn-agent-rust/course-audit.json"


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def digest(content):
    return hashlib.sha256(content).hexdigest()


def configuration():
    course = json.loads((ROOT / "scripts/learn-agent-rust-lessons.json").read_text())
    rows = json.loads((ROOT / "scripts/learn-agent-rust-experiments.json").read_text())["lessons"]
    written = [r for r in course["lessons"] if r["status"] == "written"]
    if [(r["id"], r["slug"]) for r in rows] != [(r["id"], r["slug"]) for r in written]:
        raise ValueError("Experiment mapping must match every written lesson, in course order")
    lessons = []
    for lesson, row in zip(written, rows):
        lessons.append(dict(lesson, **{k: v for k, v in row.items() if k not in lesson}))
    return lessons


def source_files(lesson):
    base = "docs/public/learn-agent-rust/code/" + lesson["slug"]
    if lesson["kind"] == "rustc":
        files = {lesson["slug"] + ".rs": (ROOT / (base + ".rs")).read_bytes()}
        readme = ROOT / (base + "-README.md")
        if readme.exists():
            files["README.md"] = readme.read_bytes()
        return files
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", base + "/"],
        cwd=ROOT, text=True).splitlines()
    return {name[len(base) + 1:]: (ROOT / name).read_bytes() for name in sorted(set(names))}


def inputs(lesson):
    result = {"code/" + name: digest(value) for name, value in source_files(lesson).items()}
    for path in [ROOT / lesson["verifier"], ROOT / ("scripts/data/learn-agent-rust/" + lesson["id"].lower() + "-results.json")]:
        result[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    if lesson["archive"]:
        result["archive/" + lesson["archive"]] = digest((PUBLIC / lesson["archive"]).read_bytes())
    return result


def chapter_files(lesson):
    sources = source_files(lesson)
    files = {}
    if lesson["archive"]:
        with zipfile.ZipFile(PUBLIC / lesson["archive"]) as archive:
            for item in archive.infolist():
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
                    raise ValueError("Invalid chapter archive entry: " + item.filename)
                if not item.is_dir():
                    name = "/".join(path.parts[1:])
                    if name in files:
                        raise ValueError("Duplicate chapter archive entry: " + name)
                    files[name] = archive.read(item)
        for name, content in sources.items():
            if files.get(name) != content:
                raise ValueError("Chapter archive missing/stale source: " + lesson["id"] + "/" + name)
    else:
        files.update(sources)
        files["README.md"] = ("# {} {}\n\n教程：{}\n\n本章只有 Rust 标准库依赖。\n"
            "从代码库根目录运行 `python3 run.py run {}`，或在本目录运行：\n\n"
            "```sh\nrustc --edition=2024 -D warnings {}.rs -o lab\n./lab\n```\n\n"
            "全部输出见 outputs/，验证口径见 evidence.json。模型使用固定脚本，文件读取实际发生。\n"
            ).format(lesson["id"], lesson["title"], "https://lewislau86.github.io/learn-agent-rust/" + lesson["slug"],
                     lesson["id"], lesson["slug"]).encode()
    evidence = ROOT / ("scripts/data/learn-agent-rust/" + lesson["id"].lower() + "-results.json")
    files["evidence.json"] = evidence.read_bytes()
    for path in sorted((PUBLIC / "outputs").glob(lesson["id"].lower() + "-*")):
        name = "outputs/" + path.name[len(lesson["id"]) + 1:]
        value = path.read_bytes()
        if name in files and files[name] != value:
            raise ValueError("Chapter archive output differs from website: " + name)
        files[name] = value
    return files


def main_readme(lessons, report):
    lines = ["# Learn Agent by Rust · 全书实验代码库", "",
        "本目录由网站唯一实验源码和通过检查的章节包生成，可以单独复制或下载使用。",
        "教程正文：https://lewislau86.github.io/learn-agent-rust/ 。章节目录按主题命名，编号与对应关系见下表和 manifest.json。", "",
        "## 先运行一章", "", "需要 Python 3.9+（仅标准库）、Rust 1.99.1、rustfmt、Clippy、Git 与系统 C 编译工具。",
        "已实际检查 macOS；自动检查配置使用 Linux。建议 Windows 读者使用 WSL。", "",
        "```sh", "rustup toolchain install 1.99.1 --profile minimal --component rustfmt --component clippy",
        "python3 run.py list", "python3 run.py doctor", "python3 run.py integrity",
        "python3 run.py run R01", "python3 run.py test R01", "python3 run.py run R20 --keep ./my-results", "```", "",
        "`run` 编译并运行表中的演示；`test` 还运行格式检查、Rust 测试和 Cargo 工程的 Clippy。",
        "每次复制章节到临时目录运行，退出清理；`--keep` 保存演示的数据与证据，拒绝覆盖同名结果。",
        "修改 chapters 中的源码后也可重跑。编译缓存与最近一次结果保存在 .cache/，无需网站、Node.js、VitePress 或其他项目。", "",
        "## 全书检查", "", "```sh", "python3 run.py test --all", "# 依赖和固定工具链已下载后：",
        "python3 run.py test --all --offline", "# 未安装 PostgreSQL 时明确跳过两章，汇总会列出 skipped：",
        "python3 run.py test --all --skip-postgres", "```", "",
        "首次获取 Rust 工具链和 Cargo 依赖需要网络；zip 不附带第三方 crate 或编译器。",
        "P01、P04 需要 PostgreSQL 18 服务端全套工具，以普通 Unix 用户运行；不使用现有数据库。工具不在 PATH 时设置：", "",
        "```sh", "# 改成自己的安装路径；Linux 常见 /usr/lib/postgresql/18/bin",
        "export P01_PG_BIN=/opt/homebrew/opt/postgresql@18/bin", "export P04_PG_BIN=$P01_PG_BIN", "python3 run.py test P01", "python3 run.py test P04", "```", "",
        "## 章节对应", "", "| 编号 | 教程 | 实验目录 | 统一入口运行内容 |", "| --- | --- | --- | --- |"]
    for row in lessons:
        lines.append("| {} | [{}](https://lewislau86.github.io/learn-agent-rust/{}) | [chapters/{}](chapters/{}/README.md) | {} |".format(
            row["id"], row["title"], row["slug"], row["slug"], row["slug"], row["run_scope"]))
    lines.extend(["", "## 检查证据与范围", "", "发布前逐章原验证器：{}/{} 通过，记录见 [audit.json](audit.json)。".format(
        sum(row["exit_code"] == 0 for row in report["lessons"]), len(lessons)),
        "原验证器检查正文引用、故障场景、实际产物及章节下载包；本代码库的 `test --all` 检查 Rust 测试、格式、Clippy 与运行表中的演示。两种检查分别记录。",
        "P01/P03/P04/P05 的统一入口运行章节 lab.py 完整本地套件；其余章节的更多故障场景见各章 README 和源码。",
        "各章 outputs/ 与 evidence.json 是发布时的记录，包含源码摘要与实验边界。时延、PID、平台路径等现场值不能逐字比较。",
        "默认入口只调用确定性模型/输入夹具；P03 真实启动本地 HTTP，R19/R20 真实运行 stdio 子进程，数据库和文件效果按章实测。",
        "P03 的可选 live 命令需要读者自行配置模型服务；统一入口和自动检查始终使用 fixture，不读取模型凭据。",
        "P06 是有限策略搜索与发布门控实验。数据公开，顺序种子只有两种固定排列，结论不延伸为真实 RSI 或泛化质量。", "",
        "## 维护与来源", "", "网站源码：https://github.com/lewislau86/lewislau86.github.io 。",
        "不要在生成目录维护第二份课程源码。维护者在网站仓库修改 docs/public/learn-agent-rust/code/，",
        "更新相应章节验证产物，执行 `python3 scripts/verify-agent-experiments.py`，再执行 `python3 scripts/package-agent-experiments.py`。",
        "`checksums.json` 核对下载包的文件内容，`manifest.json` 保存编号、目录、依赖和运行步骤。", ""])
    return "\n".join(lines).encode()


def render_page(lessons, report):
    lines = ["---", "title: 全书实验代码库", "description: 按章节下载、运行和检查 Learn Agent by Rust 的全部实验。",
        "pageClass: learn-agent-rust-course", "---", "", "# 全书实验代码库", "",
        "[课程总览](./index.md) · [环境准备](./setup.md) · [学习路径](./learning-path.md)", "",
        "全书 {} 个实验单元按主题目录打包，包含源码、Cargo 锁文件、夹具、运行说明、发布时输出和检查证据。解压后可独立运行。".format(len(lessons)), "",
        '<a href="/learn-agent-rust/learn-agent-rust-experiments.zip" download>下载全书实验代码库（zip）</a> · [在 GitHub 浏览代码库](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust)', "",
        "## 下载后先跑一章", "", "按[环境准备](./setup.md)安装 Rust 1.99.1、rustfmt、Clippy、Git 和 C 编译工具；统一入口需要 Python 3.9+ 标准库。建议使用 macOS、Linux 或 WSL。", "",
        "解压后进入 `learn-agent-rust-experiments` 目录：", "", "```sh", "python3 run.py list", "python3 run.py doctor", "python3 run.py integrity", "python3 run.py run R01", "python3 run.py test R01", "python3 run.py run R20 --keep ./my-results", "```", "",
        "`run` 编译并执行本页对应的演示；`test` 增加 Rust 测试、格式检查和 Cargo 工程的 Clippy。程序在临时目录运行，`--keep` 保存运行产物。每章也可进入 `chapters/<主题>/`，按 README 单独操作。", "",
        "## 全书重跑", "", "```sh", "python3 run.py test --all", "# 工具链和依赖已缓存后，可检查离线运行：", "python3 run.py test --all --offline", "```", "",
        "首次构建需要网络下载依赖。P01、P04 另需 PostgreSQL 18 服务端工具，脚本以普通用户创建并清理专用临时集群；工具不在 PATH 时设置 `P01_PG_BIN` 和 `P04_PG_BIN`。没有数据库环境时可显式加 `--skip-postgres`，结果会列出跳过项。", "",
        "## 按章找到实验", "", "目录名与文章主题名一致；编号仅用于阅读和命令选择。", ""]
    for row in lessons:
        lines.extend(["### {} · {} {{#{}}}".format(row["id"], row["title"], row["slug"]), "",
            "[阅读本章](./{}.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/{})".format(row["slug"], row["slug"]), "",
            "目录：`chapters/{}/`；运行：`python3 run.py run {}`。{}{}".format(row["slug"], row["id"], row["run_scope"], "；需要 PostgreSQL 18。" if row["requires_postgres"] else "。"), "",
            "原章节验证器：`{}`。".format(row["verifier"]), ""])
    lines.extend(["## 发布前检查记录", "", "逐章原验证器 {}/{} 通过。<a href=\"/learn-agent-rust/experiment-audit.json\" download>下载全书检查记录</a>，内含检查日期、逐章退出码、工具环境和源码摘要。".format(sum(r["exit_code"] == 0 for r in report["lessons"]),len(lessons)), "",
        "这些原验证器检查各章正常与故障场景、正文引用输出和已有章节包。统一代码库的 `test --all` 另行检查格式、Rust 测试、Clippy 和本页列出的演示；P01、P03、P04、P05 会执行各章 Python 完整本地套件。", "",
        "模型响应与审批使用固定夹具；HTTP、stdio、文件、SQLite、PostgreSQL 与 Git 操作是否真实执行，以各章 evidence.json 的范围为准。P03 可选外部模型请求未纳入默认命令，协议通过和模型质量分别记录。时延、进程号与平台路径属于当次观测。", "",
        "## 维护唯一来源", "", "`experiments/learn-agent-rust/` 和 zip 均由 `scripts/package-agent-experiments.py` 生成；修改实验时先改网站 `docs/public/learn-agent-rust/code/` 的源码，更新章节验证产物，再运行全书检查与打包。`--check` 会拒绝缺章、源码与章节包不一致、检查证据过期或生成目录漂移。", ""])
    return "\n".join(lines).encode()


def build():
    lessons = configuration()
    report = json.loads(REPORT.read_text())
    by_id = {row["id"]: row for row in report["lessons"]}
    if set(by_id) != {row["id"] for row in lessons}:
        raise ValueError("Full course audit must cover every lesson")
    files = {}
    for row in lessons:
        checked = by_id[row["id"]]
        if checked["exit_code"] != 0 or checked["inputs_sha256"] != inputs(row):
            raise ValueError("Missing/failed/stale audit for " + row["id"])
        chapter = chapter_files(row)
        if row["kind"] == "cargo":
            row["binary"] = re.search(r'^name\s*=\s*"([^"]+)"', chapter["Cargo.toml"].decode(), re.M)[1]
        row["run_scope"] = "完整本地 Python 套件" if row["id"] in {"P01", "P03", "P04", "P05"} else "跨进程写入与召回演示" if row["id"] == "R09" else "多步持久状态演示" if row["id"] in {"R12", "R14", "R17"} else "三种策略发布/拒绝/回滚演示" if row["id"] == "P06" else "11 个检索与证据场景" if row["id"] == "K01" else "本章正常路径演示"
        files.update({"chapters/" + row["slug"] + "/" + name: value for name, value in chapter.items()})
    files["manifest.json"] = encoded(dict(schema_version=1, lessons=lessons))
    files["audit.json"] = REPORT.read_bytes()
    files["run.py"] = (ROOT / "scripts/templates/agent-experiments-run.py").read_bytes()
    files["environment/check-environment.sh"] = (PUBLIC / "code/check-environment.sh").read_bytes()
    files[".gitignore"] = b".cache/\n__pycache__/\n.DS_Store\n"
    files["README.md"] = main_readme(lessons, report)
    files["checksums.json"] = encoded({name: digest(value) for name, value in sorted(files.items())})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, value in sorted(files.items()):
            info = zipfile.ZipInfo("learn-agent-rust-experiments/" + name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, value)
    return files, {ARCHIVE: buffer.getvalue(), PAGE: render_page(lessons, report), PUBLIC / "experiment-audit.json": REPORT.read_bytes()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files, targets = build()
    actual = {str(p.relative_to(DEST)) for p in DEST.rglob("*") if p.is_file() and not any(part in {".cache", "__pycache__"} for part in p.relative_to(DEST).parts)} if DEST.exists() else set()
    extra = actual - set(files)
    if extra:
        previous = json.loads((DEST / "checksums.json").read_text()) if (DEST / "checksums.json").exists() else {}
        for name in sorted(extra):
            if args.check or previous.get(name) != digest((DEST / name).read_bytes()):
                raise ValueError("Unexpected/modified generated file; inspect before removal: " + name)
        for name in sorted(extra):
            (DEST / name).unlink()
    targets.update({DEST / name: value for name, value in files.items()})
    for path, value in targets.items():
        if args.check:
            if not path.exists() or path.read_bytes() != value:
                raise ValueError("Missing/stale generated artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
    print("{} {} files / {} lessons; deterministic zip {} bytes".format("Checked" if args.check else "Generated", len(files), len(configuration()), ARCHIVE.stat().st_size))


if __name__ == "__main__":
    main()
