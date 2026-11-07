"""Sync course metadata blocks and sidebar; create missing planning pages only.

Run: python3 scripts/sync-learn-agent-rust-course.py [--check]
Chapter prose stays in docs/learn-agent-rust and is never overwritten.
"""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/learn-agent-rust"
MANIFEST = ROOT / "scripts/learn-agent-rust-lessons.json"
ASSETS = ROOT / "scripts/learn-agent-rust-upstream-assets.json"


def load_course():
    course = json.loads(MANIFEST.read_text(encoding="utf-8"))
    lessons = course["lessons"]
    ids = {row["id"] for row in lessons}
    slugs = {row["slug"] for row in lessons}
    parts = {row["id"] for row in course["parts"]}
    if len(ids) != len(lessons) or len(slugs) != len(lessons):
        raise ValueError("Duplicate lesson id or slug")
    by_id = {row["id"]: row for row in lessons}
    visited = set()

    def visit(lesson_id, path):
        if lesson_id in path:
            raise ValueError("Cyclic lesson prerequisites: " + lesson_id)
        if lesson_id in visited:
            return
        for dependency in by_id[lesson_id]["prerequisites"]:
            if dependency not in ids:
                raise ValueError("Unknown prerequisite: " + dependency)
            visit(dependency, path | {lesson_id})
        visited.add(lesson_id)

    for row in lessons:
        if row["part"] not in parts or row["status"] not in {"planned", "written"}:
            raise ValueError("Invalid lesson part/status: " + row["id"])
        if not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", row["slug"]):
            raise ValueError("Invalid topic slug: " + row["slug"])
        visit(row["id"], set())
    return course


def label(row):
    number = int(row["id"][1:])
    prefix = "第 {} 章".format(number) if row["id"].startswith("R") else "专题 {}".format(number)
    return prefix + " · " + row["title"]


def reference(row):
    return "[{}](./{}.md)".format(label(row), row["slug"])


def render_catalog(course):
    lines = []
    for part in course["parts"]:
        lines.extend(["### " + part["title"], "", "| 章节 | 本章问题 | 状态 |", "| --- | --- | --- |"])
        for row in course["lessons"]:
            if row["part"] == part["id"]:
                status = "规划中" if row["status"] == "planned" else "正文已成文；实验见章内说明"
                lines.append("| {} | {} | {} |".format(reference(row), row["question"], status))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_timeline(course):
    lines = []
    for part in course["parts"]:
        lines.extend(["## " + part["title"], ""])
        for row in course["lessons"]:
            if row["part"] != part["id"]:
                continue
            # Stable IDs also let the overview link to any point in the roadmap.
            lines.extend(["### {} · {} {{#{}}}".format(row["id"], row["title"], row["id"].lower()), ""])
            status = "规划中 · 正文与实验待完成" if row["status"] == "planned" else "正文已成文 · 实验状态见章内"
            lines.extend(["> {} · {}".format(row["domain"], status), "", "**本章问题：** " + row["question"], "", "**新增机制：** " + row["addition"], ""])
            dependencies = "、".join("[{}](#{})".format(item, item.lower()) for item in row["prerequisites"])
            lines.extend(["**前置与基础：** " + (dependencies or "Rust 基础、JSON 与基本 async/await；从本章建立全貌。"), "", "**计划验收：** " + row["outcome"], ""])
            if row["status"] == "written":
                lines.append("[阅读正文 →](./{}.md)".format(row["slug"]))
            else:
                lines.append("[查看章节提纲（规划中） →](./{}.md)".format(row["slug"]))
            lines.append("")
    return "\n".join(lines).rstrip()


