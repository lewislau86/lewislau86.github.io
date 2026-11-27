"""Check the shared scaffolding of Learn Agent by Rust chapters migrated to ADK-Rust 3.0.

对 scripts/learn-agent-rust-lessons.json 里 stack 为 adk3 的每一章检查：
- docs/public/learn-agent-rust/code/<slug>/src/trace.rs 含有与 scripts/snippets/adk-trace.rs 完全一致的 region；
- .cargo/config.toml 与全书基线一致：注释里的提交、每个 patch 都指向 ../adk-rust/<crate>；
- Cargo.toml 不自带 [patch]，ADK 依赖写正式版本号；rust-toolchain.toml 使用课程工具链。

用法：
    python3 scripts/check-learn-agent-rust-snippets.py              # 检查
    python3 scripts/check-learn-agent-rust-snippets.py --sync SLUG  # 按实际依赖重写该章的 trace.rs 与 .cargo/config.toml
                                                                    # （需要 cargo 和 ADK-Rust 源码，见 learn_agent_rust_adk.py）
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learn_agent_rust_adk as adk  # noqa: E402

LESSONS = adk.ROOT / "scripts/learn-agent-rust-lessons.json"


def projects(slug: str) -> list[str]:
    """章节里使用 ADK 的工程：带 .cargo/config.toml 的目录（章节根目录或子目录，如 side-effect-reliability/adk）。"""
    root = adk.CODE / slug
    found = sorted(p.parent.parent.relative_to(adk.CODE).as_posix() for p in root.rglob(".cargo/config.toml")
                   if "target" not in p.parts)
    return found or [slug]


def problems_for(slug: str) -> list[str]:
    folder = adk.CODE / slug
    depth = slug.count("/")
    out = []
    trace = folder / "src/trace.rs"
    expected = adk.snippet_region(adk.SNIPPET.read_text(encoding="utf-8"))
    if not trace.exists() or expected not in trace.read_text(encoding="utf-8"):
        out.append(f"{slug}: src/trace.rs 缺少与 scripts/snippets/adk-trace.rs 一致的 adk-trace region")
    config = folder / ".cargo/config.toml"
    if not config.exists():
        out.append(f"{slug}: 缺少 .cargo/config.toml")
    else:
        text = config.read_text(encoding="utf-8")
        if adk.BASELINE["rev"] not in text:
            out.append(f"{slug}: .cargo/config.toml 的基线提交不是 {adk.BASELINE['rev'][:12]}")
        for name, path in re.findall(r'^(\S+) = \{ path = "([^"]+)" \}$', text, re.M):
            if path != "../" * (depth + 1) + f"{adk.SIBLING}/{name}":
                out.append(f"{slug}: patch {name} 指向 {path}")
        crates = re.findall(r'^(\S+) = \{ path = ', text, re.M)
        if text != adk.patch_config(crates, depth):
            out.append(f"{slug}: .cargo/config.toml 不是 patch_config() 生成的格式（运行 --sync {slug}）")
    manifest = (folder / "Cargo.toml").read_text(encoding="utf-8") if (folder / "Cargo.toml").exists() else ""
    if not manifest:
        out.append(f"{slug}: 缺少 Cargo.toml")
    if "[patch" in manifest:
        out.append(f"{slug}: Cargo.toml 不应自带 [patch]，统一放在 .cargo/config.toml")
    for name, spec in re.findall(r'^(adk-[a-z-]+)\s*=\s*(.+)$', manifest, re.M):
        if f'"{adk.BASELINE["version"]}"' not in spec:
            out.append(f"{slug}: {name} 应写版本 \"{adk.BASELINE['version']}\"")
    toolchain = folder / "rust-toolchain.toml"
    if not toolchain.exists() or f'channel = "{adk.BASELINE["toolchain"]}"' not in toolchain.read_text():
        out.append(f"{slug}: rust-toolchain.toml 应固定 {adk.BASELINE['toolchain']}")
    return out


def sync(slug: str):
    """Rewrite trace.rs, the minimal patch list and Cargo.lock; cargo runs in a temp copy."""
    import shutil
    import tempfile

    folder = adk.CODE / slug
    depth = slug.count("/")
    trace = folder / "src/trace.rs"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text(adk.snippet_region(adk.SNIPPET.read_text(encoding="utf-8")), encoding="utf-8")
    env = adk.cargo_env(f"lar-{slug.replace('/', '-')}-target")
    with tempfile.TemporaryDirectory(prefix="lar-sync-") as directory:
        stage = Path(directory) / slug
        shutil.copytree(folder, stage, ignore=shutil.ignore_patterns("target"))
        (Path(directory) / adk.SIBLING).symlink_to(adk.adk_source(), target_is_directory=True)
        crates = adk.used_adk_crates(stage, env, depth)
        config = adk.patch_config(crates, depth)
        (stage / ".cargo").mkdir(exist_ok=True)
        (stage / ".cargo/config.toml").write_text(config, encoding="utf-8")
        adk.run(["cargo", "metadata", "--format-version", "1"], stage, env)  # creates/updates Cargo.lock
        (folder / ".cargo").mkdir(exist_ok=True)
        (folder / ".cargo/config.toml").write_text(config, encoding="utf-8")
        (folder / "Cargo.lock").write_bytes((stage / "Cargo.lock").read_bytes())
    print(f"{slug}: trace.rs, .cargo/config.toml and Cargo.lock written ({len(crates)} ADK crates)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sync", metavar="SLUG")
    args = parser.parse_args()
    if args.sync:
        sync(args.sync)
    lessons = json.loads(LESSONS.read_text(encoding="utf-8"))["lessons"]
    migrated = [row["slug"] for row in lessons if row["stack"] == "adk3"]
    problems = [p for slug in migrated for project in projects(slug) for p in problems_for(project)]
    for problem in problems:
        print(problem)
    print(f"checked {len(migrated)} ADK-Rust 3.0 chapter(s), {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
