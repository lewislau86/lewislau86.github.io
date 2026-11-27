"""Shared helpers for Learn Agent by Rust chapters migrated to ADK-Rust 3.0.

章节验证器（scripts/verify-agent-*.py）引入本模块，统一处理：
- 全书 ADK-Rust 基线（scripts/learn-agent-rust-adk.json）与本地源码位置；
- 章节 `.cargo/config.toml` 的 path patch（ADK-Rust 3.0 发布到 crates.io 之前使用）；
- 把章节打包、解压到临时目录，在旁边放好 `adk-rust/`，再运行 cargo；
- 证据里统一的版本字段、确定性重复运行、可复现的 zip。

源码位置：环境变量 ADK_RUST_SRC，默认 <仓库>/.cache/adk-rust。
取源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust
编译缓存：环境变量 LAR_CACHE，默认 <仓库>/.cache。
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/public/learn-agent-rust"
CODE = PUBLIC / "code"
BASELINE = json.loads((ROOT / "scripts/learn-agent-rust-adk.json").read_text(encoding="utf-8"))
SNIPPET = ROOT / "scripts/snippets/adk-trace.rs"
SIBLING = BASELINE["source_dir"]  # 章节目录旁边的源码目录名
NOT_PUBLISHED = {"xtask", "adk-durability-gates"}
ZIP_TIME = (2020, 1, 1, 0, 0, 0)


class VerifyError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise VerifyError(message)


def adk_source() -> Path:
    path = Path(os.environ.get("ADK_RUST_SRC", ROOT / ".cache/adk-rust")).expanduser().resolve()
    require((path / "Cargo.toml").is_file() and (path / "adk-core/Cargo.toml").is_file(),
            f"ADK-Rust source not found at {path}; run: python3 scripts/fetch-adk-rust.py {path}")
    return path


def cache_dir(name: str) -> Path:
    base = Path(os.environ.get("LAR_CACHE", ROOT / ".cache")).expanduser()
    path = base / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_crates(source: Path | None = None) -> list[str]:
    """Publishable crates of the pinned ADK-Rust workspace, read from its root manifest."""
    text = ((source or adk_source()) / "Cargo.toml").read_text(encoding="utf-8")
    members = text.split("members = [", 1)[1].split("]", 1)[0]
    names = re.findall(r'^\s*"([^"]+)"', members, re.M)
    return sorted(n for n in names if n not in NOT_PUBLISHED)


def patch_config(crates, depth: int = 0) -> str:
    """depth：工程目录在章节目录下的层数（章节根目录为 0，例如 side-effect-reliability/adk 为 1）。
    源码始终放在章节目录旁边，所以路径前缀是 depth + 1 个 ../。"""
    up = "../" * (depth + 1)
    lines = [
        "# ADK-Rust 3.0 尚未发布到 crates.io：本章通过 path patch 使用固定提交的源码。",
        f"# 基线：{BASELINE['repository']} @ {BASELINE['rev']}（{BASELINE['rev_date']}）",
        f"# 源码放在本章目录旁边的 {SIBLING}/：python3 fetch-adk-rust.py ../{SIBLING}",
        "# 3.0.0 正式发布后删除本文件并改用 crates.io 版本。",
        "[patch.crates-io]",
    ]
    lines += [f'{name} = {{ path = "{up}{SIBLING}/{name}" }}' for name in sorted(crates)]
    return "\n".join(lines) + "\n"


def snippet_region(text: str, name: str = "adk-trace") -> str:
    match = re.search(rf"// region {name}\n.*?// endregion {name}\n", text, re.S)
    require(match is not None, f"region {name} not found")
    return match.group(0)


def cargo_env(target: str) -> dict:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(cache_dir(target))
    env.pop("RUSTUP_TOOLCHAIN", None)
    return env


def run(args, cwd, env, timeout=900, ok=(0,)):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, text=True,
                       timeout=timeout)
    require(p.returncode in ok, f"{args} exited {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


def pack(prefix: str, files: dict[str, bytes]) -> bytes:
    """Deterministic zip: fixed timestamps and permissions, sorted entries."""
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(f"{prefix}/{name}", ZIP_TIME)
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return content.getvalue()


def chapter_files(slug: str, names) -> dict[str, bytes]:
    folder = CODE / slug
    files = {name: (folder / name).read_bytes() for name in names}
    require(".cargo/config.toml" in files, f"{slug}: .cargo/config.toml must be packaged")
    return files


@contextmanager
def staged(slug: str, archive: bytes):
    """Extract a chapter archive into a temp dir and put adk-rust/ beside it, as a reader would.
    slug may name a project inside a chapter, e.g. side-effect-reliability/adk."""
    with tempfile.TemporaryDirectory(prefix=f"lar-{slug.replace('/', '-')}-") as directory:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            bundle.extractall(directory)
        (Path(directory) / SIBLING).symlink_to(adk_source(), target_is_directory=True)
        yield Path(directory) / slug


def used_adk_crates(folder: Path, env: dict, depth: int = 0) -> list[str]:
    """Which ADK crates the chapter actually resolves (to keep its patch list minimal)."""
    crates = workspace_crates()
    config = folder / ".cargo/config.toml"
    original = config.read_text(encoding="utf-8") if config.exists() else None
    config.parent.mkdir(exist_ok=True)
    config.write_text(patch_config(crates, depth), encoding="utf-8")
    try:
        out = run(["cargo", "metadata", "--format-version", "1"], folder, env).stdout
    finally:
        if original is None:
            config.unlink()
        else:
            config.write_text(original, encoding="utf-8")
    resolved = {p["name"] for p in json.loads(out)["packages"] if p["source"] is None}
    return sorted(resolved & set(crates))


def standard_checks(folder: Path, env: dict) -> dict:
    """fmt, clippy -D warnings, tests and an offline locked build, as every chapter requires."""
    run(["cargo", "fmt", "--check"], folder, env)
    run(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], folder, env)
    tests = run(["cargo", "test", "--locked", "--quiet"], folder, env).stdout
    passed = sum(int(n) for n in re.findall(r"test result: ok\. (\d+) passed; 0 failed", tests))
    require("FAILED" not in tests and passed > 0, tests)
    run(["cargo", "build", "--locked", "--offline", "--quiet"], folder, env)
    return {"rust_tests_passed": passed}


def repeat_identical(args, cwd, env, times=3) -> str:
    """Run a deterministic demo several times; all stdout must be byte-identical."""
    outputs = [run(args, cwd, env).stdout for _ in range(times)]
    require(len(set(outputs)) == 1, f"{args}: output differs between {times} runs")
    return outputs[0]


def evidence_header(folder: Path, env: dict) -> dict:
    manifest = (folder / "Cargo.toml").read_text(encoding="utf-8")
    deps = {}
    for name, spec in re.findall(r'^(adk-[a-z-]+)\s*=\s*(.+)$', manifest, re.M):
        features = re.search(r'features\s*=\s*\[([^\]]*)\]', spec)
        deps[name] = {
            "default_features": "default-features = false" not in spec,
            "features": re.findall(r'"([^"]+)"', features.group(1)) if features else [],
        }
    return {
        "adk_rust": {k: BASELINE[k] for k in ("repository", "rev", "rev_date", "version", "release_status")},
        "adk_dependencies": deps,
        "rustc": run(["rustc", "--version"], folder, env).stdout.strip(),
        "cargo": run(["cargo", "--version"], folder, env).stdout.strip(),
    }