def sidebar(course):
    output = [{"text": course["title"], "items": [
        {"text": "返回知识库", "link": "/"},
        {"text": "课程总览", "link": "/learn-agent-rust/"},
        {"text": "学习路径 · 能力演化", "link": "/learn-agent-rust/learning-path"},
        {"text": "课程架构与框架分工", "link": "/learn-agent-rust/architecture"},
    ]}]

    def groups(status):
        result = []
        for part in course["parts"]:
            items = [{"text": label(row), "link": "/learn-agent-rust/" + row["slug"]}
                     for row in course["lessons"] if row["part"] == part["id"] and row["status"] == status]
            if items:
                result.append({"text": part["title"], "collapsed": True, "items": items})
        return result

    output.extend(groups("written"))
    planned = groups("planned")
    if planned:
        output.append({"text": "规划中（尚未成文）", "collapsed": True, "items": planned})
    return json.dumps(output, ensure_ascii=False, indent=2) + "\n"


def skeleton(row, by_id, assets):
    title = label(row).replace(" · ", "：", 1)
    dependencies = "、".join(reference(by_id[item]) for item in row["prerequisites"])
    lines = ["---", "title: " + json.dumps(title, ensure_ascii=False),
             "description: " + json.dumps(row["question"], ensure_ascii=False),
             "pageClass: learn-agent-rust-course", "search: false", "prev: false", "next: false", "---", "", "# " + title, "",
             "[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)", "",
             "::: info 本章状态：规划中", "本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。", ":::", "",
             "## 本章问题", "", row["question"], "",
             "## 本章主线选择（待实验验证）", "", row["addition"], "",
             "**所在模块：** " + row["domain"], "",
             "**前置与基础：** " + (dependencies or "Rust 基础、JSON 与基本 async/await。"), "",
             "## 计划验收", "", row["outcome"], ""]
    images = [asset for asset in assets if asset.get("lesson_id") == row["id"]]
    if images:
        lines.extend(["## 保留的参考原图", "",
                      "以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。", ""])
        for image in images:
            lines.extend(["![{}](/learn-agent-rust/figures/upstream/{})".format(image["alt_zh"], image["local_name"]), "",
                          "图源：[参考章节]({}) · [原图]({})。{}".format(image["page_url"], image["source_url"], image["reading_note"]), ""])
        lines.extend(["来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。", ""])
    lines.extend(["回到[学习路径](./learning-path.md#" + row["id"].lower() + ")查看本章位置。", ""])
    return "\n".join(lines)


def replace_block(text, name, content):
    start = "<!-- " + name + ":start -->"
    end = "<!-- " + name + ":end -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError("Missing or repeated metadata block: " + name)
    before, rest = text.split(start)
    _, after = rest.split(end)
    return before + start + "\n\n" + content + "\n\n" + end + after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check without changing files")
    args = parser.parse_args()
    course = load_course()
    assets = json.loads(ASSETS.read_text(encoding="utf-8"))["assets"] if ASSETS.exists() else []
    by_id = {row["id"]: row for row in course["lessons"]}
    targets = {ROOT / "docs/.vitepress/learn-agent-rust-sidebar.json": sidebar(course)}
    for filename, name, content in [
        ("index.md", "course-catalog", render_catalog(course)),
        ("learning-path.md", "course-timeline", render_timeline(course)),
    ]:
        path = DOCS / filename
        targets[path] = replace_block(path.read_text(encoding="utf-8"), name, content)
    for row in course["lessons"]:
        path = DOCS / (row["slug"] + ".md")
        if not path.exists():
            if row["status"] != "planned":
                raise ValueError("Written chapter is missing: " + row["id"])
            targets[path] = skeleton(row, by_id, assets)
    changed = [path for path, text in targets.items()
               if not path.exists() or path.read_text(encoding="utf-8") != text]
    if args.check and changed:
        raise SystemExit("Outdated or missing:\n" + "\n".join(str(path.relative_to(ROOT)) for path in changed))
    if not args.check:
        for path in changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(targets[path], encoding="utf-8")
    print("{}: {} lessons, {} file(s) {}".format("Checked" if args.check else "Synced", len(course["lessons"]), len(changed), "outdated" if args.check else "updated"))


if __name__ == "__main__":
    main()
